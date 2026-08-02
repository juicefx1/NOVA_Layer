"""Frame histogram analysis for Viewer diagnostics (Phase 9D-1).

Pure NumPy computation of PREVIEW / SOURCE / SCENE channel distributions.
Not an export QC tool — intentionally allows stride downsampling for UI.

Cache peeks for frame pixels are preferred by call sites; this module only
analyzes already-loaded arrays and holds a small analysis-result LRU.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.ports.media import MediaReadError

if TYPE_CHECKING:
    from nova_layer.app.frame_decode_service import FrameDecodeService
    from nova_layer.app.preview_pipeline import TransformIdentity

# Rec.709 luma coefficients.
_LUMA_R = 0.2126
_LUMA_G = 0.7152
_LUMA_B = 0.0722

DEFAULT_HISTOGRAM_BINS = 256
DEFAULT_SCENE_RANGE: tuple[float, float] = (0.0, 4.0)
DEFAULT_MAX_SAMPLES = 1_000_000
DEFAULT_HISTOGRAM_CACHE_ENTRIES = 16

HistogramCacheKey = tuple[str, int, str, str, int, float, float]


@dataclass(frozen=True, slots=True)
class ChannelHistogram:
    bins: NDArray[np.int64]
    minimum: float
    maximum: float
    mean: float
    median: float
    clipped_low: int
    clipped_high: int


@dataclass(frozen=True, slots=True)
class FrameHistogramData:
    """Pure analysis result (no media path / frame metadata)."""

    policy: str
    red: ChannelHistogram
    green: ChannelHistogram
    blue: ChannelHistogram
    luminance: ChannelHistogram
    sample_count: int
    bins: int
    value_range: tuple[float, float]
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class FrameHistogram:
    policy: str
    frame_number: int
    media_path: Path
    red: ChannelHistogram
    green: ChannelHistogram
    blue: ChannelHistogram
    luminance: ChannelHistogram
    sample_count: int
    bins: int = DEFAULT_HISTOGRAM_BINS
    value_range: tuple[float, float] = DEFAULT_SCENE_RANGE
    warning: str | None = None


def empty_channel_histogram(*, bins: int = DEFAULT_HISTOGRAM_BINS) -> ChannelHistogram:
    return ChannelHistogram(
        bins=np.zeros(bins, dtype=np.int64),
        minimum=0.0,
        maximum=0.0,
        mean=0.0,
        median=0.0,
        clipped_low=0,
        clipped_high=0,
    )


def empty_frame_histogram(
    *,
    policy: str,
    media_path: Path | None = None,
    frame_number: int = -1,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    value_range: tuple[float, float] = DEFAULT_SCENE_RANGE,
    warning: str | None = None,
) -> FrameHistogram:
    empty = empty_channel_histogram(bins=bins)
    return FrameHistogram(
        policy=policy,
        frame_number=frame_number,
        media_path=media_path or Path("."),
        red=empty,
        green=empty,
        blue=empty,
        luminance=empty,
        sample_count=0,
        bins=bins,
        value_range=value_range,
        warning=warning,
    )


def _stride_for_samples(pixel_count: int, max_samples: int) -> int:
    if pixel_count <= max_samples:
        return 1
    # Uniform 2D stride so ≈ pixel_count / stride² ≤ max_samples.
    return max(1, int(np.ceil(np.sqrt(pixel_count / float(max_samples)))))


def downsample_rgb(
    image: NDArray[np.floating | np.integer],
    *,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> tuple[NDArray[np.floating | np.integer], int]:
    """Return (possibly strided) HxWxC view/copy and resulting sample count."""
    if image.ndim < 2:
        raise ValueError(f"Expected HxW[xC] image, got shape {image.shape!r}")
    height, width = int(image.shape[0]), int(image.shape[1])
    pixel_count = height * width
    stride = _stride_for_samples(pixel_count, max_samples)
    sampled = image if stride == 1 else image[::stride, ::stride]
    sample_count = int(sampled.shape[0]) * int(sampled.shape[1])
    return sampled, sample_count


def _channel_stats_uint8(values: NDArray[np.floating | np.integer]) -> ChannelHistogram:
    flat = np.asarray(values, dtype=np.float64).ravel()
    if flat.size == 0:
        return empty_channel_histogram(bins=256)
    quant = np.clip(np.rint(flat), 0, 255).astype(np.uint8)
    counts = np.bincount(quant, minlength=256).astype(np.int64)[:256]
    return ChannelHistogram(
        bins=counts,
        minimum=float(flat.min()),
        maximum=float(flat.max()),
        mean=float(flat.mean()),
        median=float(np.median(flat)),
        clipped_low=int(np.count_nonzero(quant == 0)),
        clipped_high=int(np.count_nonzero(quant == 255)),
    )


def _channel_stats_scene(
    values: NDArray[np.floating | np.integer],
    *,
    bins: int,
    scene_range: tuple[float, float],
) -> ChannelHistogram:
    flat = np.asarray(values, dtype=np.float64).ravel()
    if flat.size == 0:
        return empty_channel_histogram(bins=bins)
    low, high = float(scene_range[0]), float(scene_range[1])
    if high <= low:
        raise ValueError(f"Invalid scene_range: {scene_range!r}")
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        counts = np.zeros(bins, dtype=np.int64)
        return ChannelHistogram(
            bins=counts,
            minimum=float("nan"),
            maximum=float("nan"),
            mean=float("nan"),
            median=float("nan"),
            clipped_low=int(flat.size),
            clipped_high=0,
        )
    counts, _ = np.histogram(finite, bins=bins, range=(low, high))
    clipped_low = int(np.count_nonzero(finite < low))
    clipped_high = int(np.count_nonzero(finite > high))
    return ChannelHistogram(
        bins=counts.astype(np.int64, copy=False),
        minimum=float(finite.min()),
        maximum=float(finite.max()),
        mean=float(finite.mean()),
        median=float(np.median(finite)),
        clipped_low=clipped_low,
        clipped_high=clipped_high,
    )


def _luminance(rgb: NDArray[np.floating]) -> NDArray[np.float64]:
    return (
        _LUMA_R * rgb[..., 0]
        + _LUMA_G * rgb[..., 1]
        + _LUMA_B * rgb[..., 2]
    )


def compute_frame_histogram(
    image: NDArray[np.floating | np.integer],
    *,
    policy: ProcessingColorPolicy | str,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    scene_range: tuple[float, float] = DEFAULT_SCENE_RANGE,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> FrameHistogramData:
    """Compute RGB + Rec.709 luminance histograms (Qt-free, pure NumPy).

    PREVIEW / SOURCE use uint8 0..255 bins. SCENE uses fixed ``scene_range``
    for binning; min/max/mean/median remain unclipped finite statistics.
    """
    if bins < 1:
        raise ValueError("bins must be positive")
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

    policy_value = (
        policy.value if isinstance(policy, ProcessingColorPolicy) else str(policy)
    )
    sampled, sample_count = downsample_rgb(array[..., :3], max_samples=max_samples)
    rgb = np.asarray(sampled, dtype=np.float64)
    luma = _luminance(rgb)

    if policy_value in {
        ProcessingColorPolicy.PREVIEW.value,
        ProcessingColorPolicy.SOURCE.value,
    }:
        value_range = (0.0, 255.0)
        if bins != 256:
            # Contract for viewer diagnostics: uint8 uses 256 bins.
            bins = 256
        red = _channel_stats_uint8(rgb[..., 0])
        green = _channel_stats_uint8(rgb[..., 1])
        blue = _channel_stats_uint8(rgb[..., 2])
        luminance = _channel_stats_uint8(luma)
    elif policy_value == ProcessingColorPolicy.SCENE.value:
        value_range = (float(scene_range[0]), float(scene_range[1]))
        red = _channel_stats_scene(rgb[..., 0], bins=bins, scene_range=value_range)
        green = _channel_stats_scene(rgb[..., 1], bins=bins, scene_range=value_range)
        blue = _channel_stats_scene(rgb[..., 2], bins=bins, scene_range=value_range)
        luminance = _channel_stats_scene(luma, bins=bins, scene_range=value_range)
    else:
        raise ValueError(f"Unsupported histogram policy: {policy_value!r}")

    return FrameHistogramData(
        policy=policy_value,
        red=red,
        green=green,
        blue=blue,
        luminance=luminance,
        sample_count=sample_count,
        bins=bins,
        value_range=value_range,
        warning=None,
    )


def frame_histogram_from_data(
    data: FrameHistogramData,
    *,
    media_path: Path,
    frame_number: int,
) -> FrameHistogram:
    return FrameHistogram(
        policy=data.policy,
        frame_number=frame_number,
        media_path=media_path,
        red=data.red,
        green=data.green,
        blue=data.blue,
        luminance=data.luminance,
        sample_count=data.sample_count,
        bins=data.bins,
        value_range=data.value_range,
        warning=data.warning,
    )


def format_transform_cache_token(identity: TransformIdentity | None) -> str:
    if identity is None:
        return "none"
    return (
        f"{identity.backend}|{identity.config_path}|{identity.config_source}|"
        f"{identity.input_color_space}|{identity.display}|{identity.view}|"
        f"{identity.exposure:g}"
    )


def histogram_cache_identity(
    policy: ProcessingColorPolicy | str,
    *,
    transform_identity: TransformIdentity | None = None,
    source_transform_version: str = SOURCE_TRANSFORM_VERSION,
) -> str:
    policy_value = (
        policy.value if isinstance(policy, ProcessingColorPolicy) else str(policy)
    )
    if policy_value == ProcessingColorPolicy.PREVIEW.value:
        return format_transform_cache_token(transform_identity)
    if policy_value == ProcessingColorPolicy.SOURCE.value:
        return source_transform_version or SOURCE_TRANSFORM_VERSION
    if policy_value == ProcessingColorPolicy.SCENE.value:
        return "scene_raw"
    raise ValueError(f"Unsupported histogram policy: {policy_value!r}")


class HistogramAnalysisCache:
    """Small LRU for computed FrameHistogram results (entry-count only)."""

    def __init__(self, max_entries: int = DEFAULT_HISTOGRAM_CACHE_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = int(max_entries)
        self._items: OrderedDict[HistogramCacheKey, FrameHistogram] = OrderedDict()
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
        """Drop PREVIEW entries after viewer transform changes."""
        with self._lock:
            keys = [
                key
                for key in self._items
                if key[2] == ProcessingColorPolicy.PREVIEW.value
            ]
            for key in keys:
                del self._items[key]

    def get(self, key: HistogramCacheKey) -> FrameHistogram | None:
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return cached

    def put(self, key: HistogramCacheKey, value: FrameHistogram) -> None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            self._items[key] = value
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)


def build_histogram_cache_key(
    path: Path,
    frame_number: int,
    policy: ProcessingColorPolicy | str,
    *,
    identity: str,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    scene_range: tuple[float, float] = DEFAULT_SCENE_RANGE,
) -> HistogramCacheKey:
    policy_value = (
        policy.value if isinstance(policy, ProcessingColorPolicy) else str(policy)
    )
    resolved = str(path.expanduser().resolve())
    return (
        resolved,
        int(frame_number),
        policy_value,
        identity,
        int(bins),
        float(scene_range[0]),
        float(scene_range[1]),
    )


def get_frame_histogram_for_decoder(
    decoder: FrameDecodeService,
    path: Path,
    frame_number: int,
    policy: ProcessingColorPolicy,
    *,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    scene_range: tuple[float, float] = DEFAULT_SCENE_RANGE,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    allow_decode: bool = True,
) -> FrameHistogram:
    """Peek-first histogram for a media path/frame/policy (shared by services)."""
    resolved = path.expanduser().resolve()
    pipeline = decoder.pipeline
    identity = histogram_cache_identity(
        policy,
        transform_identity=pipeline.transform_identity,
        source_transform_version=SOURCE_TRANSFORM_VERSION,
    )
    key = build_histogram_cache_key(
        resolved,
        frame_number,
        policy,
        identity=identity,
        bins=bins,
        scene_range=scene_range,
    )
    cache = pipeline.histogram_cache
    cached = cache.get(key)
    if cached is not None:
        return cached

    warning: str | None = None
    image: NDArray[np.floating | np.integer] | None = None

    if policy is ProcessingColorPolicy.PREVIEW:
        image = pipeline.peek_preview(resolved, frame_number)
        if image is None and allow_decode:
            image = decoder.get_preview_frame(
                resolved, frame_number, schedule_prefetch=False
            )
    elif policy is ProcessingColorPolicy.SOURCE:
        image = pipeline.peek_source(resolved, frame_number)
        if image is None and allow_decode:
            frame = decoder.get_processing_frame(
                resolved,
                frame_number,
                policy=ProcessingColorPolicy.SOURCE,
            )
            if isinstance(frame, np.ndarray):
                image = frame
    elif policy is ProcessingColorPolicy.SCENE:
        scene = pipeline.peek_scene(resolved, frame_number)
        if scene is None and allow_decode:
            try:
                scene = decoder.get_scene_frame(resolved, frame_number)
            except MediaReadError as exc:
                warning = str(exc) or "SCENE unsupported"
                scene = None
            except Exception as exc:  # noqa: BLE001
                warning = f"SCENE unavailable: {exc}"
                scene = None
        if scene is not None:
            image = scene.pixels
    else:
        raise ValueError(f"Unsupported histogram policy: {policy!r}")

    if image is None:
        result = empty_frame_histogram(
            policy=policy.value,
            media_path=resolved,
            frame_number=frame_number,
            bins=bins,
            value_range=(
                (0.0, 255.0)
                if policy is not ProcessingColorPolicy.SCENE
                else scene_range
            ),
            warning=warning or "No pixel data available",
        )
        # Cache terminal unsupported/empty only after an allowed decode attempt
        # so peek-only probes do not sticky-cache incomplete results.
        if allow_decode:
            cache.put(key, result)
        return result

    data = compute_frame_histogram(
        image,
        policy=policy,
        bins=bins,
        scene_range=scene_range,
        max_samples=max_samples,
    )
    result = frame_histogram_from_data(
        data,
        media_path=resolved,
        frame_number=frame_number,
    )
    if warning is not None:
        result = FrameHistogram(
            policy=result.policy,
            frame_number=result.frame_number,
            media_path=result.media_path,
            red=result.red,
            green=result.green,
            blue=result.blue,
            luminance=result.luminance,
            sample_count=result.sample_count,
            bins=result.bins,
            value_range=result.value_range,
            warning=warning,
        )
    cache.put(key, result)
    return result
