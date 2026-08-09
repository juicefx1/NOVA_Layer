"""In-memory LRU cache for DepthFrame (Phase D1 — no disk cache)."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from nova_layer.app.frame_cache_stats import FrameCacheStats, bytes_from_env_mb
from nova_layer.ports.depth import DepthFrame, copy_depth_frame

DEFAULT_DEPTH_FRAME_CACHE_SIZE = 8
DEFAULT_DEPTH_CACHE_MAX_BYTES = 256 * 1024 * 1024


def _default_depth_max_bytes() -> int:
    return bytes_from_env_mb("NOVA_DEPTH_CACHE_MB", DEFAULT_DEPTH_CACHE_MAX_BYTES)


@dataclass(frozen=True, slots=True)
class DepthCacheKey:
    media_fingerprint: str
    frame_number: int
    model_id: str
    model_version: str
    preprocessing_version: str
    input_policy: str


def _entry_nbytes(frame: DepthFrame) -> int:
    total = int(frame.depth.nbytes)
    if frame.valid_mask is not None:
        total += int(frame.valid_mask.nbytes)
    return total


class DepthFrameCache:
    """Thread-safe LRU for DepthFrame with entry + byte budgets.

    Oversized foreground policy matches RawFrameCache: a single frame exceeding
    ``max_bytes`` clears the cache and admits that one entry.
    """

    def __init__(
        self,
        *,
        max_entries: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        if max_entries is None:
            max_entries = DEFAULT_DEPTH_FRAME_CACHE_SIZE
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes is None:
            max_bytes = _default_depth_max_bytes()
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        self._max_bytes = int(max_bytes)
        self._max_entries = int(max_entries)
        self._items: OrderedDict[DepthCacheKey, DepthFrame] = OrderedDict()
        self._entry_bytes: dict[DepthCacheKey, int] = {}
        self._current_bytes = 0
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._oversized_rejections = 0
        self._oversized_admissions = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    def stats(self) -> FrameCacheStats:
        with self._lock:
            return FrameCacheStats(
                count=len(self._items),
                current_bytes=self._current_bytes,
                max_bytes=self._max_bytes,
                max_entries=self._max_entries,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                oversized_rejections=self._oversized_rejections,
                oversized_admissions=self._oversized_admissions,
            )

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._entry_bytes.clear()
            self._current_bytes = 0

    def get(self, key: DepthCacheKey) -> DepthFrame | None:
        with self._lock:
            frame = self._items.get(key)
            if frame is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return copy_depth_frame(frame)

    def put(self, key: DepthCacheKey, frame: DepthFrame, *, allow_eviction: bool = True) -> bool:
        stored = copy_depth_frame(frame)
        nbytes = _entry_nbytes(stored)

        with self._lock:
            if nbytes > self._max_bytes:
                if not allow_eviction:
                    self._oversized_rejections += 1
                    return False
                self._items.clear()
                self._entry_bytes.clear()
                self._items[key] = stored
                self._entry_bytes[key] = nbytes
                self._current_bytes = nbytes
                self._items.move_to_end(key)
                self._oversized_admissions += 1
                return True

            old_nbytes = self._entry_bytes.get(key)
            replacing = old_nbytes is not None
            next_bytes = self._current_bytes - (old_nbytes or 0) + nbytes
            next_count = len(self._items) if replacing else len(self._items) + 1

            if not allow_eviction:
                if next_bytes > self._max_bytes or next_count > self._max_entries:
                    return False
                if replacing:
                    self._current_bytes -= old_nbytes or 0
                self._items[key] = stored
                self._entry_bytes[key] = nbytes
                self._current_bytes += nbytes
                self._items.move_to_end(key)
                return True

            if replacing:
                self._current_bytes -= old_nbytes or 0
            self._items[key] = stored
            self._entry_bytes[key] = nbytes
            self._current_bytes += nbytes
            self._items.move_to_end(key)
            self._evict_until_fit_unlocked(protect_key=key)
            return True

    def _evict_until_fit_unlocked(self, *, protect_key: DepthCacheKey | None = None) -> None:
        while self._items and (
            self._current_bytes > self._max_bytes or len(self._items) > self._max_entries
        ):
            victim_key = None
            for candidate in self._items:
                if candidate != protect_key:
                    victim_key = candidate
                    break
            if victim_key is None:
                break
            self._items.pop(victim_key)
            removed = self._entry_bytes.pop(victim_key, 0)
            self._current_bytes -= removed
            self._evictions += 1
        if self._current_bytes < 0:
            self._current_bytes = 0
