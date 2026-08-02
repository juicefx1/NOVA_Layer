from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

from nova_layer.ports.scene_frames import SceneFrame

# Default capacity keeps ~8×1080p float32 RGB (~190 MB) or ~8×4K (~760 MB).
DEFAULT_RAW_FRAME_CACHE_SIZE = 8


def _cache_key(path: Path, frame_number: int) -> tuple[Path, int]:
    return (path.expanduser().resolve(), frame_number)


class RawFrameCache:
    """Thread-safe LRU cache for EXR scene-linear float frames.

    Stored pixels are copied on put. ``get`` returns a ``SceneFrame`` whose
    ``pixels`` array is also a copy so callers cannot mutate cache contents.
    """

    def __init__(self, capacity: int = DEFAULT_RAW_FRAME_CACHE_SIZE) -> None:
        if capacity < 1:
            raise ValueError("raw_cache_size must be positive")
        self._capacity = capacity
        self._items: OrderedDict[tuple[Path, int], SceneFrame] = OrderedDict()
        self._lock = Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def count(self) -> int:
        return len(self)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def contains(self, path: Path, frame_number: int) -> bool:
        key = _cache_key(path, frame_number)
        with self._lock:
            return key in self._items

    def get(self, path: Path, frame_number: int) -> SceneFrame | None:
        key = _cache_key(path, frame_number)
        with self._lock:
            frame = self._items.get(key)
            if frame is None:
                return None
            self._items.move_to_end(key)
            return _copy_scene_frame(frame)

    def put(self, frame: SceneFrame) -> None:
        key = _cache_key(frame.path, frame.frame_number)
        stored = _copy_scene_frame(frame)
        with self._lock:
            self._items[key] = stored
            self._items.move_to_end(key)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)


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
    )
