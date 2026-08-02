"""Phase 9D-1: Histogram dock UI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from color_pipeline_fixtures import install_fake_oiio, make_decoder, make_exr_sequence
from nova_layer.app.histogram_analysis import empty_frame_histogram
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.histogram_panel import HistogramChannelMode, HistogramPanel
from nova_layer.ui.workspace import WorkspaceWindow


def _workspace(tmp_path: Path, qtbot: QtBot) -> WorkspaceWindow:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Histogram", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_view_menu_histogram_action(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.histogram_action is not None
    assert window.histogram_action.text() == "Histogram"
    assert window.histogram_action.isCheckable()
    assert not window.histogram_dock.isVisible()


def test_dock_show_hide(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.histogram_action.setChecked(True)
    assert window.histogram_dock.isVisible()
    window.histogram_action.setChecked(False)
    assert not window.histogram_dock.isVisible()


def test_policy_combo_and_channel_toggle(qtbot: QtBot) -> None:
    panel = HistogramPanel()
    qtbot.addWidget(panel)
    panel.policy_combo.setCurrentIndex(1)
    assert panel.current_policy() is ProcessingColorPolicy.SOURCE
    panel.channel_combo.setCurrentIndex(1)
    assert panel.current_channel_mode() is HistogramChannelMode.LUMINANCE


def test_stats_labels_and_unsupported_scene(qtbot: QtBot) -> None:
    panel = HistogramPanel()
    qtbot.addWidget(panel)
    from nova_layer.app.histogram_analysis import compute_frame_histogram, frame_histogram_from_data

    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    rgb[:, :] = (10, 20, 30)
    data = compute_frame_histogram(rgb, policy=ProcessingColorPolicy.PREVIEW)
    hist = frame_histogram_from_data(data, media_path=Path("/m"), frame_number=0)
    panel.apply_histogram(hist)
    assert panel.min_label.text() != "—"
    assert panel.sample_count_label.text() == "16"
    panel.apply_histogram(
        empty_frame_histogram(
            policy=ProcessingColorPolicy.SCENE.value,
            warning="SCENE unsupported for non-EXR media",
        )
    )
    assert "SCENE" in panel.status_label.text().upper()


def test_hidden_dock_skips_computation(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.histogram_dock.hide()
    calls: list[int] = []

    def fail_refresh(*, force: bool = False) -> None:
        del force
        calls.append(1)

    window._refresh_histogram = fail_refresh  # type: ignore[method-assign]
    window._schedule_histogram_refresh(force=True)
    window._flush_histogram_refresh()
    assert calls == []


def test_refresh_button_forces_update(
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
    window.histogram_dock.show()
    # Paint via direct controller bypass (no active shot media linked)
    hist = window.controller._frame_decoder.get_frame_histogram(
        seq, 0, ProcessingColorPolicy.PREVIEW
    )
    window.histogram_panel.apply_histogram(hist)
    assert window.histogram_panel.sample_count_label.text() != "—"
    with qtbot.waitSignal(window.histogram_panel.refresh_requested, timeout=1000):
        window.histogram_panel.refresh_button.click()


def test_no_media_empty_state(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.histogram_dock.show()
    window._refresh_histogram(force=True)
    assert window.histogram_panel.status_label.text() == "No media"


def test_color_settings_apply_schedules_refresh(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.histogram_dock.show()
    window.histogram_panel.auto_refresh_check.setChecked(True)
    scheduled: list[bool] = []
    window._schedule_histogram_refresh = (  # type: ignore[method-assign]
        lambda force=False: scheduled.append(bool(force))
    )
    window._apply_effective_color_settings()
    assert scheduled


def test_empty_graph_does_not_crash(qtbot: QtBot) -> None:
    panel = HistogramPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.clear(status="Empty")
    panel.graph.repaint()
