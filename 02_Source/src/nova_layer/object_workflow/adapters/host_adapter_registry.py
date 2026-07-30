from __future__ import annotations

from collections.abc import Callable

from nova_layer.object_workflow.adapters.host_filesystem_export import FilesystemExportAdapter
from nova_layer.object_workflow.adapters.host_reveal import (
    FakeHostAdapter,
    GenericOpenFileAdapter,
    RevealAdapter,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.ports.host_delivery import (
    HostAdapter,
    HostAdapterDescriptor,
    ProcessLauncher,
)

HostAdapterFactory = Callable[[], HostAdapter]


class HostAdapterRegistry:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._factories: dict[str, HostAdapterFactory] = {}
        self._instances: dict[str, HostAdapter] = {}

    def register(self, adapter_id: str, factory: HostAdapterFactory) -> None:
        if adapter_id in self._factories:
            raise ApplicationError(
                "DUPLICATE_HOST_ADAPTER",
                f"host adapter already registered: {adapter_id!r}",
            )
        self._order.append(adapter_id)
        self._factories[adapter_id] = factory

    def contains(self, adapter_id: str) -> bool:
        return adapter_id in self._factories

    def get(self, adapter_id: str) -> HostAdapter:
        if adapter_id not in self._factories:
            raise ApplicationError(
                "INVALID_HOST_ADAPTER",
                f"unknown host adapter: {adapter_id!r}",
            )
        if adapter_id not in self._instances:
            self._instances[adapter_id] = self._factories[adapter_id]()
        return self._instances[adapter_id]

    def list(self) -> list[HostAdapterDescriptor]:
        return [self.get(adapter_id).descriptor for adapter_id in self._order]

    def refresh(self) -> None:
        """Drop cached instances so availability can be re-evaluated cheaply."""
        self._instances.clear()

    def create(self, adapter_id: str) -> HostAdapter:
        adapter = self.get(adapter_id)
        if adapter.descriptor.availability != "available":
            raise ApplicationError(
                "HOST_ADAPTER_UNAVAILABLE",
                adapter.descriptor.availability_message
                or f"host adapter unavailable: {adapter_id}",
            )
        return adapter


def build_default_host_adapter_registry(
    *,
    launcher: ProcessLauncher | None = None,
    include_fake_host: bool = False,
) -> HostAdapterRegistry:
    registry = HostAdapterRegistry()
    registry.register("filesystem", FilesystemExportAdapter)
    registry.register("reveal", lambda: RevealAdapter(launcher=launcher))
    registry.register("generic_open_file", lambda: GenericOpenFileAdapter(launcher=launcher))
    if include_fake_host:
        registry.register("fake_host", FakeHostAdapter)
    return registry
