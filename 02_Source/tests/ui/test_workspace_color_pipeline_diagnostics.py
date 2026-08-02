"""Workspace wiring smoke tests for Color Pipeline Diagnostics (Phase 9B-2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_pipeline_diagnostics_dialog import (
    ColorPipelineDiagnosticsDialog,
)
from nova_layer.ui.workspace import WorkspaceWindow


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceManager:
    WorkspaceManager.reset_shared_for_tests()
    manager = WorkspaceManager(tmp_path / "workspace.json")
    manager.load()
    return manager


@pytest.fixture
def project_controller(tmp_path: Path) -> ProjectController:
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Diag UI", root) is not None
    return controller


def test_menu_action_exists(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    assert window.color_pipeline_diagnostics_action is not None
    assert (
        window.color_pipeline_diagnostics_action.text()
        == "Color Pipeline Diagnostics…"
    )


def test_dialog_safe_without_media(qtbot: object) -> None:
    controller = ProjectController()
    dialog = ColorPipelineDiagnosticsDialog(controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.shot_label.text() == "None"
    assert dialog.media_label.text() == "None"
    dialog.refresh()
    assert dialog.result() in {0, int(QDialog.DialogCode.Rejected)}


def test_open_action_shows_dialog(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    opened: list[object] = []

    def _fake_exec(self: ColorPipelineDiagnosticsDialog) -> int:
        opened.append(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ColorPipelineDiagnosticsDialog, "exec", _fake_exec)
    window.color_pipeline_diagnostics_action.trigger()
    assert len(opened) == 1
    assert isinstance(opened[0], ColorPipelineDiagnosticsDialog)
