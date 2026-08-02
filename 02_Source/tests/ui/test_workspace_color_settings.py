from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QMessageBox

from nova_layer.adapters.color.display_transform import LegacyDisplayTransform
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_settings_dialog import (
    COLOR_SETTINGS_PREFERENCE_KEY,
    ColorSettingsDialog,
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
    assert controller.create_project("Color UI", root) is not None
    return controller


def test_legacy_apply_sets_legacy_transform(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("Legacy")

    assert dialog.apply_settings() is True
    transform = project_controller._display_transform
    assert isinstance(transform, LegacyDisplayTransform)
    assert transform.diagnostics.backend == "legacy"
    assert transform.diagnostics.fallback_reason is None
    saved = workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY)
    assert isinstance(saved, dict)
    assert saved["backend"] == "legacy"


def test_ocio_apply_falls_back_with_warning(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, str]] = []

    def _fake_warning(parent: object, title: str, text: str, *args: object, **kwargs: object) -> int:
        del parent, args, kwargs
        warnings.append((title, text))
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "warning", _fake_warning)

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    missing = tmp_path / "missing.ocio"
    dialog.config_path_edit.setText(str(missing))
    dialog.input_color_space_edit.setText("scene_linear")
    dialog.exposure_spin.setValue(1.5)

    assert dialog.apply_settings() is True
    transform = project_controller._display_transform
    assert isinstance(transform, LegacyDisplayTransform)
    assert transform.diagnostics.fallback_reason is not None
    assert abs(transform.diagnostics.exposure - 1.5) < 1e-6
    assert warnings
    assert "fallback" in warnings[0][1].lower() or "Legacy" in warnings[0][1]


def test_cancel_does_not_call_set_display_transform(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    spy = MagicMock()
    project_controller.set_display_transform = spy  # type: ignore[method-assign]

    dialog.backend_combo.setCurrentText("OCIO")
    dialog.exposure_spin.setValue(2.0)
    dialog.reject()

    spy.assert_not_called()
    assert workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY) is None


def test_apply_without_active_shot_is_safe(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    assert project_controller.active_shot is None
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("Legacy")
    assert dialog.apply_settings() is True
    assert isinstance(project_controller._display_transform, LegacyDisplayTransform)


def test_dialog_reopen_shows_diagnostics(
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
    first = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(first)  # type: ignore[attr-defined]
    first.backend_combo.setCurrentText("OCIO")
    first.config_path_edit.setText(str(tmp_path / "absent.ocio"))
    first.exposure_spin.setValue(-1.25)
    assert first.apply_settings() is True

    second = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(second)  # type: ignore[attr-defined]
    text = second.diagnostics_label.text()
    assert "backend:" in text
    assert "exposure:" in text
    assert "fallback reason:" in text
    assert second.exposure_spin.value() == pytest.approx(-1.25)
    # Preference retains user intent (OCIO); runtime diagnostics show Legacy fallback.
    assert second.backend_combo.currentText() == "OCIO"
    assert project_controller.display_transform_diagnostics is not None
    assert project_controller.display_transform_diagnostics.fallback_reason
    assert project_controller.display_transform_diagnostics.fallback_reason in text


def test_workspace_opens_color_settings_action(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    assert window.color_settings_action is not None
    assert window.color_settings_action.text() == "Color Settings…"

    opened: list[ColorSettingsDialog] = []

    class _FakeDialog(ColorSettingsDialog):
        def exec(self) -> int:  # noqa: A003 - Qt API
            opened.append(self)
            return 0

    monkeypatch.setattr(
        "nova_layer.ui.workspace.ColorSettingsDialog",
        _FakeDialog,
    )
    window.color_settings_action.trigger()
    assert len(opened) == 1
