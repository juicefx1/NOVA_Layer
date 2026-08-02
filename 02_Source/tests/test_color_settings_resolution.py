from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nova_layer.adapters.color.settings import (
    ColorSettings,
    resolve_color_settings,
)


def test_project_backend_over_workspace() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(backend="ocio"),
        workspace=ColorSettings(backend="legacy"),
    )
    assert resolved.backend == "ocio"
    assert resolved.source_backend == "project"


def test_workspace_backend_when_project_missing() -> None:
    resolved = resolve_color_settings(
        project=None,
        workspace=ColorSettings(backend="ocio"),
    )
    assert resolved.backend == "ocio"
    assert resolved.source_backend == "workspace"


def test_default_backend_legacy() -> None:
    resolved = resolve_color_settings(project=None, workspace=None)
    assert resolved.backend == "legacy"
    assert resolved.source_backend == "default"


def test_invalid_backend_falls_through_with_warning() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(backend="ACES"),
        workspace=ColorSettings(backend="ocio"),
    )
    assert resolved.backend == "ocio"
    assert resolved.source_backend == "workspace"
    assert any("invalid" in item for item in resolved.warnings)


def test_invalid_backend_both_falls_to_legacy() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(backend="nope"),
        workspace=ColorSettings(backend=""),
    )
    assert resolved.backend == "legacy"
    assert resolved.source_backend == "default"


def test_project_input_color_space_priority() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(input_color_space="ACEScg"),
        workspace=ColorSettings(input_color_space="Raw"),
    )
    assert resolved.input_color_space == "ACEScg"
    assert resolved.source_input_color_space == "project"


def test_default_input_color_space() -> None:
    resolved = resolve_color_settings(project=None, workspace=None)
    assert resolved.input_color_space == "scene_linear"
    assert resolved.source_input_color_space == "default"


def test_pin_display_view_true_prefers_project() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(
            pin_display_view=True,
            display="Rec709",
            view="Film",
        ),
        workspace=ColorSettings(display="sRGB", view="Raw"),
    )
    assert resolved.display == "Rec709"
    assert resolved.view == "Film"
    assert resolved.source_display == "project"
    assert resolved.source_view == "project"


def test_pin_display_view_false_prefers_workspace() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(
            pin_display_view=False,
            display="Rec709",
            view="Film",
        ),
        workspace=ColorSettings(display="sRGB", view="Raw"),
    )
    assert resolved.display == "sRGB"
    assert resolved.view == "Raw"
    assert resolved.source_display == "workspace"
    assert resolved.source_view == "workspace"


def test_pin_false_falls_to_project_when_workspace_missing() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(display="Rec709", view="Film"),
        workspace=None,
    )
    assert resolved.display == "Rec709"
    assert resolved.view == "Film"
    assert resolved.source_display == "project"


def test_session_exposure_priority() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(exposure=1.0),
        workspace=ColorSettings(exposure=2.0),
        session=ColorSettings(exposure=-0.5),
    )
    assert resolved.exposure == pytest.approx(-0.5)
    assert resolved.source_exposure == "session"


def test_workspace_exposure_over_project() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(exposure=1.0),
        workspace=ColorSettings(exposure=2.0),
        session=None,
    )
    assert resolved.exposure == pytest.approx(2.0)
    assert resolved.source_exposure == "workspace"


def test_default_exposure_zero() -> None:
    resolved = resolve_color_settings(project=None, workspace=None)
    assert resolved.exposure == 0.0
    assert resolved.source_exposure == "default"


def test_invalid_exposure_falls_through() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(exposure=1.0),
        workspace=ColorSettings(exposure=float("nan")),
        session=ColorSettings(exposure=float("inf")),
    )
    assert resolved.exposure == pytest.approx(1.0)
    assert resolved.source_exposure == "project"
    assert len(resolved.warnings) >= 2


def test_env_config_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "studio.ocio"
    config.write_text("dummy", encoding="utf-8")
    monkeypatch.setenv("MY_OCIO", str(config))
    resolved = resolve_color_settings(
        project=ColorSettings(config_kind="env", config_value="MY_OCIO"),
        workspace=None,
        environ={"MY_OCIO": str(config)},
    )
    assert resolved.config_path == config.resolve()
    assert resolved.config_source == "env:MY_OCIO"
    assert resolved.source_config == "environment"


def test_env_default_variable_name(tmp_path: Path) -> None:
    config = tmp_path / "from_ocio.ocio"
    config.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=ColorSettings(config_kind="env", config_value=None),
        workspace=None,
        environ={"OCIO": str(config)},
    )
    assert resolved.config_path == config.resolve()
    assert resolved.config_source == "env:OCIO"


