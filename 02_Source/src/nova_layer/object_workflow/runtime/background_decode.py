from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import TypeVar

from nova_layer.object_workflow.runtime.metrics import InFlightDeduper

T = TypeVar("T")


class BackgroundDecodeService:
    """Decode heavy assets off the caller thread when a pool is available.

    Callers that need a synchronous result may still use ``run_sync`` which
    deduplicates concurrent identical work.
    """

    def __init__(self, *, max_workers: int = 2) -> None:
        workers = max(1, int(max_workers))
        self._pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="nova-decode",
        )
        self._lock = Lock()
        self._closed = False
        self._deduper = InFlightDeduper()

    def run_sync(self, key: object, worker: Callable[[], T]) -> T:
        return self._deduper.run(key, worker)

    def submit(self, key: object, worker: Callable[[], T]) -> Future[T]:
        with self._lock:
            if self._closed:
                future: Future[T] = Future()
                try:
                    future.set_result(worker())
                except BaseException as exc:
                    future.set_exception(exc)
                return future
            return self._pool.submit(self._deduper.run, key, worker)

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=wait, cancel_futures=True)
        self._deduper.clear()
