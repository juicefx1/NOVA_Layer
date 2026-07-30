from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova_layer.object_workflow.plugin_sdk.constants import (
    KNOWN_CAPABILITIES,
    SUPPORTED_PLUGIN_TYPES,
    SUPPORTED_SDK_VERSIONS,
    PluginType,
)
from nova_layer.object_workflow.plugin_sdk.errors import PluginValidationError


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    display_name: str
    description: str
    version: str
    author: str
    sdk_version: str
    plugin_type: PluginType
    capabilities: tuple[str, ...]
    entry_module: str
    optional_dependencies: tuple[str, ...] = ()
    source_path: Path | None = None

    @property
    def entry_file(self) -> Path | None:
        if self.source_path is None:
            return None
        return self.source_path / f"{self.entry_module}.py"


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Load and structurally validate manifest.json from a plugin directory."""
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PluginValidationError(f"manifest missing: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginValidationError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PluginValidationError("manifest root must be a JSON object")
    return parse_manifest(raw, source_path=plugin_dir)


def parse_manifest(raw: dict[str, Any], *, source_path: Path | None = None) -> PluginManifest:
    plugin_id = _require_str(raw, "plugin_id")
    display_name = _require_str(raw, "display_name")
    description = str(raw.get("description", "")).strip()
    version = _require_str(raw, "version")
    author = str(raw.get("author", "")).strip() or "unknown"
    sdk_version = _require_str(raw, "sdk_version")
    plugin_type = _require_str(raw, "plugin_type")
    entry_module = _require_str(raw, "entry_module")
    capabilities = _parse_string_list(raw.get("capabilities", []), field="capabilities")
    optional_dependencies = _parse_string_list(
        raw.get("optional_dependencies", []),
        field="optional_dependencies",
    )

    if not plugin_id:
        raise PluginValidationError("plugin_id must be non-empty")
    if "/" in plugin_id or "\\" in plugin_id or ".." in plugin_id:
        raise PluginValidationError(f"invalid plugin_id: {plugin_id!r}")
    if plugin_type not in SUPPORTED_PLUGIN_TYPES:
        raise PluginValidationError(
            f"unsupported plugin_type: {plugin_type!r}",
            code="PLUGIN_TYPE_UNSUPPORTED",
        )
    if sdk_version not in SUPPORTED_SDK_VERSIONS:
        raise PluginValidationError(
            f"incompatible sdk_version: {sdk_version!r} "
            f"(supported: {sorted(SUPPORTED_SDK_VERSIONS)})",
            code="PLUGIN_SDK_INCOMPATIBLE",
        )
    if not entry_module or "/" in entry_module or "\\" in entry_module or "." in entry_module:
        raise PluginValidationError(
            f"entry_module must be a simple module name, got {entry_module!r}"
        )
    if not capabilities:
        raise PluginValidationError("capabilities must declare at least one capability")
    unknown = [item for item in capabilities if item not in KNOWN_CAPABILITIES]
    # Unknown capabilities are allowed for forward compatibility but must be non-empty strings.
    for item in capabilities:
        if not item or not isinstance(item, str):
            raise PluginValidationError("capability entries must be non-empty strings")
    _ = unknown

    return PluginManifest(
        plugin_id=plugin_id,
        display_name=display_name,
        description=description,
        version=version,
        author=author,
        sdk_version=sdk_version,
        plugin_type=plugin_type,  # type: ignore[arg-type]
        capabilities=tuple(capabilities),
        entry_module=entry_module,
        optional_dependencies=tuple(optional_dependencies),
        source_path=source_path,
    )


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginValidationError(f"manifest field {key!r} must be a non-empty string")
    return value.strip()


def _parse_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PluginValidationError(f"manifest field {field!r} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PluginValidationError(
                f"manifest field {field!r} entries must be non-empty strings"
            )
        result.append(item.strip())
    return result
