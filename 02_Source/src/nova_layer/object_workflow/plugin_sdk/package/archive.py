from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nova_layer.object_workflow.plugin_sdk.package.constants import (
    PACKAGE_EXTENSION,
    PACKAGE_MANIFEST_FILENAME,
    PLUGIN_MANIFEST_FILENAME,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import (
    PluginPackageInstallError,
    PluginPackageValidationError,
)
from nova_layer.object_workflow.plugin_sdk.package.models import OpenedPackage


def is_nova_plugin_path(path: Path | str) -> bool:
    candidate = Path(path)
    if candidate.is_dir():
        return (candidate / PACKAGE_MANIFEST_FILENAME).is_file() and (
            candidate / PLUGIN_MANIFEST_FILENAME
        ).is_file()
    return candidate.suffix.lower() == PACKAGE_EXTENSION


def open_package(path: Path | str) -> OpenedPackage:
    """Open a .nova-plugin archive or an unpacked package directory."""
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise PluginPackageValidationError(
            f"package path does not exist: {candidate}",
            code="PLUGIN_PACKAGE_NOT_FOUND",
        )
    if candidate.is_dir():
        return OpenedPackage(root=candidate, cleanup=False)
    if candidate.suffix.lower() != PACKAGE_EXTENSION:
        raise PluginPackageValidationError(
            f"expected {PACKAGE_EXTENSION} archive or package directory, got {candidate.name!r}",
            code="PLUGIN_PACKAGE_INVALID_EXTENSION",
        )
    if not zipfile.is_zipfile(candidate):
        raise PluginPackageValidationError(
            f"not a valid zip-based {PACKAGE_EXTENSION}: {candidate}",
            code="PLUGIN_PACKAGE_CORRUPT",
        )
    temp = tempfile.TemporaryDirectory(prefix="nova_plugin_")
    root = Path(temp.name)
    try:
        _safe_extract_zip(candidate, root)
    except Exception:
        temp.cleanup()
        raise
    return OpenedPackage(root=root, cleanup=True, _temp_dir=temp)


def path_is_within(path: Path, root: Path) -> bool:
    """Return True when path resolves inside root (prevents prefix-path tricks)."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    dest_root = destination.resolve()
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                # Create directories explicitly only when they stay inside dest_root.
                if name and name.endswith("/"):
                    _validate_member_name(name.rstrip("/"))
                    target_dir = (destination / name).resolve()
                    if not path_is_within(target_dir, dest_root):
                        raise PluginPackageValidationError(
                            f"archive member escapes destination: {info.filename!r}",
                            code="PLUGIN_PACKAGE_UNSAFE_PATH",
                        )
                    target_dir.mkdir(parents=True, exist_ok=True)
                continue
            _validate_member_name(name)
            if _zip_member_is_symlink(info):
                raise PluginPackageValidationError(
                    f"symbolic links are not allowed in plugin packages: {info.filename!r}",
                    code="PLUGIN_PACKAGE_SYMLINK_FORBIDDEN",
                )
            target = (destination / name).resolve()
            if not path_is_within(target, dest_root):
                raise PluginPackageValidationError(
                    f"archive member escapes destination: {info.filename!r}",
                    code="PLUGIN_PACKAGE_UNSAFE_PATH",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def _validate_member_name(name: str) -> None:
    if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
        raise PluginPackageValidationError(
            f"unsafe archive member path: {name!r}",
            code="PLUGIN_PACKAGE_UNSAFE_PATH",
        )
    if name.startswith("..") or name == "..":
        raise PluginPackageValidationError(
            f"unsafe archive member path: {name!r}",
            code="PLUGIN_PACKAGE_UNSAFE_PATH",
        )


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True when the zip member is a Unix symbolic link."""
    is_symlink = getattr(info, "is_symlink", None)
    if callable(is_symlink):
        return bool(is_symlink())
    # external_attr upper 16 bits = Unix st_mode when create_system == 3 (UNIX).
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginPackageValidationError(f"invalid JSON at {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PluginPackageValidationError(f"{path.name} root must be a JSON object")
    return raw


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 64)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def copy_package_payload(source_root: Path, destination: Path) -> None:
    """Atomically install package payload into destination.

    Writes into a sibling staging directory, then swaps into place. On failure the
    previous destination (if any) remains usable.
    """
    destination = destination.expanduser()
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = parent / f".staging_{destination.name}_{token}"
    backup = parent / f".backup_{destination.name}_{token}"
    try:
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source_root, staging)
        if destination.exists():
            if backup.exists():
                shutil.rmtree(backup)
            destination.rename(backup)
            try:
                staging.rename(destination)
            except Exception:
                # Restore previous install so a failed update leaves it usable.
                if destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                backup.rename(destination)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.rename(destination)
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, PluginPackageInstallError):
            raise
        raise PluginPackageInstallError(
            f"failed to install package payload at {destination}: {exc}",
            code="PLUGIN_PACKAGE_INSTALL_FAILED",
        ) from exc


def iter_payload_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path
