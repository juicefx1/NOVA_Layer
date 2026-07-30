from __future__ import annotations

import threading
import time
from dataclasses import replace

from nova_layer.object_workflow.ports.operation_executor import (
    OperationExecutorListener,
    OperationProgress,
    OperationSnapshot,
    OperationWork,
    OperationWorkResult,
)


class MockOperationExecutor:
    """Deterministic in-process executor. Uses threads internally; none are exposed."""

    def __init__(self, *, step_delay_seconds: float = 0.0, max_workers: int = 2) -> None:
        self._step_delay_seconds = step_delay_seconds
        self._max_workers = max(1, max_workers)
        self._lock = threading.RLock()
        self._listener: OperationExecutorListener | None = None
        self._snapshots: dict[str, OperationSnapshot] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._worker_slots = threading.Semaphore(self._max_workers)

    def set_listener(self, listener: OperationExecutorListener | None) -> None:
        with self._lock:
            self._listener = listener

    def submit(
        self,
        *,
        operation_id: str,
        operation_type: str,
        work: OperationWork,
    ) -> None:
        with self._lock:
            existing = self._snapshots.get(operation_id)
            if existing is not None and existing.status == "running":
                raise RuntimeError(f"operation already running: {operation_id}")
            cancel_flag = threading.Event()
            self._cancel_flags[operation_id] = cancel_flag
            snapshot = OperationSnapshot(
                operation_id=operation_id,
                operation_type=operation_type,
                status="running",
                progress_current=0,
                progress_total=1,
                message="queued",
            )
            self._snapshots[operation_id] = snapshot
            thread = threading.Thread(
                target=self._run,
                args=(operation_id, operation_type, work, cancel_flag),
                name=f"nova-op-{operation_id[:8]}",
                daemon=True,
            )
            self._threads[operation_id] = thread
            thread.start()

    def cancel(self, operation_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(operation_id)
            snapshot = self._snapshots.get(operation_id)
            if flag is None or snapshot is None or snapshot.status != "running":
                return False
            flag.set()
            return True

    def query(self, operation_id: str) -> OperationSnapshot | None:
        with self._lock:
            snapshot = self._snapshots.get(operation_id)
            return None if snapshot is None else replace(snapshot)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            threads = list(self._threads.values())
            for flag in self._cancel_flags.values():
                flag.set()
        if wait:
            for thread in threads:
                thread.join(timeout=5.0)

    def _run(
        self,
        operation_id: str,
        operation_type: str,
        work: OperationWork,
        cancel_flag: threading.Event,
    ) -> None:
        self._worker_slots.acquire()
        try:
            def should_cancel() -> bool:
                return cancel_flag.is_set()

            def report_progress(current: int, total: int, message: str) -> None:
                if self._step_delay_seconds > 0:
                    time.sleep(self._step_delay_seconds)
                with self._lock:
                    current_snapshot = self._snapshots.get(operation_id)
                    if current_snapshot is None or current_snapshot.status != "running":
                        return
                    updated = replace(
                        current_snapshot,
                        progress_current=current,
                        progress_total=max(total, 1),
                        message=message,
                    )
                    self._snapshots[operation_id] = updated
                    listener = self._listener
                if listener is not None:
                    listener.on_progress(
                        OperationProgress(
                            operation_id=operation_id,
                            current=current,
                            total=max(total, 1),
                            message=message,
                        )
                    )

            try:
                if should_cancel():
                    result = OperationWorkResult(
                        status="cancelled",
                        error_message="cancelled before start",
                    )
                else:
                    result = work.run(
                        should_cancel=should_cancel,
                        report_progress=report_progress,
                    )
                    if should_cancel() and result.status == "succeeded":
                        result = OperationWorkResult(
                            status="cancelled",
                            error_message="cancelled",
                        )
            except Exception as exc:  # noqa: BLE001 - boundary catch for executor
                result = OperationWorkResult(
                    status="failed",
                    error_code="EXECUTOR_FAILED",
                    error_message=str(exc),
                )

            with self._lock:
                previous = self._snapshots.get(operation_id)
                terminal = OperationSnapshot(
                    operation_id=operation_id,
                    operation_type=operation_type,
                    status=result.status,
                    progress_current=previous.progress_current if previous else 0,
                    progress_total=previous.progress_total if previous else 1,
                    message=result.error_message or result.status,
                    error_code=result.error_code,
                    error_message=result.error_message,
                    result_payload=dict(result.payload),
                )
                listener = self._listener
            if listener is not None:
                listener.on_terminal(terminal)
            with self._lock:
                self._snapshots[operation_id] = terminal
                self._cancel_flags.pop(operation_id, None)
                self._threads.pop(operation_id, None)
        finally:
            self._worker_slots.release()
