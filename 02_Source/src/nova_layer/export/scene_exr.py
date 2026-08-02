"""True Scene Linear EXR compose / write helpers (Phase 10A / 10B).

Separate from uint8-derived ``write_openexr_rgba`` — no 0–1 remapping.

Phase 10B records convenience OpenEXR header attributes. The export
``manifest.json`` remains authoritative; header failures never block pixel write.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np
from numpy.typing import NDArray

SCENE_EXR_WRITER_VERSION = "10B.1"

# Stable key order for serializer output (tests rely on this).
_HEADER_KEY_ORDER: tuple[str, ...] = (
    "software",
    "framesPerSecond",
    "nova:colorPolicy",
    "nova:sceneLinear",
    "nova:sourceColorSpace",
    "nova:interpretationColorSpace",
    "nova:premultiplied",
    "nova:alphaMode",
    "nova:pixelEncoding",
    "nova:sourceRenderVersion",
    "nova:sourceFingerprint",
    "nova:projectId",
    "nova:shotId",
    "nova:layerId",
    "nova:frameNumber",
    "nova:writerVersion",
)

_ABS_PATH_RE = re.compile(
    r"^(?:"
    r"~|"  # home
    r"/|"  # POSIX abs
    r"[A-Za-z]:[\\/]|"  # Windows drive
    r"\\\\"  # UNC
    r")"
)


class SceneExrError(RuntimeError):
    """Raised when scene-linear EXR compose/write cannot complete."""


@dataclass(frozen=True, slots=True)
class SceneExrHeaderMetadata:
    """Convenience header fields for Scene Linear EXR (manifest remains authoritative)."""

    color_policy: str
    scene_linear: bool
    source_color_space: str | None
    interpretation_color_space: str | None
    premultiplied: bool
    alpha_mode: str
    pixel_encoding: str
    source_render_version: int | None
    source_fingerprint: str | None
    project_id: str | None
    shot_id: str | None
    layer_id: str | None
    frame_number: int
    writer_version: str = SCENE_EXR_WRITER_VERSION
    frames_per_second: float | None = None
    software: str = "NOVA Layer"

    def with_frame_number(self, frame_number: int) -> SceneExrHeaderMetadata:
        return replace(self, frame_number=int(frame_number))


@dataclass(frozen=True, slots=True)
class ExrHeaderWriteResult:
    written_keys: tuple[str, ...] = ()
    skipped_keys: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def openexr_writer_available() -> bool:
    """Return True when OpenEXR + Imath can be imported for scene/look EXR write."""
    try:
        import Imath  # type: ignore[import-untyped]
        import OpenEXR  # type: ignore[import-not-found]
    except ImportError:
        return False
    return OpenEXR is not None and Imath is not None


def looks_like_filesystem_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if _ABS_PATH_RE.match(text):
        return True
    if "/" in text or "\\" in text:
        return True
    return False


def sanitize_header_text(value: str | None) -> str | None:
    """Return a header-safe text token, or None if the value should be omitted.

    Absolute paths / path-like strings become basename when the basename is a
    simple token; otherwise they are dropped (never home/abs paths in headers).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if looks_like_filesystem_path(text):
        base = PureWindowsPath(text).name if "\\" in text else PurePosixPath(text).name
        base = base.strip()
        if not base or base in {".", ".."}:
            return None
        # Basename of a path must not still look absolute.
        if looks_like_filesystem_path(base):
            return None
        return base
    return text


def _encode_header_string(value: object) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value if value else None
    if isinstance(value, Enum):
        return _encode_header_string(value.value)
    if isinstance(value, Path):
        sanitized = sanitize_header_text(str(value))
        return None if sanitized is None else sanitized.encode("utf-8")
    if isinstance(value, (list, tuple, dict, set)):
        return None
    sanitized = sanitize_header_text(str(value))
    return None if sanitized is None else sanitized.encode("utf-8")


def build_openexr_header_attributes(
    metadata: SceneExrHeaderMetadata,
) -> dict[str, bytes | int | float]:
    """Serialize typed metadata to OpenEXR-safe header attribute values.

    Binding contract (OpenEXR 3.4.x): use bytes for strings (Python str may drop
    silently). Bool → int 0/1. None / NaN / Inf / containers → omit.
    """
    raw: dict[str, bytes | int | float | None] = {
        "software": _encode_header_string(metadata.software),
        "framesPerSecond": (
            float(metadata.frames_per_second)
            if metadata.frames_per_second is not None
            and math.isfinite(float(metadata.frames_per_second))
            else None
        ),
        "nova:colorPolicy": _encode_header_string(metadata.color_policy),
        "nova:sceneLinear": 1 if metadata.scene_linear else 0,
        "nova:sourceColorSpace": _encode_header_string(metadata.source_color_space),
        "nova:interpretationColorSpace": _encode_header_string(
            metadata.interpretation_color_space
        ),
        "nova:premultiplied": 1 if metadata.premultiplied else 0,
        "nova:alphaMode": _encode_header_string(metadata.alpha_mode),
        "nova:pixelEncoding": _encode_header_string(metadata.pixel_encoding),
        "nova:sourceRenderVersion": (
            int(metadata.source_render_version)
            if metadata.source_render_version is not None
            else None
        ),
        "nova:sourceFingerprint": _encode_header_string(metadata.source_fingerprint),
        "nova:projectId": _encode_header_string(metadata.project_id),
        "nova:shotId": _encode_header_string(metadata.shot_id),
        "nova:layerId": _encode_header_string(metadata.layer_id),
        "nova:frameNumber": int(metadata.frame_number),
        "nova:writerVersion": _encode_header_string(metadata.writer_version),
    }
    ordered: dict[str, bytes | int | float] = {}
    for key in _HEADER_KEY_ORDER:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        ordered[key] = value
    return ordered


