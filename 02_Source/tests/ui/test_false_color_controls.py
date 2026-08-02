"""Phase 9D-2: False Color dock UI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from color_pipeline_fixtures import install_fake_oiio, make_decoder, make_exr_sequence
from nova_layer.app.false_color import FalseColorMode, FalseColorSettings
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.false_color_controls import FalseColorControlsPanel
from nova_layer.ui.guidance_viewer import GuidanceViewer
from nova_layer.ui.workspace import WorkspaceWindow


def _workspace(tmp_path: Path, qtbot: QtBot) -> WorkspaceWindow:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("False Color", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_view_menu_false_color_action(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.false_color_action.text() == "False Color"
    assert window.false_color_action.isCheckable()
    assert not window.false_color_dock.isVisible()
    assert window.false_color_panel.current_settings().mode is FalseColorMode.OFF


def test_mode_opacity_legend_reset(qtbot: QtBot) -> None:
    panel = FalseColorControlsPanel()
    qtbot.addWidget(panel)
    panel.mode_combo.setCurrentIndex(1)
    assert panel.current_settings().mode is FalseColorMode.PREVIEW_LUMA
    panel.opacity_spin.setValue(0.4)
    assert panel.current_settings().opacity == pytest.approx(0.4)
    panel.legend_check.setChecked(False)
    assert panel.current_settings().show_legend is False
    panel.reset_button.click()
    assert panel.current_settings().mode is FalseColorMode.OFF
    assert panel.current_settings().opacity == pytest.approx(1.0)


def test_viewer_keeps_original_frame(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    original = np.full((4, 4, 3), 17, dtype=np.uint8)
    false = np.full((4, 4, 3), 200, dtype=np.uint8)
    viewer.set_frame(original)
    viewer.set_false_color_frame(false, legend=[("A", (200, 0, 0))], show_legend=True)
    assert viewer.original_frame is not None
    assert np.array_equal(viewer.original_frame, original)
    assert viewer._false_color_frame is not None
    viewer.clear_false_color()
    assert viewer._false_color_frame is None
    assert np.array_equal(viewer.original_frame, original)


def test_hidden_or_off_skips_compute(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.false_color_dock.hide()
    calls: list[int] = []

    def fail_refresh() -> None:
        calls.append(1)

    window._refresh_false_color = fail_refresh  # type: ignore[method-assign]
    window._false_color_settings = FalseColorSettings(mode=FalseColorMode.PREVIEW_LUMA)
    window._schedule_false_color_refresh(force=True)
    window._flush_false_color_refresh()
    assert calls == []

    # mode OFF short-circuits in schedule (no timer / no decode)
    window.false_color_dock.show()
    window._false_color_settings = FalseColorSettings(mode=FalseColorMode.OFF)
    window._false_color_refresh_timer.stop()
    window._schedule_false_color_refresh(force=True)
    assert not window._false_color_refresh_timer.isActive()
    assert calls == []


def test_color_settings_schedules_refresh(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.false_color_dock.show()
    window._false_color_settings = FalseColorSettings(
        mode=FalseColorMode.PREVIEW_LUMA
    )
    scheduled: list[bool] = []
    window._schedule_false_color_refresh = (  # type: ignore[method-assign]
        lambda force=False: scheduled.append(bool(force))
    )
    window._apply_effective_color_settings()
    assert scheduled


def test_frame_change_schedules_when_active(
    tmp_path: Path,
    qtbot: QtBot,
) -> None:
    window = _workspace(tmp_path, qtbot)
    window.false_color_dock.show()
    window._false_color_settings = FalseColorSettings(
        mode=FalseColorMode.SOURCE_LUMA
    )
    scheduled: list[int] = []
    window._schedule_false_color_refresh = (  # type: ignore[method-assign]
        lambda force=False: scheduled.append(1)
    )
    window.set_frame(1, np.full((8, 8, 3), 9, dtype=np.uint8))
    assert scheduled


def test_refresh_applies_overlay(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    window = _workspace(tmp_path, qtbot)
    media = tmp_path / "exr_root"
    media.mkdir()
    seq = make_exr_sequence(media)
    window.controller._frame_decoder = make_decoder()
    preview = window.controller._frame_decoder.get_preview_frame(
        seq, 0, schedule_prefetch=False
    )
    window.viewer.set_frame(preview)
    window.false_color_dock.show()
    window._false_color_settings = FalseColorSettings(
        mode=FalseColorMode.PREVIEW_LUMA,
        opacity=1.0,
        show_legend=True,
    )
    # Bypass active-shot requirement by calling decoder path via monkeypatch
    def fake_get(*, mode, opacity=1.0, allow_decode=True):
        del allow_decode
        return window.controller._frame_decoder.get_false_color_frame(
            seq, 0, mode=mode, opacity=opacity
        )

    window.controller.get_false_color_frame = fake_get  # type: ignore[method-assign]
    window._refresh_false_color()
    assert window.viewer._false_color_frame is not None
    assert np.array_equal(window.viewer.original_frame, preview)
