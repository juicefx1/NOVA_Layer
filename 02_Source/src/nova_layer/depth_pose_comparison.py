from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nova_layer.benchmark_comparison import report_sha256


@dataclass(frozen=True, slots=True)
class DepthPoseComparison:
    passed: bool
    baseline_report_sha256: str
    candidate_report_sha256: str
    baseline_mean_joint_error: float
    candidate_mean_joint_error: float
    mean_joint_error_delta: float
    baseline_mean_pck: float
    candidate_mean_pck: float
    mean_pck_delta: float
    joint_coverage_delta: float
    depth_coverage_delta: float
    sampled_depth_coverage_delta: float
    latency_increase_fraction: float
    temporal_relative_depth_delta_change: float | None
    temporal_transition_coverage_delta: float | None
    shared_cases: int
    added_cases: tuple[str, ...]
    removed_cases: tuple[str, ...]
    regressed_cases: tuple[str, ...]
    candidate_gates_passed: bool
    reasons: tuple[str, ...]


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError(f"Invalid Depth/Pose benchmark report: {path}")
    if not isinstance(payload.get("summary"), dict):
        raise ValueError(f"Depth/Pose report has no summary: {path}")
    return payload


def _results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for raw in payload["results"]:
        if not isinstance(raw, dict) or "case_id" not in raw:
            raise ValueError("Depth/Pose report contains an invalid result.")
        case_id = str(raw["case_id"])
        if case_id in mapped:
            raise ValueError(f"Depth/Pose report contains duplicate case ID: {case_id}")
        mapped[case_id] = raw
    return mapped


def _number(mapping: dict[str, Any], name: str) -> float:
    value = mapping.get(name)
    if not isinstance(value, int | float):
        raise ValueError(f"Depth/Pose report is missing numeric {name}.")
    return float(value)


def _optional_number(mapping: dict[str, Any], name: str) -> float | None:
    value = mapping.get(name)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"Depth/Pose report has invalid {name}.")
    return float(value)


def compare_depth_pose_reports(
    baseline_path: Path,
    candidate_path: Path,
    *,
    maximum_joint_error_increase: float = 0.01,
    maximum_pck_drop: float = 0.02,
    maximum_coverage_drop: float = 0.02,
    maximum_latency_increase_fraction: float = 0.2,
    maximum_temporal_depth_delta_increase: float = 0.05,
) -> DepthPoseComparison:
    thresholds = (
        maximum_joint_error_increase,
        maximum_pck_drop,
        maximum_coverage_drop,
        maximum_latency_increase_fraction,
        maximum_temporal_depth_delta_increase,
    )
    if any(value < 0 for value in thresholds):
        raise ValueError("Depth/Pose regression thresholds must be non-negative.")
    baseline = _load(baseline_path)
    candidate = _load(candidate_path)
    if baseline.get("suite") != candidate.get("suite"):
        raise ValueError("Depth/Pose reports belong to different suites.")
    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    baseline_results = _results(baseline)
    candidate_results = _results(candidate)
    baseline_ids, candidate_ids = set(baseline_results), set(candidate_results)
    shared = baseline_ids & candidate_ids
    removed = tuple(sorted(baseline_ids - candidate_ids))
    added = tuple(sorted(candidate_ids - baseline_ids))
    regressed = tuple(
        sorted(
            case_id
            for case_id in shared
            if (
                _number(candidate_results[case_id], "mean_joint_error")
                - _number(baseline_results[case_id], "mean_joint_error")
                > maximum_joint_error_increase
                or _number(baseline_results[case_id], "pck")
                - _number(candidate_results[case_id], "pck")
                > maximum_pck_drop
                or _number(baseline_results[case_id], "joint_coverage")
                - _number(candidate_results[case_id], "joint_coverage")
                > maximum_coverage_drop
                or _number(baseline_results[case_id], "depth_coverage")
                - _number(candidate_results[case_id], "depth_coverage")
                > maximum_coverage_drop
                or _number(baseline_results[case_id], "sampled_depth_coverage")
                - _number(candidate_results[case_id], "sampled_depth_coverage")
                > maximum_coverage_drop
            )
        )
    )
    baseline_error = _number(baseline_summary, "mean_joint_error")
    candidate_error = _number(candidate_summary, "mean_joint_error")
    baseline_pck = _number(baseline_summary, "mean_pck")
    candidate_pck = _number(candidate_summary, "mean_pck")
    joint_coverage_delta = _number(candidate_summary, "mean_joint_coverage") - _number(
        baseline_summary, "mean_joint_coverage"
    )
    depth_coverage_delta = _number(candidate_summary, "mean_depth_coverage") - _number(
        baseline_summary, "mean_depth_coverage"
    )
    sampled_depth_coverage_delta = _number(
        candidate_summary, "mean_sampled_depth_coverage"
    ) - _number(baseline_summary, "mean_sampled_depth_coverage")
    baseline_duration = _number(baseline_summary, "mean_duration_seconds")
    candidate_duration = _number(candidate_summary, "mean_duration_seconds")
    latency_increase = (
        (candidate_duration - baseline_duration) / baseline_duration
        if baseline_duration > 0
        else (0.0 if candidate_duration == 0 else float("inf"))
    )
    baseline_temporal = _optional_number(baseline_summary, "mean_temporal_relative_depth_delta")
    candidate_temporal = _optional_number(candidate_summary, "mean_temporal_relative_depth_delta")
    temporal_change = (
        candidate_temporal - baseline_temporal
        if baseline_temporal is not None and candidate_temporal is not None
        else None
    )
    baseline_temporal_coverage = _optional_number(
        baseline_summary, "temporal_depth_transition_coverage"
    )
    candidate_temporal_coverage = _optional_number(
        candidate_summary, "temporal_depth_transition_coverage"
    )
    temporal_coverage_change = (
        candidate_temporal_coverage - baseline_temporal_coverage
        if baseline_temporal_coverage is not None and candidate_temporal_coverage is not None
        else None
    )
    candidate_gates = candidate_summary.get("passed") is True
    reasons: list[str] = []
    if candidate_error - baseline_error > maximum_joint_error_increase:
        reasons.append("Mean joint error regression exceeds the allowed increase.")
    if baseline_pck - candidate_pck > maximum_pck_drop:
        reasons.append("Mean PCK regression exceeds the allowed drop.")
    if joint_coverage_delta < -maximum_coverage_drop:
        reasons.append("Mean joint coverage regression exceeds the allowed drop.")
    if depth_coverage_delta < -maximum_coverage_drop:
        reasons.append("Mean depth coverage regression exceeds the allowed drop.")
    if sampled_depth_coverage_delta < -maximum_coverage_drop:
        reasons.append("Mean sampled-depth coverage regression exceeds the allowed drop.")
    if latency_increase > maximum_latency_increase_fraction:
        reasons.append("Mean latency regression exceeds the allowed increase.")
    if temporal_change is not None and temporal_change > maximum_temporal_depth_delta_increase:
        reasons.append("Temporal relative-depth instability exceeds the allowed increase.")
    if temporal_coverage_change is not None and temporal_coverage_change < -maximum_coverage_drop:
        reasons.append("Temporal transition coverage regression exceeds the allowed drop.")
    if removed:
        reasons.append("Candidate report is missing baseline cases.")
    if regressed:
        reasons.append("One or more shared cases exceed an allowed regression threshold.")
    if not candidate_gates:
        reasons.append("Candidate report did not pass its configured suite gates.")
    return DepthPoseComparison(
        passed=not reasons,
        baseline_report_sha256=report_sha256(baseline_path),
        candidate_report_sha256=report_sha256(candidate_path),
        baseline_mean_joint_error=baseline_error,
        candidate_mean_joint_error=candidate_error,
        mean_joint_error_delta=candidate_error - baseline_error,
        baseline_mean_pck=baseline_pck,
        candidate_mean_pck=candidate_pck,
        mean_pck_delta=candidate_pck - baseline_pck,
        joint_coverage_delta=joint_coverage_delta,
        depth_coverage_delta=depth_coverage_delta,
        sampled_depth_coverage_delta=sampled_depth_coverage_delta,
        latency_increase_fraction=latency_increase,
        temporal_relative_depth_delta_change=temporal_change,
        temporal_transition_coverage_delta=temporal_coverage_change,
        shared_cases=len(shared),
        added_cases=added,
        removed_cases=removed,
        regressed_cases=regressed,
        candidate_gates_passed=candidate_gates,
        reasons=tuple(reasons),
    )