def apply_openexr_header_attributes(
    header: Any,
    attributes: Mapping[str, bytes | int | float],
) -> ExrHeaderWriteResult:
    """Best-effort assign attributes; never raise for a single failed key."""
    written: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    for key, value in attributes.items():
        try:
            header[key] = value
        except Exception as exc:  # noqa: BLE001 — binding-dependent
            skipped.append(key)
            warnings.append(f"{key}: {type(exc).__name__}: {exc}")
            continue
        written.append(key)
    return ExrHeaderWriteResult(
        written_keys=tuple(written),
        skipped_keys=tuple(skipped),
        warnings=tuple(warnings),
    )


def compose_scene_rgba(
    scene_rgb: NDArray[np.float32],
    mask: NDArray[np.uint8],
) -> NDArray[np.float32]:
    """Compose straight (unpremultiplied) scene-linear RGBA.

    Contract:
    - RGB copied from ``scene_rgb`` unchanged (including where alpha is 0).
    - Alpha is ``mask / 255.0`` (float32).
    - ``premultiplied`` is False.
    - Negative / over-range RGB values are preserved.
    - Inputs are not mutated.
    """
    rgb = np.asarray(scene_rgb)
    alpha_src = np.asarray(mask)
    if rgb.dtype != np.float32 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(
            "compose_scene_rgba requires float32 HxWx3 scene RGB "
            f"(got dtype={rgb.dtype}, shape={getattr(rgb, 'shape', None)})."
        )
    if alpha_src.dtype != np.uint8 or alpha_src.ndim != 2:
        raise ValueError(
            "compose_scene_rgba requires uint8 HxW mask "
            f"(got dtype={alpha_src.dtype}, shape={getattr(alpha_src, 'shape', None)})."
        )
    if alpha_src.shape != rgb.shape[:2]:
        raise ValueError(
            "compose_scene_rgba mask shape must match RGB HxW "
            f"(rgb={rgb.shape[:2]}, mask={alpha_src.shape})."
        )
    rgba = np.empty((*rgb.shape[:2], 4), dtype=np.float32)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = alpha_src.astype(np.float32) / np.float32(255.0)
    return rgba


def write_scene_openexr_rgba(
    path: Path,
    rgba: NDArray[np.float32],
    *,
    pixel_type: str = "half",
    compression: str = "zip",
    metadata: SceneExrHeaderMetadata | None = None,
) -> ExrHeaderWriteResult:
    """Write scene-linear float RGBA to OpenEXR (default HALF).

    Does **not** remap values into 0–1. Negative and values > 1 are preserved
    within the chosen pixel type's representable range.

    Header metadata is best-effort: attribute failures never block pixel write.
    Chromaticities / adoptedNeutral are intentionally never written.
    """
    try:
        import Imath  # type: ignore[import-untyped]
        import OpenEXR  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise SceneExrError(
            "Scene OpenEXR export requires the optional desktop dependency `OpenEXR`."
        ) from exc

    array = np.asarray(rgba)
    if array.dtype != np.float32 or array.ndim != 3 or array.shape[2] != 4:
        raise SceneExrError(
            "Scene OpenEXR export requires float32 HxWx4 RGBA "
            f"(got dtype={array.dtype}, shape={getattr(array, 'shape', None)})."
        )
    if pixel_type not in {"half", "float"}:
        raise SceneExrError(
            f"Unsupported scene OpenEXR pixel_type: {pixel_type!r} (use 'half' or 'float')."
        )

    height, width, _ = array.shape
    header = OpenEXR.Header(width, height)
    pix = (
        Imath.PixelType(Imath.PixelType.HALF)
        if pixel_type == "half"
        else Imath.PixelType(Imath.PixelType.FLOAT)
    )
    header["channels"] = {
        "R": Imath.Channel(pix),
        "G": Imath.Channel(pix),
        "B": Imath.Channel(pix),
        "A": Imath.Channel(pix),
    }
    compression_key = compression.strip().casefold()
    if compression_key == "zip":
        header["compression"] = Imath.Compression(Imath.Compression.ZIP_COMPRESSION)
    elif compression_key in {"none", "no"}:
        header["compression"] = Imath.Compression(Imath.Compression.NO_COMPRESSION)
    else:
        raise SceneExrError(
            f"Unsupported scene OpenEXR compression: {compression!r}"
        )

    header_result = ExrHeaderWriteResult()
    if metadata is not None:
        try:
            attributes = build_openexr_header_attributes(metadata)
            header_result = apply_openexr_header_attributes(header, attributes)
        except Exception as exc:  # noqa: BLE001 — never block pixels for metadata
            header_result = ExrHeaderWriteResult(
                skipped_keys=("__all__",),
                warnings=(f"header metadata build failed: {type(exc).__name__}: {exc}",),
            )

    if pixel_type == "half":
        payload = np.ascontiguousarray(array, dtype=np.float16)
    else:
        payload = np.ascontiguousarray(array, dtype=np.float32)

    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                "R": payload[:, :, 0].tobytes(),
                "G": payload[:, :, 1].tobytes(),
                "B": payload[:, :, 2].tobytes(),
                "A": payload[:, :, 3].tobytes(),
            }
        )
    finally:
        output.close()
    return header_result


