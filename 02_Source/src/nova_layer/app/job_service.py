from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import TypeVar

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal

ResultT = TypeVar("ResultT")
ProgressCallback = Callable[[int, int, str], None]
JobOperation = Callable[[Event, ProgressCallback], ResultT]

logger = logging.getLogger(__name__)

DEFAULT_SHUTDOWN_TIMEOUT_MS = 5000


@dataclass(frozen=True, slots=True)
class JobResult[ResultT]:
    name: str
    value: ResultT


class JobWorkerSignals(QObject):
    progress = Signal(str, int, int, str)
    completed = Signal(object)
    cancelled = Signal(str)
    failed = Signal(str, str)


class JobWorker[ResultT](QRunnable):
    def __init__(self, name: str, operation: JobOperation[ResultT], cancel_event: Event) -> None:
        super().__init__()
        self.name = name
        self.operation = operation
        self.cancel_event = cancel_event
        self.signals = JobWorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        def report(current: int, total: int, message: str) -> None:
            self.signals.progress.emit(self.name, current, total, message)

        try:
            value = self.operation(self.cancel_event, report)
        except Exception as exc:
            self.signals.failed.emit(self.name, str(exc))
            return
        if self.cancel_event.is_set():
            self.signals.cancelled.emit(self.name)
            return
        self.signals.completed.emit(JobResult(self.name, value))


class ProcessingJobService(QObject):
    started = Signal(str)
    progress = Signal(str, int, int, str)
    completed = Signal(object)
    cancelled = Signal(str)
    failed = Signal(str, str)

    def __init__(self, thread_pool: QThreadPool | None = None) -> None:
        super().__init__()
        # Prefer a dedicated pool so shutdown waitForDone() does not block on
        # unrelated globalInstance work.
        self._owns_pool = thread_pool is None
        self._thread_pool = thread_pool or QThreadPool()
        if self._owns_pool:
            self._thread_pool.setMaxThreadCount(1)
            self._thread_pool.setObjectName("novaProcessingJobPool")
        self._worker: JobWorker[object] | None = None
        self._cancel_event: Event | None = None
        self._shutting_down = False

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def thread_pool(self) -> QThreadPool:
        return self._thread_pool

    def start(self, name: str, operation: JobOperation[object]) -> bool:
        if self._shutting_down or self.is_running:
            return False
        cancel_event = Event()
        worker = JobWorker(name, operation, cancel_event)
        worker.signals.progress.connect(self.progress)
        worker.signals.completed.connect(self._completed)
        worker.signals.cancelled.connect(self._cancelled)
        worker.signals.failed.connect(self._failed)
        self._worker = worker
        self._cancel_event = cancel_event
        self.started.emit(name)
        self._thread_pool.start(worker)
        return True

    def cancel(self) -> bool:
        if self._cancel_event is None:
            return False
        self._cancel_event.set()
        return True

    def shutdown(self, *, timeout_ms: int = DEFAULT_SHUTDOWN_TIMEOUT_MS) -> bool:
        """Cancel any active job and wait up to ``timeout_ms`` for the pool to drain.

        Returns True when no job remains active after the wait (including when none
        was running). Returns False on timeout without forcing a kill.
        """
        self._shutting_down = True
        if not self.is_running:
            return True
        self.cancel()
        finished = self._thread_pool.waitForDone(max(0, int(timeout_ms)))
        # Worker completion signals are queued to this thread — flush them so
        # _clear_active runs before we return to closeEvent callers.
        QCoreApplication.processEvents()
        if finished:
            self._clear_active()
            return True
        logger.warning(
            "ProcessingJobService shutdown timed out after %sms (job still active).",
            timeout_ms,
        )
        return not self.is_running and self._thread_pool.activeThreadCount() == 0

    def _completed(self, result: JobResult[object]) -> None:
        if self._worker is None and not self._shutting_down:
            return
        self._clear_active()
        if not self._shutting_down:
            self.completed.emit(result)

    def _cancelled(self, name: str) -> None:
        if self._worker is None and not self._shutting_down:
            return
        self._clear_active()
        self.cancelled.emit(name)

    def _failed(self, name: str, message: str) -> None:
        if self._worker is None and not self._shutting_down:
            return
        self._clear_active()
        if not self._shutting_down:
            self.failed.emit(name, message)

    def _clear_active(self) -> None:
        self._worker = None
        self._cancel_event = None
