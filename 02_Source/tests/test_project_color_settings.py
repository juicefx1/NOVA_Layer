from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nova_layer.adapters.color.settings import to_runtime_color_settings
from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.domain.models import Project, ProjectColorSettings
from test_domain import make_project


def test_new_project_schema_version_is_1_1() -> None:
    project = Project(name="Color Schema")
    assert project.schema_version == "1.1"
    assert project.color_settings is None


def test_make_project_defaults() -> None:
    project = make_project()
    assert project.schema_version == "1.1"
    assert project.color_settings is None


def test_project_color_settings_roundtrip_fields() -> None:
    settings = ProjectColorSettings(
        backend="ocio",
        config_kind="package_relative",
        config_value="configs/show.ocio",
        input_color_space="scene_linear",
        display="sRGB",
        view="Raw",
        exposure=0.5,
        pin_display_view=True,
    )
    restored = ProjectColorSettings.model_validate(settings.model_dump(mode="json"))
    assert restored == settings


@pytest.mark.parametrize(
    "kind",
    ["env", "package_relative", "absolute", "named"],
)
def test_all_config_kinds_accepted(kind: str) -> None:
    settings = ProjectColorSettings(config_kind=kind, config_value="x")  # type: ignore[arg-type]
    assert settings.config_kind == kind


def test_invalid_backend_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectColorSettings(backend="aces")  # type: ignore[arg-type]


def test_invalid_config_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectColorSettings(config_kind="builtin")  # type: ignore[arg-type]


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectColorSettings.model_validate({"backend": "legacy", "unexpected": 1})


def test_project_with_color_settings_store_roundtrip(tmp_path: Path) -> None:
    project = make_project()
    project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="absolute",
        config_value="/tmp/studio.ocio",
        input_color_space="ACEScg",
        display="Rec709",
        view="Film",
        exposure=-1.0,
        pin_display_view=False,
    )
    package = tmp_path / project.package_name
    store = JsonProjectStore()
    store.save(project, package)
    restored = store.load(package)
    assert restored.schema_version == "1.1"
    assert restored.color_settings is not None
    assert restored.color_settings.backend == "ocio"
    assert restored.color_settings.config_kind == "absolute"
    assert restored.color_settings.input_color_space == "ACEScg"
    assert restored.color_settings.exposure == pytest.approx(-1.0)


def test_to_runtime_color_settings_helper() -> None:
    project_settings = ProjectColorSettings(
        backend="legacy",
        config_kind="env",
        config_value="OCIO",
        input_color_space="Raw",
        pin_display_view=True,
    )
    runtime = to_runtime_color_settings(project_settings)
    assert runtime is not None
    assert runtime.backend == "legacy"
    assert runtime.config_kind == "env"
    assert runtime.config_value == "OCIO"
    assert runtime.input_color_space == "Raw"
    assert runtime.pin_display_view is True
    assert to_runtime_color_settings(None) is None
