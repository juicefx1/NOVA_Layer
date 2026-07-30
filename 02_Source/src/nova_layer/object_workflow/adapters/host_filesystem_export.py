from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from nova_layer.object_workflow.adapters.image_codec import decode_rgba_png_bytes
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.ports.host_delivery import (
    HostAdapterCapabilities,
    HostAdapterDescriptor,
    HostDeliveryRequest,
    HostDeliverySuccess,
)

ADAPTER_ID = "filesystem"
ADAPTER_VERSION = "1.0.0"


class FilesystemExportAdapter:
    """Copy committed RGBA PNG bytes to a user-selected destination."""

    def __init__(self) -> None:
        self._descriptor = HostAdapterDescriptor(
            adapter_id=ADAPTER_ID,
            display_name="Filesystem Export",
            adapter_version=ADAPTER_VERSION,
            availability="available",
            availability_message="Copy committed RGBA PNG to a chosen path",
            capabilities=HostAdapterCapabilities(
                export_copy=True,
                receive_premultiplied_alpha=True,
                receive_straight_alpha=True,
                receive_full_source_coordinates=True,
            ),
        )

    @property
    def descriptor(self) -> HostAdapterDescriptor:
        return self._descriptor

    def validate(self, request: HostDeliveryRequest) -> None:
        if request.action != "export_copy":
            raise ApplicationError(
                "UNSUPPORTED_HOST_ACTION",
                f"filesystem adapter does not support action: {request.action}",
            )
        if not request.destination:
            raise ApplicationError("INVALID_DESTINATION", "export destination is required")
        destination = Path(request.destination).expanduser()
        if destination.suffix.lower() != ".png":
            raise ApplicationError(
                "INVALID_DESTINATION",
                "export destination must use a .png extension",
            )
        if ".." in destination.parts:
            raise ApplicationError("PATH_TRAVERSAL", "destination path traversal is forbidden")
        try:
            parent = destination.parent.resolve()
        except OSError as exc:
            raise ApplicationError(
                "INVALID_DESTINATION",
                f"export destination parent is not resolvable: {destination.parent}",
            ) from exc
        # Ensure the final filename cannot escape the resolved parent directory.
        resolved = (parent / destination.name).resolve()
        if resolved.parent != parent:
            raise ApplicationError("PATH_TRAVERSAL", "destination path traversal is forbidden")
        if not request.rgba_asset_bytes:
            raise ApplicationError("EXTRACTION_ASSET_MISSING", "committed asset bytes are empty")
        if destination.exists() and not request.allow_overwrite:
            raise ApplicationError(
                "DESTINATION_EXISTS",
                f"destination exists and overwrite is not allowed: {destination}",
            )

    def deliver(self, request: HostDeliveryRequest) -> HostDeliverySuccess:
        self.validate(request)
        assert request.destination is not None
        destination = Path(request.destination).expanduser()
        try:
            parent = destination.parent.resolve()
        except OSError as exc:
            raise ApplicationError(
                "INVALID_DESTINATION",
                f"export destination parent is not resolvable: {destination.parent}",
            ) from exc
        destination = parent / destination.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(request.rgba_asset_bytes)
            width, height, rgba = decode_rgba_png_bytes(temporary.read_bytes())
            if width != request.width or height != request.height:
                raise ApplicationError(
                    "EXTRACTION_ASSET_DIMENSION_MISMATCH",
                    f"exported image {width}x{height} does not match "
                    f"{request.width}x{request.height}",
                )
            if len(rgba) != width * height * 4:
                raise ApplicationError(
                    "EXTRACTION_ASSET_HAS_NO_ALPHA",
                    "exported image is not RGBA",
                )
            # Atomic promote into the final destination.
            os.replace(temporary, destination)
        except ApplicationError:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise ApplicationError("EXPORT_FAILED", str(exc)) from exc
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

        return HostDeliverySuccess(
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            action="export_copy",
            output_reference=str(destination.resolve()),
            host_display_name=self._descriptor.display_name,
            metadata={
                "bytes_copied": len(request.rgba_asset_bytes),
                "width": request.width,
                "height": request.height,
                "premultiplied_alpha": request.premultiplied_alpha,
                "crop_mode": request.crop_mode,
            },
        )
