from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova_layer.object_workflow.plugin_sdk.manifest import PluginManifest


@dataclass(frozen=True, slots=True)
class PluginPackageManifest:
    """Feature 12 package.json contract (distinct from Plugin SDK manifest.json)."""

    package_format: str
    plugin_id: str
    version: str
    sdk_version: str
    display_name: str = ""
    description: str = ""
    author: str = ""
    checksum_sha256: str | None = None
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "package_format": self.package_format,
            "plugin_id": self.plugin_id,
            "version": self.version,
            "sdk_version": self.sdk_version,
        }
        if self.display_name:
            payload["display_name"] = self.display_name
        if self.description:
            payload["description"] = self.description
        if self.author:
            payload["author"] = self.author
        if self.checksum_sha256:
            payload["checksum_sha256"] = self.checksum_sha256
        return payload


@dataclass(frozen=True, slots=True)
class PackageCompatibilityReport:
    compatible: bool
    reasons: tuple[str, ...] = ()
    sdk_version: str = ""
    package_format: str = ""
    plugin_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "reasons": list(self.reasons),
            "sdk_version": self.sdk_version,
            "package_format": self.package_format,
            "plugin_type": self.plugin_type,
        }


@dataclass(frozen=True, slots=True)
class PackageValidationResult:
    ok: bool
    package_path: Path
    package_manifest: PluginPackageManifest | None = None
    plugin_manifest: PluginManifest | None = None
    compatibility: PackageCompatibilityReport | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "package_path": str(self.package_path),
            "package_manifest": (
                None if self.package_manifest is None else self.package_manifest.to_dict()
            ),
            "plugin_manifest": (
                None
                if self.plugin_manifest is None
                else {
                    "plugin_id": self.plugin_manifest.plugin_id,
                    "version": self.plugin_manifest.version,
                    "sdk_version": self.plugin_manifest.sdk_version,
                    "plugin_type": self.plugin_manifest.plugin_type,
                }
            ),
            "compatibility": (
                None if self.compatibility is None else self.compatibility.to_dict()
            ),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class InstalledPluginRecord:
    plugin_id: str
    version: str
    sdk_version: str
    plugin_type: str
    display_name: str
    install_path: str
    package_format: str
    source_package: str | None = None
    installed_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "version": self.version,
            "sdk_version": self.sdk_version,
            "plugin_type": self.plugin_type,
            "display_name": self.display_name,
            "install_path": self.install_path,
            "package_format": self.package_format,
            "source_package": self.source_package,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> InstalledPluginRecord:
        return cls(
            plugin_id=str(raw.get("plugin_id", "")),
            version=str(raw.get("version", "")),
            sdk_version=str(raw.get("sdk_version", "")),
            plugin_type=str(raw.get("plugin_type", "")),
            display_name=str(raw.get("display_name", "")),
            install_path=str(raw.get("install_path", "")),
            package_format=str(raw.get("package_format", "")),
            source_package=(
                None
                if raw.get("source_package") in (None, "")
                else str(raw.get("source_package"))
            ),
            installed_at=str(raw.get("installed_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )


@dataclass
class OpenedPackage:
    """Temporary or directory-backed view of package contents."""

    root: Path
    cleanup: bool = False
    _temp_dir: Any = field(default=None, repr=False)

    def close(self) -> None:
        if not self.cleanup:
            return
        temp = self._temp_dir
        if temp is not None:
            temp.cleanup()
            self._temp_dir = None
