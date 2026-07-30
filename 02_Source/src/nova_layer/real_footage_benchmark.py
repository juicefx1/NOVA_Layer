from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.app.capability_selection import select_interactive_segmentation
from nova_layer.benchmark_dataset import validate_review_history
from nova_layer.domain.models import BoundingRegion, GuidancePoint
from nova_layer.ports.capabilities import InteractiveSegmentationCapability
from nova_layer.ports.media import MediaReader


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    media_path: Path
    frame_number: int
    ground_truth_path: Path
    points: tuple[GuidancePoint, ...]
    bounding_region: BoundingRegion | None
    minimum_iou: float
    annotation_status: str
    source_media_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    case_id: str
    status: str
    frame_number: int
    iou: float
    precision: float
    recall: float
    confidence: float
    duration_seconds: float
    adapter: str | None = None
    adapter_version: str | None = None
    model_identifier: str | None = None
    device: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SuiteGates:
    minimum_mean_iou: float = 0.8
    minimum_pass_rate: float = 1.0
    maximum_mean_duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class SuiteEvaluation:
    passed: bool
    case_passed: int
    case_total: int
    mean_iou: float
    pass_rate: float
    mean_duration_seconds: float
    gate_results: tuple[dict[str, Any], ...]


def load_suite_gates(path: Path) -> SuiteGates:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("gates", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raise ValueError("Benchmark gates must be an object.")
    gates = SuiteGates(
        minimum_mean_iou=float(raw.get("minimum_mean_iou", 0.8)),
        minimum_pass_rate=float(raw.get("minimum_pass_rate", 1.0)),
        maximum_mean_duration_seconds=(
            float(raw["maximum_mean_duration_seconds"])
            if raw.get("maximum_mean_duration_seconds") is not None
            else None
        ),
    )
    if not 0.0 <= gates.minimum_mean_iou <= 1.0:
        raise ValueError("minimum_mean_iou must be between 0 and 1.")
    if not 0.0 <= gates.minimum_pass_rate <= 1.0:
        raise ValueError("minimum_pass_rate must be between 0 and 1.")
    if gates.maximum_mean_duration_seconds is not None and gates.maximum_mean_duration_seconds <= 0:
        raise ValueError("maximum_mean_duration_seconds must be positive.")
    return gates


def load_manifest(
    path: Path, *, allow_unreviewed: bool = False
) -> tuple[str, tuple[BenchmarkCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Benchmark manifest must contain a cases array.")
    root = path.resolve().parent
    cases: list[BenchmarkCase] = []
    for raw in payload["cases"]:
        if not isinstance(raw, dict):
            raise ValueError("Each benchmark case must be an object.")
        case_id = str(raw["id"])
        points = tuple(GuidancePoint.model_validate(item) for item in raw.get("points", []))
        region_raw = raw.get("bounding_region")
        region = BoundingRegion.model_validate(region_raw) if region_raw is not None else None
        minimum_iou = float(raw.get("minimum_iou", 0.8))
        if not 0.0 <= minimum_iou <= 1.0:
            raise ValueError(f"Case {case_id}: minimum_iou must be between 0 and 1.")
        if not points and region is None:
            raise ValueError(f"Case {case_id}: guidance is required.")
        annotation_status = str(raw.get("annotation_status", "unreviewed"))
        if annotation_status != "approved" and not allow_unreviewed:
            raise ValueError(
                f"Case {case_id}: annotation status is {annotation_status}; "
                "human QA approval is required."
            )
        ground_truth_path = (root / str(raw["ground_truth_mask"])).resolve()
        if annotation_status == "approved":
            review = raw.get("review")
            if not isinstance(review, dict):
                raise ValueError(f"Case {case_id}: approved annotation has no review record.")
            review_history = raw.get("review_history")
            try:
                validated_history = validate_review_history(review_history)
            except ValueError as exc:
                raise ValueError(f"Case {case_id}: {exc}") from exc
            latest_review = validated_history[-1]
            if latest_review.get("status") != "approved":
                raise ValueError(
                    f"Case {case_id}: active approval does not match the review history."
                )
            for field in (
                "reviewer",
                "reviewed_at",
                "notes",
                "ground_truth_sha256",
                "source_media_fingerprint",
                "previous_review_sha256",
                "review_sha256",
            ):
                if latest_review.get(field) != review.get(field):
                    raise ValueError(
                        f"Case {case_id}: active review differs from the audit history."
                    )
            expected_hash = review.get("ground_truth_sha256")
            if not isinstance(expected_hash, str):
                raise ValueError(f"Case {case_id}: approved annotation has no review checksum.")
            if not ground_truth_path.is_file():
                raise ValueError(f"Case {case_id}: ground-truth mask is missing.")
            with ground_truth_path.open("rb") as stream:
                actual_hash = file_digest(stream, "sha256").hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Case {case_id}: ground-truth mask changed after human QA approval."
                )
            reviewed_media_fingerprint = review.get("source_media_fingerprint")
            manifest_media_fingerprint = raw.get("source_media_fingerprint")
            if reviewed_media_fingerprint != manifest_media_fingerprint:
                raise ValueError(
                    f"Case {case_id}: source-media fingerprint changed after QA approval."
                )
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                media_path=(root / str(raw["media"])).resolve(),
                frame_number=int(raw["frame"]),
                ground_truth_path=ground_truth_path,
                points=points,
                bounding_region=region,
                minimum_iou=minimum_iou,
                annotation_status=annotation_status,
                source_media_fingerprint=(
                    str(raw["source_media_fingerprint"])
                    if raw.get("source_media_fingerprint") is not None
                    else None
                ),
            )
        )
    suite = str(payload.get("suite", path.stem))
    return suite, tuple(cases)


