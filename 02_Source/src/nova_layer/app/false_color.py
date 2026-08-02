"""False Color overlay transforms for Viewer diagnostics (Phase 9D-2).

Pure NumPy mapping of PREVIEW / SOURCE / SCENE values to fixed palettes.
Does not mutate frame caches. Not applied to export/render paths.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from nova_layer.app.histogram_analysis import format_transform_cache_token
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.ports.media import MediaReadError

if TYPE_CHECKING:
    from nova_layer.app.frame_decode_service import FrameDecodeService
    from nova_layer.app.preview_pipeline import TransformIdentity

_LUMA_R = 0.2126
_LUMA_G = 0.7152
_LUMA_B = 0.0722
_SCENE_EPS = 1e-8
DEFAULT_FALSE_COLOR_CACHE_ENTRIES = 8
NEUTRAL_GRAY = (128, 128, 128)
NAN_SAFE_COLOR = (40, 40, 40)

FalseColorCacheKey = tuple[str, int, str, float, str]


class FalseColorMode(str, Enum):
    OFF = "off"
    PREVIEW_LUMA = "preview_luma"
    SOURCE_LUMA = "source_luma"
    SCENE_EXPOSURE = "scene_exposure"
    SCENE_CLIPPING = "scene_clipping"


@dataclass(frozen=True, slots=True)
class FalseColorSettings:
    mode: FalseColorMode = FalseColorMode.OFF
    opacity: float = 1.0
    show_legend: bool = True

    def __post_init__(self) -> None:
        opacity = float(self.opacity)
        if opacity < 0.0 or opacity > 1.0:
            raise ValueError(f"opacity must be in [0, 1], got {opacity}")


@dataclass(frozen=True, slots=True)
class FalseColorBand:
    """Fixed palette band for tests and legend."""

    label: str
    color: tuple[int, int, int]
    low: float | None
    high: float | None
    unit: str = ""


# PREVIEW / SOURCE Rec.709 luma as fraction of 0..255.
LUMA_BANDS: tuple[FalseColorBand, ...] = (
    FalseColorBand("0–5%", (8, 12, 72), 0.00, 0.05, "%"),
    FalseColorBand("5–20%", (24, 56, 210), 0.05, 0.20, "%"),
    FalseColorBand("20–40%", (24, 196, 220), 0.20, 0.40, "%"),
    FalseColorBand("40–60%", (48, 196, 64), 0.40, 0.60, "%"),
    FalseColorBand("60–80%", (232, 214, 40), 0.60, 0.80, "%"),
    FalseColorBand("80–95%", (236, 140, 32), 0.80, 0.95, "%"),
    FalseColorBand("95–100%", (220, 40, 40), 0.95, 1.00, "%"),
)

SCENE_EXPOSURE_BANDS: tuple[FalseColorBand, ...] = (
    FalseColorBand("< −6 EV", (12, 16, 64), None, -6.0, "EV"),
    FalseColorBand("−6 ~ −4 EV", (28, 72, 200), -6.0, -4.0, "EV"),
    FalseColorBand("−4 ~ −2 EV", (32, 180, 210), -4.0, -2.0, "EV"),
    FalseColorBand("−2 ~ 0 EV", (56, 190, 70), -2.0, 0.0, "EV"),
    FalseColorBand("0 ~ +2 EV", (230, 210, 40), 0.0, 2.0, "EV"),
    FalseColorBand("+2 ~ +4 EV", (236, 132, 28), 2.0, 4.0, "EV"),
    FalseColorBand("> +4 EV", (220, 36, 36), 4.0, None, "EV"),
)

SCENE_CLIPPING_BANDS: tuple[FalseColorBand, ...] = (
    FalseColorBand("> 4 (magenta)", (220, 40, 200), 4.0, None, "scene"),
    FalseColorBand("> 1 (red)", (220, 40, 40), 1.0, 4.0, "scene"),
    FalseColorBand("< 0 (blue)", (40, 80, 220), None, 0.0, "scene"),
    FalseColorBand("normal", NEUTRAL_GRAY, 0.0, 1.0, "scene"),
)


def legend_for_mode(mode: FalseColorMode) -> tuple[FalseColorBand, ...]:
    if mode in {FalseColorMode.PREVIEW_LUMA, FalseColorMode.SOURCE_LUMA}:
        return LUMA_BANDS
    if mode is FalseColorMode.SCENE_EXPOSURE:
        return SCENE_EXPOSURE_BANDS
    if mode is FalseColorMode.SCENE_CLIPPING:
        return SCENE_CLIPPING_BANDS
    return ()


def _require_rgb(image: NDArray[np.floating | np.integer]) -> NDArray[np.floating]:
    if image is None:
        raise ValueError("image is required")
    array = np.asarray(image)
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError(
            f"Expected HxWx3(+) RGB image, got shape {getattr(array, 'shape', None)!r}"
        )
    if array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("image must have positive spatial size")
    return np.asarray(array[..., :3], dtype=np.float64)


def _rec709_luma(rgb: NDArray[np.floating]) -> NDArray[np.float64]:
    return _LUMA_R * rgb[..., 0] + _LUMA_G * rgb[..., 1] + _LUMA_B * rgb[..., 2]


def _palette_lookup(
    values: NDArray[np.float64],
    bands: Sequence[FalseColorBand],
    *,
    inclusive_high: bool = True,
) -> NDArray[np.uint8]:
    """Map scalar field to RGB using ordered bands (low ≤ x < high, last closed)."""
    height, width = values.shape
    out = np.zeros((height, width, 3), dtype=np.uint8)
    # NaN / Inf → safe dark
    safe = np.isfinite(values)
    assigned = np.zeros(values.shape, dtype=bool)
    for index, band in enumerate(bands):
        color = np.asarray(band.color, dtype=np.uint8)
        low = band.low
        high = band.high
        mask = safe & ~assigned
        if low is not None:
            mask &= values >= low
        if high is not None:
            if index == len(bands) - 1 and inclusive_high:
                mask &= values <= high
            else:
                mask &= values < high
        out[mask] = color
        assigned |= mask
    # Leftover finite values (e.g. >1.0 for luma) → last band color
    leftover = safe & ~assigned
    if np.any(leftover):
        out[leftover] = np.asarray(bands[-1].color, dtype=np.uint8)
    out[~safe] = np.asarray(NAN_SAFE_COLOR, dtype=np.uint8)
    return out


def _luma_false_color(rgb_u8: NDArray[np.floating | np.integer]) -> NDArray[np.uint8]:
    rgb = _require_rgb(rgb_u8)
    luma = np.clip(_rec709_luma(rgb) / 255.0, 0.0, 1.0)
    return _palette_lookup(luma, LUMA_BANDS)


def _scene_exposure_false_color(
    scene_rgb: NDArray[np.floating | np.integer],
) -> NDArray[np.uint8]:
    rgb = _require_rgb(scene_rgb)
    luma = _rec709_luma(rgb)
    # Non-positive / non-finite handled via safe masking; clamp eps for log2.
    positive = np.isfinite(luma) & (luma > 0.0)
    ev = np.full(luma.shape, np.nan, dtype=np.float64)
    ev[positive] = np.log2(np.maximum(luma[positive], _SCENE_EPS))
    # Non-positive finite → treat as below lowest band
    nonpos = np.isfinite(luma) & (luma <= 0.0)
    ev[nonpos] = -1.0e9
    return _palette_lookup(ev, SCENE_EXPOSURE_BANDS, inclusive_high=False)


def _scene_clipping_false_color(
    scene_rgb: NDArray[np.floating | np.integer],
    *,
    base_preview: NDArray[np.uint8] | None = None,
) -> NDArray[np.uint8]:
    rgb = _require_rgb(scene_rgb)
    height, width = rgb.shape[:2]
    if base_preview is not None:
        base = np.asarray(base_preview[..., :3], dtype=np.uint8)
        if base.shape[:2] != (height, width):
            raise ValueError("base_preview spatial size must match scene frame")
        out = np.ascontiguousarray(base.copy())
    else:
        out = np.full((height, width, 3), NEUTRAL_GRAY, dtype=np.uint8)

    finite = np.isfinite(rgb)
    # Channel-wise comparisons; ignore non-finite for clip masks
    safe_rgb = np.where(finite, rgb, 0.0)
    any_gt4 = np.any((safe_rgb > 4.0) & finite, axis=-1)
    any_gt1 = np.any((safe_rgb > 1.0) & finite, axis=-1) & ~any_gt4
    any_lt0 = np.any((safe_rgb < 0.0) & finite, axis=-1) & ~any_gt4 & ~any_gt1
    # Non-finite pixels → safe dark
    any_bad = ~np.all(finite, axis=-1)

    out[any_gt4] = np.asarray(SCENE_CLIPPING_BANDS[0].color, dtype=np.uint8)
    out[any_gt1] = np.asarray(SCENE_CLIPPING_BANDS[1].color, dtype=np.uint8)
    out[any_lt0] = np.asarray(SCENE_CLIPPING_BANDS[2].color, dtype=np.uint8)
    out[any_bad] = np.asarray(NAN_SAFE_COLOR, dtype=np.uint8)
    return out


def blend_false_color(
    base: NDArray[np.uint8],
    colored: NDArray[np.uint8],
    *,
    opacity: float,
) -> NDArray[np.uint8]:
    """Blend ``colored`` over ``base`` with opacity in [0, 1]."""
    opacity = float(opacity)
    if opacity < 0.0 or opacity > 1.0:
        raise ValueError(f"opacity must be in [0, 1], got {opacity}")
    base_arr = np.asarray(base[..., :3], dtype=np.float64)
    color_arr = np.asarray(colored[..., :3], dtype=np.float64)
    if base_arr.shape != color_arr.shape:
        raise ValueError("base and colored shapes must match")
    if opacity <= 0.0:
        return np.ascontiguousarray(base[..., :3], dtype=np.uint8)
    if opacity >= 1.0:
        return np.ascontiguousarray(colored[..., :3], dtype=np.uint8)
    mixed = (1.0 - opacity) * base_arr + opacity * color_arr
    return np.ascontiguousarray(np.clip(np.rint(mixed), 0, 255).astype(np.uint8))


def apply_false_color(
    image: NDArray[np.floating | np.integer],
    *,
    mode: FalseColorMode,
    opacity: float = 1.0,
    base_preview: NDArray[np.uint8] | None = None,
) -> NDArray[np.uint8]:
    """Return uint8 RGB false-color visualization (Qt-free).

    ``base_preview`` is used for opacity blending and SCENE_CLIPPING normals.
    When ``mode`` is OFF, returns ``base_preview`` (required) or a copy of
    ``image`` cast to uint8.
    """
    if not isinstance(mode, FalseColorMode):
        mode = FalseColorMode(str(mode))
    opacity = float(opacity)
    if opacity < 0.0 or opacity > 1.0:
        raise ValueError(f"opacity must be in [0, 1], got {opacity}")

    if mode is FalseColorMode.OFF:
        if base_preview is not None:
            return np.ascontiguousarray(base_preview[..., :3], dtype=np.uint8)
        rgb = _require_rgb(image)
        return np.ascontiguousarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8))

    if mode in {FalseColorMode.PREVIEW_LUMA, FalseColorMode.SOURCE_LUMA}:
        colored = _luma_false_color(image)
        base = (
            np.ascontiguousarray(base_preview[..., :3], dtype=np.uint8)
            if base_preview is not None
            else np.ascontiguousarray(
                np.clip(np.rint(_require_rgb(image)), 0, 255).astype(np.uint8)
            )
        )
        return blend_false_color(base, colored, opacity=opacity)

    if mode is FalseColorMode.SCENE_EXPOSURE:
        colored = _scene_exposure_false_color(image)
        if base_preview is None:
            base = np.full(colored.shape, NEUTRAL_GRAY, dtype=np.uint8)
        else:
            base = np.ascontiguousarray(base_preview[..., :3], dtype=np.uint8)
        return blend_false_color(base, colored, opacity=opacity)

    if mode is FalseColorMode.SCENE_CLIPPING:
        # Already composites normals from base_preview / gray.
        colored = _scene_clipping_false_color(image, base_preview=base_preview)
        if base_preview is None:
            return colored if opacity >= 1.0 else blend_false_color(
                np.full(colored.shape, NEUTRAL_GRAY, dtype=np.uint8),
                colored,
                opacity=opacity,
            )
        base = np.ascontiguousarray(base_preview[..., :3], dtype=np.uint8)
        return blend_false_color(base, colored, opacity=opacity)

    raise ValueError(f"Unsupported false color mode: {mode!r}")


def false_color_cache_identity(
    mode: FalseColorMode,
    *,
    transform_identity: TransformIdentity | None = None,
    source_transform_version: str = SOURCE_TRANSFORM_VERSION,
) -> str:
    if mode is FalseColorMode.OFF:
        return "off"
    if mode is FalseColorMode.PREVIEW_LUMA:
        return format_transform_cache_token(transform_identity)
    if mode is FalseColorMode.SOURCE_LUMA:
        return source_transform_version or SOURCE_TRANSFORM_VERSION
    if mode in {FalseColorMode.SCENE_EXPOSURE, FalseColorMode.SCENE_CLIPPING}:
        return "scene_raw"
    raise ValueError(f"Unsupported false color mode: {mode!r}")


def build_false_color_cache_key(
    path: Path,
    frame_number: int,
    mode: FalseColorMode,
    *,
    opacity: float,
    identity: str,
) -> FalseColorCacheKey:
    return (
        str(path.expanduser().resolve()),
        int(frame_number),
        mode.value,
        round(float(opacity), 4),
        identity,
    )


class FalseColorCache:
    """Small LRU for computed false-color uint8 frames."""

    def __init__(self, max_entries: int = DEFAULT_FALSE_COLOR_CACHE_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = int(max_entries)
        self._items: OrderedDict[FalseColorCacheKey, NDArray[np.uint8]] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def invalidate_preview(self) -> None:
        with self._lock:
            keys = [
                key
                for key in self._items
                if key[2] == FalseColorMode.PREVIEW_LUMA.value
            ]
            for key in keys:
                del self._items[key]

    def get(self, key: FalseColorCacheKey) -> NDArray[np.uint8] | None:
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return np.ascontiguousarray(cached).copy()

    def put(self, key: FalseColorCacheKey, value: NDArray[np.uint8]) -> None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            self._items[key] = np.ascontiguousarray(value).copy()
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)


def get_false_color_frame_for_decoder(
    decoder: FrameDecodeService,
    path: Path,
    frame_number: int,
    *,
    mode: FalseColorMode,
    opacity: float = 1.0,
    allow_decode: bool = True,
) -> tuple[NDArray[np.uint8] | None, str | None]:
    """Peek-first false-color frame. Returns ``(rgb, warning)``.

    OFF returns preview (or None) without writing false-color cache.
    Original frame caches are never mutated with false-color pixels.
    """
    if not isinstance(mode, FalseColorMode):
        mode = FalseColorMode(str(mode))
    resolved = path.expanduser().resolve()
    pipeline = decoder.pipeline

    if mode is FalseColorMode.OFF:
        preview = pipeline.peek_preview(resolved, frame_number)
        if preview is None and allow_decode:
            preview = decoder.get_preview_frame(
                resolved, frame_number, schedule_prefetch=False
            )
        return (
            None if preview is None else np.ascontiguousarray(preview),
            None,
        )

    identity = false_color_cache_identity(
        mode,
        transform_identity=pipeline.transform_identity,
        source_transform_version=SOURCE_TRANSFORM_VERSION,
    )
    key = build_false_color_cache_key(
        resolved,
        frame_number,
        mode,
        opacity=opacity,
        identity=identity,
    )
    cached = pipeline.false_color_cache.get(key)
    if cached is not None:
        return cached, None

    warning: str | None = None
    preview = pipeline.peek_preview(resolved, frame_number)
    if preview is None and allow_decode:
        try:
            preview = decoder.get_preview_frame(
                resolved, frame_number, schedule_prefetch=False
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"PREVIEW unavailable: {exc}"

    source_image: NDArray[np.uint8] | None = None
    scene_pixels: NDArray[np.floating] | None = None

    if mode is FalseColorMode.PREVIEW_LUMA:
        if preview is None:
            return None, warning or "No preview frame"
        result = apply_false_color(
            preview,
            mode=mode,
            opacity=opacity,
            base_preview=preview,
        )
    elif mode is FalseColorMode.SOURCE_LUMA:
        source_image = pipeline.peek_source(resolved, frame_number)
        if source_image is None and allow_decode:
            frame = decoder.get_processing_frame(
                resolved,
                frame_number,
                policy=ProcessingColorPolicy.SOURCE,
            )
            if isinstance(frame, np.ndarray):
                source_image = frame
        if source_image is None:
            return None, warning or "No SOURCE frame"
        base = preview if preview is not None else source_image
        result = apply_false_color(
            source_image,
            mode=mode,
            opacity=opacity,
            base_preview=base,
        )
    elif mode in {FalseColorMode.SCENE_EXPOSURE, FalseColorMode.SCENE_CLIPPING}:
        scene = pipeline.peek_scene(resolved, frame_number)
        if scene is None and allow_decode:
            try:
                scene = decoder.get_scene_frame(resolved, frame_number)
            except MediaReadError as exc:
                return None, str(exc) or "SCENE unsupported"
            except Exception as exc:  # noqa: BLE001
                return None, f"SCENE unavailable: {exc}"
        if scene is None:
            return None, warning or "SCENE unsupported"
        scene_pixels = scene.pixels
        result = apply_false_color(
            scene_pixels,
            mode=mode,
            opacity=opacity,
            base_preview=preview,
        )
    else:
        raise ValueError(f"Unsupported false color mode: {mode!r}")

    pipeline.false_color_cache.put(key, result)
    return result, warning
