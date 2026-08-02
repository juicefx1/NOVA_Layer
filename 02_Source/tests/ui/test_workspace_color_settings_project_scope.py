from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QFileDialog, QMessageBox

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.app.effective_color_settings import (
    COLOR_SETTINGS_PREFERENCE_KEY,
    to_package_relative_config_value,
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
    assert controller.create_project("Project Scope", root) is not None
    return controller


@pytest.fixture
def silence_qmessage(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []

    def _fake_warning(
        parent: object, title: str, text: str, *args: object, **kwargs: object
    ) -> int:
        del parent, title, args, kwargs
        messages.append(text)
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "warning", _fake_warning)
    return messages


def _select_scope(dialog: ColorSettingsDialog, scope: str) -> None:
    index = dialog.scope_combo.findData(scope)
    assert index >= 0
    dialog.scope_combo.setCurrentIndex(index)


def test_no_project_disables_project_scope(
    qtbot: object,
    workspace: WorkspaceManager,
) -> None:
    controller = ProjectController()
    dialog = ColorSettingsDialog(controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.scope_combo.currentData() == "workspace"
    model = dialog.scope_combo.model()
    assert isinstance(model, QStandardItemModel)
    item = model.item(1)
    assert item is not None
    assert not item.isEnabled()
    assert "No project" in dialog.scope_status_label.text()


def test_workspace_scope_apply_only_updates_prefs(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(backend="ocio")
    project_controller.save_current_project()

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.scope_combo.currentData() == "workspace"
    dialog.backend_combo.setCurrentText("Legacy")
    dialog.exposure_spin.setValue(0.5)
    assert dialog.apply_settings() is True

    saved = workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY)
    assert isinstance(saved, dict)
    assert saved["backend"] == "legacy"
    assert project_controller.project.color_settings is not None
    assert project_controller.project.color_settings.backend == "ocio"


def test_project_scope_apply_saves_manifest_roundtrip(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    silence_qmessage: list[str],
) -> None:
    config = tmp_path / "pack.ocio"
    config.write_text("x", encoding="utf-8")
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(backend="legacy", display="sRGB", view="Raw"),
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_kind_combo.setCurrentText("Absolute Path")
    dialog.config_path_edit.setText(str(config))
    dialog.input_color_space_combo.setEditText("ACEScg")
    dialog.display_combo.setEditText("Rec709")
    dialog.view_combo.setEditText("Film")
    dialog.exposure_spin.setValue(1.25)
    dialog.pin_display_view_checkbox.setChecked(True)
    assert dialog.apply_settings() is True

    assert project_controller.project is not None
    settings = project_controller.project.color_settings
    assert settings is not None
    assert settings.backend == "ocio"
    assert settings.config_kind == "absolute"
    assert settings.config_value == str(config)
    assert settings.input_color_space == "ACEScg"
    assert settings.display == "Rec709"
    assert settings.view == "Film"
    assert settings.exposure == pytest.approx(1.25)
    assert settings.pin_display_view is True

    package = project_controller.package_path
    assert package is not None
    reloaded = JsonProjectStore().load(package)
    assert reloaded.color_settings is not None
    assert reloaded.color_settings.backend == "ocio"
    assert reloaded.color_settings.config_kind == "absolute"
    assert reloaded.color_settings.pin_display_view is True
    assert reloaded.color_settings.input_color_space == "ACEScg"


def test_project_scope_apply_effective_prefers_project(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    silence_qmessage: list[str],
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(backend="legacy", exposure=0.0),
    )
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    dialog = ColorSettingsDialog(
        project_controller,
        workspace=workspace,
        apply_effective=window._apply_effective_color_settings,
    )
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_kind_combo.setCurrentText("Named")
    dialog.config_path_edit.setText("aces_1.3")
    assert dialog.apply_settings() is True

    assert window.last_resolved_color_settings is not None
    assert window.last_resolved_color_settings.backend == "ocio"
    assert window.last_resolved_color_settings.source_backend == "project"


def test_use_workspace_defaults_clears_project_settings(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    silence_qmessage: list[str],
) -> None:
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        input_color_space="ACEScg",
    )
    assert project_controller.save_current_project()

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog._use_workspace_defaults()

    assert project_controller.project.color_settings is None
    package = project_controller.package_path
    assert package is not None
    reloaded = JsonProjectStore().load(package)
    assert reloaded.color_settings is None
    assert "No project override" in dialog.scope_status_label.text()


def test_pin_display_view_persists(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    silence_qmessage: list[str],
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.pin_display_view_checkbox.setChecked(True)
    dialog.display_combo.setEditText("sRGB")
    dialog.view_combo.setEditText("Raw")
    assert dialog.apply_settings() is True

    dialog2 = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog2)  # type: ignore[attr-defined]
    _select_scope(dialog2, "project")
    assert dialog2.pin_display_view_checkbox.isChecked()
    assert dialog2.display_combo.currentText() == "sRGB"
    assert dialog2.view_combo.currentText() == "Raw"


def test_config_kind_and_value_persist(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    silence_qmessage: list[str],
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_kind_combo.setCurrentText("Environment")
    dialog.config_path_edit.setText("MY_OCIO")
    assert dialog.apply_settings() is True

    assert project_controller.project is not None
    settings = project_controller.project.color_settings
    assert settings is not None
    assert settings.config_kind == "env"
    assert settings.config_value == "MY_OCIO"


def test_project_relative_browse_stores_relative_path(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
    silence_qmessage: list[str],
) -> None:
    package = project_controller.package_path
    assert package is not None
    config = package / "configs" / "show.ocio"
    config.parent.mkdir(parents=True)
    config.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(config), "OCIO Config (*.ocio)"),
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_kind_combo.setCurrentText("Project Relative")
    dialog._browse_config()

    assert dialog.config_path_edit.text() == "configs/show.ocio"
    assert dialog.apply_settings() is True
    assert project_controller.project is not None
    assert project_controller.project.color_settings is not None
    assert project_controller.project.color_settings.config_kind == "package_relative"
    assert project_controller.project.color_settings.config_value == "configs/show.ocio"


def test_project_relative_outside_path_rejected(
    project_controller: ProjectController,
    tmp_path: Path,
) -> None:
    package = project_controller.package_path
    assert package is not None
    outside = tmp_path / "outside.ocio"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the project package"):
        to_package_relative_config_value(outside, package)


def test_project_relative_browse_warns_outside(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    silence_qmessage: list[str],
) -> None:
    outside = tmp_path / "outside.ocio"
    outside.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(outside), "OCIO Config (*.ocio)"),
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_kind_combo.setCurrentText("Project Relative")
    dialog._browse_config()

    assert dialog.config_path_edit.text() == ""
    assert silence_qmessage
    assert "inside the project package" in silence_qmessage[0]


