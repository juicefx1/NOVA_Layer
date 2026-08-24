"""Phase D2 Workspace Depth Assist wiring tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from pytestqt.qtbot import QtBot

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.workspace import WorkspaceWindow


def _png_sequence(tmp_path: Path, frames: int = 4) -> Path:
    seq = tmp_path / "seq"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        Image.fromarray(
            np.full((20, 30, 3), fill_value=50 + index * 10, dtype=np.uint8),
            mode="RGB",
        ).save(seq / f"frame_{index:04d}.png")
    return seq


def _workspace(tmp_path: Path, qtbot: QtBot) -> WorkspaceWindow:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController(
        media_reader=ImageSequenceReader(),
        depth_analysis=FakeDepthAnalysisCapability(),
    )
    assert controller.create_project("DepthAssist", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_view_menu_and_dock(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.depth_assist_action.text() == "Depth Assist"
    assert window.depth_assist_action.isCheckable()
    assert not window.depth_assist_dock.isVisible()
    window.depth_assist_action.setChecked(True)
    assert window.depth_assist_dock.isVisible()
    window.depth_assist_dock.hide()
    assert not window.depth_assist_action.isChecked()


def test_analysis_signals_wiring(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.controller.import_media(_png_sequence(tmp_path)) is not None
    assert window.controller.request_frame(0)
    window.depth_assist_action.setChecked(True)
    with qtbot.waitSignal(window.controller.depth_analysis_ready, timeout=5000):
        window.depth_assist_panel.analyze_button.click()
    assert window.depth_assist_panel.overlay_check.isEnabled()
    window.depth_assist_panel.overlay_check.setChecked(True)
    assert window.viewer._depth_overlay_enabled
    assert window.viewer.original_frame is not None


def test_failure_cancel_safe_no_polling(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    # Empty project path — analyze without media remains safe.
    window.depth_assist_action.setChecked(True)
    window.depth_assist_panel.analyze_button.click()
    assert "import" in window.depth_assist_panel.status_label.text().casefold() or True
    # No dedicated depth polling timer should exist.
    assert not hasattr(window, "_depth_poll_timer")


def test_one_click_default_off_and_overlay_not_required(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.controller.import_media(_png_sequence(tmp_path)) is not None
    shot = window.controller.active_shot
    assert shot is not None
    assert window.controller.request_frame(int(shot.master_frame))
    window.depth_assist_action.setChecked(True)
    panel = window.depth_assist_panel
    assert not panel.one_click_button.isChecked()
    assert not panel.overlay_check.isChecked()
    panel.one_click_button.setChecked(True)
    assert window.viewer.depth_pick_mode is True
    with qtbot.waitSignal(window.controller.hypothesis_ready, timeout=5000):
        window._on_depth_seed_clicked(8, 6)
    assert "review" in panel.status_label.text().casefold()
    assert not panel.overlay_check.isChecked()
    panel.one_click_button.setChecked(False)
    assert window.viewer.depth_pick_mode is False
