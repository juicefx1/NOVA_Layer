from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from nova_layer.app.raw_frame_cache import RawFrameCache
from nova_layer.ports.scene_frames import SceneFrame


def _frame(path: Path, number: int, value: float = 0.5) -> SceneFrame:
    pixels = np.full((2, 2, 3), value, dtype=np.float32)
    return SceneFrame(
        path=path,
        frame_number=number,
        pixels=pixels,
        width=2,
        height=2,
    )


def test_same_frame_put_get_returns_copy(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=4)
    path = tmp_path / "seq"
    path.mkdir()
    original = _frame(path, 0, 0.25)
    cache.put(original)
    original.pixels[0, 0, 0] = 9.0

    got = cache.get(path, 0)
    assert got is not None
    assert float(got.pixels[0, 0, 0]) == 0.25
    got.pixels[0, 0, 0] = 3.0
    again = cache.get(path, 0)
    assert again is not None
    assert float(again.pixels[0, 0, 0]) == 0.25


def test_lru_eviction(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=2)
    path = tmp_path / "seq"
    path.mkdir()
    for index in range(3):
        cache.put(_frame(path, index, float(index)))
    assert cache.count == 2
    assert cache.get(path, 0) is None
    assert cache.get(path, 1) is not None
    assert cache.get(path, 2) is not None


def test_clear(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=2)
    path = tmp_path / "seq"
    path.mkdir()
    cache.put(_frame(path, 0))
    cache.clear()
    assert cache.count == 0
    assert cache.get(path, 0) is None


def test_thread_safe_smoke(tmp_path: Path) -> None:
    cache = RawFrameCache(capacity=8)
    path = tmp_path / "seq"
    path.mkdir()

    def worker(index: int) -> None:
        cache.put(_frame(path, index % 4, float(index)))
        cache.get(path, index % 4)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(40)))
    assert cache.count <= 8
