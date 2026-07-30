import json
from pathlib import Path

import pytest

from nova_layer.benchmark_baseline import promote_benchmark_baseline
from nova_layer.depth_pose_comparison import compare_depth_pose_reports, write_comparison


def write_report(
    path: Path,
    *,
    error: float,
    pck: float,
    coverage: float,
    duration: float,
    temporal: float | None,
    passed: bool = True,
) -> None:
    path.write_text(
        json.dumps(
            {
                "suite": "Pose Suite",
                "summary": {
                    "passed": passed,
                    "mean_joint_error": error,
                    "mean_pck": pck,
                    "mean_joint_coverage": coverage,
                    "mean_depth_coverage": coverage,
                    "mean_sampled_depth_coverage": coverage,
                    "mean_duration_seconds": duration,
                    "mean_temporal_relative_depth_delta": temporal,
                    "temporal_depth_transition_coverage": coverage,
                },
                "results": [
                    {
                        "case_id": "person",
                        "mean_joint_error": error,
                        "pck": pck,
                        "joint_coverage": coverage,
                        "depth_coverage": coverage,
                        "sampled_depth_coverage": coverage,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_depth_pose_comparison_accepts_stable_candidate(tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "base.json", tmp_path / "candidate.json"
    write_report(baseline, error=0.04, pck=0.9, coverage=0.9, duration=10, temporal=0.1)
    write_report(candidate, error=0.035, pck=0.92, coverage=0.91, duration=11, temporal=0.09)

    comparison = compare_depth_pose_reports(baseline, candidate)

    assert comparison.passed
    json_path, markdown_path = write_comparison(tmp_path / "report", comparison)
    assert json.loads(json_path.read_text(encoding="utf-8"))["passed"]
    assert "Decision: **PASS**" in markdown_path.read_text(encoding="utf-8")
    promotion = promote_benchmark_baseline(
        candidate,
        json_path,
        tmp_path / "registry",
        label="depth-pose-webgpu",
    )
    assert promotion.baseline_path.read_bytes() == candidate.read_bytes()


def test_depth_pose_comparison_blocks_quality_and_latency_regression(tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "base.json", tmp_path / "candidate.json"
    write_report(baseline, error=0.03, pck=0.95, coverage=0.95, duration=10, temporal=0.05)
    write_report(
        candidate,
        error=0.08,
        pck=0.8,
        coverage=0.8,
        duration=15,
        temporal=0.2,
        passed=False,
    )

    comparison = compare_depth_pose_reports(baseline, candidate)

    assert not comparison.passed
    assert comparison.regressed_cases == ("person",)
    assert len(comparison.reasons) == 10


def test_depth_pose_comparison_blocks_removed_cases(tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "base.json", tmp_path / "candidate.json"
    write_report(baseline, error=0.04, pck=0.9, coverage=0.9, duration=10, temporal=0.1)
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["results"].append(
        {
            "case_id": "person-b",
            "mean_joint_error": 0.04,
            "pck": 0.9,
            "joint_coverage": 0.9,
            "depth_coverage": 0.9,
            "sampled_depth_coverage": 0.9,
        }
    )
    baseline.write_text(json.dumps(payload), encoding="utf-8")
    write_report(candidate, error=0.04, pck=0.9, coverage=0.9, duration=10, temporal=0.1)

    comparison = compare_depth_pose_reports(baseline, candidate)

    assert not comparison.passed
    assert comparison.removed_cases == ("person-b",)
    assert "missing baseline cases" in comparison.reasons[0]


def test_depth_pose_comparison_blocks_temporal_coverage_drop(tmp_path: Path) -> None:
    baseline, candidate = tmp_path / "base.json", tmp_path / "candidate.json"
    write_report(baseline, error=0.04, pck=0.9, coverage=0.95, duration=10, temporal=0.1)
    write_report(candidate, error=0.04, pck=0.9, coverage=0.95, duration=10, temporal=0.1)
    candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate_payload["summary"]["temporal_depth_transition_coverage"] = 0.5
    candidate.write_text(json.dumps(candidate_payload), encoding="utf-8")

    comparison = compare_depth_pose_reports(baseline, candidate)

    assert not comparison.passed
    assert comparison.temporal_transition_coverage_delta == pytest.approx(-0.45)
    assert any("Temporal transition coverage" in reason for reason in comparison.reasons)
