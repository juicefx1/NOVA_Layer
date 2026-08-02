"""Phase 9C-1: Pixel Inspector dock UI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from pytestqt.qtbot import QtBot

from color_pipeline_fixtures import install_fake_oiio, make_decoder, make_exr_sequence
from nova_layer.app.pixel_inspection import empty_pixel_inspection
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.pixel_inspector import PixelInspectorPanel
from nova_layer.ui.workspace import WorkspaceWindow


def _workspace(tmp_path: Path, qtbot: QtBot) -> WorkspaceWindow:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Pixel Inspector", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_view_menu_pixel_inspector_action(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.pixel_inspector_action is not None
    assert window.pixel_inspector_action.text() == "Pixel Inspector"
    assert window.pixel_inspector_action.isCheckable()
    assert not window.pixel_inspector_dock.isVisible()


def test_dock_show_hide(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_action.setChecked(True)
    assert window.pixel_inspector_dock.isVisible()
    window.pixel_inspector_action.setChecked(False)
    assert not window.pixel_inspector_dock.isVisible()


def test_hover_updates_panel_values(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    window = _workspace(tmp_path, qtbot)
    media_root = tmp_path / "exr_media"
    media_root.mkdir()
    seq = make_exr_sequence(media_root)
    window.controller._frame_decoder = make_decoder()
    # Minimal shot-less path: poke panel directly via refresh helper after framing
    frame = window.controller._frame_decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    window.viewer.set_frame(frame)
    window._current_frame = 0
    window.pixel_inspector_dock.show()
    # Inject media path by monkeypatching active_shot media via inspect_pixel override
    inspection = window.controller.inspect_pixel(seq, 0, 1, 1)
    window.pixel_inspector_panel.apply_inspection(
        inspection,
        diagnostics=window.controller.color_pipeline_diagnostics,
    )
    assert window.pixel_inspector_panel._pixel_x.text() == "1"
    assert window.pixel_inspector_panel._preview_r.text() != "—"
    assert window.pixel_inspector_panel._scene_r.text() != "—"


def test_outside_image_status(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_dock.show()
    window.pixel_inspector_panel.apply_inspection(
        empty_pixel_inspection(warning="Outside image"),
        diagnostics=window.controller.color_pipeline_diagnostics,
    )
    assert window.pixel_inspector_panel._status.text() == "Outside image"


def test_no_media_empty_state(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_dock.show()
    window.pixel_inspector_panel.clear(status="No media")
    assert window.pixel_inspector_panel._status.text() == "No media"


def test_hidden_dock_skips_sampling(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_dock.hide()
    calls: list[tuple[int, int]] = []

    def fail_refresh(x: int, y: int) -> None:
        calls.append((x, y))

    window._refresh_pixel_inspection = fail_refresh  # type: ignore[method-assign]
    window._on_pixel_hovered(3, 4)
    window._flush_pixel_inspection()
    assert calls == []


def test_frame_change_refreshes_hover(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_dock.show()
    window._pixel_hover_xy = (2, 3)
    scheduled: list[tuple[int, int]] = []
    window._schedule_pixel_inspection = (  # type: ignore[method-assign]
        lambda x, y: scheduled.append((x, y))
    )
    frame = np.full((8, 8, 3), 12, dtype=np.uint8)
    window.set_frame(1, frame)
    assert scheduled == [(2, 3)]


def test_panel_handles_long_path_and_floats(qtbot: QtBot) -> None:
    panel = PixelInspectorPanel()
    qtbot.addWidget(panel)
    long_path = Path("/" + ("very_long_segment/" * 40) + "media.exr")
    inspection = empty_pixel_inspection(
        image_x=1,
        image_y=2,
        media_path=long_path,
        frame_number=99,
        warning="ok",
    )
    # Construct via inspect fields manually
    from nova_layer.app.pixel_inspection import PixelInspection, PixelSample

    inspection = PixelInspection(
        image_x=1,
        image_y=2,
        preview=PixelSample(1, 2, (1.0, 2.0, 3.0), None, "uint8", "uint8 0–255", "preview"),
        source=PixelSample(1, 2, (4.0, 5.0, 6.0), None, "uint8", "uint8 0–255", "source"),
        scene=PixelSample(
            1,
            2,
            (1.23456789, float("nan"), float("inf")),
            None,
            "float32",
            "float32 file-native",
            "scene",
        ),
        media_path=long_path,
        frame_number=99,
        warning="ok",
    )
    panel.apply_inspection(inspection, diagnostics=None)
    assert "very_long_segment" in panel._pixel_media.text()
    assert panel._scene_g.text() == "NaN"
    assert panel._scene_b.text() == "+Inf"


def test_signal_path_triggers_schedule(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.pixel_inspector_dock.show()
    window.viewer.resize(200, 200)
    window.viewer.set_frame(np.full((20, 20, 3), 7, dtype=np.uint8))
    window.viewer.show()
    qtbot.waitExposed(window.viewer)
    window.viewer._update_display_rect()
    rect = window.viewer._display_rect
    with qtbot.waitSignal(window.viewer.pixel_hovered, timeout=1000):
        window.viewer._emit_pixel_hover(
            QPointF(rect.center().x(), rect.center().y())
        )
    assert window._pixel_hover_xy is not None
