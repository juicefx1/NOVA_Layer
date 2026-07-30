from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from nova_layer.object_workflow.domain.models import Project
from nova_layer.object_workflow.ports.project_store import ProjectStoreError

ASSET_DIRS = ("source", "masks", "intent", "extractions")


def validate_relative_asset_path(relative_path: str) -> str:
    if not relative_path or relative_path.startswith("/") or relative_path.startswith("\\"):
        raise ProjectStoreError(
            "INVALID_ASSET_PATH",
            f"absolute paths are forbidden: {relative_path}",
        )
    normalized = relative_path.replace("\\", "/")
    parts = Path(normalized).parts
    if any(part in {"", ".", ".."} for part in parts) or ".." in normalized.split("/"):
        raise ProjectStoreError(
            "INVALID_ASSET_PATH",
            f"path traversal is forbidden: {relative_path}",
        )
    if normalized.startswith("assets/") is False:
        raise ProjectStoreError(
            "INVALID_ASSET_PATH",
            f"asset path must be under assets/: {relative_path}",
        )
    return normalized


class JsonProjectStore:
    manifest_name = "manifest.json"

    def save(self, project: Project, package_path: Path, assets: dict[str, bytes]) -> None:
        package_path = package_path.resolve()
        if package_path.suffix != ".nova" and not package_path.name.endswith(".nova"):
            # Allow directory names ending with .nova
            pass

        for relative_path in assets:
            validate_relative_asset_path(relative_path)
        for entity_path in _iter_relative_paths(project):
            validate_relative_asset_path(entity_path)

        temporary_path = package_path.with_name(f"{package_path.name}.{uuid4().hex}.tmp")
        backup_path = package_path.with_name(f"{package_path.name}.backup")

        if temporary_path.exists():
            raise ProjectStoreError(
                "SAVE_FAILED",
                f"temporary save path already exists: {temporary_path}",
            )

        try:
            temporary_path.mkdir(parents=True)
            assets_root = temporary_path / "assets"
            for folder in ASSET_DIRS:
                (assets_root / folder).mkdir(parents=True, exist_ok=True)

            for relative_path, blob in assets.items():
                safe = validate_relative_asset_path(relative_path)
                target = temporary_path / Path(safe)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)

            manifest_path = temporary_path / self.manifest_name
            payload = project.model_dump(mode="json", by_alias=True)
            manifest_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            if backup_path.exists():
                shutil.rmtree(backup_path)
            if package_path.exists():
                os.replace(package_path, backup_path)
            os.replace(temporary_path, package_path)
            if backup_path.exists():
                shutil.rmtree(backup_path)
        except ProjectStoreError:
            _cleanup(temporary_path, backup_path, package_path)
            raise
        except Exception as exc:
            _cleanup(temporary_path, backup_path, package_path)
            raise ProjectStoreError("SAVE_FAILED", f"could not save project: {exc}") from exc

    def load(self, package_path: Path) -> tuple[Project, dict[str, bytes]]:
        package_path = package_path.resolve()
        manifest_path = package_path / self.manifest_name
        if not manifest_path.is_file():
            raise ProjectStoreError("LOAD_FAILED", f"missing manifest: {manifest_path}")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProjectStoreError("LOAD_FAILED", f"could not parse manifest: {exc}") from exc

        schema_version = raw.get("schema_version")
        if schema_version != "2.0":
            raise ProjectStoreError(
                "UNSUPPORTED_SCHEMA",
                f"unsupported schema_version: {schema_version!r}",
            )

        try:
            project = Project.model_validate(raw)
        except Exception as exc:
            raise ProjectStoreError("LOAD_FAILED", f"invalid project document: {exc}") from exc

        from nova_layer.object_workflow.domain.generation import migrate_project_generation_history

        migrate_project_generation_history(project)

        assets: dict[str, bytes] = {}
        for relative_path in _iter_relative_paths(project):
            safe = validate_relative_asset_path(relative_path)
            asset_path = package_path / Path(safe)
            if not asset_path.is_file():
                raise ProjectStoreError("LOAD_FAILED", f"missing asset: {relative_path}")
            assets[safe] = asset_path.read_bytes()
        return project, assets


def _iter_relative_paths(project: Project) -> list[str]:
    paths: list[str] = []
    for source in project.source_images:
        paths.append(source.relative_asset_path)
    for candidate_set in project.candidate_sets:
        for candidate in candidate_set.candidates:
            paths.append(candidate.mask_relative_path)
            if candidate.preview_relative_path != candidate.mask_relative_path:
                paths.append(candidate.preview_relative_path)
    for hypothesis in project.hypotheses:
        paths.append(hypothesis.mask_relative_path)
    for confirmed in project.confirmed_objects:
        paths.append(confirmed.mask_relative_path)
    for extraction in project.extraction_results:
        paths.append(extraction.relative_asset_path)
    return paths


def _cleanup(temporary_path: Path, backup_path: Path, package_path: Path) -> None:
    if temporary_path.exists():
        shutil.rmtree(temporary_path, ignore_errors=True)
    if backup_path.exists() and not package_path.exists():
        os.replace(backup_path, package_path)
