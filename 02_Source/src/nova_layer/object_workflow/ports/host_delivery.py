from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

HostAvailability = Literal["available", "unavailable"]
HostAction = Literal[
    "export_copy",
    "reveal_file",
    "copy_reference",
    "open_file",
    "import_as_layer",
]
HostCapability = Literal[
    "export_copy",
    "reveal_file",
    "copy_reference",
    "open_file",
    "import_as_layer",
    "replace_selected_layer",
    "create_document",
    "receive_premultiplied_alpha",
    "receive_straight_alpha",
    "receive_full_source_coordinates",
]
ReferenceType = Literal["absolute_path", "file_uri", "project_relative"]


@dataclass(frozen=True, slots=True)
class HostAdapterCapabilities:
    export_copy: bool = False
    reveal_file: bool = False
    copy_reference: bool = False
    open_file: bool = False
    import_as_layer: bool = False
    replace_selected_layer: bool = False
    create_document: bool = False
    receive_premultiplied_alpha: bool = True
    receive_straight_alpha: bool = True
    receive_full_source_coordinates: bool = True

    def supports(self, action: str) -> bool:
        return bool(getattr(self, action, False))

    def enabled_actions(self) -> tuple[str, ...]:
        actions: list[str] = []
        for name in (
            "export_copy",
            "reveal_file",
            "copy_reference",
            "open_file",
            "import_as_layer",
            "replace_selected_layer",
            "create_document",
        ):
            if getattr(self, name):
                actions.append(name)
        return tuple(actions)


@dataclass(frozen=True, slots=True)
class HostAdapterDescriptor:
    adapter_id: str
    display_name: str
    adapter_version: str
    availability: HostAvailability
    availability_message: str
    capabilities: HostAdapterCapabilities


@dataclass(frozen=True, slots=True)
class HostDeliveryRequest:
    source_project_id: str
    extraction_id: str
    rgba_asset_bytes: bytes
    rgba_relative_path: str
    display_name: str
    width: int
    height: int
    premultiplied_alpha: bool
    crop_mode: str
    action: str
    destination: str | None = None
    allow_overwrite: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HostDeliverySuccess:
    adapter_id: str
    adapter_version: str
    action: str
    output_reference: str
    host_display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HostDeliveryFailure:
    adapter_id: str
    action: str
    error_code: str
    message: str


class HostAdapter(Protocol):
    @property
    def descriptor(self) -> HostAdapterDescriptor: ...

    def validate(self, request: HostDeliveryRequest) -> None: ...

    def deliver(self, request: HostDeliveryRequest) -> HostDeliverySuccess: ...


class ProcessLauncher(Protocol):
    def run(self, argv: list[str], *, timeout_seconds: float = 30.0) -> int: ...


class ClipboardWriter(Protocol):
    def write_text(self, text: str) -> None: ...
