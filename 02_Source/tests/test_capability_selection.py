import sys
from pathlib import Path

import pytest

from nova_layer.adapters.capabilities.mock import (
    MockSegmentationCapability,
)
from nova_layer.adapters.capabilities.validated_skeleton import (
    ValidatedSkeletonTrackingCapability,
)
from nova_layer.adapters.capabilities.validated_skeleton_detection import (
    ValidatedSkeletonDetectionCapability,
)
from nova_layer.app.capability_selection import (
    select_interactive_segmentation,
    select_skeleton_detection,
    select_skeleton_tracking,
    select_temporal_propagation,
)


def test_explicit_mock_mode_never_loads_optional_model(monkeypatch: object) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "mock")  # type: ignore[attr-defined]

    selection = select_interactive_segmentation()

    assert selection.mode == "mock"
    assert isinstance(selection.capability, MockSegmentationCapability)
    assert select_temporal_propagation().mode == "mock"
    assert select_skeleton_tracking().mode == "mock"
    assert select_skeleton_detection().mode == "mock"


def test_missing_checkpoint_falls_back_safely(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")  # type: ignore[attr-defined]
    monkeypatch.setenv("NOVA_SAM2_CHECKPOINT", str(tmp_path / "missing.pt"))  # type: ignore[attr-defined]

    selection = select_interactive_segmentation()

    assert selection.mode == "mock"
    assert "checkpoint" in selection.message


def test_external_skeleton_adapter_is_loaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module_path = tmp_path / "test_pose_adapter.py"
    module_path.write_text(
        "from nova_layer.adapters.capabilities.mock import MockSkeletonTrackingCapability\n"
        "def create():\n"
        "    return MockSkeletonTrackingCapability()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("NOVA_AI_MODE", "auto")
    monkeypatch.setenv("NOVA_SKELETON_ADAPTER", "test_pose_adapter:create")

    selection = select_skeleton_tracking()

    assert selection.mode == "external"
    assert isinstance(selection.capability, ValidatedSkeletonTrackingCapability)
    sys.modules.pop("test_pose_adapter", None)


def test_invalid_explicit_skeleton_adapter_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "skeleton")
    monkeypatch.setenv("NOVA_SKELETON_ADAPTER", "missing_adapter:create")

    with pytest.raises(RuntimeError, match="could not be loaded"):
        select_skeleton_tracking()


def test_external_skeleton_detector_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")
    monkeypatch.setenv(
        "NOVA_SKELETON_DETECTOR",
        "nova_layer.adapters.capabilities.mock:MockSkeletonDetectionCapability",
    )

    selection = select_skeleton_detection()

    assert selection.mode == "external"
    assert isinstance(selection.capability, ValidatedSkeletonDetectionCapability)


def test_local_depth_pose_bridge_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)
    monkeypatch.setenv("NOVA_DEPTH_POSE_BRIDGE_URL", "http://127.0.0.1:3456/api/nova/depth-pose")

    selection = select_skeleton_detection()

    assert selection.mode == "browser_bridge"
    assert isinstance(selection.capability, ValidatedSkeletonDetectionCapability)
    assert selection.adapter_spec == "http://127.0.0.1:3456/api/nova/depth-pose"


def test_remote_depth_pose_bridge_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_AI_MODE", "auto")
    monkeypatch.delenv("NOVA_SKELETON_DETECTOR", raising=False)
    monkeypatch.setenv("NOVA_DEPTH_POSE_BRIDGE_URL", "https://example.com/depth-pose")

    selection = select_skeleton_detection()

    assert selection.mode == "mock"
    assert "local HTTP address" in selection.message
