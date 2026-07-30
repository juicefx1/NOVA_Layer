import json
from pathlib import Path

import pytest

from nova_layer.benchmark_baseline import (
    activate_registered_baseline,
    audit_baseline_registry,
    promote_benchmark_baseline,
)
from nova_layer.benchmark_comparison import (
    compare_benchmark_reports,
    write_comparison_report,
)


def _report(path: Path, iou: float) -> None:
    path.write_text(
        json.dumps(
            {
                "suite": "Representative Shots",
                "runtime_mode": "sam2_mps",
                "summary": {"passed": True},
                "results": [{"case_id": "person", "iou": iou, "duration_seconds": 10.0}],
            }
        ),
        encoding="utf-8",
    )


def test_passing_candidate_is_promoted_as_immutable_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, 0.90)
    _report(candidate, 0.91)
    comparison = compare_benchmark_reports(baseline, candidate)
    comparison_json, _ = write_comparison_report(tmp_path / "comparison", comparison)

    promotion = promote_benchmark_baseline(
        candidate,
        comparison_json,
        tmp_path / "registry",
        label="sam2 tiny mps",
    )
    assert promotion.label == "sam2-tiny-mps"
    assert promotion.baseline_path.read_bytes() == candidate.read_bytes()
    registry = json.loads(promotion.registry_path.read_text(encoding="utf-8"))
    assert registry["active_baseline"]["report_sha256"] == promotion.report_sha256
    assert len(registry["history"]) == 1
    audit = audit_baseline_registry(tmp_path / "registry")
    assert audit.valid
    assert audit.checked_snapshots == 1
    assert (
        activate_registered_baseline(tmp_path / "registry", "sam2-tiny-mps")
        == promotion.baseline_path
    )
    activated_registry = json.loads(promotion.registry_path.read_text(encoding="utf-8"))
    assert len(activated_registry["activation_history"]) == 1

    with pytest.raises(ValueError, match="already exists"):
        promote_benchmark_baseline(
            candidate,
            comparison_json,
            tmp_path / "registry",
            label="sam2 tiny mps",
        )


def test_modified_candidate_cannot_reuse_regression_approval(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, 0.90)
    _report(candidate, 0.91)
    comparison = compare_benchmark_reports(baseline, candidate)
    comparison_json, _ = write_comparison_report(tmp_path / "comparison", comparison)
    _report(candidate, 0.70)

    with pytest.raises(ValueError, match="differs from the report approved"):
        promote_benchmark_baseline(
            candidate,
            comparison_json,
            tmp_path / "registry",
            label="tampered-candidate",
        )


def test_tampered_baseline_blocks_activation(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, 0.90)
    _report(candidate, 0.91)
    comparison = compare_benchmark_reports(baseline, candidate)
    comparison_json, _ = write_comparison_report(tmp_path / "comparison", comparison)
    promotion = promote_benchmark_baseline(
        candidate,
        comparison_json,
        tmp_path / "registry",
        label="approved-model",
    )
    promotion.baseline_path.write_text("tampered", encoding="utf-8")

    audit = audit_baseline_registry(tmp_path / "registry")
    assert not audit.valid
    assert "checksum mismatch" in audit.issues[0]
    with pytest.raises(ValueError, match="failed integrity audit"):
        activate_registered_baseline(tmp_path / "registry", "approved-model")
