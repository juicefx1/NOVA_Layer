from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

ResultT = TypeVar("ResultT")
ProgressCallback = Callable[[int, int, str], None]
JobOperation = Callable[[Event, ProgressCallback], ResultT]


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
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._worker: JobWorker[object] | None = None
        self._cancel_event: Event | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    def start(self, name: str, operation: JobOperation[object]) -> bool:
        if self.is_running:
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

    def _completed(self, result: JobResult[object]) -> None:
        self._clear_active()
        self.completed.emit(result)

    def _cancelled(self, name: str) -> None:
        self._clear_active()
        self.cancelled.emit(name)

    def _failed(self, name: str, message: str) -> None:
        self._clear_active()
        self.failed.emit(name, message)

    def _clear_active(self) -> None:
        self._worker = None
        self._cancel_event = None
