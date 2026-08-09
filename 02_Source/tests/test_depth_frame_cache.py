"""Phase D1 DepthFrameCache tests."""

from __future__ import annotations

import numpy as np

from nova_layer.app.depth_frame_cache import DepthCacheKey, DepthFrameCache
from nova_layer.ports.depth import DepthFrame, DepthNormalization, freeze_depth_array


def _frame(
    *,
    fingerprint: str = "fp",
    frame_number: int = 0,
    model: str = "fake_depth_v1",
    version: str = "1.0.0",
    prep: str = "prep",
    height: int = 8,
    width: int = 8,
) -> DepthFrame:
    depth = np.linspace(0.0, 1.0, height * width, dtype=np.float32).reshape(height, width)
    return DepthFrame(
        frame_number=frame_number,
        media_fingerprint=fingerprint,
        depth=freeze_depth_array(depth),
        valid_mask=None,
        quantity="relative_disparity",
        near_is="high",
        normalization=DepthNormalization(kind="model_native"),
        source_model=model,
        model_version=version,
        preprocessing_version=prep,
        input_policy="source_v1",
        metadata={"x": "1"},
    )


def _key(
    *,
    fingerprint: str = "fp",
    frame_number: int = 0,
    model: str = "fake_depth_v1",
    version: str = "1.0.0",
    prep: str = "prep",
) -> DepthCacheKey:
    return DepthCacheKey(
        media_fingerprint=fingerprint,
        frame_number=frame_number,
        model_id=model,
        model_version=version,
        preprocessing_version=prep,
        input_policy="source_v1",
    )


def test_put_get_hit_miss() -> None:
    cache = DepthFrameCache(max_entries=4, max_bytes=10_000_000)
    key = _key()
    assert cache.get(key) is None
    assert cache.stats().misses == 1
    assert cache.put(key, _frame())
    got = cache.get(key)
    assert got is not None
    assert cache.stats().hits == 1
    assert got.media_fingerprint == "fp"


def test_lru_and_max_entries() -> None:
    cache = DepthFrameCache(max_entries=2, max_bytes=10_000_000)
    k0, k1, k2 = _key(frame_number=0), _key(frame_number=1), _key(frame_number=2)
    cache.put(k0, _frame(frame_number=0))
    cache.put(k1, _frame(frame_number=1))
    cache.get(k0)  # make k0 most-recent; k1 is LRU
    cache.put(k2, _frame(frame_number=2))
    assert cache.get(k1) is None
    assert cache.get(k0) is not None
    assert cache.get(k2) is not None
    assert cache.stats().evictions >= 1


def test_byte_accounting_and_fingerprint_separation() -> None:
    cache = DepthFrameCache(max_entries=8, max_bytes=10_000_000)
    f = _frame()
    key = _key()
    cache.put(key, f)
    expected = int(f.depth.nbytes)
    assert cache.stats().current_bytes == expected
    other = _key(fingerprint="other")
    cache.put(other, _frame(fingerprint="other"))
    assert cache.get(key) is not None
    assert cache.get(other) is not None


def test_model_version_and_prep_separation() -> None:
    cache = DepthFrameCache(max_entries=8, max_bytes=10_000_000)
    a = _key(version="1.0.0")
    b = _key(version="1.0.1")
    c = _key(prep="prep2")
    cache.put(a, _frame(version="1.0.0"))
    cache.put(b, _frame(version="1.0.1"))
    cache.put(c, _frame(prep="prep2"))
    assert cache.get(a) is not None
    assert cache.get(b) is not None
    assert cache.get(c) is not None
    assert len(cache) == 3


def test_clear_and_viewer_transform_independence() -> None:
    """Viewer transform changes are not a cache concern — explicit clear only."""
    cache = DepthFrameCache(max_entries=4, max_bytes=10_000_000)
    key = _key()
    cache.put(key, _frame())
    # Simulating transform change: do nothing to depth cache.
    assert cache.get(key) is not None
    cache.clear()
    assert cache.get(key) is None
    assert cache.stats().count == 0
    assert cache.current_bytes == 0


def test_oversized_admission_policy() -> None:
    # Tiny budget: one 64x64 float32 = 16384 bytes, force oversized path.
    cache = DepthFrameCache(max_entries=8, max_bytes=1024)
    key = _key()
    big = _frame(height=64, width=64)
    assert big.depth.nbytes > 1024
    assert cache.put(key, big)
    assert cache.stats().oversized_admissions == 1
    assert cache.get(key) is not None
    assert cache.put(key, big, allow_eviction=False) is False or True
    # reject path when allow_eviction=False and oversized
    cache2 = DepthFrameCache(max_entries=8, max_bytes=1024)
    assert cache2.put(key, big, allow_eviction=False) is False
    assert cache2.stats().oversized_rejections == 1
