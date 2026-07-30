from pathlib import Path

from nova_layer.depth_pose_smoke import run_depth_pose_smoke


def test_depth_pose_smoke_passes_deterministic_suite(tmp_path: Path) -> None:
    result = run_depth_pose_smoke(tmp_path / "smoke")

    assert result.passed
    assert result.case_count == 2
    assert result.mean_joint_error == 0.0
    assert result.mean_pck == 1.0
    assert result.temporal_transition_count == 1
    assert result.report_path.exists()
    assert result.comparison_path is not None
    assert result.comparison_path.exists()
    assert (tmp_path / "smoke" / "depth_pose_smoke_summary.json").exists()
    assert result.report_path.with_suffix(".md").exists()
