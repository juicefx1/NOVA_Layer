from __future__ import annotations

from pathlib import Path

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.domain.models import ProjectColorSettings
from test_domain import make_project


def test_project_store_roundtrip_without_color_settings(tmp_path: Path) -> None:
    project = make_project()
    assert project.color_settings is None
    package = tmp_path / project.package_name
    store = JsonProjectStore()
    store.save(project, package)
    restored = store.load(package)
    assert restored.schema_version == "1.1"
    assert restored.color_settings is None
    assert restored.name == project.name
    assert len(restored.sequences[0].shots) == len(project.sequences[0].shots)


def test_project_store_roundtrip_with_color_settings(tmp_path: Path) -> None:
    project = make_project()
    project.color_settings = ProjectColorSettings(
        backend="ocio",
        config_kind="env",
        config_value="OCIO",
        input_color_space="scene_linear",
        pin_display_view=True,
    )
    package = tmp_path / project.package_name
    store = JsonProjectStore()
    store.save(project, package)
    restored = store.load(package)
    assert restored.color_settings is not None
    assert restored.color_settings.model_dump() == project.color_settings.model_dump()
