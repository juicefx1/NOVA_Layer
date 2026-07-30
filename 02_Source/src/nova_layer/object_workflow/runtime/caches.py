from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.runtime.lru_cache import CacheStats, LruMemoryCache
from nova_layer.object_workflow.runtime.metrics import InFlightDeduper, PerformanceMonitor

# Suggested defaults from Product Feature 7.
DEFAULT_IMAGE_CACHE_BUDGET = 256 * 1024 * 1024
DEFAULT_MASK_CACHE_BUDGET = 128 * 1024 * 1024
DEFAULT_THUMBNAIL_CACHE_BUDGET = 64 * 1024 * 1024
DEFAULT_PREVIEW_CACHE_BUDGET = 128 * 1024 * 1024


def ndarray_nbytes(array: NDArray[np.uint8]) -> int:
    return int(array.nbytes)


def _owned_readonly(frame: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Detach from caller memory and mark read-only (safe to share from cache)."""
    if (
        isinstance(frame, np.ndarray)
        and frame.dtype == np.uint8
        and frame.flags.c_contiguous
        and frame.flags.owndata
        and not frame.flags.writeable
    ):
        return frame
    owned = np.ascontiguousarray(frame, dtype=np.uint8)
    if not owned.flags.owndata:
        owned = owned.copy()
    else:
        # Copy so later caller mutations of the input cannot corrupt the cache.
        owned = owned.copy()
    owned.setflags(write=False)
    return owned


class ImageCache:
    """Decoded RGB source frames keyed by asset path / id."""

    def __init__(
        self,
        *,
        budget_bytes: int = DEFAULT_IMAGE_CACHE_BUDGET,
        monitor: PerformanceMonitor | None = None,
    ) -> None:
        self._cache: LruMemoryCache[NDArray[np.uint8]] = LruMemoryCache(
            budget_bytes=budget_bytes,
            name="image",
        )
        self._monitor = monitor
        self._inflight = InFlightDeduper()

    def stats(self) -> CacheStats:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()
        self._inflight.clear()

    def get(self, asset_id: str) -> NDArray[np.uint8] | None:
        value = self._cache.get(asset_id)
        if self._monitor is not None:
            self._monitor.increment("image_cache_hit" if value is not None else "image_cache_miss")
        # Stored arrays are write-protected; return without an extra copy.
        return value

    def put(self, asset_id: str, frame: NDArray[np.uint8]) -> None:
        owned = _owned_readonly(frame)
        self._cache.put(asset_id, owned, size_bytes=ndarray_nbytes(owned))

    def get_or_decode(
        self,
        asset_id: str,
        decoder: Callable[[], NDArray[np.uint8]],
    ) -> NDArray[np.uint8]:
        cached = self.get(asset_id)
        if cached is not None:
            return cached

        def _load() -> NDArray[np.uint8]:
            if self._monitor is not None:
                with self._monitor.measure("decode", kind="image", asset_id=asset_id):
                    decoded = decoder()
            else:
                decoded = decoder()
            owned = _owned_readonly(decoded)
            self._cache.put(asset_id, owned, size_bytes=ndarray_nbytes(owned))
            return owned

        return self._inflight.run(("image", asset_id), _load)


class MaskCache:
    """Decoded grayscale BinaryMask images keyed by mask asset path."""

    def __init__(
        self,
        *,
        budget_bytes: int = DEFAULT_MASK_CACHE_BUDGET,
        monitor: PerformanceMonitor | None = None,
    ) -> None:
        self._cache: LruMemoryCache[NDArray[np.uint8]] = LruMemoryCache(
            budget_bytes=budget_bytes,
            name="mask",
        )
        self._monitor = monitor
        self._inflight = InFlightDeduper()

    def stats(self) -> CacheStats:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()
        self._inflight.clear()

    def get(self, mask_asset_id: str) -> NDArray[np.uint8] | None:
        value = self._cache.get(mask_asset_id)
        if self._monitor is not None:
            self._monitor.increment("mask_cache_hit" if value is not None else "mask_cache_miss")
        return value

    def put(self, mask_asset_id: str, mask: NDArray[np.uint8]) -> None:
        owned = _owned_readonly(mask)
        self._cache.put(mask_asset_id, owned, size_bytes=ndarray_nbytes(owned))

    def get_or_decode(
        self,
        mask_asset_id: str,
        decoder: Callable[[], NDArray[np.uint8]],
    ) -> NDArray[np.uint8]:
        cached = self.get(mask_asset_id)
        if cached is not None:
            return cached

        def _load() -> NDArray[np.uint8]:
            if self._monitor is not None:
                with self._monitor.measure("decode", kind="mask", asset_id=mask_asset_id):
                    decoded = decoder()
            else:
                decoded = decoder()
            owned = _owned_readonly(decoded)
            self._cache.put(mask_asset_id, owned, size_bytes=ndarray_nbytes(owned))
            return owned

        return self._inflight.run(("mask", mask_asset_id), _load)


class ThumbnailCache:
    """Candidate thumbnail masks keyed by candidate id + thumbnail parameters."""

    def __init__(
        self,
        *,
        budget_bytes: int = DEFAULT_THUMBNAIL_CACHE_BUDGET,
        monitor: PerformanceMonitor | None = None,
    ) -> None:
        self._cache: LruMemoryCache[NDArray[np.uint8]] = LruMemoryCache(
            budget_bytes=budget_bytes,
            name="thumbnail",
        )
        self._monitor = monitor
        self._inflight = InFlightDeduper()

    def stats(self) -> CacheStats:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()
        self._inflight.clear()

    @staticmethod
    def make_key(candidate_id: UUID | str, *, preview_path: str, max_edge: int = 96) -> str:
        return f"{candidate_id}:{preview_path}:{max_edge}"

    def get(self, key: str) -> NDArray[np.uint8] | None:
        value = self._cache.get(key)
        if self._monitor is not None:
            self._monitor.increment(
                "thumbnail_cache_hit" if value is not None else "thumbnail_cache_miss"
            )
        return value

    def put(self, key: str, thumbnail: NDArray[np.uint8]) -> None:
        owned = _owned_readonly(thumbnail)
        self._cache.put(key, owned, size_bytes=ndarray_nbytes(owned))

    def get_or_decode(
        self,
        key: str,
        decoder: Callable[[], NDArray[np.uint8]],
    ) -> NDArray[np.uint8]:
        cached = self.get(key)
        if cached is not None:
            return cached

        def _load() -> NDArray[np.uint8]:
            if self._monitor is not None:
                with self._monitor.measure("thumbnail", key=key):
                    decoded = decoder()
            else:
                decoded = decoder()
            owned = _owned_readonly(decoded)
            self._cache.put(key, owned, size_bytes=ndarray_nbytes(owned))
            return owned

        return self._inflight.run(("thumbnail", key), _load)


class PreviewCache:
    """Rendered extraction preview RGBA keyed by extraction id + scale."""

    def __init__(
        self,
        *,
        budget_bytes: int = DEFAULT_PREVIEW_CACHE_BUDGET,
        monitor: PerformanceMonitor | None = None,
    ) -> None:
        self._cache: LruMemoryCache[NDArray[np.uint8]] = LruMemoryCache(
            budget_bytes=budget_bytes,
            name="preview",
        )
        self._monitor = monitor
        self._inflight = InFlightDeduper()
        self._active_extraction_id: str | None = None

    def stats(self) -> CacheStats:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()
        self._inflight.clear()
        self._active_extraction_id = None

    @staticmethod
    def make_key(extraction_id: UUID | str, *, scale: float = 1.0) -> str:
        return f"{extraction_id}:{scale:.4f}"

    def invalidate_unless(self, extraction_id: UUID | str | None) -> None:
        target = None if extraction_id is None else str(extraction_id)
        if target != self._active_extraction_id:
            self.clear()
            self._active_extraction_id = target

    def get(self, key: str) -> NDArray[np.uint8] | None:
        value = self._cache.get(key)
        if self._monitor is not None:
            self._monitor.increment(
                "preview_cache_hit" if value is not None else "preview_cache_miss"
            )
        return value

    def put(self, key: str, preview: NDArray[np.uint8]) -> None:
        owned = _owned_readonly(preview)
        self._cache.put(key, owned, size_bytes=ndarray_nbytes(owned))

    def get_or_decode(
        self,
        key: str,
        decoder: Callable[[], NDArray[np.uint8]],
    ) -> NDArray[np.uint8]:
        cached = self.get(key)
        if cached is not None:
            return cached

        def _load() -> NDArray[np.uint8]:
            if self._monitor is not None:
                with self._monitor.measure("preview_render", key=key):
                    decoded = decoder()
            else:
                decoded = decoder()
            owned = _owned_readonly(decoded)
            self._cache.put(key, owned, size_bytes=ndarray_nbytes(owned))
            return owned

        return self._inflight.run(("preview", key), _load)


class RuntimeCacheBundle:
    """Disposable runtime-only cache set for one Application/Controller session."""

    def __init__(
        self,
        *,
        monitor: PerformanceMonitor | None = None,
        image_budget: int = DEFAULT_IMAGE_CACHE_BUDGET,
        mask_budget: int = DEFAULT_MASK_CACHE_BUDGET,
        thumbnail_budget: int = DEFAULT_THUMBNAIL_CACHE_BUDGET,
        preview_budget: int = DEFAULT_PREVIEW_CACHE_BUDGET,
    ) -> None:
        self.monitor = monitor or PerformanceMonitor(max_samples=2048)
        self.images = ImageCache(budget_bytes=image_budget, monitor=self.monitor)
        self.masks = MaskCache(budget_bytes=mask_budget, monitor=self.monitor)
        self.thumbnails = ThumbnailCache(budget_bytes=thumbnail_budget, monitor=self.monitor)
        self.previews = PreviewCache(budget_bytes=preview_budget, monitor=self.monitor)

    def clear(self) -> None:
        self.images.clear()
        self.masks.clear()
        self.thumbnails.clear()
        self.previews.clear()
        self.monitor.clear()

    def snapshot(self) -> dict[str, CacheStats]:
        return {
            "image": self.images.stats(),
            "mask": self.masks.stats(),
            "thumbnail": self.thumbnails.stats(),
            "preview": self.previews.stats(),
        }
