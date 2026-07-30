from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from nova_layer.object_workflow.adapters.core_inference_registry import (
    AvailabilityProbe as InferenceAvailabilityProbe,
)
from nova_layer.object_workflow.adapters.core_inference_registry import (
    CoreInferenceProviderRegistry,
    ProviderFactory,
)
from nova_layer.object_workflow.adapters.host_adapter_registry import (
    HostAdapterFactory,
    HostAdapterRegistry,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    AvailabilityProbe as ExtractionAvailabilityProbe,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    ExtractionFactory,
    PrecisionExtractionProviderRegistry,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.plugin_sdk.errors import (
    PluginLoadError,
    PluginRuntimeError,
    PluginValidationError,
)
from nova_layer.object_workflow.plugin_sdk.manifest import PluginManifest
from nova_layer.object_workflow.ports.extraction_provider import ExtractionProviderDescriptor
from nova_layer.object_workflow.ports.provider_registry import ProviderDescriptor


@dataclass
class PluginRegistrationContext:
    """DI surface plugins use to register into Core registries.

    Plugins must never hold or mutate registries directly outside this context.
    """

    plugin_id: str
    plugin_type: str
    configuration: Mapping[str, Any]
    inference_registry: CoreInferenceProviderRegistry | None = None
    extraction_registry: PrecisionExtractionProviderRegistry | None = None
    host_registry: HostAdapterRegistry | None = None
    automation_registry: Any = None
    automation_events: Any = None
    _registered_ids: list[str] = field(default_factory=list)

    def register_inference(
        self,
        descriptor: ProviderDescriptor,
        factory: ProviderFactory,
        *,
        availability_probe: InferenceAvailabilityProbe | None = None,
    ) -> None:
        if self.plugin_type != "inference":
            raise PluginValidationError(
                f"plugin {self.plugin_id!r} type {self.plugin_type!r} "
                "cannot register inference providers"
            )
        if self.inference_registry is None:
            raise PluginRuntimeError("inference registry unavailable for plugin registration")
        try:
            self.inference_registry.register(
                descriptor,
                factory,
                availability_probe=availability_probe,
            )
        except ApplicationError as exc:
            raise PluginRuntimeError(f"{exc.code}: {exc.message}") from exc
        self._registered_ids.append(descriptor.provider_id)

    def register_matting(
        self,
        descriptor: ExtractionProviderDescriptor,
        factory: ExtractionFactory,
        *,
        availability_probe: ExtractionAvailabilityProbe | None = None,
    ) -> None:
        if self.plugin_type != "matting":
            raise PluginValidationError(
                f"plugin {self.plugin_id!r} type {self.plugin_type!r} "
                "cannot register matting providers"
            )
        if self.extraction_registry is None:
            raise PluginRuntimeError("extraction registry unavailable for plugin registration")
        try:
            self.extraction_registry.register(
                descriptor,
                factory,
                availability_probe=availability_probe,
            )
        except ApplicationError as exc:
            raise PluginRuntimeError(f"{exc.code}: {exc.message}") from exc
        self._registered_ids.append(descriptor.provider_id)

    def register_host_adapter(self, adapter_id: str, factory: HostAdapterFactory) -> None:
        if self.plugin_type != "host_adapter":
            raise PluginValidationError(
                f"plugin {self.plugin_id!r} type {self.plugin_type!r} "
                "cannot register host adapters"
            )
        if self.host_registry is None:
            raise PluginRuntimeError("host registry unavailable for plugin registration")
        try:
            self.host_registry.register(adapter_id, factory)
        except ApplicationError as exc:
            raise PluginRuntimeError(f"{exc.code}: {exc.message}") from exc
        self._registered_ids.append(adapter_id)

    def register_automation_command(
        self,
        name: str,
        handler: Any,
        *,
        permission: str = "execute",
        description: str = "",
    ) -> None:
        """Register a plugin automation command (Feature 13). Never bypasses validation."""
        if self.automation_registry is None:
            raise PluginRuntimeError(
                "automation registry unavailable for plugin command registration"
            )
        try:
            self.automation_registry.register_plugin_command(
                self.plugin_id,
                name,
                handler,
                permission=permission,
                description=description,
            )
        except Exception as exc:  # noqa: BLE001
            raise PluginRuntimeError(f"automation command registration failed: {exc}") from exc
        self._registered_ids.append(f"automation:{name}")

    def subscribe_automation_events(self, listener: Any) -> None:
        """Subscribe a plugin helper to the Automation event bus."""
        if self.automation_events is None:
            raise PluginRuntimeError("automation event bus unavailable for plugin subscription")
        self.automation_events.subscribe(listener)
        self._registered_ids.append("automation:events")

    def provide_automation_helper(self, name: str, payload: Mapping[str, Any]) -> None:
        """Publish an opaque automation helper descriptor for scripts/plugins."""
        if self.automation_registry is None:
            raise PluginRuntimeError("automation registry unavailable for helper registration")
        # Helpers are stored as no-op metadata commands under plugin namespace.
        helper_name = f"helper.{name}"
        frozen = dict(payload)

        def _helper(_session: Any, _params: Mapping[str, Any]) -> dict[str, Any]:
            return dict(frozen)

        self.register_automation_command(
            helper_name,
            _helper,
            permission="read",
            description=f"Automation helper {name}",
        )


def invoke_plugin_register(module: Any, context: PluginRegistrationContext) -> None:
    """Call the plugin entrypoint. Supports `register(context)` or `Plugin().register`."""
    register_fn = getattr(module, "register", None)
    if callable(register_fn):
        register_fn(context)
        return
    plugin_cls = getattr(module, "Plugin", None)
    if isinstance(plugin_cls, type):
        instance = plugin_cls()
        method = getattr(instance, "register", None)
        if callable(method):
            method(context)
            return
    raise PluginLoadError(
        "entry module must export register(context) or Plugin.register(context)"
    )


def validate_manifest_filesystem(manifest: PluginManifest) -> None:
    entry = manifest.entry_file
    if entry is None or not entry.is_file():
        raise PluginValidationError(
            f"entry module missing: {manifest.entry_module}.py",
            code="PLUGIN_ENTRY_MISSING",
        )