def test_cancel_does_not_mutate_project_or_workspace(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(backend="legacy")
    project_controller.save_current_project()

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    spy = MagicMock()
    project_controller.set_display_transform = spy  # type: ignore[method-assign]
    save_spy = MagicMock(return_value=True)
    project_controller.save_current_project = save_spy  # type: ignore[method-assign]

    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.exposure_spin.setValue(3.0)
    dialog.reject()

    spy.assert_not_called()
    save_spy.assert_not_called()
    assert workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY) is None
    assert project_controller.project.color_settings is not None
    assert project_controller.project.color_settings.backend == "legacy"


def test_save_failure_warns_and_preserves_previous(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
    silence_qmessage: list[str],
) -> None:
    assert project_controller.project is not None
    previous = ProjectColorSettings(backend="legacy", input_color_space="Raw")
    project_controller.project.color_settings = previous

    monkeypatch.setattr(
        project_controller,
        "save_current_project",
        lambda: False,
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    _select_scope(dialog, "project")
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.input_color_space_combo.setEditText("ACEScg")
    assert dialog.apply_settings() is False
    assert silence_qmessage
    assert project_controller.project.color_settings is not None
    assert project_controller.project.color_settings.backend == "legacy"
    assert project_controller.project.color_settings.input_color_space == "Raw"


def test_scope_switch_refreshes_form(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend="legacy",
            input_color_space="workspace_cs",
            exposure=0.1,
        ),
    )
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(
        backend="ocio",
        input_color_space="project_cs",
        exposure=2.0,
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.backend_combo.currentText() == "Legacy"
    assert "workspace_cs" in dialog.input_color_space_combo.currentText()

    _select_scope(dialog, "project")
    assert dialog.backend_combo.currentText() == "OCIO"
    assert "project_cs" in dialog.input_color_space_combo.currentText()
    assert dialog.exposure_spin.value() == pytest.approx(2.0)

    _select_scope(dialog, "workspace")
    assert dialog.backend_combo.currentText() == "Legacy"
    assert "workspace_cs" in dialog.input_color_space_combo.currentText()


def test_diagnostics_show_provenance(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert project_controller.project is not None
    project_controller.project.color_settings = ProjectColorSettings(backend="ocio")
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    text = dialog.diagnostics_label.text()
    assert "source=project" in text or "source_backend" in text or "(source=project)" in text
    assert "backend=" in text or "backend:" in text
    assert "fallback reason:" in text
