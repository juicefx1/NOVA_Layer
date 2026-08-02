from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.adapters.persistence.migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationRegistry,
    migrate_1_0_to_1_1,
)
from test_domain import make_project


def test_current_schema_version_is_1_1() -> None:
    assert CURRENT_SCHEMA_VERSION == "1.1"


def test_migrate_1_0_to_1_1_sets_version_and_leaves_color_absent() -> None:
    project = make_project()
    manifest = project.model_dump(mode="json")
    manifest["schema_version"] = "1.0"
    manifest.pop("color_settings", None)
    migrated = migrate_1_0_to_1_1(manifest)
    assert migrated["schema_version"] == "1.1"
    assert "color_settings" not in migrated or migrated.get("color_settings") is None


def test_registry_migrates_1_0_to_1_1_preserving_fields() -> None:
    project = make_project()
    original_name = project.name
    shot_count = len(project.sequences[0].shots)
    manifest = project.model_dump(mode="json")
    manifest["schema_version"] = "1.0"
    manifest.pop("color_settings", None)
    before = deepcopy(manifest)

    result = MigrationRegistry().migrate(manifest)
    assert result.original_version == "1.0"
    assert result.final_version == "1.1"
    assert result.applied_steps == ("1.0 → 1.1",)
    assert result.manifest["name"] == original_name
    assert len(result.manifest["sequences"][0]["shots"]) == shot_count
    assert before["schema_version"] == "1.0"
    restored = JsonProjectStore()._load_project_json(json.dumps(result.manifest))
    assert restored.color_settings is None


def test_migration_chain_0_9_through_1_1() -> None:
    project = make_project()
    legacy = project.model_dump(mode="json")
    legacy["schema_version"] = "0.9"
    legacy["shots"] = legacy.pop("sequences")[0]["shots"]
    legacy.pop("color_settings", None)

    result = MigrationRegistry().migrate(legacy)
    assert result.original_version == "0.9"
    assert result.final_version == "1.1"
    assert result.applied_steps == ("0.9 → 1.0", "1.0 → 1.1")
    assert "sequences" in result.manifest
    assert "shots" not in result.manifest


def test_store_load_migrates_1_0_on_disk(tmp_path: Path) -> None:
    project = make_project()
    manifest = project.model_dump(mode="json")
    manifest["schema_version"] = "1.0"
    manifest.pop("color_settings", None)
    package = tmp_path / "Old.nova"
    package.mkdir()
    manifest_path = package / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    store = JsonProjectStore()
    restored = store.load(package)
    assert restored.schema_version == "1.1"
    assert restored.color_settings is None
    assert store.last_migration_steps == ("1.0 → 1.1",)
    # Source file unchanged until explicit save.
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == "1.0"
