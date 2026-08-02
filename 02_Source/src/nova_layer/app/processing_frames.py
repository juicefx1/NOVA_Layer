"""Processing frame color policies (viewer look vs stable model input).

SOURCE is a stable uint8 RGB processing raster — not scene-linear float itself.
SCENE is EXR-only float32. MODEL normalization stays inside capability adapters.

Phase 10C-3A adds opt-in SOURCE v2 (working→sRGB texture) via
:class:`SourceTransformRequest` without changing product consumer defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray


class ProcessingColorPolicy(str, Enum):
    """How pixels are prepared for viewer vs capability / processing paths.

    PREVIEW:
        Viewer-identical uint8 RGB. Applies the active session Exposure /
        Display / View (OCIO or Legacy composition). Uses preview + raw caches.

    SOURCE:
        Viewer-look-independent stable uint8 RGB for SAM / skeleton / similar.
        - PNG / JPEG / TIFF / BMP / video: source raster uint8 RGB (no viewer
          transform).
        - EXR v1: scene float → fixed Legacy linear→sRGB (exposure 0).
        - EXR v2 (opt-in): WorkingSceneFrame → OCIO ColorSpaceTransform to
          encoded sRGB texture → clip/quantize uint8.
        Never uses workspace/project Display, View, or Exposure.

    SCENE:
        EXR raw float32 :class:`~nova_layer.ports.scene_frames.SceneFrame` via
        the raw cache. Non-EXR raises MediaReadError. Not passed directly into
        uint8-only capabilities in Phase 8C-2.
    """

    PREVIEW = "preview"
    SOURCE = "source"
    SCENE = "scene"


# Fixed source-bake identity (source cache key component). Do not rename/change.
SOURCE_TRANSFORM_VERSION = "source_legacy_srgb_v1"

# Opt-in WorkingScene → encoded sRGB texture SOURCE path (Phase 10C-3A).
SOURCE_TRANSFORM_VERSION_V2 = "source_working_srgb_v2"

# Quantize contract for SOURCE v2 (and documented for diagnostics).
SOURCE_ENCODE_VERSION = "uint8_clip_v1"

# Non-EXR raster pass-through marker when SOURCE v2 is requested.
SOURCE_RASTER_OUTPUT_COLOR_SPACE = "source_raster_uint8"


@dataclass(frozen=True, slots=True)
class SourceTransformRequest:
    """Explicit SOURCE transform selection (default = v1 Legacy bake)."""

    version: str = SOURCE_TRANSFORM_VERSION
    output_color_space: str | None = None
    allow_fallback_to_v1: bool = False

    def __post_init__(self) -> None:
        version = str(self.version or "").strip()
        if version not in {
            SOURCE_TRANSFORM_VERSION,
            SOURCE_TRANSFORM_VERSION_V2,
        }:
            raise ValueError(
                f"Unsupported SOURCE transform version: {self.version!r} "
                f"(expected {SOURCE_TRANSFORM_VERSION!r} or "
                f"{SOURCE_TRANSFORM_VERSION_V2!r})"
            )
        output = self.output_color_space
        if output is not None:
            text = str(output).strip()
            output = text if text else None
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "output_color_space", output)


def normalize_source_transform_request(
    request: SourceTransformRequest | None,
) -> SourceTransformRequest:
    """None → default v1 request."""
    if request is None:
        return SourceTransformRequest()
    return request


@dataclass(frozen=True, slots=True)
class SamProcessingProfile:
    """Runtime-only SAM SOURCE selection (not persisted / not in Project schema).

    Default keeps product SAM on SOURCE v1. Opt-in v2 via
    ``source_transform_version=SOURCE_TRANSFORM_VERSION_V2``.
    """

    source_transform_version: str = SOURCE_TRANSFORM_VERSION
    output_color_space: str | None = None
    allow_fallback_to_v1: bool = False

    def __post_init__(self) -> None:
        version = str(self.source_transform_version or "").strip()
        if version not in {
            SOURCE_TRANSFORM_VERSION,
            SOURCE_TRANSFORM_VERSION_V2,
        }:
            raise ValueError(
                f"Unsupported SAM SOURCE transform version: "
                f"{self.source_transform_version!r} "
                f"(expected {SOURCE_TRANSFORM_VERSION!r} or "
                f"{SOURCE_TRANSFORM_VERSION_V2!r})"
            )
        output = self.output_color_space
        if output is not None:
            text = str(output).strip()
            output = text if text else None
        object.__setattr__(self, "source_transform_version", version)
        object.__setattr__(self, "output_color_space", output)

    def to_source_transform_request(self) -> SourceTransformRequest | None:
        """v1 default → None (decoder default path). v2 → explicit request."""
        if self.source_transform_version == SOURCE_TRANSFORM_VERSION:
            if self.allow_fallback_to_v1 or self.output_color_space is not None:
                return SourceTransformRequest(
                    version=SOURCE_TRANSFORM_VERSION,
                    output_color_space=self.output_color_space,
                    allow_fallback_to_v1=self.allow_fallback_to_v1,
                )
            return None
        return SourceTransformRequest(
            version=self.source_transform_version,
            output_color_space=self.output_color_space,
            allow_fallback_to_v1=self.allow_fallback_to_v1,
        )


@dataclass(frozen=True, slots=True)
class ProcessingInputDiagnostics:
    """Dev-only summary of capability input pixels (no pixel buffer retained)."""

    consumer: str
    source_transform_version: str
    output_color_space: str | None
    shape: tuple[int, ...]
    dtype: str
    sha256: str
    min_value: int
    max_value: int


@dataclass(frozen=True, slots=True)
class SamSourceComparison:
    """Side-by-side SOURCE v1 vs v2 uint8 input comparison (dev/test)."""

    v1_sha256: str
    v2_sha256: str
    identical: bool
    mean_absolute_difference: float
    max_difference: int
    v1_cache_hit: bool | None
    v2_cache_hit: bool | None
    v1_shape: tuple[int, ...]
    v2_shape: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MaskComparison:
    """Binary mask similarity metrics for SAM result comparison."""

    identical: bool
    iou: float
    changed_pixel_count: int
    area_delta: int
    bbox_delta: tuple[int, int, int, int] | None


def uint8_rgb_sha256(image: NDArray[np.uint8]) -> str:
    """Stable SHA-256 of contiguous HxWx3 uint8 RGB bytes."""
    import hashlib

    arr = np.ascontiguousarray(image, dtype=np.uint8)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def build_processing_input_diagnostics(
    *,
    consumer: str,
    image: NDArray[np.uint8],
    source_transform_version: str,
    output_color_space: str | None = None,
) -> ProcessingInputDiagnostics:
    arr = np.ascontiguousarray(image, dtype=np.uint8)
    if arr.size == 0:
        min_v, max_v = 0, 0
    else:
        min_v = int(arr.min())
        max_v = int(arr.max())
    return ProcessingInputDiagnostics(
        consumer=str(consumer),
        source_transform_version=str(source_transform_version),
        output_color_space=output_color_space,
        shape=tuple(int(x) for x in arr.shape),
        dtype=str(arr.dtype),
        sha256=uint8_rgb_sha256(arr),
        min_value=min_v,
        max_value=max_v,
    )


def compare_uint8_rgb(
    a: NDArray[np.uint8],
    b: NDArray[np.uint8],
) -> tuple[bool, float, int]:
    """Return ``(identical, mean_abs_diff, max_diff)``."""
    aa = np.ascontiguousarray(a, dtype=np.uint8)
    bb = np.ascontiguousarray(b, dtype=np.uint8)
    if aa.shape != bb.shape:
        raise ValueError(
            f"compare_uint8_rgb shape mismatch: {aa.shape} vs {bb.shape}"
        )
    if aa.size == 0:
        return True, 0.0, 0
    diff = np.abs(aa.astype(np.int16) - bb.astype(np.int16))
    return bool(np.array_equal(aa, bb)), float(diff.mean()), int(diff.max())


def compare_binary_masks(
    a: NDArray[np.uint8] | NDArray[np.bool_],
    b: NDArray[np.uint8] | NDArray[np.bool_],
    *,
    threshold: int = 127,
) -> MaskComparison:
    """IoU / changed-pixels / area / bbox delta for two masks."""
    ma = np.asarray(a)
    mb = np.asarray(b)
    if ma.shape != mb.shape:
        raise ValueError(f"mask shape mismatch: {ma.shape} vs {mb.shape}")
    if ma.dtype == np.bool_ or ma.dtype == bool:
        ba = ma.astype(bool)
    else:
        ba = np.asarray(ma) > threshold
    if mb.dtype == np.bool_ or mb.dtype == bool:
        bb = mb.astype(bool)
    else:
        bb = np.asarray(mb) > threshold

    identical = bool(np.array_equal(ba, bb))
    intersection = int(np.logical_and(ba, bb).sum())
    union = int(np.logical_or(ba, bb).sum())
    iou = 1.0 if union == 0 else float(intersection) / float(union)
    changed = int(np.logical_xor(ba, bb).sum())
    area_delta = int(ba.sum()) - int(bb.sum())

    def _bbox(mask: NDArray[np.bool_]) -> tuple[int, int, int, int] | None:
        ys, xs = np.where(mask)
        if ys.size == 0:
            return None
        return (
            int(ys.min()),
            int(xs.min()),
            int(ys.max()),
            int(xs.max()),
        )

    box_a = _bbox(ba)
    box_b = _bbox(bb)
    bbox_delta: tuple[int, int, int, int] | None
    if box_a is None and box_b is None:
        bbox_delta = (0, 0, 0, 0)
    elif box_a is None or box_b is None:
        bbox_delta = None
    else:
        bbox_delta = (
            box_a[0] - box_b[0],
            box_a[1] - box_b[1],
            box_a[2] - box_b[2],
            box_a[3] - box_b[3],
        )

    return MaskComparison(
        identical=identical,
        iou=iou,
        changed_pixel_count=changed,
        area_delta=area_delta,
        bbox_delta=bbox_delta,
    )
