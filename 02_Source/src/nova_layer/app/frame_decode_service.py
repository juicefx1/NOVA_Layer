from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from nova_layer.ports.media import MediaReader

_DEFAULT_PREFETCH_COUNT = 4


class DecodeWorkerSignals(QObject):
    completed = Signal(int, str, int, object)
    failed = Signal(int, str)


class DecodeWorker(QRunnable):
    def __init__(
        self,
        request_id: int,
        path: Path,
        frame_number: int,
        reader: MediaReader,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.frame_number = frame_number
        self.reader = reader
        self.signals = DecodeWorkerSignals()

    def run(self) -> None:
        try:
            frame = self.reader.read_frame(self.path, self.frame_number)
        except Exception as exc:
            self.signals.failed.emit(self.request_id, str(exc))
            return
        self.signals.completed.emit(
            self.request_id,
            str(self.path),
            self.frame_number,
            frame,
        )


class PrefetchWorker(QRunnable):
    """Warm upcoming frames into the LRU cache without emitting frame_ready."""

    def __init__(
        self,
        service: FrameDecodeService,
        path: Path,
        anchor_frame: int,
        generation: int,
        count: int,
    ) -> None:
        super().__init__()
        self._service = service
        self._path = path
        self._anchor_frame = anchor_frame
        self._generation = generation
        self._count = count

    def run(self) -> None:
        service = self._service
        for offset in range(1, self._count + 1):
            if not service._prefetch_generation_active(self._generation):
                return
            frame_number = self._anchor_frame + offset
            key = _cache_key(self._path, frame_number)
            with service._lock:
                if not service._prefetch_generation_active_unlocked(self._generation):
                    return
                if service._cache.contains(key):
                    continue
                reader = service._reader
            try:
                frame = reader.read_frame(key[0], frame_number)
            except Exception:
                continue
            with service._lock:
                if not service._prefetch_generation_active_unlocked(self._generation):
                    return
                service._cache.put(key, frame)


class FrameCache:
    """Thread-unsafe LRU store; callers must serialize access with an external Lock."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("cache_size must be positive")
        self._capacity = capacity
        self._items: OrderedDict[tuple[Path, int], NDArray[np.uint8]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity

    def clear(self) -> None:
        self._items.clear()

    def contains(self, key: tuple[Path, int]) -> bool:
        return key in self._items

    def get(self, key: tuple[Path, int]) -> NDArray[np.uint8] | None:
        cached = self._items.get(key)
        if cached is None:
            return None
        self._items.move_to_end(key)
        return cached

    def put(
        self,
        key: tuple[Path, int],
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
    ) -> None:
        self._items[key] = np.ascontiguousarray(image).copy()
        self._items.move_to_end(key)
        if expand_to_fit and len(self._items) > self._capacity:
            self._capacity = len(self._items)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)


def _cache_key(path: Path, frame_number: int) -> tuple[Path, int]:
    return (path.expanduser().resolve(), frame_number)


class FrameDecodeService(QObject):
    frame_ready = Signal(int, object)
    error_occurred = Signal(str)

    def __init__(
        self,
        reader: MediaReader,
        *,
        cache_size: int = 32,
        prefetch_count: int = _DEFAULT_PREFETCH_COUNT,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__()
        if prefetch_count < 0:
            raise ValueError("prefetch_count must be non-negative")
        self._reader = reader
        self._cache = FrameCache(cache_size)
        self._prefetch_count = prefetch_count
        self._prefetch_generation = 0
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._request_id = 0
        self._lock = Lock()
        self._active_workers: set[DecodeWorker] = set()

    @property
    def cache_count(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def reader(self) -> MediaReader:
        return self._reader

    @reader.setter
    def reader(self, reader: MediaReader) -> None:
        """Replace the MediaReader and drop cached frames for the previous source."""
        with self._lock:
            self._reader = reader
            self._cache.clear()
            self._request_id += 1
            self._prefetch_generation += 1

    def request(self, path: Path, frame_number: int) -> None:
        key = _cache_key(path, frame_number)
        with self._lock:
            self._prefetch_generation += 1
            self._request_id += 1
            request_id = self._request_id
            cached = self._cache.get(key)
            if cached is not None:
                frame = cached.copy()
            else:
                frame = None
        if frame is not None:
            self.frame_ready.emit(frame_number, frame)
            self._schedule_prefetch(key[0], frame_number)
            return

        worker = DecodeWorker(request_id, key[0], frame_number, self._reader)
        worker.signals.completed.connect(self._completed)
        worker.signals.failed.connect(self._failed)
        self._active_workers.add(worker)
        self._thread_pool.start(worker)

    def get_cached(self, path: Path, frame_number: int) -> NDArray[np.uint8] | None:
        """Return a copy of a cached frame, or None on miss (does not decode)."""
        key = _cache_key(path, frame_number)
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            return cached.copy()

    def put_cached(
        self,
        path: Path,
        frame_number: int,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
    ) -> None:
        """Warm the decode cache (used by Application range-decode jobs)."""
        key = _cache_key(path, frame_number)
        with self._lock:
            self._cache.put(key, image, expand_to_fit=expand_to_fit)

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        """Synchronous decode with LRU cache reuse."""
        key = _cache_key(path, frame_number)
        with self._lock:
            self._prefetch_generation += 1
            cached = self._cache.get(key)
            if cached is not None:
                frame = cached.copy()
            else:
                frame = None
        if frame is not None:
            self._schedule_prefetch(key[0], frame_number)
            return frame
        decoded = self._reader.read_frame(key[0], frame_number)
        with self._lock:
            self._cache.put(key, decoded)
        self._schedule_prefetch(key[0], frame_number)
        return decoded.copy()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._request_id += 1
            self._prefetch_generation += 1

    def _prefetch_generation_active(self, generation: int) -> bool:
        with self._lock:
            return self._prefetch_generation_active_unlocked(generation)

    def _prefetch_generation_active_unlocked(self, generation: int) -> bool:
        return generation == self._prefetch_generation

    def _schedule_prefetch(self, path: Path, frame_number: int) -> None:
        with self._lock:
            if self._prefetch_count < 1:
                return
            self._prefetch_generation += 1
            generation = self._prefetch_generation
            count = self._prefetch_count
        worker = PrefetchWorker(self, path, frame_number, generation, count)
        self._thread_pool.start(worker)

    def _completed(
        self,
        request_id: int,
        path: str,
        frame_number: int,
        frame: NDArray[np.uint8],
    ) -> None:
        key = _cache_key(Path(path), frame_number)
        with self._lock:
            self._cache.put(key, frame)
            is_latest = request_id == self._request_id
        self._discard_finished_worker(request_id)
        if is_latest:
            self.frame_ready.emit(frame_number, frame)
            self._schedule_prefetch(key[0], frame_number)

    def _failed(self, request_id: int, message: str) -> None:
        with self._lock:
            is_latest = request_id == self._request_id
        self._discard_finished_worker(request_id)
        if is_latest:
            self.error_occurred.emit(message)

    def _discard_finished_worker(self, request_id: int) -> None:
        finished = next(
            (worker for worker in self._active_workers if worker.request_id == request_id),
            None,
        )
        if finished is not None:
            self._active_workers.discard(finished)
