from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nova_layer.object_workflow.adapters.host_asset_validation import (
    ValidatedExtractionAsset,
    materialize_asset_under_workspace,
    validate_committed_extraction_asset,
)
from nova_layer.object_workflow.adapters.host_naming import suggested_export_filename, to_file_uri
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.domain.generation import latest_generation_record
from nova_layer.object_workflow.domain.models import ExtractionResult, Project
from nova_layer.object_workflow.ports.host_delivery import (
    HostAdapterDescriptor,
    HostDeliveryRequest,
    HostDeliverySuccess,
    ReferenceType,
)


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    extraction_id: str
    adapter_id: str
    adapter_version: str
    action: str
    output_reference: str
    host_display_name: str
    message: str
    generation_number: int | None = None
    candidate_number: int | None = None
    extraction_provider: str | None = None
    width: int | None = None
    height: int | None = None
    premultiply_alpha: bool | None = None
    source_name: str | None = None


def delivery_binding_metadata(
    project: Project,
    extraction: ExtractionResult,
) -> dict[str, Any]:
    source = next(
        (item for item in project.source_images if item.id == extraction.source_image_id),
        None,
    )
    generation_number = None
    if extraction.confirmed_generation_id is not None:
        record = latest_generation_record(project, extraction.confirmed_generation_id)
        if record is not None:
            generation_number = record.sequence_number
    candidate_number = None
    if (
        extraction.confirmed_candidate_set_id is not None
        and extraction.confirmed_candidate_id is not None
    ):
        candidate_set = next(
            (
                item
                for item in project.candidate_sets
                if item.id == extraction.confirmed_candidate_set_id
            ),
            None,
        )
        if candidate_set is not None:
            for index, candidate in enumerate(candidate_set.candidates):
                if candidate.id == extraction.confirmed_candidate_id:
                    candidate_number = index + 1
                    break
    settings = extraction.settings
    return {
        "project_id": str(project.id),
        "source_id": str(extraction.source_image_id),
        "source_name": None if source is None else source.original_filename,
        "extraction_id": str(extraction.id),
        "extraction_operation_id": str(extraction.operation_id),
        "confirmed_generation_id": _uuid_str(extraction.confirmed_generation_id),
        "confirmed_candidate_set_id": _uuid_str(extraction.confirmed_candidate_set_id),
        "confirmed_candidate_id": _uuid_str(extraction.confirmed_candidate_id),
        "confirmed_hypothesis_id": _uuid_str(extraction.confirmed_hypothesis_id),
        "extraction_provider_id": extraction.provider_id,
        "extraction_provider_version": extraction.provider_version,
        "generation_number": generation_number,
        "candidate_number": candidate_number,
        "premultiply_alpha": False if settings is None else settings.premultiply_alpha,
        "crop_mode": "full_source" if settings is None else settings.crop_mode,
        "width": extraction.width,
        "height": extraction.height,
    }


def build_host_delivery_request(
    *,
    project: Project,
    validated: ValidatedExtractionAsset,
    action: str,
    destination: str | None = None,
    allow_overwrite: bool = False,
    extra_metadata: dict[str, Any] | None = None,
) -> HostDeliveryRequest:
    binding = delivery_binding_metadata(project, validated.extraction)
    metadata = dict(binding)
    if extra_metadata:
        metadata.update(extra_metadata)
    display_name = binding["source_name"] or project.name
    return HostDeliveryRequest(
        source_project_id=str(project.id),
        extraction_id=str(validated.extraction.id),
        rgba_asset_bytes=validated.png_bytes,
        rgba_relative_path=validated.relative_path,
        display_name=str(display_name),
        width=validated.width,
        height=validated.height,
        premultiplied_alpha=bool(binding["premultiply_alpha"]),
        crop_mode=str(binding["crop_mode"]),
        action=action,
        destination=destination,
        allow_overwrite=allow_overwrite,
        metadata=metadata,
    )


def suggested_filename_for_extraction(
    project: Project,
    extraction: ExtractionResult,
) -> str:
    binding = delivery_binding_metadata(project, extraction)
    return suggested_export_filename(
        source_name=str(binding["source_name"] or project.name),
        generation_number=binding["generation_number"],
        candidate_number=binding["candidate_number"],
        extraction_provider=extraction.provider_id,
    )


def format_delivery_summary(
    *,
    success: HostDeliverySuccess,
    extraction: ExtractionResult,
    binding: dict[str, Any],
) -> DeliverySummary:
    action_label = {
        "export_copy": f"Exported to {success.output_reference}",
        "reveal_file": f"Revealed {success.output_reference}",
        "copy_reference": f"Copied {success.output_reference}",
        "open_file": f"Opened with {success.host_display_name}",
        "import_as_layer": f"Sent to {success.host_display_name} as Full-Frame Layer",
    }.get(success.action, f"{success.action} via {success.host_display_name}")
    return DeliverySummary(
        extraction_id=str(extraction.id),
        adapter_id=success.adapter_id,
        adapter_version=success.adapter_version,
        action=success.action,
        output_reference=success.output_reference,
        host_display_name=success.host_display_name,
        message=action_label,
        generation_number=binding.get("generation_number"),
        candidate_number=binding.get("candidate_number"),
        extraction_provider=extraction.provider_id,
        width=extraction.width,
        height=extraction.height,
        premultiply_alpha=binding.get("premultiply_alpha"),
        source_name=binding.get("source_name"),
    )


def resolve_reference_text(
    *,
    reference_type: ReferenceType,
    relative_path: str,
    absolute_path: str | None,
    last_export_path: str | None,
) -> str:
    if reference_type == "project_relative":
        return relative_path
    if reference_type == "absolute_path":
        if absolute_path:
            return absolute_path
        if last_export_path:
            return last_export_path
        raise ApplicationError(
            "REFERENCE_UNAVAILABLE",
            "no absolute path available; export or materialize the asset first",
        )
    if reference_type == "file_uri":
        from pathlib import Path

        path = absolute_path or last_export_path
        if not path:
            raise ApplicationError(
                "REFERENCE_UNAVAILABLE",
                "no file URI available; export or materialize the asset first",
            )
        return to_file_uri(Path(path))
    raise ApplicationError("INVALID_REFERENCE_TYPE", f"unknown reference type: {reference_type}")


def adapter_actions(descriptor: HostAdapterDescriptor) -> tuple[str, ...]:
    return descriptor.capabilities.enabled_actions()


def _uuid_str(value: UUID | None) -> str | None:
    return None if value is None else str(value)


# Re-export helpers used by the Application service.
__all__ = [
    "DeliverySummary",
    "adapter_actions",
    "build_host_delivery_request",
    "delivery_binding_metadata",
    "format_delivery_summary",
    "materialize_asset_under_workspace",
    "resolve_reference_text",
    "suggested_filename_for_extraction",
    "validate_committed_extraction_asset",
]
