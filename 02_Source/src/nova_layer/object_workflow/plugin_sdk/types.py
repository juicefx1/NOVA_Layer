from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from nova_layer.object_workflow.plugin_sdk.constants import PluginType
from nova_layer.object_workflow.plugin_sdk.manifest import PluginManifest

PluginLifecycle = Literal[
    "discovered",
    "validated",
    "loaded",
    "registered",
    "available",
    "unavailable",
    "failed",
    "shutdown",
]


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """UI / diagnostic view of a plugin (available or failed)."""

    plugin_id: str
    display_name: str
    description: str
    version: str
    author: str
    sdk_version: str
    plugin_type: PluginType | str
    capabilities: tuple[str, ...]
    availability: Literal["available", "unavailable"]
    failure_reason: str
    lifecycle: PluginLifecycle
    source_path: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginRecord:
    """Mutable manager-owned record for one discovered plugin directory."""

    plugin_dir: Path
    manifest: PluginManifest | None = None
    lifecycle: PluginLifecycle = "discovered"
    failure_reason: str = ""
    module_name: str | None = None
    instance: Any | None = None
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_info(self) -> PluginInfo:
        if self.manifest is None:
            return PluginInfo(
                plugin_id=self.plugin_dir.name,
                display_name=self.plugin_dir.name,
                description="",
                version="",
                author="",
                sdk_version="",
                plugin_type="unknown",
                capabilities=(),
                availability="unavailable",
                failure_reason=self.failure_reason or "manifest not loaded",
                lifecycle=self.lifecycle,
                source_path=str(self.plugin_dir),
                configuration=dict(self.configuration),
            )
        available = self.lifecycle in {"registered", "available"} and not self.failure_reason
        return PluginInfo(
            plugin_id=self.manifest.plugin_id,
            display_name=self.manifest.display_name,
            description=self.manifest.description,
            version=self.manifest.version,
            author=self.manifest.author,
            sdk_version=self.manifest.sdk_version,
            plugin_type=self.manifest.plugin_type,
            capabilities=self.manifest.capabilities,
            availability="available" if available else "unavailable",
            failure_reason=self.failure_reason,
            lifecycle="available" if available else self.lifecycle,
            source_path=str(self.plugin_dir),
            configuration=dict(self.configuration),
        )
