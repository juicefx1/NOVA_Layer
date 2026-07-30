from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0
    bytes_used: int = 0
    budget_bytes: int = 0


class LruMemoryCache[T]:
    """Thread-safe LRU cache with an approximate memory budget in bytes."""

    def __init__(self, *, budget_bytes: int, name: str = "cache") -> None:
        if budget_bytes < 1:
            raise ValueError("budget_bytes must be >= 1")
        self._name = name
        self._budget = int(budget_bytes)
        self._lock = Lock()
        self._entries: OrderedDict[Hashable, tuple[T, int]] = OrderedDict()
        self._bytes_used = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def budget_bytes(self) -> int:
        return self._budget

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._entries),
                bytes_used=self._bytes_used,
                budget_bytes=self._budget,
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes_used = 0

    def get(self, key: Hashable) -> T | None:
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                self._misses += 1
                return None
            value, size = item
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: Hashable, value: T, *, size_bytes: int) -> None:
        if size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._bytes_used -= existing[1]
            self._entries[key] = (value, size_bytes)
            self._bytes_used += size_bytes
            self._entries.move_to_end(key)
            while self._bytes_used > self._budget and self._entries:
                _evicted_key, (_evicted_value, evicted_size) = self._entries.popitem(last=False)
                self._bytes_used -= evicted_size
                self._evictions += 1

    def get_or_load(
        self,
        key: Hashable,
        loader: Callable[[], tuple[T, int]],
    ) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value, size_bytes = loader()
        self.put(key, value, size_bytes=size_bytes)
        return value

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
