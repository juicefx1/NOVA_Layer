from __future__ import annotations

from pathlib import Path
from threading import Lock

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from nova_layer.adapters.color.display_transform import (
    DisplayTransformProtocol,
    LegacyDisplayTransform,
)
from nova_layer.app.preview_pipeline import DEFAULT_PREVIEW_CACHE_SIZE, PreviewPipeline
from nova_layer.app.raw_frame_cache import DEFAULT_RAW_FRAME_CACHE_SIZE
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
        pipeline: PreviewPipeline,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.frame_number = frame_number
        self.pipeline = pipeline
        self.signals = DecodeWorkerSignals()

    def run(self) -> None:
        try:
            frame = self.pipeline.read_frame(self.path, self.frame_number)
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
    """Warm upcoming preview frames (and EXR raw via the pipeline) without emitting."""

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
        # Prefer raw EXR warm first so exposure scrub reuses OIIO results.
        service._pipeline.prefetch_raw(
            self._path,
            self._anchor_frame,
            self._count,
            is_current=lambda: service._prefetch_generation_active(self._generation),
        )
        for offset in range(1, self._count + 1):
            if not service._prefetch_generation_active(self._generation):
                return
            frame_number = self._anchor_frame + offset
            with service._lock:
                if not service._prefetch_generation_active_unlocked(self._generation):
                    return
                if service._pipeline.get_preview(self._path, frame_number) is not None:
                    continue
                pipeline = service._pipeline
            try:
                frame = pipeline.read_frame(self._path, frame_number)
            except Exception:
                continue
            with service._lock:
                if not service._prefetch_generation_active_unlocked(self._generation):
                    return
                # read_frame already cached preview under current transform identity
                del frame


class FrameDecodeService(QObject):
    frame_ready = Signal(int, object)
    error_occurred = Signal(str)

    def __init__(
        self,
        reader: MediaReader,
        *,
        display_transform: DisplayTransformProtocol | None = None,
        cache_size: int = DEFAULT_PREVIEW_CACHE_SIZE,
        raw_cache_size: int = DEFAULT_RAW_FRAME_CACHE_SIZE,
        prefetch_count: int = _DEFAULT_PREFETCH_COUNT,
        thread_pool: QThreadPool | None = None,
        pipeline: PreviewPipeline | None = None,
    ) -> None:
        super().__init__()
        if prefetch_count < 0:
            raise ValueError("prefetch_count must be non-negative")
        transform = display_transform
        if transform is None:
            transform = getattr(reader, "display_transform", None)
        if transform is None:
            transform = LegacyDisplayTransform()
        self._pipeline = pipeline or PreviewPipeline(
            reader,
            transform,
            raw_cache_size=raw_cache_size,
            preview_cache_size=cache_size,
        )
        self._prefetch_count = prefetch_count
        self._prefetch_generation = 0
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._request_id = 0
        self._lock = Lock()
        self._active_workers: set[DecodeWorker] = set()

    @property
    def cache_count(self) -> int:
        return self._pipeline.preview_cache_count

    @property
    def pipeline(self) -> PreviewPipeline:
        return self._pipeline

    @property
    def reader(self) -> MediaReader:
        return self._pipeline.reader

    @reader.setter
    def reader(self, reader: MediaReader) -> None:
        """Replace the MediaReader and drop caches for the previous source."""
        with self._lock:
            self._pipeline.set_reader(reader, keep_raw_cache=False)
            self._request_id += 1
            self._prefetch_generation += 1

    def set_display_transform(self, transform: DisplayTransformProtocol | None) -> None:
        """Update color transform; keep EXR raw cache, clear preview cache."""
        with self._lock:
            self._pipeline.set_display_transform(transform)
            self._request_id += 1
            self._prefetch_generation += 1

    def request(self, path: Path, frame_number: int) -> None:
        resolved = path.expanduser().resolve()
        with self._lock:
            self._prefetch_generation += 1
            self._request_id += 1
            request_id = self._request_id
            cached = self._pipeline.get_preview(resolved, frame_number)
        if cached is not None:
            self.frame_ready.emit(frame_number, cached)
            self._schedule_prefetch(resolved, frame_number)
            return

        worker = DecodeWorker(request_id, resolved, frame_number, self._pipeline)
        worker.signals.completed.connect(self._completed)
        worker.signals.failed.connect(self._failed)
        self._active_workers.add(worker)
        self._thread_pool.start(worker)

    def get_cached(self, path: Path, frame_number: int) -> NDArray[np.uint8] | None:
        """Return a copy of a cached preview frame, or None on miss (does not decode)."""
        return self._pipeline.get_preview(path, frame_number)

    def put_cached(
        self,
        path: Path,
        frame_number: int,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
    ) -> None:
        """Warm the preview cache (used by Application range-decode jobs)."""
        self._pipeline.put_preview(
            path,
            frame_number,
            image,
            expand_to_fit=expand_to_fit,
        )

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        """Synchronous decode with preview (+ EXR raw) cache reuse."""
        resolved = path.expanduser().resolve()
        with self._lock:
            self._prefetch_generation += 1
        decoded = self._pipeline.read_frame(resolved, frame_number)
        self._schedule_prefetch(resolved, frame_number)
        return decoded

    def clear(self) -> None:
        with self._lock:
            self._pipeline.clear_all()
            self._request_id += 1
            self._prefetch_generation += 1

    def clear_preview_cache(self) -> None:
        with self._lock:
            self._pipeline.clear_preview_cache()
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
        with self._lock:
            is_latest = request_id == self._request_id
        self._discard_finished_worker(request_id)
        if is_latest:
            self.frame_ready.emit(frame_number, frame)
            self._schedule_prefetch(Path(path), frame_number)

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
