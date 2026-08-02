from __future__ import annotations

from pathlib import Path

from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.workspace import WorkspaceWindow


def test_workspace_has_view_color_settings_and_header_controls(
    qtbot: object,
    tmp_path: Path,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()

    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Workspace Smoke", root) is not None

    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()

    assert window.windowTitle() == "Workspace Smoke — NOVA Layer"
    assert window.import_button.isVisible()
    assert window.color_settings_action is not None
    menus = [action.text() for action in window.menuBar().actions()]
    assert any("View" in text for text in menus)
