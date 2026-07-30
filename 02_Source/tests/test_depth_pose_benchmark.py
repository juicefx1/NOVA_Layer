import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from nova_layer.adapters.capabilities.mock import MockSkeletonDetectionCapability
from nova_layer.depth_pose_benchmark import (
    DepthPoseBenchmarkCase,
    DepthPoseBenchmarkResult,
    DepthPoseSuiteGates,
    evaluate_suite,
    load_manifest,
    load_suite_gates,
    pose_metrics,
    review_case,
    run_benchmark,
    temporal_depth_metrics,
    write_report,
)
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint
from nova_layer.ports.capabilities import SkeletonDetectionResult
from nova_layer.ports.media import MediaInfo


class PoseMediaReader:
    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path,
            fingerprint="pose-benchmark",
            frame_count=2,
            frame_rate=24.0,
            width=8,
            height=8,
            time_base="1/24",
            pixel_format="rgb24",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path, frame_number
        return np.zeros((8, 8, 3), dtype=np.uint8)


def skeleton(offset: float = 0.0) -> SkeletonGuidance:
    left = SkeletonJoint(x=0.3 + offset, y=0.4, label="left_shoulder")
    right = SkeletonJoint(x=0.7 + offset, y=0.4, label="right_shoulder")
    return SkeletonGuidance(
        joints=[left, right],
        bones=[SkeletonBone(start_joint_id=left.id, end_joint_id=right.id)],
    )


def test_pose_metrics_are_semantic_and_normalized() -> None:
    metrics = pose_metrics(
        skeleton(),
        skeleton(0.03),
        {"left_shoulder": 0.9, "right_shoulder": 0.8},
        {"left_shoulder": 0.7},
        {"left_shoulder": 0.2, "right_shoulder": 0.6},
        pck_threshold=0.05,
    )

    assert metrics["matched_joints"] == 2
    assert metrics["mean_joint_error"] == 0.03
    assert metrics["pck"] == 1.0
    assert metrics["joint_coverage"] == 1.0
    assert metrics["depth_coverage"] == 0.5
    assert metrics["sampled_depth_coverage"] == 1.0
    assert metrics["mean_sampled_depth"] == 0.4
    assert np.isclose(metrics["mean_bone_depth_delta"], 0.4)


