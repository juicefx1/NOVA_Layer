from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    passed: bool
    baseline_report_sha256: str
    candidate_report_sha256: str
    baseline_mean_iou: float
    candidate_mean_iou: float
    mean_iou_delta: float
    baseline_mean_duration_seconds: float
    candidate_mean_duration_seconds: float
    latency_increase_fraction: float
    shared_cases: int
    added_cases: tuple[str, ...]
    removed_cases: tuple[str, ...]
    regressed_cases: tuple[str, ...]
    candidate_gates_passed: bool
    reasons: tuple[str, ...]


def _load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError(f"Invalid benchmark report: {path}")
    return payload


def report_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _result_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for raw in payload["results"]:
        if not isinstance(raw, dict) or "case_id" not in raw:
            raise ValueError("Benchmark report contains an invalid result.")
        case_id = str(raw["case_id"])
        if case_id in results:
            raise ValueError(f"Benchmark report contains duplicate case ID: {case_id}")
        results[case_id] = raw
    return results


def _mean(results: dict[str, dict[str, Any]], field: str) -> float:
    return (
        sum(float(item.get(field, 0.0)) for item in results.values()) / len(results)
        if results
        else 0.0
    )


def compare_benchmark_reports(
    baseline_path: Path,
    candidate_path: Path,
    *,
    maximum_iou_drop: float = 0.01,
    maximum_latency_increase_fraction: float = 0.2,
) -> BenchmarkComparison:
    if maximum_iou_drop < 0:
        raise ValueError("Maximum IoU drop must be non-negative.")
    if maximum_latency_increase_fraction < 0:
        raise ValueError("Maximum latency increase must be non-negative.")
    baseline = _load_report(baseline_path)
    candidate = _load_report(candidate_path)
    if baseline.get("suite") != candidate.get("suite"):
        raise ValueError("Benchmark reports belong to different suites.")
    baseline_results = _result_map(baseline)
    candidate_results = _result_map(candidate)
    baseline_ids = set(baseline_results)
    candidate_ids = set(candidate_results)
    shared = baseline_ids & candidate_ids
    added = tuple(sorted(candidate_ids - baseline_ids))
    removed = tuple(sorted(baseline_ids - candidate_ids))
    regressed = tuple(
        sorted(
            case_id
            for case_id in shared
            if float(baseline_results[case_id].get("iou", 0.0))
            - float(candidate_results[case_id].get("iou", 0.0))
            > maximum_iou_drop
        )
    )
    baseline_iou = _mean(baseline_results, "iou")
    candidate_iou = _mean(candidate_results, "iou")
    baseline_duration = _mean(baseline_results, "duration_seconds")
    candidate_duration = _mean(candidate_results, "duration_seconds")
    latency_increase = (
        (candidate_duration - baseline_duration) / baseline_duration
        if baseline_duration > 0
        else (0.0 if candidate_duration == 0 else float("inf"))
    )
    summary = candidate.get("summary")
    candidate_gates_passed = bool(summary.get("passed")) if isinstance(summary, dict) else False
    reasons: list[str] = []
    if candidate_iou < baseline_iou - maximum_iou_drop:
        reasons.append("Mean IoU regression exceeds the allowed drop.")
    if latency_increase > maximum_latency_increase_fraction:
        reasons.append("Mean latency regression exceeds the allowed increase.")
    if removed:
        reasons.append("Candidate report is missing baseline cases.")
    if regressed:
        reasons.append("One or more shared cases exceed the allowed IoU drop.")
    if not candidate_gates_passed:
        reasons.append("Candidate report did not pass its configured suite gates.")
    return BenchmarkComparison(
        passed=not reasons,
        baseline_report_sha256=report_sha256(baseline_path),
        candidate_report_sha256=report_sha256(candidate_path),
        baseline_mean_iou=baseline_iou,
        candidate_mean_iou=candidate_iou,
        mean_iou_delta=candidate_iou - baseline_iou,
        baseline_mean_duration_seconds=baseline_duration,
        candidate_mean_duration_seconds=candidate_duration,
        latency_increase_fraction=latency_increase,
        shared_cases=len(shared),
        added_cases=added,
        removed_cases=removed,
        regressed_cases=regressed,
        candidate_gates_passed=candidate_gates_passed,
        reasons=tuple(reasons),
    )


def write_comparison_report(output_dir: Path, result: BenchmarkComparison) -> tuple[Path, Path]:
    generated_at = datetime.now(UTC).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "real_footage_regression_latest.json"
    markdown_path = output_dir / "real_footage_regression_latest.md"
    payload = {"generated_at": generated_at, **asdict(result)}
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# NOVA Layer Real-Footage Regression Comparison",
        "",
        f"Generated: {generated_at}",
        f"Decision: **{'PASS' if result.passed else 'FAIL'}**",
        "",
        f"- Mean IoU: {result.baseline_mean_iou:.4f} → {result.candidate_mean_iou:.4f} "
        f"({result.mean_iou_delta:+.4f})",
        f"- Mean duration: {result.baseline_mean_duration_seconds:.3f}s → "
        f"{result.candidate_mean_duration_seconds:.3f}s "
        f"({result.latency_increase_fraction:+.1%})",
        f"- Shared cases: {result.shared_cases}",
        f"- Added cases: {', '.join(result.added_cases) or 'none'}",
        f"- Removed cases: {', '.join(result.removed_cases) or 'none'}",
        f"- Regressed cases: {', '.join(result.regressed_cases) or 'none'}",
    ]
    if result.reasons:
        lines.extend(["", "## Blocking Reasons", ""])
        lines.extend(f"- {reason}" for reason in result.reasons)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two real-footage benchmark reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--maximum-iou-drop", type=float, default=0.01)
    parser.add_argument("--maximum-latency-increase", type=float, default=0.2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_benchmark_reports(
        args.baseline,
        args.candidate,
        maximum_iou_drop=args.maximum_iou_drop,
        maximum_latency_increase_fraction=args.maximum_latency_increase,
    )
    json_path, markdown_path = write_comparison_report(args.output, result)
    print(f"Real-footage regression: {'PASS' if result.passed else 'FAIL'}")
    print(json_path)
    print(markdown_path)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
