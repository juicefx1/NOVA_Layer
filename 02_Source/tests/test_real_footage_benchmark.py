import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.capabilities.mock import MockSegmentationCapability
from nova_layer.benchmark_dataset import review_dataset_case
from nova_layer.benchmark_review_assets import generate_review_assets
from nova_layer.domain.models import GuidancePoint
from nova_layer.ports.media import MediaInfo
from nova_layer.real_footage_benchmark import (
    BenchmarkCase,
    SuiteGates,
    evaluate_suite,
    load_manifest,
    load_suite_gates,
    run_benchmark,
    segmentation_metrics,
    write_report,
)


class BenchmarkMediaReader:
    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path,
            fingerprint="benchmark",
            frame_count=3,
            frame_rate=24.0,
            width=8,
            height=6,
            time_base="1/24",
            pixel_format="rgb24",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path, frame_number
        return np.zeros((6, 8, 3), dtype=np.uint8)


def test_segmentation_metrics_handle_overlap_and_empty_masks() -> None:
    expected = np.array([[255, 255], [0, 0]], dtype=np.uint8)
    predicted = np.array([[255, 0], [255, 0]], dtype=np.uint8)
    assert segmentation_metrics(predicted, expected) == (1 / 3, 0.5, 0.5)
    empty = np.zeros((2, 2), dtype=np.uint8)
    assert segmentation_metrics(empty, empty) == (1.0, 1.0, 1.0)


def test_manifest_benchmark_and_reports_are_reproducible(tmp_path: Path) -> None:
    manifest = tmp_path / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "suite": "Representative Shots",
                "gates": {
                    "minimum_mean_iou": 0.95,
                    "minimum_pass_rate": 1.0,
                    "maximum_mean_duration_seconds": 10.0,
                },
                "cases": [
                    {
                        "id": "person-closeup",
                        "media": "person.mov",
                        "source_media_fingerprint": "benchmark",
                        "frame": 1,
                        "ground_truth_mask": "person.png",
                        "points": [{"x": 0.5, "y": 0.5, "polarity": "positive"}],
                        "minimum_iou": 0.9,
                        "annotation_status": "candidate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="human QA approval is required"):
        load_manifest(manifest)
    suite, cases = load_manifest(manifest, allow_unreviewed=True)
    gates = load_suite_gates(manifest)
    assert suite == "Representative Shots"
    assert gates.minimum_mean_iou == 0.95
    assert cases[0].media_path == (tmp_path / "person.mov").resolve()

    capability = MockSegmentationCapability()
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    ground_truth = capability.predict(
        frame_number=1,
        image=frame,
        width=8,
        height=6,
        points=(GuidancePoint(x=0.5, y=0.5, polarity="positive"),),
        bounding_region=None,
    ).mask
    results = run_benchmark(
        cases,
        capability,
        media_reader=BenchmarkMediaReader(),
        mask_loader=lambda path: ground_truth,
    )
    assert len(results) == 1
    assert results[0].status == "passed"
    assert results[0].iou == 1.0
    assert results[0].adapter == "deterministic_mock"

    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"fixed-model-weights")
    json_path, markdown_path = write_report(
        tmp_path / "reports",
        suite,
        results,
        runtime_mode="test",
        runtime_message="deterministic adapter",
        gates=gates,
        checkpoint_path=checkpoint,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["passed"]
    assert payload["summary"]["case_passed"] == 1
    assert payload["summary"]["mean_iou"] == 1.0
    assert payload["model_provenance"][0]["adapter"] == "deterministic_mock"
    assert len(payload["checkpoint"]["sha256"]) == 64
    assert "person-closeup" in markdown_path.read_text(encoding="utf-8")
    assert not evaluate_suite(
        results,
        SuiteGates(maximum_mean_duration_seconds=0.000000001),
    ).passed

    review_index = generate_review_assets(
        cases,
        tmp_path / "review_assets",
        media_reader=BenchmarkMediaReader(),
        mask_loader=lambda path: ground_truth,
    )
    assert review_index.is_file()
    review_html = review_index.read_text(encoding="utf-8")
    assert "person-closeup" in review_html
    assert (review_index.parent / "person-closeup_overlay.png").is_file()


def test_benchmark_records_case_errors_without_stopping_suite(tmp_path: Path) -> None:
    case = BenchmarkCase(
        case_id="bad-frame",
        media_path=tmp_path / "source.mov",
        frame_number=9,
        ground_truth_path=tmp_path / "mask.png",
        points=(GuidancePoint(x=0.5, y=0.5, polarity="positive"),),
        bounding_region=None,
        minimum_iou=0.8,
        annotation_status="approved",
        source_media_fingerprint=None,
    )
    result = run_benchmark(
        (case,),
        MockSegmentationCapability(),
        media_reader=BenchmarkMediaReader(),
    )[0]
    assert result.status == "error"
    assert result.error == "Frame number is outside the source media range."

    changed_media_case = BenchmarkCase(
        case_id="changed-media",
        media_path=tmp_path / "source.mov",
        frame_number=1,
        ground_truth_path=tmp_path / "mask.png",
        points=(GuidancePoint(x=0.5, y=0.5, polarity="positive"),),
        bounding_region=None,
        minimum_iou=0.8,
        annotation_status="approved",
        source_media_fingerprint="different-fingerprint",
    )
    changed_media_result = run_benchmark(
        (changed_media_case,),
        MockSegmentationCapability(),
        media_reader=BenchmarkMediaReader(),
    )[0]
    assert changed_media_result.status == "error"
    assert changed_media_result.error == (
        "Source media fingerprint differs from the reviewed dataset case."
    )


def test_approved_ground_truth_is_checksum_locked(tmp_path: Path) -> None:
    mask_path = tmp_path / "mask.png"
    mask_path.write_bytes(b"reviewed-mask")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "locked-mask",
                        "media": "source.mov",
                        "frame": 0,
                        "ground_truth_mask": "mask.png",
                        "points": [{"x": 0.5, "y": 0.5, "polarity": "positive"}],
                        "annotation_status": "candidate",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    review_dataset_case(
        manifest_path,
        "locked-mask",
        status="approved",
        reviewer="QA Artist",
    )
    _, cases = load_manifest(manifest_path)
    assert cases[0].annotation_status == "approved"

    mask_path.write_bytes(b"modified-after-review")
    with pytest.raises(ValueError, match="changed after human QA approval"):
        load_manifest(manifest_path)
    review_dataset_case(
        manifest_path,
        "locked-mask",
        status="rejected",
        reviewer="QA Artist",
        notes="Revision needs another edge pass.",
    )
    with pytest.raises(ValueError, match="human QA approval is required"):
        load_manifest(manifest_path)
    review_dataset_case(
        manifest_path,
        "locked-mask",
        status="approved",
        reviewer="Senior QA Artist",
        notes="Revised mask approved.",
    )
    _, revised_cases = load_manifest(manifest_path)
    assert revised_cases[0].annotation_status == "approved"
    revised_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    history = revised_manifest["cases"][0]["review_history"]
    assert [item["status"] for item in history] == ["approved", "rejected", "approved"]
    assert history[1]["previous_review_sha256"] == history[0]["review_sha256"]
    history[0]["notes"] = "tampered historical decision"
    manifest_path.write_text(json.dumps(revised_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Review history checksum mismatch"):
        load_manifest(manifest_path)
