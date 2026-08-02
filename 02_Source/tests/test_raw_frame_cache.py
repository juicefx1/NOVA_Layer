from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from nova_layer.app.raw_frame_cache import RawFrameCache
from nova_layer.ports.scene_frames import SceneFrame


def _frame(
    path: Path,
    number: int,
    *,
    value: float = 0.5,
    shape: tuple[int, int, int] = (2, 2, 3),
) -> SceneFrame:
    pixels = np.full(shape, value, dtype=np.float32)
    return SceneFrame(
        path=path,
        frame_number=number,
        pixels=pixels,
        width=shape[1],
        height=shape[0],
    )


def test_same_frame_put_get_returns_copy(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=4)
    path = tmp_path / "seq"
    path.mkdir()
    original = _frame(path, 0, value=0.25)
    assert cache.put(original) is True
    original.pixels[0, 0, 0] = 9.0

    got = cache.get(path, 0)
    assert got is not None
    assert float(got.pixels[0, 0, 0]) == 0.25
    got.pixels[0, 0, 0] = 3.0
    again = cache.get(path, 0)
    assert again is not None
    assert float(again.pixels[0, 0, 0]) == 0.25


def test_lru_eviction_by_entries(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=2, max_bytes=10_000_000)
    path = tmp_path / "seq"
    path.mkdir()
    for index in range(3):
        assert cache.put(_frame(path, index, value=float(index))) is True
    assert cache.count == 2
    assert cache.get(path, 0) is None
    assert cache.get(path, 1) is not None
    assert cache.get(path, 2) is not None


def test_byte_accounting_and_replacement(tmp_path: Path) -> None:
    cache = RawFrameCache(max_entries=4, max_bytes=10_000_000)
    path = tmp_path / "seq"
    path.mkdir()
    small = _frame(path, 0, shape=(10, 10, 3))
    assert cache.put(small) is True
    nbytes = small.pixels.nbytes
    assert cache.current_bytes == nbytes
    big = _frame(path, 0, shape=(20, 20, 3))
    assert cache.put(big) is True
    assert cache.count == 1
    assert cache.current_bytes == big.pixels.nbytes


def test_lru_eviction_by_bytes(tmp_path: Path) -> None:
    frame_bytes = 2 * 2 * 3 * 4  # 48
    cache = RawFrameCache(max_entries=10, max_bytes=frame_bytes * 2)
    path = tmp_path / "seq"
    path.mkdir()
    for index in range(3):
        assert cache.put(_frame(path, index)) is True
    assert cache.count == 2
    assert cache.current_bytes == frame_bytes * 2
    assert cache.stats().evictions >= 1


def test_oversized_foreground_admission(tmp_path: Path) -> None:
    cache = RawFrameCache(max_entries=4, max_bytes=100)
    path = tmp_path / "seq"
    path.mkdir()
    assert cache.put(_frame(path, 0)) is True
    huge = _frame(path, 1, shape=(20, 20, 3))  # 4800 bytes > 100
    assert cache.put(huge, allow_eviction=True) is True
    assert cache.count == 1
    assert cache.current_bytes == huge.pixels.nbytes
    assert cache.current_bytes > cache.max_bytes
    assert cache.stats().oversized_admissions == 1
    assert cache.get(path, 0) is None
    assert cache.get(path, 1) is not None


def test_second_oversized_replaces_first(tmp_path: Path) -> None:
    cache = RawFrameCache(max_entries=4, max_bytes=100)
    path = tmp_path / "seq"
    path.mkdir()
    first = _frame(path, 0, shape=(20, 20, 3))
    second = _frame(path, 1, shape=(30, 30, 3))
    assert cache.put(first) is True
    assert cache.put(second) is True
    assert cache.count == 1
    assert cache.get(path, 0) is None
    assert cache.get(path, 1) is not None
    assert cache.stats().oversized_admissions == 2


def test_oversized_prefetch_rejected(tmp_path: Path) -> None:
    cache = RawFrameCache(max_entries=4, max_bytes=100)
    path = tmp_path / "seq"
    path.mkdir()
    keep = _frame(path, 0)
    assert cache.put(keep) is True
    huge = _frame(path, 1, shape=(20, 20, 3))
    assert cache.put(huge, allow_eviction=False) is False
    assert cache.count == 1
    assert cache.get(path, 0) is not None
    assert cache.stats().oversized_rejections == 1


def test_prefetch_no_evict_skips_when_full(tmp_path: Path) -> None:
    frame_bytes = 2 * 2 * 3 * 4
    cache = RawFrameCache(max_entries=2, max_bytes=frame_bytes * 2)
    path = tmp_path / "seq"
    path.mkdir()
    assert cache.put(_frame(path, 0)) is True
    assert cache.put(_frame(path, 1)) is True
    assert cache.put(_frame(path, 2), allow_eviction=False) is False
    assert cache.count == 2
    assert cache.get(path, 0) is not None


def test_clear_zeros_bytes(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=2)
    path = tmp_path / "seq"
    path.mkdir()
    cache.put(_frame(path, 0))
    cache.clear()
    assert cache.count == 0
    assert cache.current_bytes == 0
    assert cache.get(path, 0) is None


def test_hit_miss_stats(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=2)
    path = tmp_path / "seq"
    path.mkdir()
    cache.put(_frame(path, 0))
    assert cache.get(path, 0) is not None
    assert cache.get(path, 9) is None
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1


def test_thread_safe_smoke(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=8)
    path = tmp_path / "seq"
    path.mkdir()

    def worker(index: int) -> None:
        cache.put(_frame(path, index % 4, value=float(index)))
        cache.get(path, index % 4)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(40)))
    assert cache.count <= 8
