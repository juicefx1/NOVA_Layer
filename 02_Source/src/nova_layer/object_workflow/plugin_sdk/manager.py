from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from nova_layer.object_workflow.adapters.core_inference_registry import (
    CoreInferenceProviderRegistry,
)
from nova_layer.object_workflow.adapters.host_adapter_registry import HostAdapterRegistry
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    PrecisionExtractionProviderRegistry,
)
from nova_layer.object_workflow.plugin_sdk.context import (
    PluginRegistrationContext,
    invoke_plugin_register,
    validate_manifest_filesystem,
)
from nova_layer.object_workflow.plugin_sdk.discovery import (
    discover_plugin_directories,
    resolve_plugin_roots,
)
from nova_layer.object_workflow.plugin_sdk.errors import (
    PluginDependencyError,
    PluginError,
    PluginLoadError,
    PluginRuntimeError,
    PluginValidationError,
)
from nova_layer.object_workflow.plugin_sdk.manifest import load_manifest
from nova_layer.object_workflow.plugin_sdk.types import PluginInfo, PluginRecord


class PluginManager:
    """Discovers, validates, loads, and registers plugins into Core registries.

    Plugin failures are isolated: they never abort application startup.
    Registration is additive only; Core builtins remain owned by build_default_* registries.
    """

    def __init__(
        self,
        *,
        plugin_roots: Path | str | Sequence[Path | str] | None = None,
        environ: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        configurations: Mapping[str, Mapping[str, Any]] | None = None,
        include_default_roots: bool = True,
        install_roots: Path | str | Sequence[Path | str] | None = None,
        include_install_root: bool = True,
    ) -> None:
        self._explicit_roots = plugin_roots
        self._environ = dict(environ) if environ is not None else None
        self._cwd = cwd
        self._include_default_roots = include_default_roots
        self._install_roots = install_roots
        self._include_install_root = include_install_root
        self._configurations: dict[str, dict[str, Any]] = {
            key: dict(value) for key, value in (configurations or {}).items()
        }
        self._records: list[PluginRecord] = []
        self._by_id: dict[str, PluginRecord] = {}
        self._loaded = False
        self._modules: dict[str, Any] = {}
        self._inference_registry: CoreInferenceProviderRegistry | None = None
        self._extraction_registry: PrecisionExtractionProviderRegistry | None = None
        self._host_registry: HostAdapterRegistry | None = None
        self._automation_registry: Any = None
        self._automation_events: Any = None

    def set_automation_registry(self, registry: Any) -> None:
        """Attach Feature 13 AutomationCommandRegistry (optional, additive)."""
        self._automation_registry = registry

    def set_automation_event_bus(self, events: Any) -> None:
        """Attach Feature 13 AutomationEventBus for plugin event subscriptions."""
        self._automation_events = events

    @property
    def loaded(self) -> bool:
        return self._loaded

    def set_plugin_configuration(self, plugin_id: str, configuration: Mapping[str, Any]) -> None:
        """Store opaque plugin configuration (Core stores; plugin interprets)."""
        self._configurations[plugin_id] = dict(configuration)
        record = self._by_id.get(plugin_id)
        if record is not None:
            record.configuration = dict(configuration)

    def get_plugin_configuration(self, plugin_id: str) -> dict[str, Any]:
        return dict(self._configurations.get(plugin_id, {}))

    def discover(self) -> list[Path]:
        roots = resolve_plugin_roots(
            explicit=self._explicit_roots,
            environ=self._environ,
            cwd=self._cwd,
            include_defaults=self._include_default_roots,
            install_roots=self._install_roots,
            include_install_root=self._include_install_root,
        )
        return discover_plugin_directories(roots)

    def load_and_register(
        self,
        *,
        inference_registry: CoreInferenceProviderRegistry | None = None,
        extraction_registry: PrecisionExtractionProviderRegistry | None = None,
        host_registry: HostAdapterRegistry | None = None,
    ) -> list[PluginInfo]:
        """Discover → validate → load → register. Safe on repeated calls after first load."""
        if self._loaded:
            return self.list_plugins()
        self._inference_registry = inference_registry
        self._extraction_registry = extraction_registry
        self._host_registry = host_registry
        directories = self.discover()
        seen_ids: set[str] = set()
        for plugin_dir in directories:
            record = PluginRecord(plugin_dir=plugin_dir)
            self._records.append(record)
            try:
                self._process_plugin(
                    record,
                    seen_ids=seen_ids,
                    inference_registry=inference_registry,
                    extraction_registry=extraction_registry,
                    host_registry=host_registry,
                )
            except PluginError as exc:
                record.lifecycle = "failed"
                record.failure_reason = f"{exc.code}: {exc.message}"
            except Exception as exc:  # noqa: BLE001 — isolate all plugin failures
                record.lifecycle = "failed"
                record.failure_reason = f"PLUGIN_LOAD_ERROR: {exc}"
            if record.manifest is not None:
                self._by_id[record.manifest.plugin_id] = record
        self._loaded = True
        return self.list_plugins()

    def register_plugin_directory(self, plugin_dir: Path | str) -> PluginInfo:
        """Load one additional plugin directory after startup (Feature 12 install).

        Additive only. Duplicate plugin_ids fail closed without affecting Core.
        """
        path = Path(plugin_dir)
        record = PluginRecord(plugin_dir=path)
        self._records.append(record)
        seen_ids = {
            item.manifest.plugin_id
            for item in self._records
            if item is not record and item.manifest is not None
        }
        try:
            self._process_plugin(
                record,
                seen_ids=seen_ids,
                inference_registry=self._inference_registry,
                extraction_registry=self._extraction_registry,
                host_registry=self._host_registry,
            )
        except PluginError as exc:
            record.lifecycle = "failed"
            record.failure_reason = f"{exc.code}: {exc.message}"
        except Exception as exc:  # noqa: BLE001
            record.lifecycle = "failed"
            record.failure_reason = f"PLUGIN_LOAD_ERROR: {exc}"
        if record.manifest is not None:
            self._by_id[record.manifest.plugin_id] = record
        self._loaded = True
        return record.to_info()

    def list_plugins(self) -> list[PluginInfo]:
        return [record.to_info() for record in self._records]

    def get_plugin(self, plugin_id: str) -> PluginInfo | None:
        record = self._by_id.get(plugin_id)
        return None if record is None else record.to_info()

    def shutdown(self) -> None:
        for record in self._records:
            instance = record.instance
            if instance is not None:
                shutdown = getattr(instance, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception:  # noqa: BLE001
                        pass
            record.lifecycle = "shutdown"
        self._modules.clear()

    def _process_plugin(
        self,
        record: PluginRecord,
        *,
        seen_ids: set[str],
        inference_registry: CoreInferenceProviderRegistry | None,
        extraction_registry: PrecisionExtractionProviderRegistry | None,
        host_registry: HostAdapterRegistry | None,
    ) -> None:
        record.lifecycle = "discovered"
        manifest = load_manifest(record.plugin_dir)
        record.manifest = manifest
        record.configuration = dict(self._configurations.get(manifest.plugin_id, {}))
        record.lifecycle = "validated"

        if manifest.plugin_id in seen_ids:
            raise PluginValidationError(
                f"duplicate plugin_id: {manifest.plugin_id!r}",
                code="PLUGIN_DUPLICATE_ID",
            )
        seen_ids.add(manifest.plugin_id)

        validate_manifest_filesystem(manifest)
        self._check_optional_dependencies(manifest.optional_dependencies)

        module = self._import_entry_module(manifest.plugin_id, manifest.entry_file)
        record.module_name = getattr(module, "__name__", None)
        record.lifecycle = "loaded"

        context = PluginRegistrationContext(
            plugin_id=manifest.plugin_id,
            plugin_type=manifest.plugin_type,
            configuration=dict(record.configuration),
            inference_registry=inference_registry,
            extraction_registry=extraction_registry,
            host_registry=host_registry,
            automation_registry=self._automation_registry,
            automation_events=self._automation_events,
        )
        try:
            invoke_plugin_register(module, context)
        except PluginError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PluginRuntimeError(str(exc)) from exc

        if not context._registered_ids:
            raise PluginRuntimeError(
                f"plugin {manifest.plugin_id!r} registered no providers/adapters"
            )
        record.lifecycle = "registered"
        # Mark available unless plugin set a soft-unavailable probe later.
        record.lifecycle = "available"
        record.failure_reason = ""

    def _check_optional_dependencies(self, dependencies: Sequence[str]) -> None:
        missing: list[str] = []
        for name in dependencies:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        if missing:
            raise PluginDependencyError(
                "missing optional dependencies: " + ", ".join(missing)
            )

    def _import_entry_module(self, plugin_id: str, entry_file: Path | None) -> Any:
        if entry_file is None or not entry_file.is_file():
            raise PluginLoadError("entry module file not found")
        module_name = f"nova_layer_plugin_{_safe_module_token(plugin_id)}_{uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(module_name, entry_file)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"unable to create import spec for {entry_file}")
        module = importlib.util.module_from_spec(spec)
        # Ensure relative imports inside plugin can resolve against plugin dir.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"failed to import plugin entry: {exc}") from exc
        self._modules[plugin_id] = module
        return module


def _safe_module_token(plugin_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in plugin_id)
