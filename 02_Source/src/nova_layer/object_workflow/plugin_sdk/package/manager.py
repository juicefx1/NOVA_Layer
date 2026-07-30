from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.plugin_sdk.package.archive import (
    copy_package_payload,
    open_package,
    path_is_within,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import (
    PluginPackageInstallError,
    PluginPackageValidationError,
)
from nova_layer.object_workflow.plugin_sdk.package.models import (
    InstalledPluginRecord,
    PackageValidationResult,
)
from nova_layer.object_workflow.plugin_sdk.package.paths import (
    default_plugin_install_root,
    safe_install_dirname,
)
from nova_layer.object_workflow.plugin_sdk.package.validation import validate_plugin_package


class PluginPackageManager:
    """Local-only installer for .nova-plugin packages (Product Feature 12).

    Preserves the Plugin SDK discovery/load path: packages are extracted into an
    install root that PluginManager can discover like any other plugin directory.
    """

    def __init__(
        self,
        *,
        install_root: Path | str | None = None,
        workspace: WorkspaceManager | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._workspace = workspace
        self._environ = dict(environ) if environ is not None else None
        if install_root is not None:
            self._install_root = Path(install_root).expanduser()
        elif workspace is not None:
            configured = workspace.plugin_install_root()
            self._install_root = (
                Path(configured).expanduser()
                if configured
                else default_plugin_install_root(environ=self._environ)
            )
        else:
            self._install_root = default_plugin_install_root(environ=self._environ)

    @property
    def install_root(self) -> Path:
        return self._install_root

    @property
    def workspace(self) -> WorkspaceManager | None:
        return self._workspace

    def validate(self, package_path: Path | str) -> PackageValidationResult:
        return validate_plugin_package(package_path)

    def inspect(self, package_path: Path | str) -> PackageValidationResult:
        result = validate_plugin_package(package_path)
        if not result.ok:
            detail = "; ".join(result.errors) or "package validation failed"
            raise PluginPackageValidationError(detail)
        return result

    def list_installed(self) -> list[InstalledPluginRecord]:
        if self._workspace is not None:
            return [
                InstalledPluginRecord.from_dict(item)
                for item in self._workspace.installed_plugins()
            ]
        records: list[InstalledPluginRecord] = []
        if not self._install_root.is_dir():
            return records
        for child in sorted(self._install_root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / "manifest.json").is_file():
                continue
            result = validate_plugin_package(child)
            if not result.ok or result.plugin_manifest is None or result.package_manifest is None:
                continue
            plugin = result.plugin_manifest
            package = result.package_manifest
            records.append(
                InstalledPluginRecord(
                    plugin_id=plugin.plugin_id,
                    version=plugin.version,
                    sdk_version=plugin.sdk_version,
                    plugin_type=plugin.plugin_type,
                    display_name=plugin.display_name,
                    install_path=str(child),
                    package_format=package.package_format,
                )
            )
        return records

    def get_installed(self, plugin_id: str) -> InstalledPluginRecord | None:
        for record in self.list_installed():
            if record.plugin_id == plugin_id:
                return record
        return None

    def install_destination(self, plugin_id: str) -> Path:
        """Canonical managed install directory for a plugin_id."""
        return self._install_root / safe_install_dirname(plugin_id)

    def install(
        self,
        package_path: Path | str,
        *,
        replace: bool = False,
    ) -> InstalledPluginRecord:
        result = self.inspect(package_path)
        assert result.plugin_manifest is not None
        assert result.package_manifest is not None
        plugin = result.plugin_manifest
        package = result.package_manifest
        existing = self.get_installed(plugin.plugin_id)
        if existing is not None and not replace:
            raise PluginPackageInstallError(
                f"plugin already installed: {plugin.plugin_id!r} "
                f"(version {existing.version}); use update() or replace=True",
                code="PLUGIN_PACKAGE_ALREADY_INSTALLED",
            )

        destination = self.install_destination(plugin.plugin_id)
        self._assert_managed_path(destination)
        opened = open_package(package_path)
        try:
            copy_package_payload(opened.root, destination)
        finally:
            opened.close()

        now = _utc_now()
        record = InstalledPluginRecord(
            plugin_id=plugin.plugin_id,
            version=plugin.version,
            sdk_version=plugin.sdk_version,
            plugin_type=plugin.plugin_type,
            display_name=plugin.display_name or package.display_name,
            install_path=str(destination),
            package_format=package.package_format,
            source_package=str(Path(package_path).expanduser()),
            installed_at=existing.installed_at if existing is not None else now,
            updated_at=now,
        )
        if self._workspace is not None:
            self._workspace.set_plugin_install_root(self._install_root)
            self._workspace.record_installed_plugin(record.to_dict())
        return record

    def update(self, package_path: Path | str) -> InstalledPluginRecord:
        result = self.inspect(package_path)
        assert result.plugin_manifest is not None
        plugin_id = result.plugin_manifest.plugin_id
        existing = self.get_installed(plugin_id)
        if existing is None:
            raise PluginPackageInstallError(
                f"cannot update; plugin not installed: {plugin_id!r}",
                code="PLUGIN_PACKAGE_NOT_INSTALLED",
            )
        return self.install(package_path, replace=True)

    def uninstall(self, plugin_id: str) -> InstalledPluginRecord:
        existing = self.get_installed(plugin_id)
        if existing is None:
            raise PluginPackageInstallError(
                f"plugin not installed: {plugin_id!r}",
                code="PLUGIN_PACKAGE_NOT_INSTALLED",
            )
        destination = self.install_destination(plugin_id)
        self._assert_managed_path(destination)

        if existing.install_path:
            recorded = Path(existing.install_path).expanduser()
            if recorded.exists() and not path_is_within(recorded, self._install_root):
                raise PluginPackageInstallError(
                    f"refusing to uninstall: recorded install_path escapes managed "
                    f"install root ({recorded})",
                    code="PLUGIN_PACKAGE_UNINSTALL_PATH_UNSAFE",
                )
            # Only delete the recorded path when it is the canonical managed destination.
            if recorded.exists() and recorded.resolve() != destination.resolve():
                raise PluginPackageInstallError(
                    "refusing to uninstall: recorded install_path does not match the "
                    f"managed destination for {plugin_id!r}",
                    code="PLUGIN_PACKAGE_UNINSTALL_PATH_MISMATCH",
                )

        if destination.is_dir():
            shutil.rmtree(destination)
        if self._workspace is not None:
            self._workspace.remove_installed_plugin(plugin_id)
            selected = self._workspace.selected_plugin_id()
            if selected == plugin_id:
                self._workspace.set_selected_plugin_id(None)
            configs = self._workspace.plugin_configurations()
            if plugin_id in configs:
                remaining = {key: value for key, value in configs.items() if key != plugin_id}
                self._workspace.replace_plugin_configurations(remaining)
        return existing

    def _assert_managed_path(self, path: Path) -> None:
        if not path_is_within(path, self._install_root):
            raise PluginPackageInstallError(
                f"path is outside managed plugin install root: {path}",
                code="PLUGIN_PACKAGE_PATH_OUTSIDE_INSTALL_ROOT",
            )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
