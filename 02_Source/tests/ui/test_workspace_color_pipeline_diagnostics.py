"""Phase 9B: Workspace Color Pipeline Diagnostics UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
)
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


def test_dialog_fields_and_refresh(
    qtbot: object,
    project_controller: ProjectController,
) -> None:
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.backend_label.text() == "legacy"
    assert dialog.raw_cache_label.text()
    assert "entries" in dialog.preview_cache_label.text()
    assert dialog.last_render_policy_label.text() == "—"

    project_controller.set_display_transform(
        LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=None,
                config_source=None,
                display="dispA",
                view="viewA",
                input_color_space="scene_linear",
                exposure=1.25,
                fallback_reason="test fallback",
            )
        )
    )
    dialog.refresh()
    assert dialog.display_label.text() == "dispA"
    assert dialog.view_label.text() == "viewA"
    assert dialog.exposure_label.text() == "1.25"
    assert dialog.fallback_label.text() == "test fallback"
    assert "test fallback" in dialog.warnings_label.text()


def test_copy_button_text(
    qtbot: object,
    project_controller: ProjectController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    captured: list[str] = []

    class FakeClipboard:
        def setText(self, text: str) -> None:
            captured.append(text)

    monkeypatch.setattr(
        "nova_layer.ui.color_pipeline_diagnostics_dialog.QGuiApplication.clipboard",
        lambda: FakeClipboard(),
    )
    dialog.copy_to_clipboard()
    assert captured
    assert "NOVA Layer Color Pipeline Diagnostics" in captured[0]
    assert "Backend:" in captured[0]
    assert dialog.copy_text() == captured[0]


def test_dialog_safe_without_media(qtbot: object) -> None:
    controller = ProjectController()
    dialog = ColorPipelineDiagnosticsDialog(controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.shot_label.text() == "—"
    assert dialog.media_label.text() == "—"
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
