from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nova_layer.object_workflow.adapters.image_codec import (
    ImageCodecError,
    decode_rgba_png_bytes,
)
from nova_layer.object_workflow.adapters.json_project_store import validate_relative_asset_path
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.domain.models import ExtractionResult
from nova_layer.object_workflow.ports.project_store import ProjectStoreError


@dataclass(frozen=True, slots=True)
class ValidatedExtractionAsset:
    extraction: ExtractionResult
    relative_path: str
    png_bytes: bytes
    width: int
    height: int
    rgba: bytes


def validate_committed_extraction_asset(
    extraction: ExtractionResult | None,
    assets: dict[str, bytes],
) -> ValidatedExtractionAsset:
    if extraction is None:
        raise ApplicationError("NO_ACTIVE_EXTRACTION", "no committed ExtractionResult")
    relative = extraction.relative_asset_path
    try:
        safe = validate_relative_asset_path(relative)
    except ProjectStoreError as exc:
        raise ApplicationError("UNTRUSTED_ASSET_PATH", exc.message) from exc
    if safe != relative.replace("\\", "/"):
        raise ApplicationError("UNTRUSTED_ASSET_PATH", f"untrusted asset path: {relative}")
    if any(marker in Path(safe).name for marker in (".tmp", ".partial", ".incomplete")):
        raise ApplicationError(
            "EXTRACTION_ASSET_INVALID_FORMAT",
            f"temporary or incomplete asset rejected: {safe}",
        )
    if safe not in assets:
        raise ApplicationError(
            "EXTRACTION_ASSET_MISSING",
            f"committed extraction asset missing: {safe}",
        )
    png_bytes = assets[safe]
    if not png_bytes:
        raise ApplicationError("EXTRACTION_ASSET_UNREADABLE", "committed asset is empty")
    try:
        width, height, rgba = decode_rgba_png_bytes(png_bytes)
    except ImageCodecError as exc:
        raise ApplicationError(
            "EXTRACTION_ASSET_INVALID_FORMAT",
            f"committed asset is not a valid RGBA PNG: {exc}",
        ) from exc
    expected_width = extraction.width
    expected_height = extraction.height
    if expected_width is not None and expected_height is not None:
        if width != expected_width or height != expected_height:
            raise ApplicationError(
                "EXTRACTION_ASSET_DIMENSION_MISMATCH",
                f"asset {width}x{height} does not match ExtractionResult "
                f"{expected_width}x{expected_height}",
            )
    if len(rgba) != width * height * 4:
        raise ApplicationError(
            "EXTRACTION_ASSET_HAS_NO_ALPHA",
            "committed asset does not contain an alpha channel",
        )
    # Spot-check that alpha plane is present (any value is acceptable).
    alpha_plane = rgba[3::4]
    if not alpha_plane:
        raise ApplicationError(
            "EXTRACTION_ASSET_HAS_NO_ALPHA",
            "committed asset has empty alpha plane",
        )
    return ValidatedExtractionAsset(
        extraction=extraction,
        relative_path=safe,
        png_bytes=png_bytes,
        width=width,
        height=height,
        rgba=rgba,
    )


def materialize_asset_under_workspace(
    workspace: Path,
    relative_path: str,
    png_bytes: bytes,
) -> Path:
    """Write a trusted mirror of the committed asset for OS reveal/open."""
    try:
        safe = validate_relative_asset_path(relative_path)
    except ProjectStoreError as exc:
        raise ApplicationError("UNTRUSTED_ASSET_PATH", exc.message) from exc
    root = workspace.resolve()
    target = (root / Path(safe)).resolve()
    if root not in target.parents and target != root:
        raise ApplicationError(
            "UNTRUSTED_ASSET_PATH",
            f"materialized path escapes workspace: {target}",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_bytes() != png_bytes:
        target.write_bytes(png_bytes)
    if not target.is_file():
        raise ApplicationError("EXTRACTION_ASSET_MISSING", f"could not materialize: {safe}")
    return target
