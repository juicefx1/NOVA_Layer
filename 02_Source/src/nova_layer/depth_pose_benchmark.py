from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict
from uuid import uuid4

import numpy as np

from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.app.capability_selection import select_skeleton_detection
from nova_layer.benchmark_dataset import review_record_sha256, validate_review_history
from nova_layer.domain.models import SkeletonGuidance
from nova_layer.ports.capabilities import SkeletonDetectionCapability
from nova_layer.ports.media import MediaReader


@dataclass(frozen=True, slots=True)
class DepthPoseBenchmarkCase:
    case_id: str
    media_path: Path
    frame_number: int
    artist_skeleton: SkeletonGuidance
    ground_truth_skeleton: SkeletonGuidance
    pck_threshold: float = 0.05
    minimum_pck: float = 0.8
    minimum_joint_coverage: float = 0.8
    minimum_depth_coverage: float = 0.8
    minimum_sampled_depth_coverage: float = 0.8
    maximum_duration_seconds: float | None = None
    annotation_status: str = "unreviewed"
    source_media_fingerprint: str | None = None
    depth_sequence: str | None = None


def skeleton_sha256(skeleton: SkeletonGuidance) -> str:
    canonical = json.dumps(
        skeleton.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class DepthPoseGateResult:
    name: str
    actual: float | None
    required: float | None
    operator: str
    passed: bool | None


@dataclass(frozen=True, slots=True)
class DepthPoseSuiteGates:
    maximum_mean_temporal_relative_depth_delta: float | None = None
    minimum_temporal_transition_coverage: float | None = None


@dataclass(frozen=True, slots=True)
class DepthPoseSuiteEvaluation:
    passed: bool
    temporal: tuple[dict[str, Any], ...]
    mean_temporal_relative_depth_delta: float | None
    temporal_transition_count: int
    comparable_temporal_transition_count: int
    temporal_transition_coverage: float | None
    gate_results: tuple[DepthPoseGateResult, ...]


@dataclass(frozen=True, slots=True)
class DepthPoseBenchmarkResult:
    case_id: str
    status: str
    frame_number: int
    matched_joints: int
    expected_joints: int
    mean_joint_error: float
    pck: float
    joint_coverage: float
    depth_coverage: float
    mean_joint_confidence: float
    mean_depth_confidence: float
    sampled_depth_coverage: float
    mean_sampled_depth: float | None
    minimum_sampled_depth: float | None
    maximum_sampled_depth: float | None
    mean_bone_depth_delta: float | None
    depth_sequence: str | None
    sampled_joint_depths: dict[str, float]
    duration_seconds: float
    pck_threshold: float
    gates: tuple[DepthPoseGateResult, ...]
    adapter: str | None = None
    model_identifier: str | None = None
    device: str | None = None
    error: str | None = None


class PoseMetricValues(TypedDict):
    matched_joints: int
    expected_joints: int
    mean_joint_error: float
    pck: float
    joint_coverage: float
    depth_coverage: float
    mean_joint_confidence: float
    mean_depth_confidence: float
    sampled_depth_coverage: float
    mean_sampled_depth: float | None
    minimum_sampled_depth: float | None
    maximum_sampled_depth: float | None
    mean_bone_depth_delta: float | None


def load_suite_gates(path: Path) -> DepthPoseSuiteGates:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("gates", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raise ValueError("Depth/Pose benchmark gates must be an object.")
    maximum_temporal = raw.get("maximum_mean_temporal_relative_depth_delta")
    minimum_temporal_coverage = raw.get("minimum_temporal_transition_coverage")
    gates = DepthPoseSuiteGates(
        maximum_mean_temporal_relative_depth_delta=(
            float(maximum_temporal) if maximum_temporal is not None else None
        ),
        minimum_temporal_transition_coverage=(
            float(minimum_temporal_coverage) if minimum_temporal_coverage is not None else None
        ),
    )
    if (
        gates.maximum_mean_temporal_relative_depth_delta is not None
        and not 0.0 <= gates.maximum_mean_temporal_relative_depth_delta <= 1.0
    ):
        raise ValueError("maximum_mean_temporal_relative_depth_delta must be between 0 and 1.")
    if (
        gates.minimum_temporal_transition_coverage is not None
        and not 0.0 <= gates.minimum_temporal_transition_coverage <= 1.0
    ):
        raise ValueError("minimum_temporal_transition_coverage must be between 0 and 1.")
    return gates


def load_manifest(
    path: Path, *, allow_unreviewed: bool = False
) -> tuple[str, tuple[DepthPoseBenchmarkCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Depth/Pose manifest must contain a cases array.")
    root = path.resolve().parent
    cases: list[DepthPoseBenchmarkCase] = []
    for raw in payload["cases"]:
        if not isinstance(raw, dict):
            raise ValueError("Each Depth/Pose benchmark case must be an object.")
        threshold = float(raw.get("pck_threshold", 0.05))
        if not 0 < threshold <= 1:
            raise ValueError("pck_threshold must be between 0 and 1.")
        minimum_pck = float(raw.get("minimum_pck", 0.8))
        minimum_joint_coverage = float(raw.get("minimum_joint_coverage", 0.8))
        minimum_depth_coverage = float(raw.get("minimum_depth_coverage", 0.8))
        minimum_sampled_depth_coverage = float(raw.get("minimum_sampled_depth_coverage", 0.8))
        maximum_duration = raw.get("maximum_duration_seconds")
        if not all(
            0 <= value <= 1
            for value in (
                minimum_pck,
                minimum_joint_coverage,
                minimum_depth_coverage,
                minimum_sampled_depth_coverage,
            )
        ):
            raise ValueError("PCK and coverage gates must be between 0 and 1.")
        if maximum_duration is not None and float(maximum_duration) <= 0:
            raise ValueError("maximum_duration_seconds must be positive.")
        artist = SkeletonGuidance.model_validate(raw["artist_skeleton"])
        expected = SkeletonGuidance.model_validate(raw["ground_truth_skeleton"])
        if not artist.semantic_joint_map() or not expected.semantic_joint_map():
            raise ValueError("Both benchmark skeletons require semantic joint labels.")
        annotation_status = str(raw.get("annotation_status", "unreviewed"))
        if annotation_status != "approved" and not allow_unreviewed:
            raise ValueError(
                f"Case {raw['id']}: annotation status is {annotation_status}; "
                "human QA approval is required."
            )
        source_fingerprint = raw.get("source_media_fingerprint")
        if annotation_status == "approved":
            review = raw.get("review")
            if not isinstance(review, dict):
                raise ValueError(f"Case {raw['id']}: approved annotation has no review record.")
            for field in ("reviewer", "reviewed_at", "ground_truth_skeleton_sha256"):
                if not isinstance(review.get(field), str) or not review[field]:
                    raise ValueError(f"Case {raw['id']}: review field {field} is required.")
            if review["ground_truth_skeleton_sha256"] != skeleton_sha256(expected):
                raise ValueError(
                    f"Case {raw['id']}: ground-truth skeleton changed after human QA approval."
                )
            if not isinstance(source_fingerprint, str) or not source_fingerprint:
                raise ValueError(
                    f"Case {raw['id']}: approved annotation requires a media fingerprint."
                )
            if review.get("source_media_fingerprint") != source_fingerprint:
                raise ValueError(
                    f"Case {raw['id']}: source-media fingerprint changed after QA approval."
                )
            history = validate_review_history(raw.get("review_history"))
            latest = history[-1]
            if latest.get("status") != "approved":
                raise ValueError(f"Case {raw['id']}: latest review is not approved.")
            for field in (
                "reviewer",
                "reviewed_at",
                "notes",
                "source_media_fingerprint",
                "ground_truth_skeleton_sha256",
                "previous_review_sha256",
                "review_sha256",
            ):
                if latest.get(field) != review.get(field):
                    raise ValueError(f"Case {raw['id']}: active review differs from its history.")
        cases.append(
            DepthPoseBenchmarkCase(
                case_id=str(raw["id"]),
                media_path=(root / str(raw["media"])).resolve(),
                frame_number=int(raw["frame"]),
                artist_skeleton=artist,
                ground_truth_skeleton=expected,
                pck_threshold=threshold,
                minimum_pck=minimum_pck,
                minimum_joint_coverage=minimum_joint_coverage,
                minimum_depth_coverage=minimum_depth_coverage,
                minimum_sampled_depth_coverage=minimum_sampled_depth_coverage,
                maximum_duration_seconds=(
                    float(maximum_duration) if maximum_duration is not None else None
                ),
                annotation_status=annotation_status,
                source_media_fingerprint=(
                    str(source_fingerprint) if source_fingerprint is not None else None
                ),
                depth_sequence=(
                    str(raw["depth_sequence"]) if raw.get("depth_sequence") is not None else None
                ),
            )
        )
    return str(payload.get("suite", path.stem)), tuple(cases)


def pose_metrics(
    expected: SkeletonGuidance,
    detected: SkeletonGuidance,
    joint_confidences: dict[str, float],
    depth_confidences: dict[str, float],
    joint_depths: dict[str, float],
    *,
    pck_threshold: float,
) -> PoseMetricValues:
    expected_map = expected.semantic_joint_map()
    detected_map = detected.semantic_joint_map()
    labels = sorted(set(expected_map) & set(detected_map))
    errors = [
        float(
            np.hypot(
                expected_map[label].x - detected_map[label].x,
                expected_map[label].y - detected_map[label].y,
            )
        )
        for label in labels
    ]
    expected_count = len(expected_map)
    matched = len(labels)
    sampled_labels = [label for label in labels if label in joint_depths]
    sampled_values = [joint_depths[label] for label in sampled_labels]
    detected_by_id = {joint.id: joint for joint in detected.joints}
    bone_deltas: list[float] = []
    for bone in detected.bones:
        start = detected_by_id[bone.start_joint_id].label
        end = detected_by_id[bone.end_joint_id].label
        if start in joint_depths and end in joint_depths:
            bone_deltas.append(abs(joint_depths[start] - joint_depths[end]))
    return {
        "matched_joints": matched,
        "expected_joints": expected_count,
        "mean_joint_error": float(np.mean(errors)) if errors else 1.0,
        "pck": sum(error <= pck_threshold for error in errors) / expected_count,
        "joint_coverage": matched / expected_count,
        "depth_coverage": sum(label in depth_confidences for label in labels) / expected_count,
        "mean_joint_confidence": (
            float(np.mean([joint_confidences.get(label, 0.0) for label in labels]))
            if labels
            else 0.0
        ),
        "mean_depth_confidence": (
            float(np.mean([depth_confidences.get(label, 0.0) for label in labels]))
            if labels
            else 0.0
        ),
        "sampled_depth_coverage": len(sampled_labels) / expected_count,
        "mean_sampled_depth": float(np.mean(sampled_values)) if sampled_values else None,
        "minimum_sampled_depth": min(sampled_values) if sampled_values else None,
        "maximum_sampled_depth": max(sampled_values) if sampled_values else None,
        "mean_bone_depth_delta": float(np.mean(bone_deltas)) if bone_deltas else None,
    }


def run_benchmark(
    cases: Sequence[DepthPoseBenchmarkCase],
    capability: SkeletonDetectionCapability,
    *,
    media_reader: MediaReader | None = None,
) -> tuple[DepthPoseBenchmarkResult, ...]:
    reader = media_reader or PyAvMediaReader()
    results: list[DepthPoseBenchmarkResult] = []
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
            image = reader.read_frame(case.media_path, case.frame_number)
            detection = capability.detect(
                frame_number=case.frame_number,
                image=image,
                artist_skeleton=case.artist_skeleton,
            )
            metrics = pose_metrics(
                case.ground_truth_skeleton,
                detection.skeleton,
                detection.joint_confidences,
                detection.depth_confidences,
                detection.joint_depths,
                pck_threshold=case.pck_threshold,
            )
            duration = perf_counter() - started
            gates = (
                DepthPoseGateResult(
                    "pck",
                    float(metrics["pck"]),
                    case.minimum_pck,
                    ">=",
                    float(metrics["pck"]) >= case.minimum_pck,
                ),
                DepthPoseGateResult(
                    "joint_coverage",
                    float(metrics["joint_coverage"]),
                    case.minimum_joint_coverage,
                    ">=",
                    float(metrics["joint_coverage"]) >= case.minimum_joint_coverage,
                ),
                DepthPoseGateResult(
                    "depth_coverage",
                    float(metrics["depth_coverage"]),
                    case.minimum_depth_coverage,
                    ">=",
                    float(metrics["depth_coverage"]) >= case.minimum_depth_coverage,
                ),
                DepthPoseGateResult(
                    "sampled_depth_coverage",
                    float(metrics["sampled_depth_coverage"]),
                    case.minimum_sampled_depth_coverage,
                    ">=",
                    float(metrics["sampled_depth_coverage"]) >= case.minimum_sampled_depth_coverage,
                ),
                DepthPoseGateResult(
                    "duration_seconds",
                    duration,
                    case.maximum_duration_seconds,
                    "<=",
                    (
                        duration <= case.maximum_duration_seconds
                        if case.maximum_duration_seconds is not None
                        else None
                    ),
                ),
            )
            passed = all(gate.passed is not False for gate in gates)
            results.append(
                DepthPoseBenchmarkResult(
                    case_id=case.case_id,
                    status="passed" if passed else "failed",
                    frame_number=case.frame_number,
                    matched_joints=int(metrics["matched_joints"]),
                    expected_joints=int(metrics["expected_joints"]),
                    mean_joint_error=float(metrics["mean_joint_error"]),
                    pck=float(metrics["pck"]),
                    joint_coverage=float(metrics["joint_coverage"]),
                    depth_coverage=float(metrics["depth_coverage"]),
                    mean_joint_confidence=float(metrics["mean_joint_confidence"]),
                    mean_depth_confidence=float(metrics["mean_depth_confidence"]),
                    sampled_depth_coverage=float(metrics["sampled_depth_coverage"]),
                    mean_sampled_depth=(
                        float(metrics["mean_sampled_depth"])
                        if metrics["mean_sampled_depth"] is not None
                        else None
                    ),
                    minimum_sampled_depth=(
                        float(metrics["minimum_sampled_depth"])
                        if metrics["minimum_sampled_depth"] is not None
                        else None
                    ),
                    maximum_sampled_depth=(
                        float(metrics["maximum_sampled_depth"])
                        if metrics["maximum_sampled_depth"] is not None
                        else None
                    ),
                    mean_bone_depth_delta=(
                        float(metrics["mean_bone_depth_delta"])
                        if metrics["mean_bone_depth_delta"] is not None
                        else None
                    ),
                    depth_sequence=case.depth_sequence,
                    sampled_joint_depths=dict(detection.joint_depths),
                    duration_seconds=duration,
                    pck_threshold=case.pck_threshold,
                    gates=gates,
                    adapter=detection.provenance.adapter,
                    model_identifier=detection.provenance.model_identifier,
                    device=detection.provenance.device,
                )
            )
        except Exception as exc:
            duration = perf_counter() - started
            results.append(
                DepthPoseBenchmarkResult(
                    case_id=case.case_id,
                    status="error",
                    frame_number=case.frame_number,
                    matched_joints=0,
                    expected_joints=len(case.ground_truth_skeleton.semantic_joint_map()),
                    mean_joint_error=1.0,
                    pck=0.0,
                    joint_coverage=0.0,
                    depth_coverage=0.0,
                    mean_joint_confidence=0.0,
                    mean_depth_confidence=0.0,
                    sampled_depth_coverage=0.0,
                    mean_sampled_depth=None,
                    minimum_sampled_depth=None,
                    maximum_sampled_depth=None,
                    mean_bone_depth_delta=None,
                    depth_sequence=case.depth_sequence,
                    sampled_joint_depths={},
                    duration_seconds=duration,
                    pck_threshold=case.pck_threshold,
                    gates=(
                        DepthPoseGateResult("pck", None, case.minimum_pck, ">=", None),
                        DepthPoseGateResult(
                            "joint_coverage",
                            None,
                            case.minimum_joint_coverage,
                            ">=",
                            None,
                        ),
                        DepthPoseGateResult(
                            "depth_coverage",
                            None,
                            case.minimum_depth_coverage,
                            ">=",
                            None,
                        ),
                        DepthPoseGateResult(
                            "sampled_depth_coverage",
                            None,
                            case.minimum_sampled_depth_coverage,
                            ">=",
                            None,
                        ),
                        DepthPoseGateResult(
                            "duration_seconds",
                            duration,
                            case.maximum_duration_seconds,
                            "<=",
                            None,
                        ),
                    ),
                    error=str(exc),
                )
            )
    return tuple(results)


def temporal_depth_metrics(
    results: Sequence[DepthPoseBenchmarkResult],
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, list[DepthPoseBenchmarkResult]] = {}
    for result in results:
        if result.depth_sequence and result.status in {"passed", "failed"}:
            grouped.setdefault(result.depth_sequence, []).append(result)
    transitions: list[dict[str, Any]] = []
    for sequence, group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: (item.frame_number, item.case_id))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            labels = sorted(set(previous.sampled_joint_depths) & set(current.sampled_joint_depths))
            if not labels:
                transitions.append(
                    {
                        "depth_sequence": sequence,
                        "from_case": previous.case_id,
                        "to_case": current.case_id,
                        "from_frame": previous.frame_number,
                        "to_frame": current.frame_number,
                        "matched_labels": 0,
                        "mean_absolute_depth_delta": None,
                        "maximum_absolute_depth_delta": None,
                        "mean_relative_depth_delta": None,
                        "maximum_relative_depth_delta": None,
                        "relative_depth_comparable": False,
                    }
                )
                continue
            deltas = [
                abs(current.sampled_joint_depths[label] - previous.sampled_joint_depths[label])
                for label in labels
            ]
            previous_values = [previous.sampled_joint_depths[label] for label in labels]
            current_values = [current.sampled_joint_depths[label] for label in labels]
            previous_range = max(previous_values) - min(previous_values)
            current_range = max(current_values) - min(current_values)
            if previous_range > 1e-9 and current_range > 1e-9:
                relative_deltas = [
                    abs(
                        (current.sampled_joint_depths[label] - min(current_values)) / current_range
                        - (previous.sampled_joint_depths[label] - min(previous_values))
                        / previous_range
                    )
                    for label in labels
                ]
                mean_relative_delta: float | None = float(np.mean(relative_deltas))
                maximum_relative_delta: float | None = max(relative_deltas)
            else:
                mean_relative_delta = None
                maximum_relative_delta = None
            transitions.append(
                {
                    "depth_sequence": sequence,
                    "from_case": previous.case_id,
                    "to_case": current.case_id,
                    "from_frame": previous.frame_number,
                    "to_frame": current.frame_number,
                    "matched_labels": len(labels),
                    "mean_absolute_depth_delta": float(np.mean(deltas)),
                    "maximum_absolute_depth_delta": max(deltas),
                    "mean_relative_depth_delta": mean_relative_delta,
                    "maximum_relative_depth_delta": maximum_relative_delta,
                    "relative_depth_comparable": mean_relative_delta is not None,
                }
            )
    return tuple(transitions)


def evaluate_suite(
    results: Sequence[DepthPoseBenchmarkResult],
    gates: DepthPoseSuiteGates | None = None,
) -> DepthPoseSuiteEvaluation:
    temporal = temporal_depth_metrics(results)
    relative_deltas = [
        float(item["mean_relative_depth_delta"])
        for item in temporal
        if item["mean_relative_depth_delta"] is not None
    ]
    temporal_mean = float(np.mean(relative_deltas)) if relative_deltas else None
    transition_count = len(temporal)
    comparable_count = len(relative_deltas)
    transition_coverage = comparable_count / transition_count if transition_count > 0 else None
    configured = gates or DepthPoseSuiteGates()
    gate_results: list[DepthPoseGateResult] = []
    maximum_temporal = configured.maximum_mean_temporal_relative_depth_delta
    if maximum_temporal is not None:
        gate_results.append(
            DepthPoseGateResult(
                name="mean_temporal_relative_depth_delta",
                actual=temporal_mean,
                required=maximum_temporal,
                operator="<=",
                passed=temporal_mean is not None and temporal_mean <= maximum_temporal,
            )
        )
    minimum_coverage = configured.minimum_temporal_transition_coverage
    if minimum_coverage is not None:
        gate_results.append(
            DepthPoseGateResult(
                name="temporal_transition_coverage",
                actual=transition_coverage,
                required=minimum_coverage,
                operator=">=",
                passed=(
                    transition_coverage is not None and transition_coverage >= minimum_coverage
                ),
            )
        )
    return DepthPoseSuiteEvaluation(
        passed=(
            bool(results)
            and all(result.status == "passed" for result in results)
            and all(gate.passed is True for gate in gate_results)
        ),
        temporal=temporal,
        mean_temporal_relative_depth_delta=temporal_mean,
        temporal_transition_count=transition_count,
        comparable_temporal_transition_count=comparable_count,
        temporal_transition_coverage=transition_coverage,
        gate_results=tuple(gate_results),
    )


def write_report(
    output: Path,
    suite: str,
    results: Sequence[DepthPoseBenchmarkResult],
    *,
    gates: DepthPoseSuiteGates | None = None,
) -> Path:
    completed = [result for result in results if result.status in {"passed", "failed"}]
    evaluation = evaluate_suite(results, gates)
    temporal = evaluation.temporal
    summary: dict[str, Any] = {
        "case_total": len(results),
        "case_completed": len(completed),
        "case_passed": sum(result.status == "passed" for result in results),
        "passed": evaluation.passed,
        "mean_joint_error": (
            float(np.mean([result.mean_joint_error for result in completed])) if completed else 1.0
        ),
        "mean_pck": float(np.mean([result.pck for result in completed])) if completed else 0.0,
        "mean_joint_coverage": (
            float(np.mean([result.joint_coverage for result in completed])) if completed else 0.0
        ),
        "mean_depth_coverage": (
            float(np.mean([result.depth_coverage for result in completed])) if completed else 0.0
        ),
        "mean_sampled_depth_coverage": (
            float(np.mean([result.sampled_depth_coverage for result in completed]))
            if completed
            else 0.0
        ),
        "mean_duration_seconds": (
            float(np.mean([result.duration_seconds for result in completed])) if completed else 0.0
        ),
        "temporal_depth_transition_count": evaluation.temporal_transition_count,
        "comparable_temporal_depth_transition_count": (
            evaluation.comparable_temporal_transition_count
        ),
        "temporal_depth_transition_coverage": evaluation.temporal_transition_coverage,
        "mean_temporal_relative_depth_delta": (evaluation.mean_temporal_relative_depth_delta),
        "suite_gate_results": [asdict(gate) for gate in evaluation.gate_results],
    }
    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "schema_version": "1.1",
        "generated_at": generated_at,
        "suite": suite,
        "summary": summary,
        "results": [asdict(result) for result in results],
        "temporal_depth": list(temporal),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_output = output.with_suffix(".md")
    markdown_output.write_text(
        _render_markdown_report(
            suite=suite,
            generated_at=generated_at,
            summary=summary,
            results=results,
            temporal=temporal,
        ),
        encoding="utf-8",
    )
    return output


def _format_metric(value: object, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", " ")


def _render_markdown_report(
    *,
    suite: str,
    generated_at: str,
    summary: dict[str, Any],
    results: Sequence[DepthPoseBenchmarkResult],
    temporal: Sequence[dict[str, Any]],
) -> str:
    decision = "PASS" if summary["passed"] else "FAIL"
    temporal_mean = _format_metric(summary["mean_temporal_relative_depth_delta"])
    lines = [
        f"# {_markdown_cell(suite)} — Depth/Pose Benchmark",
        "",
        f"Generated: `{generated_at}`  ",
        f"Decision: **{decision}**",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['case_passed']}/{summary['case_total']} passed "
        f"({summary['case_completed']} completed)",
        f"- Mean joint error: {_format_metric(summary['mean_joint_error'])}",
        f"- Mean PCK: {_format_metric(summary['mean_pck'])}",
        f"- Mean joint coverage: {_format_metric(summary['mean_joint_coverage'])}",
        f"- Mean depth coverage: {_format_metric(summary['mean_depth_coverage'])}",
        f"- Mean sampled-depth coverage: {_format_metric(summary['mean_sampled_depth_coverage'])}",
        f"- Mean duration: {_format_metric(summary['mean_duration_seconds'])} s",
        f"- Temporal transitions: {summary['temporal_depth_transition_count']}",
        "- Comparable temporal transitions: "
        f"{summary['comparable_temporal_depth_transition_count']}",
        "- Temporal transition coverage: "
        f"{_format_metric(summary['temporal_depth_transition_coverage'])}",
        f"- Mean temporal relative-depth delta: {temporal_mean}",
    ]
    suite_gates = summary["suite_gate_results"]
    if suite_gates:
        lines.extend(
            [
                "",
                "## Suite Gate Evidence",
                "",
                "| Gate | Actual | Requirement | Decision |",
                "|---|---:|---:|---:|",
            ]
        )
        for gate in suite_gates:
            lines.append(
                f"| {_markdown_cell(gate['name'])} | {_format_metric(gate['actual'])} | "
                f"{gate['operator']} {_format_metric(gate['required'])} | "
                f"{'PASS' if gate['passed'] else 'FAIL'} |"
            )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Status | Frame | Joint error | PCK | PCK radius | Joint cov. | "
            "Depth cov. | Sampled-depth cov. | Depth range | Time (s) | Gates | Runtime |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for result in results:
        if result.minimum_sampled_depth is None or result.maximum_sampled_depth is None:
            depth_range = "—"
        else:
            depth_range = (
                f"{_format_metric(result.minimum_sampled_depth)}–"
                f"{_format_metric(result.maximum_sampled_depth)}"
            )
        runtime = (
            " / ".join(
                value for value in (result.adapter, result.model_identifier, result.device) if value
            )
            or "—"
        )
        gate_summary = (
            ", ".join(
                f"{gate.name} "
                + ("N/A" if gate.passed is None else "PASS" if gate.passed else "FAIL")
                for gate in result.gates
            )
            or "—"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(result.case_id),
                    _markdown_cell(result.status.upper()),
                    str(result.frame_number),
                    _format_metric(result.mean_joint_error),
                    _format_metric(result.pck),
                    _format_metric(result.pck_threshold),
                    _format_metric(result.joint_coverage),
                    _format_metric(result.depth_coverage),
                    _format_metric(result.sampled_depth_coverage),
                    depth_range,
                    _format_metric(result.duration_seconds),
                    gate_summary,
                    _markdown_cell(runtime),
                ]
            )
            + " |"
        )

    configured_gates = [
        (result, gate) for result in results for gate in result.gates if gate.required is not None
    ]
    if configured_gates:
        lines.extend(
            [
                "",
                "## Gate Evidence",
                "",
                "| Case | Gate | Actual | Requirement | Decision |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for result, gate in configured_gates:
            lines.append(
                f"| {_markdown_cell(result.case_id)} | {_markdown_cell(gate.name)} | "
                f"{_format_metric(gate.actual)} | {gate.operator} "
                f"{_format_metric(gate.required)} | "
                f"{'N/A' if gate.passed is None else 'PASS' if gate.passed else 'FAIL'} |"
            )

    errors = [result for result in results if result.error]
    if errors:
        lines.extend(["", "## Errors", ""])
        for result in errors:
            lines.append(f"- **{_markdown_cell(result.case_id)}:** {_markdown_cell(result.error)}")

    if temporal:
        lines.extend(
            [
                "",
                "## Temporal Depth",
                "",
                "| Sequence | Transition | Frames | Matched | Mean absolute delta | "
                "Mean relative delta | Comparable |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in temporal:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(item["depth_sequence"]),
                        _markdown_cell(f"{item['from_case']} → {item['to_case']}"),
                        f"{item['from_frame']} → {item['to_frame']}",
                        str(item["matched_labels"]),
                        _format_metric(item["mean_absolute_depth_delta"]),
                        _format_metric(item["mean_relative_depth_delta"]),
                        "YES" if item["relative_depth_comparable"] else "NO",
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "> Sampled and temporal depth values are observational monocular-depth signals. "
            "They are not metric distances. Relative temporal deltas normalize each frame's "
            "sampled depth range to reduce scale and offset ambiguity.",
            "",
        ]
    )
    return "\n".join(lines)


def review_case(
    manifest_path: Path,
    case_id: str,
    *,
    status: str,
    reviewer: str,
    notes: str = "",
) -> None:
    if status not in {"approved", "rejected"}:
        raise ValueError("Review status must be approved or rejected.")
    if not reviewer.strip():
        raise ValueError("Reviewer is required for Depth/Pose QA decisions.")
    manifest_path = manifest_path.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Depth/Pose manifest is invalid.")
    matches = [
        item for item in payload["cases"] if isinstance(item, dict) and item.get("id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Depth/Pose case must exist exactly once: {case_id}")
    case = matches[0]
    expected = SkeletonGuidance.model_validate(case.get("ground_truth_skeleton"))
    source_fingerprint = case.get("source_media_fingerprint")
    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise ValueError("Source media fingerprint is required before review.")
    history_raw = case.get("review_history", [])
    if not isinstance(history_raw, list):
        raise ValueError("Depth/Pose review history is invalid.")
    previous = (
        str(validate_review_history(history_raw)[-1]["review_sha256"]) if history_raw else None
    )
    record: dict[str, object] = {
        "status": status,
        "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "notes": notes.strip(),
        "source_media_fingerprint": source_fingerprint,
        "ground_truth_skeleton_sha256": skeleton_sha256(expected),
        "previous_review_sha256": previous,
    }
    record["review_sha256"] = review_record_sha256(record)
    case["annotation_status"] = status
    case["review"] = {key: value for key, value in record.items() if key != "status"}
    case["review_history"] = [*history_raw, record]
    temporary = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, manifest_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark semantic browser Depth/Pose detection.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("depth_pose_benchmark.json"))
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="Development only: run candidate annotations without human QA approval",
    )
    args = parser.parse_args()
    suite, cases = load_manifest(args.manifest, allow_unreviewed=args.allow_unreviewed)
    gates = load_suite_gates(args.manifest)
    selection = select_skeleton_detection()
    results = run_benchmark(cases, selection.capability)
    report = write_report(args.output, suite, results, gates=gates)
    print(report)
    if not evaluate_suite(results, gates).passed:
        raise SystemExit(1)


def review_main() -> None:
    parser = argparse.ArgumentParser(description="Review a Depth/Pose benchmark annotation.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("case_id")
    parser.add_argument("--status", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    review_case(
        args.manifest,
        args.case_id,
        status=args.status,
        reviewer=args.reviewer,
        notes=args.notes,
    )


if __name__ == "__main__":
    main()
