"""Phase 9E-1: Performance HUD overlay."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot

from nova_layer.app.color_pipeline_diagnostics import build_color_pipeline_diagnostics
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.guidance_viewer import GuidanceViewer
from nova_layer.ui.performance_hud import (
    PerformanceHudSettings,
    format_performance_hud_lines,
    format_performance_hud_text,
)
from nova_layer.ui.workspace import WorkspaceWindow


def _workspace(tmp_path: Path, qtbot: QtBot) -> WorkspaceWindow:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Performance HUD", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_view_menu_performance_hud_default_off(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.performance_hud_action.text() == "Performance HUD"
    assert window.performance_hud_action.isCheckable()
    assert not window.performance_hud_action.isChecked()
    assert window._performance_hud_settings.enabled is False


def test_toggle_on_off_shows_snapshot(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.performance_hud_action.setChecked(True)
    assert window.viewer._performance_hud_enabled
    assert window.viewer._performance_hud_lines
    text = "\n".join(str(getattr(line, "text", line)) for line in window.viewer._performance_hud_lines)
    assert "RAW" in text and "PRV" in text and "SRC" in text
    window.performance_hud_action.setChecked(False)
    assert not window.viewer._performance_hud_enabled


def test_empty_state_format() -> None:
    diagnostics = build_color_pipeline_diagnostics(pipeline=None)
    text = format_performance_hud_text(diagnostics, compact=True)
    assert "No active media" in text
    assert "RAW" in text and "PRV" in text and "SRC" in text
    assert "0.0" in text or "MiB" in text


def test_compact_and_expanded_format() -> None:
    diagnostics = build_color_pipeline_diagnostics(pipeline=None)
    compact = format_performance_hud_text(diagnostics, compact=True)
    expanded = format_performance_hud_text(diagnostics, compact=False)
    assert "Decode" in compact
    assert "Hit" in expanded
    assert "Transform:" in expanded
    assert "Evict" in expanded
    assert len(expanded.splitlines()) > len(compact.splitlines())


def test_warning_and_budget_lines() -> None:
    from dataclasses import replace

    base = build_color_pipeline_diagnostics(pipeline=None)
    diagnostics = replace(
        base,
        fallback_reason="using legacy fallback",
        raw_cache_mib=450.0,
        raw_cache_max_mib=512.0,
    )
    lines = format_performance_hud_lines(diagnostics, compact=True)
    assert any(line.warn and "Warnings" in line.text for line in lines)
    assert any(line.warn and line.text.startswith("RAW") for line in lines)


def test_off_skips_diagnostics_lookup(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    calls: list[int] = []

    def counted_refresh() -> None:
        calls.append(1)

    window._refresh_performance_hud = counted_refresh  # type: ignore[method-assign]
    window._schedule_performance_hud_refresh(force=True)
    window._flush_performance_hud()
    assert calls == []


def test_frame_ready_and_color_settings_schedule(
    tmp_path: Path,
    qtbot: QtBot,
) -> None:
    window = _workspace(tmp_path, qtbot)
    window.performance_hud_action.setChecked(True)
    scheduled: list[int] = []
    window._schedule_performance_hud_refresh = (  # type: ignore[method-assign]
        lambda force=False: scheduled.append(1)
    )
    window.set_frame(3, np.full((8, 8, 3), 5, dtype=np.uint8))
    assert scheduled
    scheduled.clear()
    window._apply_effective_color_settings()
    assert scheduled


def test_same_snapshot_skips_repaint(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.performance_hud_action.setChecked(True)
    first_sig = window._last_performance_hud_signature
    assert first_sig is not None
    updates: list[int] = []
    original = window.viewer.set_performance_hud

    def tracking(**kwargs):  # type: ignore[no-untyped-def]
        updates.append(1)
        return original(**kwargs)

    window.viewer.set_performance_hud = tracking  # type: ignore[method-assign]
    window._refresh_performance_hud()
    assert updates == []


def test_refresh_does_not_mutate_cache_stats(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    pipeline = window.controller._frame_decoder.pipeline
    before = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
        pipeline.pipeline_stats.raw_decodes,
    )
    window.performance_hud_action.setChecked(True)
    window._refresh_performance_hud()
    after = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
        pipeline.pipeline_stats.raw_decodes,
    )
    for a, b in zip(before[:3], after[:3], strict=True):
        assert a.hits == b.hits
        assert a.misses == b.misses
    assert before[3] == after[3]


def test_hud_and_false_color_legend_positions(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(400, 300)
    viewer.set_frame(np.full((40, 40, 3), 20, dtype=np.uint8))
    viewer.set_false_color_frame(
        np.full((40, 40, 3), 40, dtype=np.uint8),
        legend=[("A", (255, 0, 0)), ("B", (0, 255, 0))],
        show_legend=True,
    )
    lines = format_performance_hud_lines(
        build_color_pipeline_diagnostics(pipeline=None),
        compact=True,
    )
    viewer.set_performance_hud(enabled=True, lines=lines, opacity=0.8)
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    # Legend is right-aligned; HUD uses left margin.
    assert viewer._display_rect.left() + 8 < viewer._display_rect.right() - 168
    viewer.repaint()


def test_small_widget_no_crash(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.setMinimumSize(0, 0)
    viewer.resize(64, 48)
    viewer.set_performance_hud(
        enabled=True,
        lines=format_performance_hud_lines(
            build_color_pipeline_diagnostics(pipeline=None),
            compact=True,
        ),
    )
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer.repaint()


def test_expanded_action(tmp_path: Path, qtbot: QtBot) -> None:
    window = _workspace(tmp_path, qtbot)
    window.performance_hud_action.setChecked(True)
    window.performance_hud_expanded_action.setChecked(True)
    assert window._performance_hud_settings.compact is False
    text = "\n".join(
        str(getattr(line, "text", line)) for line in window.viewer._performance_hud_lines
    )
    assert "Hit" in text or "Transform" in text


def test_settings_validation() -> None:
    try:
        PerformanceHudSettings(opacity=1.5)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_frame_buffers_unchanged_by_hud(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    frame = np.full((6, 6, 3), 33, dtype=np.uint8)
    false = np.full((6, 6, 3), 99, dtype=np.uint8)
    viewer.set_frame(frame)
    viewer.set_false_color_frame(false)
    viewer.set_performance_hud(
        enabled=True,
        lines=format_performance_hud_lines(
            build_color_pipeline_diagnostics(pipeline=None), compact=True
        ),
    )
    assert np.array_equal(viewer.original_frame, frame)
    assert viewer._false_color_frame is not None
    assert np.array_equal(viewer._false_color_frame, false)
