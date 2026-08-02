from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

CURRENT_SCHEMA_VERSION = "1.1"
Manifest = dict[str, Any]
Migration = Callable[[Manifest], Manifest]


class MigrationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationResult:
    manifest: Manifest
    original_version: str
    final_version: str
    applied_steps: tuple[str, ...]


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise MigrationError(f"Invalid project schema version: {value}") from exc


def migrate_0_9_to_1_0(manifest: Manifest) -> Manifest:
    migrated = deepcopy(manifest)
    legacy_shots = migrated.pop("shots", [])
    migrated.setdefault("name", "Untitled Project")
    migrated.setdefault("sequences", [{"name": "Sequence 1", "shots": legacy_shots}])
    migrated["schema_version"] = "1.0"
    return migrated


def migrate_1_0_to_1_1(manifest: Manifest) -> Manifest:
    """Additive Soft bump: optional Project.color_settings (default absent/None)."""
    migrated = deepcopy(manifest)
    migrated["schema_version"] = "1.1"
    # Do not invent color_settings; missing key → Project.color_settings = None.
    # Strip accidental non-object values from experimental files.
    if "color_settings" in migrated and migrated["color_settings"] is not None:
        if not isinstance(migrated["color_settings"], dict):
            migrated["color_settings"] = None
    return migrated


class MigrationRegistry:
    def __init__(self) -> None:
        self._migrations: dict[str, tuple[str, Migration]] = {
            "0.9": ("1.0", migrate_0_9_to_1_0),
            "1.0": ("1.1", migrate_1_0_to_1_1),
        }

    def migrate(self, manifest: Manifest) -> MigrationResult:
        working = deepcopy(manifest)
        original_version = str(working.get("schema_version", "0.9"))
        current_tuple = _version_tuple(CURRENT_SCHEMA_VERSION)
        original_tuple = _version_tuple(original_version)
        if original_tuple > current_tuple:
            raise MigrationError(
                f"Project schema {original_version} is newer than supported schema "
                f"{CURRENT_SCHEMA_VERSION}. Open it with a newer NOVA Layer version."
            )

        version = original_version
        applied: list[str] = []
        while version != CURRENT_SCHEMA_VERSION:
            migration_entry = self._migrations.get(version)
            if migration_entry is None:
                raise MigrationError(
                    f"No safe migration path exists from schema {version} to "
                    f"{CURRENT_SCHEMA_VERSION}."
                )
            next_version, migration = migration_entry
            working = migration(working)
            if str(working.get("schema_version")) != next_version:
                raise MigrationError(
                    f"Migration {version} → {next_version} did not produce the expected schema."
                )
            applied.append(f"{version} → {next_version}")
            version = next_version

        return MigrationResult(
            manifest=working,
            original_version=original_version,
            final_version=version,
            applied_steps=tuple(applied),
        )