def build_scene_export_manifest_fields(
    *,
    source_color_space: str | None = None,
    source_color_space_source: str | None = None,
    interpretation_color_space: str | None = None,
    input_color_space: str | None = None,
    media_fingerprint: str | None = None,
    project_id: str | None = None,
    shot_id: str | None = None,
    layer_id: str | None = None,
    source_render_version: int | None = None,
    frame_start: int,
    frame_end: int,
    pixel_type: str = "half",
    config_path: str | None = None,
    config_source: str | None = None,
) -> dict[str, Any]:
    """Top-level + nested color_policy block for scene_openexr_sequence manifests.

    Phase 10B separates file/source tags from PREVIEW interpretation ICS:

    - ``source_color_space`` — SceneFrame tag (file-native; ``"unspecified"`` if none)
    - ``interpretation_color_space`` — resolved project/workspace ``input_color_space``
    - ``export_color_space`` — equals ``source_color_space`` (no working-space convert)
    - ``working_color_space`` — always null in this phase
    - ``input_color_space`` — backward-compatible alias of interpretation
    """
    source_tag = (
        str(source_color_space).strip()
        if source_color_space is not None and str(source_color_space).strip()
        else "unspecified"
    )
    source_tag_source = (
        str(source_color_space_source).strip()
        if source_color_space_source is not None and str(source_color_space_source).strip()
        else "unspecified"
    )
    interpretation = interpretation_color_space
    if interpretation is None:
        interpretation = input_color_space
    interpretation_text = (
        str(interpretation).strip()
        if interpretation is not None and str(interpretation).strip()
        else None
    )

    pixel_encoding = (
        "file_native_scene_half" if pixel_type == "half" else "file_native_scene_float"
    )
    ocio_identity: dict[str, str | None] | None = None
    if config_path or config_source:
        ocio_identity = {
            "config_path": config_path,
            "config_source": config_source,
        }

    color_policy: dict[str, Any] = {
        "color_policy": "scene",
        "render_source": "scene",
        "export_mode": "compose_scene",
        "scene_linear": True,
        "scene_display_transformed": False,
        "pixel_encoding": pixel_encoding,
        "pixel_type": pixel_type,
        "source_color_space": source_tag,
        "source_color_space_source": source_tag_source,
        "interpretation_color_space": interpretation_text,
        "working_color_space": None,
        "export_color_space": source_tag,
        "color_transform_applied": False,
        # Backward-compatible: historical field tracks PREVIEW interpretation ICS.
        "input_color_space": interpretation_text,
        "source_transform_version": None,
        "color_backend": "scene",
        "config_path": config_path,
        "config_source": config_source,
        "ocio_config_identity": ocio_identity,
        "display": None,
        "view": None,
        "exposure": None,
        "alpha_mode": "straight",
        "premultiplied": False,
    }
    return {
        "export_mode": "compose_scene",
        "color_policy": color_policy,
        "color_policy_id": "scene",
        "render_source": "scene",
        "scene_linear": True,
        "scene_display_transformed": False,
        "pixel_encoding": pixel_encoding,
        "pixel_type": pixel_type,
        "source_color_space": source_tag,
        "source_color_space_source": source_tag_source,
        "interpretation_color_space": interpretation_text,
        "working_color_space": None,
        "export_color_space": source_tag,
        "color_transform_applied": False,
        "input_color_space": interpretation_text,
        "source_transform_version": None,
        "color_backend": "scene",
        "config_path": config_path,
        "config_source": config_source,
        "ocio_config_identity": ocio_identity,
        "display": None,
        "view": None,
        "exposure": None,
        "alpha_mode": "straight",
        "premultiplied": False,
        "media_fingerprint": media_fingerprint,
        "project_id": project_id,
        "shot_id": shot_id,
        "layer_id": layer_id,
        "source_render_version": source_render_version,
        "frame_start": frame_start,
        "frame_end": frame_end,
    }
