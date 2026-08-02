"""Working-space float frame cache (Phase 10C-1 skeleton).

Not wired into PreviewPipeline yet — unit tests only.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

from nova_layer.app.frame_cache_stats import FrameCacheStats, bytes_from_env_mb
from nova_layer.app.working_space import WorkingTransformIdentity
from nova_layer.ports.scene_frames import WorkingSceneFrame

DEFAULT_WORKING_SCENE_CACHE_SIZE = 4
DEFAULT_WORKING_CACHE_MAX_BYTES = 256 * 1024 * 1024

WorkingCacheKey = tuple[Path, int, WorkingTransformIdentity]


def _cache_key(
    path: Path,
    frame_number: int,
    identity: WorkingTransformIdentity,
) -> WorkingCacheKey:
    return (path.expanduser().resolve(), int(frame_number), identity)


def _default_working_max_bytes() -> int:
    return bytes_from_env_mb("NOVA_WORKING_CACHE_MB", DEFAULT_WORKING_CACHE_MAX_BYTES)


def _identity_from_frame(frame: WorkingSceneFrame) -> WorkingTransformIdentity:
    identity = WorkingTransformIdentity.try_create(
        source_color_space=frame.source_color_space,
        working_color_space=frame.working_color_space,
        ocio_config_identity=frame.ocio_config_identity,
        converter_version=frame.converter_version,
    )
    if identity is None:
        raise ValueError(
            "WorkingSceneFrame is missing required identity fields for cache key"
        )
    return identity


def _copy_working_scene_frame(frame: WorkingSceneFrame) -> WorkingSceneFrame:
    return WorkingSceneFrame(
        path=frame.path,
        frame_number=frame.frame_number,
        pixels=frame.pixels.copy(),
        width=frame.width,
        height=frame.height,
        channels=frame.channels,
        pixel_format=frame.pixel_format,
        source_color_space=frame.source_color_space,
        working_color_space=frame.working_color_space,
        ocio_config_identity=frame.ocio_config_identity,
        converter_version=frame.converter_version,
    )


class WorkingSceneCache:
    """Thread-safe LRU for WorkingSceneFrame with byte budget + entry cap.

    Accounting uses ``WorkingSceneFrame.pixels.nbytes`` only.
    """

    def __init__(
        self,
        capacity: int | None = None,
        *,
        max_bytes: int | None = None,
        max_entries: int | None = None,
    ) -> None:
        if capacity is not None and max_entries is None:
            max_entries = capacity
        if max_entries is None:
            max_entries = DEFAULT_WORKING_SCENE_CACHE_SIZE
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes is None:
            max_bytes = _default_working_max_bytes()
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        self._max_bytes = int(max_bytes)
        self._max_entries = int(max_entries)
        self._items: OrderedDict[WorkingCacheKey, WorkingSceneFrame] = OrderedDict()
        self._entry_bytes: dict[WorkingCacheKey, int] = {}
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

    def contains(
        self,
        path: Path,
        frame_number: int,
        identity: WorkingTransformIdentity,
    ) -> bool:
        key = _cache_key(path, frame_number, identity)
        with self._lock:
            return key in self._items

    def get(
        self,
        path: Path,
        frame_number: int,
        identity: WorkingTransformIdentity,
    ) -> WorkingSceneFrame | None:
        key = _cache_key(path, frame_number, identity)
        with self._lock:
            frame = self._items.get(key)
            if frame is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return _copy_working_scene_frame(frame)

    def put(self, frame: WorkingSceneFrame, *, allow_eviction: bool = True) -> bool:
        """Store a working scene frame. Returns False when skipped."""
        identity = _identity_from_frame(frame)
        key = _cache_key(frame.path, frame.frame_number, identity)
        stored = _copy_working_scene_frame(frame)
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

            if replacing:
                self._current_bytes -= old_nbytes or 0
            self._items[key] = stored
            self._entry_bytes[key] = nbytes
            self._current_bytes += nbytes
            self._items.move_to_end(key)
            self._evict_until_fit_unlocked(protect_key=key)
            return True

    def _evict_until_fit_unlocked(
        self,
        *,
        protect_key: WorkingCacheKey | None = None,
    ) -> None:
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
