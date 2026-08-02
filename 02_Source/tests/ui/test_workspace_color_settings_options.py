from __future__ import annotations

from pathlib import Path

import pytest

from nova_layer.adapters.color.display_transform import ColorTransformError
from nova_layer.adapters.color.ocio_adapter import (
    OcioConfigOptions,
    is_ocio_available,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_settings_dialog import (
    ColorSettingsDialog,
    ColorSettingsPreference,
    save_color_settings_preference,
)

MULTI_DISPLAY_OCIO_CONFIG = """ocio_profile_version: 2

environment:
  {}

search_path: ""

roles:
  default: Raw
  scene_linear: Raw
  data: Raw

file_rules:
  - !<Rule> {name: Default, colorspace: default}

displays:
  sRGB:
    - !<View> {name: Raw, colorspace: Raw}
    - !<View> {name: Linear, colorspace: LinearCS}
  Rec709:
    - !<View> {name: Film, colorspace: LinearCS}

active_displays: [sRGB, Rec709]
active_views: [Raw, Linear, Film]

colorspaces:
  - !<ColorSpace>
    name: Raw
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
  - !<ColorSpace>
    name: LinearCS
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
"""


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
    assert controller.create_project("Color Options", root) is not None
    return controller


@pytest.fixture
def multi_ocio_config(tmp_path: Path) -> Path:
    path = tmp_path / "multi.ocio"
    path.write_text(MULTI_DISPLAY_OCIO_CONFIG, encoding="utf-8")
    return path


def _fake_options() -> OcioConfigOptions:
    return OcioConfigOptions(
        color_spaces=("scene_linear", "Raw", "LinearCS"),
        displays=("sRGB", "Rec709"),
        views_by_display={
            "sRGB": ("Raw", "Linear"),
            "Rec709": ("Film",),
        },
        default_display="sRGB",
        default_view="Raw",
        config_path="/tmp/fake.ocio",
        config_source="explicit",
    )


def test_display_change_updates_view_list(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.load_ocio_config_options",
        lambda config_path=None: _fake_options(),
    )

    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog._reload_ocio_options()

    assert [dialog.display_combo.itemText(i) for i in range(dialog.display_combo.count())] == [
        "sRGB",
        "Rec709",
    ]
    assert [dialog.view_combo.itemText(i) for i in range(dialog.view_combo.count())] == [
        "Raw",
        "Linear",
    ]

    dialog.display_combo.setCurrentText("Rec709")
    assert [dialog.view_combo.itemText(i) for i in range(dialog.view_combo.count())] == [
        "Film",
    ]
    assert dialog.view_combo.currentText() == "Film"


def test_default_display_and_view_selected(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.load_ocio_config_options",
        lambda config_path=None: _fake_options(),
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog._reload_ocio_options()
    assert dialog.display_combo.currentText() == "sRGB"
    assert dialog.view_combo.currentText() == "Raw"
    assert dialog.input_color_space_combo.currentText() == "scene_linear"


def test_saved_values_restored_into_combos(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend="ocio",
            config_path="/tmp/fake.ocio",
            input_color_space="LinearCS",
            display="Rec709",
            view="Film",
            exposure=0.0,
        ),
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.load_ocio_config_options",
        lambda config_path=None: _fake_options(),
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.input_color_space_combo.currentText() == "LinearCS"
    assert dialog.display_combo.currentText() == "Rec709"
    assert dialog.view_combo.currentText() == "Film"


def test_unknown_saved_value_kept_with_warning(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_color_settings_preference(
        workspace,
        ColorSettingsPreference(
            backend="ocio",
            config_path="/tmp/fake.ocio",
            input_color_space="MissingSpace",
            display="sRGB",
            view="Raw",
        ),
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.load_ocio_config_options",
        lambda config_path=None: _fake_options(),
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.input_color_space_combo.currentText() == "MissingSpace"
    assert "not in config list" in dialog.diagnostics_label.text()


def test_ocio_missing_shows_diagnostics_not_crash(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: False,
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog._reload_ocio_options()
    assert "PyOpenColorIO is not installed" in dialog.diagnostics_label.text()
    assert dialog.input_color_space_combo.isEnabled()


def test_invalid_config_path_shows_diagnostics(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.is_ocio_available",
        lambda: True,
    )

    def _raise(config_path=None):  # type: ignore[no-untyped-def]
        raise ColorTransformError(f"OCIO config file not found: {config_path}")

    monkeypatch.setattr(
        "nova_layer.ui.color_settings_dialog.load_ocio_config_options",
        _raise,
    )
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_path_edit.setText(str(tmp_path / "missing.ocio"))
    dialog._reload_ocio_options()
    assert "not found" in dialog.diagnostics_label.text()


def test_legacy_keeps_ocio_combos_disabled(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("Legacy")
    assert dialog.input_color_space_combo.isEnabled() is False
    assert dialog.display_combo.isEnabled() is False
    assert dialog.view_combo.isEnabled() is False
    assert dialog.apply_settings() is True


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_real_config_populates_combos(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    multi_ocio_config: Path,
) -> None:
    pytest.importorskip("PyOpenColorIO")
    dialog = ColorSettingsDialog(project_controller, workspace=workspace)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.backend_combo.setCurrentText("OCIO")
    dialog.config_path_edit.setText(str(multi_ocio_config))
    dialog._reload_ocio_options()
    assert dialog.display_combo.findText("sRGB") >= 0
    assert dialog.display_combo.findText("Rec709") >= 0
    dialog.display_combo.setCurrentText("Rec709")
    assert dialog.view_combo.currentText() == "Film"
