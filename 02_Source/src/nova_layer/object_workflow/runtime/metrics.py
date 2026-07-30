from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class TimingSample:
    name: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class PerformanceMonitor:
    """Runtime-only timing and counter store. Never persisted."""

    def __init__(self, *, max_samples: int = 256) -> None:
        self._lock = Lock()
        self._samples: list[TimingSample] = []
        self._counters: dict[str, int] = {}
        self._max_samples = max(1, int(max_samples))

    def record_timing(
        self,
        name: str,
        duration_ms: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        sample = TimingSample(
            name=name,
            duration_ms=float(duration_ms),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._samples.append(sample)
            if len(self._samples) > self._max_samples:
                overflow = len(self._samples) - self._max_samples
                del self._samples[:overflow]

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def counter(self, name: str) -> int:
        with self._lock:
            return int(self._counters.get(name, 0))

    def samples(self, name: str | None = None) -> list[TimingSample]:
        with self._lock:
            if name is None:
                return list(self._samples)
            return [item for item in self._samples if item.name == name]

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._counters.clear()

    def measure(self, name: str, **metadata: Any) -> _TimingContext:
        return _TimingContext(self, name, metadata)


class _TimingContext:
    def __init__(
        self,
        monitor: PerformanceMonitor,
        name: str,
        metadata: dict[str, Any],
    ) -> None:
        self._monitor = monitor
        self._name = name
        self._metadata = metadata
        self._started = 0.0

    def __enter__(self) -> _TimingContext:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        elapsed_ms = (time.perf_counter() - self._started) * 1000.0
        self._monitor.record_timing(self._name, elapsed_ms, metadata=self._metadata)


class InFlightDeduper:
    """Reuse identical in-flight work for concurrent callers."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._futures: dict[Hashable, Future[Any]] = {}

    def run(self, key: Hashable, worker: Callable[[], T]) -> T:
        with self._lock:
            existing = self._futures.get(key)
            if existing is not None:
                future = existing
                owner = False
            else:
                future = Future()
                self._futures[key] = future
                owner = True
        if not owner:
            return future.result()  # type: ignore[no-any-return]
        try:
            result = worker()
        except BaseException as exc:
            future.set_exception(exc)
            with self._lock:
                self._futures.pop(key, None)
            raise
        future.set_result(result)
        with self._lock:
            self._futures.pop(key, None)
        return result

    def clear(self) -> None:
        with self._lock:
            self._futures.clear()
