from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

from nova_layer.app.frame_cache_stats import FrameCacheStats, bytes_from_env_mb
from nova_layer.ports.scene_frames import SceneFrame

# Entry-count soft cap (also used as legacy ``capacity`` / ``raw_cache_size``).
DEFAULT_RAW_FRAME_CACHE_SIZE = 8

# ~512 MiB hard RAM budget for scene-linear float RGB (override: NOVA_RAW_CACHE_MB).
DEFAULT_RAW_CACHE_MAX_BYTES = 512 * 1024 * 1024


def _cache_key(path: Path, frame_number: int) -> tuple[Path, int]:
    return (path.expanduser().resolve(), frame_number)


def _default_raw_max_bytes() -> int:
    return bytes_from_env_mb("NOVA_RAW_CACHE_MB", DEFAULT_RAW_CACHE_MAX_BYTES)


class RawFrameCache:
    """Thread-safe LRU for EXR scene frames with byte budget + optional entry cap.

    Accounting uses ``SceneFrame.pixels.nbytes`` only (no dataclass overhead).

    Oversized foreground: if a single frame exceeds ``max_bytes``, the cache is
    cleared and that one frame is admitted (``current_bytes`` may exceed
    ``max_bytes``). Prefetch must pass ``allow_eviction=False`` and never admits
    oversized frames; it also never evicts existing entries.
    """

    def __init__(
        self,
        capacity: int | None = None,
        *,
        max_bytes: int | None = None,
        max_entries: int | None = None,
    ) -> None:
        # Legacy: RawFrameCache(8) / RawFrameCache(capacity=8)
        if capacity is not None and max_entries is None:
            max_entries = capacity
        if max_entries is None:
            max_entries = DEFAULT_RAW_FRAME_CACHE_SIZE
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes is None:
            max_bytes = _default_raw_max_bytes()
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        self._max_bytes = int(max_bytes)
        self._max_entries = int(max_entries)
        self._items: OrderedDict[tuple[Path, int], SceneFrame] = OrderedDict()
        self._entry_bytes: dict[tuple[Path, int], int] = {}
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
    def capacity(self) -> int:
        """Legacy alias for ``max_entries``."""
        return self._max_entries

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

    @property
    def count(self) -> int:
        return len(self)

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

    def contains(self, path: Path, frame_number: int) -> bool:
        key = _cache_key(path, frame_number)
        with self._lock:
            return key in self._items

    def peek(self, path: Path, frame_number: int) -> SceneFrame | None:
        """Return a copy if present without updating hit/miss or LRU order.

        Intended for read-only diagnostics snapshots.
        """
        key = _cache_key(path, frame_number)
        with self._lock:
            frame = self._items.get(key)
            if frame is None:
                return None
            return _copy_scene_frame(frame)

    def get(self, path: Path, frame_number: int) -> SceneFrame | None:
        key = _cache_key(path, frame_number)
        with self._lock:
            frame = self._items.get(key)
            if frame is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return _copy_scene_frame(frame)

    def put(self, frame: SceneFrame, *, allow_eviction: bool = True) -> bool:
        """Store a scene frame. Returns False when skipped (prefetch no-fit / reject)."""
        key = _cache_key(frame.path, frame.frame_number)
        stored = _copy_scene_frame(frame)
        nbytes = int(stored.pixels.nbytes)

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

            # Foreground: insert/replace then evict LRU until within limits.
            if replacing:
                self._current_bytes -= old_nbytes or 0
            self._items[key] = stored
            self._entry_bytes[key] = nbytes
            self._current_bytes += nbytes
            self._items.move_to_end(key)
            self._evict_until_fit_unlocked(protect_key=key)
            return True

    def _evict_until_fit_unlocked(self, *, protect_key: tuple[Path, int] | None = None) -> None:
        while self._items and (
            self._current_bytes > self._max_bytes or len(self._items) > self._max_entries
        ):
            # Prefer evicting non-protected (newly inserted) victims.
            victim_key = None
            for candidate in self._items:
                if candidate != protect_key:
                    victim_key = candidate
                    break
            if victim_key is None:
                # Only the protected oversized-or-sole entry remains.
                break
            self._items.pop(victim_key)
            removed = self._entry_bytes.pop(victim_key, 0)
            self._current_bytes -= removed
            self._evictions += 1
        if self._current_bytes < 0:
            self._current_bytes = 0


def _copy_scene_frame(frame: SceneFrame) -> SceneFrame:
    pixels = frame.pixels.copy()
    return SceneFrame(
        path=frame.path,
        frame_number=frame.frame_number,
        pixels=pixels,
        width=frame.width,
        height=frame.height,
        channels=frame.channels,
        pixel_format=frame.pixel_format,
        color_space=frame.color_space,
        color_space_source=frame.color_space_source,
    )
