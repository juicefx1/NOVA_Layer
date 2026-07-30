from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from nova_layer.object_workflow.plugin_sdk.manifest import load_manifest
from nova_layer.object_workflow.plugin_sdk.package.constants import (
    PACKAGE_EXTENSION,
    PACKAGE_FORMAT_VERSION,
    PACKAGE_MANIFEST_FILENAME,
    PLUGIN_MANIFEST_FILENAME,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import PluginPackageValidationError
from nova_layer.object_workflow.plugin_sdk.package.models import PluginPackageManifest


def build_nova_plugin_package(
    plugin_dir: Path | str,
    destination: Path | str,
    *,
    package_manifest: dict[str, Any] | PluginPackageManifest | None = None,
) -> Path:
    """Build a local .nova-plugin zip from a Plugin SDK plugin directory.

    Intended for tests and offline packaging. Never downloads anything.
    """
    source = Path(plugin_dir).expanduser()
    dest = Path(destination).expanduser()
    if dest.suffix.lower() != PACKAGE_EXTENSION:
        dest = dest.with_suffix(PACKAGE_EXTENSION)
    if not source.is_dir():
        raise PluginPackageValidationError(f"plugin directory not found: {source}")
    plugin_manifest_path = source / PLUGIN_MANIFEST_FILENAME
    if not plugin_manifest_path.is_file():
        raise PluginPackageValidationError(
            f"missing {PLUGIN_MANIFEST_FILENAME} in {source}"
        )
    plugin = load_manifest(source)

    if isinstance(package_manifest, PluginPackageManifest):
        package_payload = package_manifest.to_dict()
    elif isinstance(package_manifest, dict):
        package_payload = dict(package_manifest)
    else:
        package_payload = {
            "package_format": PACKAGE_FORMAT_VERSION,
            "plugin_id": plugin.plugin_id,
            "version": plugin.version,
            "sdk_version": plugin.sdk_version,
            "display_name": plugin.display_name,
            "description": plugin.description,
            "author": plugin.author,
        }

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            PACKAGE_MANIFEST_FILENAME,
            json.dumps(package_payload, indent=2, sort_keys=True) + "\n",
        )
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            if relative == PACKAGE_MANIFEST_FILENAME:
                continue
            zf.write(path, arcname=relative)
    return dest
