from __future__ import annotations

import pytest

from nova_layer.skeleton_adapter_check import check_adapter, check_detection_adapter, main

MOCK_SPEC = "nova_layer.adapters.capabilities.mock:MockSkeletonTrackingCapability"
DETECTION_SPEC = "nova_layer.adapters.capabilities.mock:MockSkeletonDetectionCapability"


def test_skeleton_adapter_check_passes_valid_adapter() -> None:
    report = check_adapter(MOCK_SPEC)

    assert report["status"] == "passed"
    assert report["result_frames"] == [9, 11]
    assert report["provenance"]["capability"] == "skeleton_tracking"
    assert len(report["contract_checks"]) == 6


def test_skeleton_detection_adapter_check_passes_valid_adapter() -> None:
    report = check_detection_adapter(DETECTION_SPEC)

    assert report["status"] == "passed"
    assert report["role"] == "detection"
    assert report["provenance"]["capability"] == "skeleton_detection"
    assert report["detected_labels"] == ["left_shoulder", "left_wrist"]
    assert len(report["contract_checks"]) == 6


def test_skeleton_adapter_check_cli_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["nova-skeleton-check", "missing.module:create"])

    with pytest.raises(SystemExit, match="1"):
        main()

    assert '"status": "failed"' in capsys.readouterr().out