def write_comparison(output: Path, result: DepthPoseComparison) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    json_path = output / "depth_pose_regression_latest.json"
    markdown_path = output / "depth_pose_regression_latest.md"
    json_path.write_text(
        json.dumps({"generated_at": generated_at, **asdict(result)}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporal = result.temporal_relative_depth_delta_change
    temporal_coverage = result.temporal_transition_coverage_delta
    lines = [
        "# NOVA Depth/Pose Regression Comparison",
        "",
        f"Generated: {generated_at}",
        f"Decision: **{'PASS' if result.passed else 'FAIL'}**",
        "",
        f"- Mean joint error delta: {result.mean_joint_error_delta:+.4f}",
        f"- Mean PCK delta: {result.mean_pck_delta:+.4f}",
        f"- Joint coverage delta: {result.joint_coverage_delta:+.4f}",
        f"- Depth coverage delta: {result.depth_coverage_delta:+.4f}",
        f"- Sampled-depth coverage delta: {result.sampled_depth_coverage_delta:+.4f}",
        f"- Latency change: {result.latency_increase_fraction:+.1%}",
        f"- Temporal relative-depth delta change: "
        f"{f'{temporal:+.4f}' if temporal is not None else 'not comparable'}",
        f"- Temporal transition coverage delta: "
        f"{f'{temporal_coverage:+.4f}' if temporal_coverage is not None else 'not comparable'}",
        f"- Regressed cases: {', '.join(result.regressed_cases) or 'none'}",
        f"- Removed cases: {', '.join(result.removed_cases) or 'none'}",
    ]
    if result.reasons:
        lines.extend(["", "## Blocking Reasons", ""])
        lines.extend(f"- {reason}" for reason in result.reasons)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two Depth/Pose benchmark reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--maximum-joint-error-increase", type=float, default=0.01)
    parser.add_argument("--maximum-pck-drop", type=float, default=0.02)
    parser.add_argument("--maximum-coverage-drop", type=float, default=0.02)
    parser.add_argument("--maximum-latency-increase", type=float, default=0.2)
    parser.add_argument("--maximum-temporal-depth-increase", type=float, default=0.05)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_depth_pose_reports(
        args.baseline,
        args.candidate,
        maximum_joint_error_increase=args.maximum_joint_error_increase,
        maximum_pck_drop=args.maximum_pck_drop,
        maximum_coverage_drop=args.maximum_coverage_drop,
        maximum_latency_increase_fraction=args.maximum_latency_increase,
        maximum_temporal_depth_delta_increase=args.maximum_temporal_depth_increase,
    )
    json_path, markdown_path = write_comparison(args.output, result)
    print(f"Depth/Pose regression: {'PASS' if result.passed else 'FAIL'}")
    print(json_path)
    print(markdown_path)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