def test_manifest_run_and_report(tmp_path: Path) -> None:
    manifest = tmp_path / "pose.json"
    artist = skeleton()
    manifest.write_text(
        json.dumps(
            {
                "suite": "Pose QA",
                "gates": {"maximum_mean_temporal_relative_depth_delta": 0.2},
                "cases": [
                    {
                        "id": "person-1",
                        "media": "person.mov",
                        "frame": 1,
                        "artist_skeleton": artist.model_dump(mode="json"),
                        "ground_truth_skeleton": artist.model_dump(mode="json"),
                        "pck_threshold": 0.05,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    suite, cases = load_manifest(manifest, allow_unreviewed=True)
    suite_gates = load_suite_gates(manifest)
    results = run_benchmark(
        cases,
        MockSkeletonDetectionCapability(),
        media_reader=PoseMediaReader(),
    )
    report = write_report(tmp_path / "report.json", suite, results)
    payload = json.loads(report.read_text(encoding="utf-8"))
    markdown = report.with_suffix(".md")
    markdown_text = markdown.read_text(encoding="utf-8")

    assert suite == "Pose QA"
    assert suite_gates.maximum_mean_temporal_relative_depth_delta == 0.2
    assert results[0].status == "passed"
    assert results[0].matched_joints == 2
    assert results[0].pck == 1.0
    assert payload["summary"]["case_completed"] == 1
    assert payload["summary"]["passed"]
    assert payload["schema_version"] == "1.1"
    assert payload["results"][0]["pck_threshold"] == 0.05
    assert payload["results"][0]["gates"][0] == {
        "name": "pck",
        "actual": 1.0,
        "required": 0.8,
        "operator": ">=",
        "passed": True,
    }
    assert markdown.exists()
    assert "# Pose QA — Depth/Pose Benchmark" in markdown_text
    assert "Decision: **PASS**" in markdown_text
    assert "| person-1 | PASSED |" in markdown_text
    assert "## Gate Evidence" in markdown_text
    assert "| person-1 | pck | 1.0000 | >= 0.8000 | PASS |" in markdown_text
    assert "not metric distances" in markdown_text


def test_out_of_range_frame_is_recorded() -> None:
    case = DepthPoseBenchmarkCase(
        case_id="bad-frame",
        media_path=Path("missing.mov"),
        frame_number=3,
        artist_skeleton=skeleton(),
        ground_truth_skeleton=skeleton(),
    )

    result = run_benchmark(
        (case,), MockSkeletonDetectionCapability(), media_reader=PoseMediaReader()
    )[0]

    assert result.status == "error"
    assert result.error == "Frame number is outside the source media range."
    assert result.gates[0].name == "pck"
    assert result.gates[0].required == 0.8
    assert result.gates[0].actual is None
    assert result.gates[0].passed is None


def test_failed_case_records_actual_gate_evidence(tmp_path: Path) -> None:
    case = DepthPoseBenchmarkCase(
        case_id="strict-pose",
        media_path=Path("person.mov"),
        frame_number=0,
        artist_skeleton=skeleton(),
        ground_truth_skeleton=skeleton(),
        pck_threshold=0.001,
        minimum_pck=1.0,
    )

    result = run_benchmark(
        (case,), MockSkeletonDetectionCapability(), media_reader=PoseMediaReader()
    )[0]
    pck_gate = next(gate for gate in result.gates if gate.name == "pck")

    assert result.status == "failed"
    assert pck_gate.actual == 0.0
    assert pck_gate.required == 1.0
    assert pck_gate.passed is False

    report = write_report(tmp_path / "failed.json", "Strict QA", (result,))
    markdown = report.with_suffix(".md").read_text(encoding="utf-8")
    assert "Decision: **FAIL**" in markdown
    assert "| strict-pose | pck | 0.0000 | >= 1.0000 | FAIL |" in markdown


def test_depth_confidence_without_depth_samples_fails_coverage_gate() -> None:
    class ConfidenceOnlyDetector(MockSkeletonDetectionCapability):
        def detect(
            self,
            *,
            frame_number: int,
            image: np.ndarray,
            artist_skeleton: SkeletonGuidance,
        ) -> SkeletonDetectionResult:
            detected = super().detect(
                frame_number=frame_number,
                image=image,
                artist_skeleton=artist_skeleton,
            )
            return replace(detected, joint_depths={})

    case = DepthPoseBenchmarkCase(
        case_id="confidence-without-depth",
        media_path=Path("person.mov"),
        frame_number=0,
        artist_skeleton=skeleton(),
        ground_truth_skeleton=skeleton(),
    )

    result = run_benchmark((case,), ConfidenceOnlyDetector(), media_reader=PoseMediaReader())[0]
    sampled_gate = next(gate for gate in result.gates if gate.name == "sampled_depth_coverage")

    assert result.depth_coverage == 1.0
    assert result.sampled_depth_coverage == 0.0
    assert sampled_gate.passed is False
    assert result.status == "failed"


def test_temporal_depth_metrics_match_semantic_labels(tmp_path: Path) -> None:
    def result(case_id: str, frame: int, depths: dict[str, float]) -> DepthPoseBenchmarkResult:
        return DepthPoseBenchmarkResult(
            case_id=case_id,
            status="passed",
            frame_number=frame,
            matched_joints=2,
            expected_joints=2,
            mean_joint_error=0.01,
            pck=1.0,
            joint_coverage=1.0,
            depth_coverage=1.0,
            mean_joint_confidence=0.9,
            mean_depth_confidence=0.8,
            sampled_depth_coverage=1.0,
            mean_sampled_depth=float(np.mean(list(depths.values()))),
            minimum_sampled_depth=min(depths.values()),
            maximum_sampled_depth=max(depths.values()),
            mean_bone_depth_delta=None,
            depth_sequence="shot-a",
            sampled_joint_depths=depths,
            duration_seconds=0.1,
            pck_threshold=0.05,
            gates=(),
        )

    results = (
        result("frame-10", 10, {"left_shoulder": 0.2, "right_shoulder": 0.4}),
        result("frame-12", 12, {"left_shoulder": 0.3, "right_shoulder": 0.7}),
    )
    transitions = temporal_depth_metrics(results)

    assert len(transitions) == 1
    assert transitions[0]["matched_labels"] == 2
    assert np.isclose(transitions[0]["mean_absolute_depth_delta"], 0.2)
    assert np.isclose(transitions[0]["maximum_absolute_depth_delta"], 0.3)
    assert transitions[0]["mean_relative_depth_delta"] == 0.0

    suite_gates = DepthPoseSuiteGates(maximum_mean_temporal_relative_depth_delta=0.01)
    assert evaluate_suite(results, suite_gates).passed
    report = write_report(tmp_path / "temporal.json", "Temporal QA", results, gates=suite_gates)
    markdown = report.with_suffix(".md").read_text(encoding="utf-8")
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert "## Temporal Depth" in markdown
    assert "## Suite Gate Evidence" in markdown
    assert "frame-10 → frame-12" in markdown
    assert "10 → 12" in markdown
    assert payload["summary"]["suite_gate_results"][0]["passed"]

    unstable = (
        result("frame-10", 10, {"left_shoulder": 0.2, "right_shoulder": 0.4}),
        result("frame-12", 12, {"left_shoulder": 0.7, "right_shoulder": 0.3}),
    )
    assert not evaluate_suite(unstable, suite_gates).passed

    partially_comparable = (
        result("frame-10", 10, {"left_shoulder": 0.2, "right_shoulder": 0.4}),
        result("frame-12", 12, {"left_shoulder": 0.3, "right_shoulder": 0.5}),
        result("frame-14", 14, {"head": 0.2, "hip": 0.6}),
    )
    coverage_evaluation = evaluate_suite(
        partially_comparable,
        DepthPoseSuiteGates(minimum_temporal_transition_coverage=1.0),
    )
    assert coverage_evaluation.temporal_transition_count == 2
    assert coverage_evaluation.comparable_temporal_transition_count == 1
    assert coverage_evaluation.temporal_transition_coverage == 0.5
    assert not coverage_evaluation.passed
    assert coverage_evaluation.temporal[1]["matched_labels"] == 0
    assert not coverage_evaluation.temporal[1]["relative_depth_comparable"]


def test_temporal_suite_gate_requires_a_comparable_transition() -> None:
    result = DepthPoseBenchmarkResult(
        case_id="single-frame",
        status="passed",
        frame_number=1,
        matched_joints=2,
        expected_joints=2,
        mean_joint_error=0.01,
        pck=1.0,
        joint_coverage=1.0,
        depth_coverage=1.0,
        mean_joint_confidence=0.9,
        mean_depth_confidence=0.8,
        sampled_depth_coverage=1.0,
        mean_sampled_depth=0.5,
        minimum_sampled_depth=0.4,
        maximum_sampled_depth=0.6,
        mean_bone_depth_delta=0.2,
        depth_sequence="shot-a",
        sampled_joint_depths={"left_shoulder": 0.4, "right_shoulder": 0.6},
        duration_seconds=0.1,
        pck_threshold=0.05,
        gates=(),
    )

    evaluation = evaluate_suite(
        (result,),
        DepthPoseSuiteGates(maximum_mean_temporal_relative_depth_delta=0.1),
    )

    assert not evaluation.passed
    assert evaluation.temporal_transition_count == 0
    assert evaluation.temporal_transition_coverage is None
    assert evaluation.gate_results[0].actual is None
    assert evaluation.gate_results[0].passed is False


def test_approved_pose_annotation_is_integrity_locked(tmp_path: Path) -> None:
    expected = skeleton()
    manifest = tmp_path / "approved.json"
    payload = {
        "cases": [
            {
                "id": "approved-person",
                "media": "person.mov",
                "source_media_fingerprint": "pose-benchmark",
                "frame": 0,
                "artist_skeleton": skeleton(0.02).model_dump(mode="json"),
                "ground_truth_skeleton": expected.model_dump(mode="json"),
                "annotation_status": "candidate",
            }
        ]
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    review_case(
        manifest,
        "approved-person",
        status="approved",
        reviewer="QA Artist",
        notes="labels verified",
    )

    _, cases = load_manifest(manifest)
    assert cases[0].annotation_status == "approved"

    modified = json.loads(manifest.read_text(encoding="utf-8"))
    modified["cases"][0]["ground_truth_skeleton"]["joints"][0]["x"] = 0.1
    manifest.write_text(json.dumps(modified), encoding="utf-8")
    try:
        load_manifest(manifest)
    except ValueError as exc:
        assert "changed after human QA approval" in str(exc)
    else:
        raise AssertionError("modified ground truth was accepted")
