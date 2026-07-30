import json
from pathlib import Path

from nova_layer.benchmark_comparison import (
    compare_benchmark_reports,
    write_comparison_report,
)


def _write_report(
    path: Path,
    results: list[tuple[str, float, float]],
    *,
    passed: bool = True,
) -> None:
    path.write_text(
        json.dumps(
            {
                "suite": "Representative Shots",
                "summary": {"passed": passed},
                "results": [
                    {
                        "case_id": case_id,
                        "iou": iou,
                        "duration_seconds": duration,
                    }
                    for case_id, iou, duration in results
                ],
            }
        ),
        encoding="utf-8",
    )


def test_benchmark_comparison_accepts_non_regressing_candidate(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, [("person", 0.90, 10.0), ("hair", 0.85, 12.0)])
    _write_report(candidate, [("person", 0.91, 10.5), ("hair", 0.85, 12.5)])

    comparison = compare_benchmark_reports(baseline, candidate)
    assert comparison.passed
    assert comparison.shared_cases == 2
    assert comparison.mean_iou_delta > 0
    json_path, markdown_path = write_comparison_report(tmp_path / "reports", comparison)
    assert json.loads(json_path.read_text(encoding="utf-8"))["passed"]
    assert "Decision: **PASS**" in markdown_path.read_text(encoding="utf-8")


def test_benchmark_comparison_blocks_quality_latency_and_coverage_regressions(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, [("person", 0.92, 10.0), ("hair", 0.88, 10.0)])
    _write_report(candidate, [("person", 0.85, 15.0)], passed=False)

    comparison = compare_benchmark_reports(baseline, candidate)
    assert not comparison.passed
    assert comparison.removed_cases == ("hair",)
    assert comparison.regressed_cases == ("person",)
    assert len(comparison.reasons) == 5
