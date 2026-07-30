from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from nova_layer.ports.media import MediaReader


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


class FrameDecodeService(QObject):
    frame_ready = Signal(int, object)
    error_occurred = Signal(str)

    def __init__(
        self,
        reader: MediaReader,
        *,
        cache_size: int = 12,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__()
        if cache_size < 1:
            raise ValueError("cache_size must be positive")
        self._reader = reader
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str, int], NDArray[np.uint8]] = OrderedDict()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._request_id = 0
        self._lock = Lock()
        self._active_workers: set[DecodeWorker] = set()

    @property
    def cache_count(self) -> int:
        return len(self._cache)

    def request(self, path: Path, frame_number: int) -> None:
        resolved = str(path.expanduser().resolve())
        key = (resolved, frame_number)
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is not None:
            self.frame_ready.emit(frame_number, cached.copy())
            return

        worker = DecodeWorker(request_id, Path(resolved), frame_number, self._reader)
        worker.signals.completed.connect(self._completed)
        worker.signals.failed.connect(self._failed)
        self._active_workers.add(worker)
        self._thread_pool.start(worker)

    def get_cached(self, path: Path, frame_number: int) -> NDArray[np.uint8] | None:
        """Return a copy of a cached frame, or None on miss (does not decode)."""
        key = (str(path.expanduser().resolve()), frame_number)
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            self._cache.move_to_end(key)
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
        key = (str(path.expanduser().resolve()), frame_number)
        with self._lock:
            self._cache[key] = np.ascontiguousarray(image).copy()
            self._cache.move_to_end(key)
            if expand_to_fit and len(self._cache) > self._cache_size:
                self._cache_size = len(self._cache)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        """Synchronous decode with cache reuse (Application vertical-slice helper)."""
        cached = self.get_cached(path, frame_number)
        if cached is not None:
            return cached
        resolved = path.expanduser().resolve()
        frame = self._reader.read_frame(resolved, frame_number)
        self.put_cached(resolved, frame_number, frame)
        return frame.copy()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._request_id += 1

    def _completed(
        self,
        request_id: int,
        path: str,
        frame_number: int,
        frame: NDArray[np.uint8],
    ) -> None:
        key = (path, frame_number)
        with self._lock:
            self._cache[key] = frame.copy()
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            is_latest = request_id == self._request_id
        self._discard_finished_worker(request_id)
        if is_latest:
            self.frame_ready.emit(frame_number, frame)

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
