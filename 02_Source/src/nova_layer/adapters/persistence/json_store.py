from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from nova_layer.adapters.persistence.migrations import MigrationError, MigrationRegistry
from nova_layer.domain.models import Project


class ProjectStoreError(RuntimeError):
    pass


class JsonProjectStore:
    manifest_name = "manifest.json"

    def __init__(self, migrations: MigrationRegistry | None = None) -> None:
        self._migrations = migrations or MigrationRegistry()
        self.last_migration_steps: tuple[str, ...] = ()

    def recovery_path(self, package_path: Path) -> Path:
        resolved = package_path.resolve()
        return resolved.with_name(f"{resolved.name}.recovery.json")

    def has_recovery(self, package_path: Path) -> bool:
        return self.recovery_path(package_path).is_file()

    def load_recovery(self, package_path: Path) -> Project:
        recovery_path = self.recovery_path(package_path)
        try:
            return self._load_project_json(recovery_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProjectStoreError(f"could not load recovery journal: {exc}") from exc

    def discard_recovery(self, package_path: Path) -> None:
        recovery_path = self.recovery_path(package_path)
        try:
            recovery_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ProjectStoreError(f"could not discard recovery journal: {exc}") from exc

    def save(self, project: Project, package_path: Path) -> Path:
        package_path = package_path.resolve()
        temporary_path = package_path.with_name(f"{package_path.name}.{uuid4().hex}.tmp")
        backup_path = package_path.with_name(f"{package_path.name}.backup")
        recovery_path = self.recovery_path(package_path)
        recovery_temporary = recovery_path.with_name(f"{recovery_path.name}.tmp")

        if temporary_path.exists():
            raise ProjectStoreError(f"temporary save path already exists: {temporary_path}")

        try:
            recovery_temporary.write_text(
                json.dumps(project.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(recovery_temporary, recovery_path)
            temporary_path.mkdir(parents=True)
            for folder in ("evidence", "masks", "previews", "renders", "cache", "logs"):
                existing_folder = package_path / folder
                temporary_folder = temporary_path / folder
                if existing_folder.is_dir():
                    shutil.copytree(existing_folder, temporary_folder)
                else:
                    temporary_folder.mkdir()

            manifest_path = temporary_path / self.manifest_name
            manifest_path.write_text(
                json.dumps(project.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            if backup_path.exists():
                shutil.rmtree(backup_path)
            if package_path.exists():
                os.replace(package_path, backup_path)
            os.replace(temporary_path, package_path)
            if backup_path.exists():
                shutil.rmtree(backup_path)
            recovery_path.unlink(missing_ok=True)
            return package_path
        except Exception as exc:
            recovery_temporary.unlink(missing_ok=True)
            if temporary_path.exists():
                shutil.rmtree(temporary_path)
            if backup_path.exists() and not package_path.exists():
                os.replace(backup_path, package_path)
            raise ProjectStoreError(f"could not save project: {exc}") from exc

    def load(self, package_path: Path) -> Project:
        manifest_path = package_path.resolve() / self.manifest_name
        try:
            return self._load_project_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProjectStoreError(f"could not load project: {exc}") from exc

    def _load_project_json(self, text: str) -> Project:
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise MigrationError("Project manifest root must be a JSON object.")
            result = self._migrations.migrate(raw)
            project = Project.model_validate(result.manifest)
        except (json.JSONDecodeError, MigrationError, ValueError) as exc:
            self.last_migration_steps = ()
            raise ProjectStoreError(str(exc)) from exc
        self.last_migration_steps = result.applied_steps
        return project
