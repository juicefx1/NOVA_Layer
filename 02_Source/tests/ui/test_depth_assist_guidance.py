"""Phase D3 Depth Assist → guidance UI wiring tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from pytestqt.qtbot import QtBot

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import GuidancePoint
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.depth_assist_panel import DepthAssistPanel
from nova_layer.ui.workspace import WorkspaceWindow


def _png_sequence(tmp_path: Path, frames: int = 5) -> Path:
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
    assert controller.create_project("DepthAssistD3", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    return window


def test_assist_button_disabled_without_region(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.show()
    assert panel.assist_button.text() == "Assist with Depth"
    assert not panel.assist_button.isEnabled()
    assert panel.clear_depth_guidance_button.text() == "Clear Depth Guidance"


def test_assist_flow_summary_clear_preserves_manual_no_auto_hypothesis(
    tmp_path: Path, qtbot: QtBot
) -> None:
    window = _workspace(tmp_path, qtbot)
    assert window.controller.import_media(_png_sequence(tmp_path)) is not None
    shot = window.controller.active_shot
    assert shot is not None
    master = int(shot.master_frame)
    assert window.controller.request_frame(master)
    window.depth_assist_action.setChecked(True)

    assert not window.depth_assist_panel.assist_button.isEnabled()

    with qtbot.waitSignal(window.controller.depth_analysis_ready, timeout=5000):
        window.depth_assist_panel.analyze_button.click()
    assert window.depth_assist_panel.overlay_check.isEnabled()

    # Manual guidance first.
    assert (
        window.controller.update_artist_guidance(
            [GuidancePoint(x=0.2, y=0.3, polarity="positive")],
            None,
        )
        is not None
    )
    window._refresh_viewer_guidance_from_controller()
    manual_before = len(window.viewer.points)

    region = window.controller.select_depth_region(x=10, y=8, tolerance=0.25)
    assert region is not None and region.pixel_count > 0
    assert window.depth_assist_panel.assist_button.isEnabled()
    assert window.viewer._depth_region_overlay is not None

    hypo_calls: list[int] = []
    window.controller.hypothesis_ready.connect(lambda *_: hypo_calls.append(1))
    processing: list[str] = []
    window.controller.processing_started.connect(lambda name: processing.append(name))

    with qtbot.waitSignal(window.controller.depth_guidance_applied, timeout=5000):
        window.depth_assist_panel.assist_button.click()

    assert window.depth_assist_panel.guidance_positive_label.text() != "—"
    assert int(window.depth_assist_panel.guidance_positive_label.text()) >= 1
    assert window.depth_assist_panel.clear_depth_guidance_button.isEnabled()
    assert len(window.viewer.points) > manual_before
    assert window.viewer._depth_region_overlay is not None
    assert hypo_calls == []
    assert "interactive_hypothesis" not in processing
    assert "propagation" not in "".join(processing)

    window.depth_assist_panel.clear_depth_guidance_button.click()
    assert any(
        abs(p.x - 0.2) < 1e-9 and abs(p.y - 0.3) < 1e-9 for p in window.viewer.points
    )
    assert window.viewer._depth_region_overlay is not None
