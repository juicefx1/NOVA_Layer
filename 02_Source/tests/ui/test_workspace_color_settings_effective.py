from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.settings import ColorSettings
from nova_layer.app.effective_color_settings import (
    COLOR_SETTINGS_PREFERENCE_KEY,
    apply_effective_color_settings,
    preference_dict_to_color_settings,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import ProjectColorSettings
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_settings_dialog import (
    ColorSettingsDialog,
    ColorSettingsPreference,
    save_color_settings_preference,
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
    assert controller.create_project("Effective Color", root) is not None
    return controller


def _set_workspace_prefs(
    workspace: WorkspaceManager,
    *,
    backend: str = "legacy",
    config_path: str = "",
    input_color_space: str = "scene_linear",
    display: str = "sRGB",
    view: str = "Raw",
    exposure: float = 0.0,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend=backend,  # type: ignore[arg-type]
            config_path=config_path,
            input_color_space=input_color_space,
            display=display,
            view=view,
            exposure=exposure,
        ),
    )


def test_preference_dict_maps_absolute_config() -> None:
    settings = preference_dict_to_color_settings(
        {
            "backend": "ocio",
            "config_path": "/tmp/a.ocio",
            "input_color_space": "ACEScg",
            "display": "sRGB",
            "view": "Raw",
            "exposure": 1.25,
        }
    )
    assert settings is not None
    assert settings.config_kind == "absolute"
    assert settings.config_value == "/tmp/a.ocio"
    assert settings.exposure == pytest.approx(1.25)


def test_project_backend_over_workspace(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    _set_workspace_prefs(workspace, backend="legacy")
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(backend="ocio")
    application = apply_effective_color_settings(
        project_controller,
        workspace,
        project_root=project_controller.package_path,
    )
    assert application.resolved.backend == "ocio"
    assert application.resolved.source_backend == "project"


def test_project_input_color_space_over_workspace(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    _set_workspace_prefs(workspace, input_color_space="Raw")
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        input_color_space="ACEScg"
    )
    application = apply_effective_color_settings(project_controller, workspace)
    assert application.resolved.input_color_space == "ACEScg"
    assert application.resolved.source_input_color_space == "project"


def test_project_absolute_config(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
) -> None:
    ocio = tmp_path / "show.ocio"
    ocio.write_text("x", encoding="utf-8")
    _set_workspace_prefs(workspace, backend="ocio", config_path=str(tmp_path / "other.ocio"))
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="absolute",
        config_value=str(ocio),
    )
    application = apply_effective_color_settings(project_controller, workspace)
    assert application.resolved.config_path == ocio.resolve()
    assert application.resolved.source_config == "project"


def test_package_relative_uses_project_root(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    root = project_controller.package_path
    assert root is not None
    configs = root / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    ocio = configs / "pack.ocio"
    ocio.write_text("x", encoding="utf-8")
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="package_relative",
        config_value="configs/pack.ocio",
    )
    application = apply_effective_color_settings(
        project_controller,
        workspace,
        project_root=root,
    )
    assert application.resolved.config_path == ocio.resolve()
    assert application.resolved.config_source == "package_relative"


def test_pin_display_view_true(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    _set_workspace_prefs(workspace, display="sRGB", view="Raw")
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        pin_display_view=True,
        display="Rec709",
        view="Film",
    )
    resolved = apply_effective_color_settings(project_controller, workspace).resolved
    assert resolved.display == "Rec709"
    assert resolved.view == "Film"
    assert resolved.source_display == "project"


def test_pin_false_workspace_display_view(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    _set_workspace_prefs(workspace, display="sRGB", view="Raw")
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        pin_display_view=False,
        display="Rec709",
        view="Film",
    )
    resolved = apply_effective_color_settings(project_controller, workspace).resolved
    assert resolved.display == "sRGB"
    assert resolved.view == "Raw"
    assert resolved.source_display == "workspace"


def test_workspace_exposure_over_project(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    _set_workspace_prefs(workspace, exposure=1.5)
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(exposure=3.0)
    resolved = apply_effective_color_settings(project_controller, workspace).resolved
    assert resolved.exposure == pytest.approx(1.5)
    assert resolved.source_exposure == "workspace"


def test_no_project_uses_workspace(workspace: WorkspaceManager, tmp_path: Path) -> None:
    controller = ProjectController()
    _set_workspace_prefs(workspace, backend="ocio", exposure=0.25)
    application = apply_effective_color_settings(controller, workspace)
    assert controller.project is None
    assert application.resolved.backend == "ocio"
    assert application.resolved.source_backend == "workspace"
    assert application.resolved.exposure == pytest.approx(0.25)


def test_neither_defaults_to_legacy(workspace: WorkspaceManager) -> None:
    controller = ProjectController()
    application = apply_effective_color_settings(controller, workspace)
    assert application.resolved.backend == "legacy"
    assert application.resolved.source_backend == "default"
    assert isinstance(application.transform, ViewerDisplayTransform)
    assert isinstance(application.transform.display_transform, LegacyDisplayTransform)


def test_workspace_apply_keeps_project_override(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        input_color_space="ACEScg",
    )
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    dialog = ColorSettingsDialog(
        project_controller,
        workspace=workspace,
        apply_effective=window._apply_effective_color_settings,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("Legacy")
    dialog.input_color_space_combo.setEditText("Raw")
    assert dialog.apply_settings() is True

    resolved = window.last_resolved_color_settings
    assert resolved is not None
    assert resolved.backend == "ocio"
    assert resolved.input_color_space == "ACEScg"
    assert resolved.source_backend == "project"
    # Workspace prefs still updated for future projects without overrides.
    saved = workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY)
    assert isinstance(saved, dict)
    assert saved["backend"] == "legacy"


def test_switching_projects_reapplies_transform(
    qtbot: object,
    workspace: WorkspaceManager,
    tmp_path: Path,
) -> None:
    _set_workspace_prefs(workspace, backend="legacy", exposure=0.0)

    first_root = tmp_path / "a"
    first_root.mkdir()
    first = ProjectController()
    assert first.create_project("Project A", first_root) is not None
    assert first.project is not None
    first.project.color_settings = ProjectColorSettings(backend="ocio", exposure=1.0)

    window_a = WorkspaceWindow(first, workspace=workspace)
    qtbot.addWidget(window_a)  # type: ignore[attr-defined]
    assert window_a.last_resolved_color_settings is not None
    assert window_a.last_resolved_color_settings.backend == "ocio"

    second_root = tmp_path / "b"
    second_root.mkdir()
    second = ProjectController()
    assert second.create_project("Project B", second_root) is not None
    assert second.project is not None
    second.project.color_settings = None

    window_b = WorkspaceWindow(second, workspace=workspace)
    qtbot.addWidget(window_b)  # type: ignore[attr-defined]
    assert window_b.last_resolved_color_settings is not None
    assert window_b.last_resolved_color_settings.backend == "legacy"
    assert window_b.last_resolved_color_settings.source_backend == "workspace"


def test_bad_project_config_falls_back_with_warnings(
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
) -> None:
    good = tmp_path / "ws.ocio"
    good.write_text("x", encoding="utf-8")
    _set_workspace_prefs(
        workspace,
        backend="ocio",
        config_path=str(good),
    )
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="absolute",
        config_value=str(tmp_path / "missing.ocio"),
    )
    application = apply_effective_color_settings(project_controller, workspace)
    assert application.resolved.config_path == good.resolve()
    assert application.resolved.source_config == "workspace"
    assert application.resolved.warnings
    assert any("not found" in item for item in application.resolved.warnings)


def test_workspace_exposes_resolve_diagnostics(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="named",
        config_value="aces_1.3",
    )
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    assert window.last_resolved_color_settings is not None
    assert window.color_resolve_warnings
    assert project_controller.display_transform_diagnostics is not None
