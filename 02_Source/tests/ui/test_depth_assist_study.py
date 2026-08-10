"""Phase D3.8 Depth Assist Study Mode UI tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from pytestqt.qtbot import QtBot

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.depth_assist_telemetry import (
    EVENT_DEPTH_ASSIST_APPLIED,
    EVENT_GENERATE_HYPOTHESIS,
    EVENT_MANUAL_POSITIVE,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import GuidancePoint
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.depth_assist_panel import DepthAssistPanel
from nova_layer.ui.workspace import WorkspaceWindow


def _png_sequence(tmp_path: Path, frames: int = 4) -> Path:
    seq = tmp_path / "seq"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        Image.fromarray(
            np.full((20, 30, 3), fill_value=40 + index * 12, dtype=np.uint8),
            mode="RGB",
        ).save(seq / f"frame_{index:04d}.png")
    return seq


def test_study_mode_off_by_default(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.show()
    assert panel.study_mode_check.isChecked() is False
    assert not panel.start_study_button.isEnabled()
    assert not panel.finish_study_button.isEnabled()
    assert not panel.export_study_button.isEnabled()
    assert panel.analyze_button.text() == "Analyze Scene"
    assert panel.assist_button.text() == "Assist with Depth"


def test_study_start_finish_export_and_counters(tmp_path: Path, qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.study_mode_check.setChecked(True)
    assert panel.start_study_button.isEnabled()
    assert panel.selected_study_workflow() == "manual"
    panel.study_workflow_combo.setCurrentIndex(1)
    assert panel.selected_study_workflow() == "depth_assist"

    started: list[int] = []
    finished: list[int] = []
    exported: list[int] = []
    panel.start_study_requested.connect(lambda: started.append(1))
    panel.finish_study_requested.connect(lambda: finished.append(1))
    panel.export_study_requested.connect(lambda: exported.append(1))

    panel.start_study_button.click()
    assert started == [1]
    panel.set_study_recording(True)
    panel.update_study_counters(interactions=3, refine_rounds=0, duration_seconds=1.25)
    assert panel.study_interactions_label.text() == "3"
    assert panel.study_refine_label.text() == "0"
    assert "1.3s" in panel.study_duration_label.text() or "1.2s" in panel.study_duration_label.text()
    panel.finish_study_button.click()
    assert finished == [1]
    panel.set_study_recording(False)
    panel.set_study_export_enabled(True)
    assert panel.export_study_button.isEnabled()
    panel.export_study_button.click()
    assert exported == [1]

    # Turning Study Mode off restores quiet state.
    panel.study_mode_check.setChecked(False)
    assert not panel.start_study_button.isEnabled()
    assert not panel.export_study_button.isEnabled()


def test_workspace_study_records_manual_and_depth_events(
    tmp_path: Path, qtbot: QtBot
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController(
        media_reader=ImageSequenceReader(),
        depth_analysis=FakeDepthAnalysisCapability(),
    )
    assert controller.create_project("StudyD38", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)
    window.show()
    assert window.depth_assist_panel.study_mode_check.isChecked() is False
    assert window.controller.import_media(_png_sequence(tmp_path)) is not None
    shot = window.controller.active_shot
    assert shot is not None
    master = int(shot.master_frame)
    assert window.controller.request_frame(master)

    # Study Mode OFF: actions do not record.
    assert (
        window.controller.update_artist_guidance(
            [GuidancePoint(x=0.2, y=0.3, polarity="positive")],
            None,
        )
        is not None
    )
    assert window._depth_study_recorder.current_session is None

    panel = window.depth_assist_panel
    panel.study_mode_check.setChecked(True)
    panel.study_workflow_combo.setCurrentIndex(1)
    panel.start_study_button.click()
    assert window._depth_study_recorder.is_recording

    # Manual positive via viewer save path.
    window._save_guidance(
        [GuidancePoint(x=0.4, y=0.5, polarity="positive")],
        None,
        window.viewer.skeleton_guidance,
    )
    # Depth analyze + assist.
    with qtbot.waitSignal(window.controller.depth_analysis_ready, timeout=5000):
        panel.analyze_button.click()
    region = window.controller.select_depth_region(x=10, y=8, tolerance=0.2)
    assert region is not None and region.pixel_count > 0
    window._record_study_event(
        "depth_region_picked",
        tolerance=float(region.tolerance),
        region_coverage=float(region.coverage),
    )
    with qtbot.waitSignal(window.controller.depth_guidance_applied, timeout=5000):
        panel.assist_button.click()
    window._on_generate_hypothesis_clicked()

    session = window._depth_study_recorder.current_session
    assert session is not None
    types = [e.event_type for e in session.events]
    assert EVENT_MANUAL_POSITIVE in types
    assert EVENT_DEPTH_ASSIST_APPLIED in types
    assert EVENT_GENERATE_HYPOTHESIS in types
    assert "source_path" not in str(session)
    assert getattr(shot.media, "source_path", None) is not None  # still in project
    # Session payload itself stays fingerprint-only.
    assert session.media_fingerprint == str(shot.media.fingerprint)

    panel.finish_study_button.click()
    finished = window._depth_study_recorder.last_finished_session
    assert finished is not None
    assert panel.export_study_button.isEnabled()
