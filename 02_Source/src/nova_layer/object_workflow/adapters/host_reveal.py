from __future__ import annotations

from pathlib import Path

from nova_layer.object_workflow.adapters.host_platform import (
    SubprocessProcessLauncher,
    open_file_argv_for_platform,
    reveal_argv_for_platform,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.ports.host_delivery import (
    HostAdapterCapabilities,
    HostAdapterDescriptor,
    HostDeliveryRequest,
    HostDeliverySuccess,
    ProcessLauncher,
)


class RevealAdapter:
    def __init__(self, launcher: ProcessLauncher | None = None) -> None:
        self._launcher = launcher or SubprocessProcessLauncher()
        self._descriptor = HostAdapterDescriptor(
            adapter_id="reveal",
            display_name="Reveal in File Browser",
            adapter_version="1.0.0",
            availability="available",
            availability_message="Reveal a file in the operating-system file browser",
            capabilities=HostAdapterCapabilities(reveal_file=True),
        )

    @property
    def descriptor(self) -> HostAdapterDescriptor:
        return self._descriptor

    def validate(self, request: HostDeliveryRequest) -> None:
        if request.action != "reveal_file":
            raise ApplicationError(
                "UNSUPPORTED_HOST_ACTION",
                f"reveal adapter does not support action: {request.action}",
            )
        target = request.destination or request.metadata.get("absolute_path")
        if not target:
            raise ApplicationError("REVEAL_TARGET_MISSING", "no file path to reveal")
        path = Path(str(target))
        if not path.is_file():
            raise ApplicationError("REVEAL_TARGET_MISSING", f"file not found: {path}")

    def deliver(self, request: HostDeliveryRequest) -> HostDeliverySuccess:
        self.validate(request)
        target = Path(str(request.destination or request.metadata.get("absolute_path")))
        argv = reveal_argv_for_platform(target)
        try:
            self._launcher.run(argv)
        except ApplicationError as exc:
            if exc.code == "HOST_LAUNCH_FAILED":
                raise ApplicationError("REVEAL_LAUNCH_FAILED", exc.message) from exc
            raise
        return HostDeliverySuccess(
            adapter_id="reveal",
            adapter_version="1.0.0",
            action="reveal_file",
            output_reference=str(target.resolve()),
            host_display_name=self._descriptor.display_name,
            metadata={"argv": argv},
        )


class GenericOpenFileAdapter:
    def __init__(self, launcher: ProcessLauncher | None = None) -> None:
        self._launcher = launcher or SubprocessProcessLauncher()
        self._descriptor = HostAdapterDescriptor(
            adapter_id="generic_open_file",
            display_name="Default Application",
            adapter_version="1.0.0",
            availability="available",
            availability_message="Open with the operating-system default application",
            capabilities=HostAdapterCapabilities(
                open_file=True,
                receive_premultiplied_alpha=True,
                receive_straight_alpha=True,
                receive_full_source_coordinates=True,
            ),
        )

    @property
    def descriptor(self) -> HostAdapterDescriptor:
        return self._descriptor

    def validate(self, request: HostDeliveryRequest) -> None:
        if request.action != "open_file":
            raise ApplicationError(
                "UNSUPPORTED_HOST_ACTION",
                f"generic open adapter does not support action: {request.action}",
            )
        target = request.destination or request.metadata.get("absolute_path")
        if not target:
            raise ApplicationError("OPEN_TARGET_MISSING", "no file path to open")
        if not Path(str(target)).is_file():
            raise ApplicationError("OPEN_TARGET_MISSING", f"file not found: {target}")

    def deliver(self, request: HostDeliveryRequest) -> HostDeliverySuccess:
        self.validate(request)
        target = Path(str(request.destination or request.metadata.get("absolute_path")))
        argv = open_file_argv_for_platform(target)
        self._launcher.run(argv)
        return HostDeliverySuccess(
            adapter_id="generic_open_file",
            adapter_version="1.0.0",
            action="open_file",
            output_reference=str(target.resolve()),
            host_display_name=self._descriptor.display_name,
            metadata={"argv": argv, "capability": "open_file"},
        )


class FakeHostAdapter:
    """Deterministic in-process Host Adapter for tests."""

    def __init__(self, *, available: bool = True) -> None:
        self.calls: list[HostDeliveryRequest] = []
        self._available = available
        self._descriptor = HostAdapterDescriptor(
            adapter_id="fake_host",
            display_name="Fake Host",
            adapter_version="1.0.0",
            availability="available" if available else "unavailable",
            availability_message=(
                "Deterministic fake Host for tests"
                if available
                else "Fake Host intentionally unavailable"
            ),
            capabilities=HostAdapterCapabilities(
                open_file=True,
                import_as_layer=True,
                receive_straight_alpha=True,
                receive_full_source_coordinates=True,
            ),
        )

    @property
    def descriptor(self) -> HostAdapterDescriptor:
        return self._descriptor

    def validate(self, request: HostDeliveryRequest) -> None:
        if not self._available:
            raise ApplicationError(
                "HOST_ADAPTER_UNAVAILABLE",
                self._descriptor.availability_message,
            )
        if request.action not in {"open_file", "import_as_layer"}:
            raise ApplicationError(
                "UNSUPPORTED_HOST_ACTION",
                f"fake host does not support action: {request.action}",
            )
        if not request.rgba_asset_bytes:
            raise ApplicationError("EXTRACTION_ASSET_MISSING", "no asset bytes")

    def deliver(self, request: HostDeliveryRequest) -> HostDeliverySuccess:
        self.validate(request)
        self.calls.append(request)
        return HostDeliverySuccess(
            adapter_id="fake_host",
            adapter_version="1.0.0",
            action=request.action,
            output_reference=f"fake://{request.extraction_id}/{request.action}",
            host_display_name=self._descriptor.display_name,
            metadata={
                "bytes": len(request.rgba_asset_bytes),
                "width": request.width,
                "height": request.height,
            },
        )