def test_missing_env_warning_then_workspace(tmp_path: Path) -> None:
    workspace_config = tmp_path / "ws.ocio"
    workspace_config.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=ColorSettings(config_kind="env", config_value="MISSING_OCIO"),
        workspace=ColorSettings(
            config_kind="absolute",
            config_value=str(workspace_config),
        ),
        environ={},
    )
    assert resolved.config_path == workspace_config.resolve()
    assert resolved.source_config == "workspace"
    assert any("MISSING_OCIO" in item for item in resolved.warnings)


def test_package_relative_ok(tmp_path: Path) -> None:
    root = tmp_path / "proj.nova"
    configs = root / "configs"
    configs.mkdir(parents=True)
    ocio = configs / "show.ocio"
    ocio.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=ColorSettings(
            config_kind="package_relative",
            config_value="configs/show.ocio",
        ),
        workspace=None,
        project_root=root,
    )
    assert resolved.config_path == ocio.resolve()
    assert resolved.config_source == "package_relative"
    assert resolved.source_config == "project"


def test_package_relative_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "proj.nova"
    root.mkdir()
    outside = tmp_path / "secret.ocio"
    outside.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=ColorSettings(
            config_kind="package_relative",
            config_value="../secret.ocio",
        ),
        workspace=None,
        project_root=root,
    )
    assert resolved.config_path is None
    assert resolved.source_config == "none"
    assert any("unsafe" in item or "escaped" in item for item in resolved.warnings)


def test_package_relative_missing_file_warning(tmp_path: Path) -> None:
    root = tmp_path / "proj.nova"
    root.mkdir()
    resolved = resolve_color_settings(
        project=ColorSettings(
            config_kind="package_relative",
            config_value="configs/missing.ocio",
        ),
        workspace=None,
        project_root=root,
    )
    assert resolved.config_path is None
    assert any("not found" in item for item in resolved.warnings)


def test_absolute_ok(tmp_path: Path) -> None:
    ocio = tmp_path / "abs.ocio"
    ocio.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=None,
        workspace=ColorSettings(config_kind="absolute", config_value=str(ocio)),
    )
    assert resolved.config_path == ocio.resolve()
    assert resolved.source_config == "workspace"


def test_absolute_missing_warning(tmp_path: Path) -> None:
    missing = tmp_path / "gone.ocio"
    resolved = resolve_color_settings(
        project=ColorSettings(config_kind="absolute", config_value=str(missing)),
        workspace=None,
    )
    assert resolved.config_path is None
    assert any("not found" in item for item in resolved.warnings)


def test_named_unsupported_warning() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(config_kind="named", config_value="aces_1.3"),
        workspace=None,
        environ={},
    )
    assert resolved.config_path is None
    assert resolved.source_config == "none"
    assert any("named" in item and "not supported" in item for item in resolved.warnings)


def test_blank_string_normalization() -> None:
    resolved = resolve_color_settings(
        project=ColorSettings(
            backend="  ",
            input_color_space="",
            display="   ",
            view="",
            config_kind="",
            config_value="",
        ),
        workspace=ColorSettings(backend="ocio", input_color_space="Raw"),
    )
    assert resolved.backend == "ocio"
    assert resolved.input_color_space == "Raw"
    assert resolved.display is None
    assert resolved.view is None


def test_fallback_env_ocio_when_layers_empty(tmp_path: Path) -> None:
    ocio = tmp_path / "global.ocio"
    ocio.write_text("dummy", encoding="utf-8")
    resolved = resolve_color_settings(
        project=None,
        workspace=None,
        environ={"OCIO": str(ocio)},
    )
    assert resolved.config_path == ocio.resolve()
    assert resolved.source_config == "environment"


def test_source_provenance_defaults() -> None:
    resolved = resolve_color_settings(project=None, workspace=None, environ={})
    assert resolved.source_backend == "default"
    assert resolved.source_config == "none"
    assert resolved.source_input_color_space == "default"
    assert resolved.source_display == "none"
    assert resolved.source_view == "none"
    assert resolved.source_exposure == "default"
    assert resolved.warnings == ()


def test_input_dataclasses_remain_immutable() -> None:
    project = ColorSettings(backend="ocio", exposure=1.0, display="sRGB")
    workspace = ColorSettings(backend="legacy", exposure=2.0)
    before_project = replace(project)
    before_workspace = replace(workspace)
    resolve_color_settings(project=project, workspace=workspace, session=None)
    assert project == before_project
    assert workspace == before_workspace
