from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from nova_layer.adapters.color.display_transform import LegacyDisplayTransform
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_settings_dialog import (
    COLOR_SETTINGS_PREFERENCE_KEY,
    ColorSettingsDialog,
    ColorSettingsPreference,
    load_color_settings_preference,
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
    assert controller.create_project("Color Persist", root) is not None
    return controller


def test_apply_persists_color_settings(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_path_edit.setText(str(tmp_path / "cfg.ocio"))
    dialog.input_color_space_combo.setEditText("ACES - ACEScg")
    dialog.display_combo.setEditText("sRGB")
    dialog.view_combo.setEditText("ACES 1.0 - SDR Video")
    dialog.exposure_spin.setValue(1.25)
    assert dialog.apply_settings() is True

    saved = load_color_settings_preference(workspace)
    assert saved is not None
    assert saved.backend == "ocio"
    assert saved.config_path == str(tmp_path / "cfg.ocio")
    assert saved.input_color_space == "ACES - ACEScg"
    assert saved.display == "sRGB"
    assert saved.view == "ACES 1.0 - SDR Video"
    assert saved.exposure == pytest.approx(1.25)


def test_new_workspace_restores_settings(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend="ocio",
            config_path=str(tmp_path / "missing.ocio"),
            input_color_space="scene_linear",
            display="sRGB",
            view="Raw",
            exposure=-0.5,
        ),
    )

    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    diagnostics = project_controller.display_transform_diagnostics
    assert diagnostics is not None
    assert diagnostics.backend == "legacy"
    assert diagnostics.fallback_reason is not None
    assert diagnostics.exposure == pytest.approx(-0.5)

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.backend_combo.currentText() == "OCIO"
    assert dialog.exposure_spin.value() == pytest.approx(-0.5)
    assert "fallback reason:" in dialog.diagnostics_label.text()


def test_cancel_does_not_persist(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.exposure_spin.setValue(3.0)
    dialog.reject()
    assert workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY) is None


def test_invalid_config_restores_as_quiet_legacy_fallback(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[object] = []

    def _capture_warning(*args: object, **kwargs: object) -> int:
        warnings.append((args, kwargs))
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "warning", _capture_warning)

    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend="ocio",
            config_path=str(tmp_path / "gone.ocio"),
            exposure=0.75,
        ),
    )

    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert warnings == []
    assert isinstance(project_controller._display_transform, LegacyDisplayTransform)
    assert project_controller.display_transform_diagnostics is not None
    assert project_controller.display_transform_diagnostics.fallback_reason


def test_exposure_restored_from_preference(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(backend="legacy", exposure=2.0),
    )
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.exposure_spin.value() == pytest.approx(2.0)


def test_missing_preference_defaults_to_legacy(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert load_color_settings_preference(workspace) is None
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    diagnostics = project_controller.display_transform_diagnostics
    assert diagnostics is not None
    assert diagnostics.backend == "legacy"
    assert diagnostics.fallback_reason is None


def test_invalid_exposure_string_falls_back_to_zero(workspace: WorkspaceManager) -> None:
    workspace.set_preference(
        COLOR_SETTINGS_PREFERENCE_KEY,
        {
            "backend": "legacy",
            "config_path": "",
            "input_color_space": "scene_linear",
            "display": "",
            "view": "",
            "exposure": "not-a-number",
        },
    )
    preference = load_color_settings_preference(workspace)
    assert preference is not None
    assert preference.exposure == 0.0