def segmentation_metrics(
    prediction: NDArray[np.uint8], ground_truth: NDArray[np.uint8]
) -> tuple[float, float, float]:
    if prediction.shape != ground_truth.shape:
        raise ValueError(
            f"Prediction shape {prediction.shape} does not match ground truth {ground_truth.shape}."
        )
    predicted = prediction > 0
    expected = ground_truth > 0
    intersection = int(np.count_nonzero(predicted & expected))
    union = int(np.count_nonzero(predicted | expected))
    predicted_count = int(np.count_nonzero(predicted))
    expected_count = int(np.count_nonzero(expected))
    iou = intersection / union if union else 1.0
    precision = intersection / predicted_count if predicted_count else float(expected_count == 0)
    recall = intersection / expected_count if expected_count else float(predicted_count == 0)
    return iou, precision, recall


def _load_png_mask(path: Path) -> NDArray[np.uint8]:
    return PngMaskStore().load(path.parent, path.name)


def run_benchmark(
    cases: Sequence[BenchmarkCase],
    capability: InteractiveSegmentationCapability,
    *,
    media_reader: MediaReader | None = None,
    mask_loader: Callable[[Path], NDArray[np.uint8]] = _load_png_mask,
) -> tuple[BenchmarkResult, ...]:
    reader = media_reader or PyAvMediaReader()
    results: list[BenchmarkResult] = []
    for case in cases:
        started = perf_counter()
        try:
            media = reader.inspect(case.media_path)
            if (
                case.source_media_fingerprint is not None
                and media.fingerprint != case.source_media_fingerprint
            ):
                raise ValueError("Source media fingerprint differs from the reviewed dataset case.")
            if not 0 <= case.frame_number < media.frame_count:
                raise ValueError("Frame number is outside the source media range.")
            frame = reader.read_frame(case.media_path, case.frame_number)
            ground_truth = mask_loader(case.ground_truth_path)
            prediction = capability.predict(
                frame_number=case.frame_number,
                image=frame,
                width=media.width,
                height=media.height,
                points=case.points,
                bounding_region=case.bounding_region,
            )
            iou, precision, recall = segmentation_metrics(prediction.mask, ground_truth)
            results.append(
                BenchmarkResult(
                    case_id=case.case_id,
                    status="passed" if iou >= case.minimum_iou else "failed",
                    frame_number=case.frame_number,
                    iou=iou,
                    precision=precision,
                    recall=recall,
                    confidence=prediction.confidence,
                    duration_seconds=perf_counter() - started,
                    adapter=prediction.provenance.adapter,
                    adapter_version=prediction.provenance.adapter_version,
                    model_identifier=prediction.provenance.model_identifier,
                    device=prediction.provenance.device,
                )
            )
        except Exception as exc:
            results.append(
                BenchmarkResult(
                    case_id=case.case_id,
                    status="error",
                    frame_number=case.frame_number,
                    iou=0.0,
                    precision=0.0,
                    recall=0.0,
                    confidence=0.0,
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
            )
    return tuple(results)


def evaluate_suite(results: Sequence[BenchmarkResult], gates: SuiteGates) -> SuiteEvaluation:
    total = len(results)
    case_passed = sum(item.status == "passed" for item in results)
    mean_iou = sum(item.iou for item in results) / total if total else 0.0
    pass_rate = case_passed / total if total else 0.0
    mean_duration = sum(item.duration_seconds for item in results) / total if total else 0.0
    gate_results: list[dict[str, Any]] = [
        {
            "gate": "minimum_mean_iou",
            "passed": mean_iou >= gates.minimum_mean_iou,
            "actual": mean_iou,
            "required": gates.minimum_mean_iou,
        },
        {
            "gate": "minimum_pass_rate",
            "passed": pass_rate >= gates.minimum_pass_rate,
            "actual": pass_rate,
            "required": gates.minimum_pass_rate,
        },
    ]
    if gates.maximum_mean_duration_seconds is not None:
        gate_results.append(
            {
                "gate": "maximum_mean_duration_seconds",
                "passed": mean_duration <= gates.maximum_mean_duration_seconds,
                "actual": mean_duration,
                "required": gates.maximum_mean_duration_seconds,
            }
        )
    passed = total > 0 and all(bool(item["passed"]) for item in gate_results)
    return SuiteEvaluation(
        passed=passed,
        case_passed=case_passed,
        case_total=total,
        mean_iou=mean_iou,
        pass_rate=pass_rate,
        mean_duration_seconds=mean_duration,
        gate_results=tuple(gate_results),
    )


def write_report(
    output_dir: Path,
    suite: str,
    results: Sequence[BenchmarkResult],
    *,
    runtime_mode: str,
    runtime_message: str,
    gates: SuiteGates | None = None,
    checkpoint_path: Path | None = None,
) -> tuple[Path, Path]:
    generated_at = datetime.now(UTC).isoformat()
    evaluation = evaluate_suite(results, gates or SuiteGates())
    provenance = sorted(
        {
            (
                item.adapter,
                item.adapter_version,
                item.model_identifier,
                item.device,
            )
            for item in results
            if item.adapter is not None
        },
        key=lambda item: tuple(str(part) for part in item),
    )
    checkpoint_hash = None
    if checkpoint_path is not None and checkpoint_path.is_file():
        with checkpoint_path.open("rb") as stream:
            checkpoint_hash = file_digest(stream, "sha256").hexdigest()
    payload: dict[str, Any] = {
        "suite": suite,
        "generated_at": generated_at,
        "runtime_mode": runtime_mode,
        "runtime_message": runtime_message,
        "model_provenance": [
            {
                "adapter": item[0],
                "adapter_version": item[1],
                "model_identifier": item[2],
                "device": item[3],
            }
            for item in provenance
        ],
        "checkpoint": (
            {"path": str(checkpoint_path.resolve()), "sha256": checkpoint_hash}
            if checkpoint_path is not None
            else None
        ),
        "summary": asdict(evaluation),
        "results": [asdict(item) for item in results],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "real_footage_segmentation_latest.json"
    markdown_path = output_dir / "real_footage_segmentation_latest.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# NOVA Layer Real-Footage Segmentation Benchmark",
        "",
        f"Generated: {generated_at}",
        f"Runtime: **{runtime_mode}** — {runtime_message}",
        f"Model provenance: **{len(provenance)} unique configuration(s)**",
        f"Checkpoint SHA-256: `{checkpoint_hash or 'not recorded'}`",
        f"Result: **{'PASSED' if evaluation.passed else 'FAILED'}** "
        f"({evaluation.case_passed}/{evaluation.case_total} cases)",
        f"Mean IoU: **{evaluation.mean_iou:.4f}** · "
        f"Pass rate: **{evaluation.pass_rate:.1%}** · "
        f"Mean time: **{evaluation.mean_duration_seconds:.3f}s**",
        "",
        "| Case | Status | IoU | Precision | Recall | Confidence | Time |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.case_id} | {item.status.upper()} | {item.iou:.4f} | "
        f"{item.precision:.4f} | {item.recall:.4f} | {item.confidence:.4f} | "
        f"{item.duration_seconds:.3f}s |"
        for item in results
    )
    lines.extend(
        ["", "## Suite Gates", "", "| Gate | Status | Actual | Required |", "|---|---:|---:|---:|"]
    )
    lines.extend(
        f"| {gate['gate']} | {'PASS' if gate['passed'] else 'FAIL'} | "
        f"{gate['actual']:.4f} | {gate['required']:.4f} |"
        for gate in evaluation.gate_results
    )
    errors = [item for item in results if item.error]
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{item.case_id}`: {item.error}" for item in errors)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark segmentation on labeled footage.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "06_Test" / "reports",
    )
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--allow-unreviewed", action="store_true")
    args = parser.parse_args()
    suite, cases = load_manifest(args.manifest, allow_unreviewed=args.allow_unreviewed)
    gates = load_suite_gates(args.manifest)
    selection = select_interactive_segmentation()
    if selection.mode == "mock" and not args.allow_mock:
        parser.error("Real-footage benchmarks require the real model; use --allow-mock explicitly.")
    results = run_benchmark(cases, selection.capability)
    json_path, markdown_path = write_report(
        args.output,
        suite,
        results,
        runtime_mode=selection.mode,
        runtime_message=selection.message,
        gates=gates,
        checkpoint_path=selection.checkpoint,
    )
    evaluation = evaluate_suite(results, gates)
    print(
        f"Real-footage segmentation: "
        f"{'PASSED' if evaluation.passed else 'FAILED'} "
        f"({evaluation.case_passed}/{evaluation.case_total} cases)"
    )
    print(json_path)
    print(markdown_path)
    return 0 if evaluation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
