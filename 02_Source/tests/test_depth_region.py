"""Phase D2 Depth Region extraction / visualization unit tests."""

from __future__ import annotations

import numpy as np
import pytest

from nova_layer.app.depth_region import (
    connected_component_8,
    depth_to_grayscale,
    effective_depth_band,
    extract_depth_region,
)
from nova_layer.ports.depth import DepthFrame, DepthNormalization, freeze_depth_array


def _frame(
    depth: np.ndarray,
    *,
    near_is: str = "high",
    valid_mask: np.ndarray | None = None,
    frame_number: int = 0,
) -> DepthFrame:
    return DepthFrame(
        frame_number=frame_number,
        media_fingerprint="fp",
        depth=freeze_depth_array(depth.astype(np.float32)),
        valid_mask=valid_mask,
        quantity="relative_disparity",
        near_is=near_is,  # type: ignore[arg-type]
        normalization=DepthNormalization(kind="model_native"),
        source_model="fake_depth_v1",
        model_version="1.0.0",
        preprocessing_version="p",
        input_policy="source_v1",
        metadata={},
    )


def test_seed_band_and_tolerance_increases_coverage() -> None:
    depth = np.zeros((9, 9), dtype=np.float32)
    depth[:, :] = 0.5
    depth[2:7, 2:7] = 0.7
    depth[4, 4] = 0.71
    frame = _frame(depth)
    tight = extract_depth_region(frame, seed_x=4, seed_y=4, tolerance=0.05)
    wide = extract_depth_region(frame, seed_x=4, seed_y=4, tolerance=0.4)
    assert tight.pixel_count >= 1
    assert wide.coverage >= tight.coverage
    assert tight.seed_depth == pytest.approx(0.71, rel=0, abs=1e-5)


def test_tolerance_zero_keeps_exact_seed_only_when_unique() -> None:
    depth = np.linspace(0.0, 1.0, 25, dtype=np.float32).reshape(5, 5)
    frame = _frame(depth)
    region = extract_depth_region(frame, seed_x=2, seed_y=2, tolerance=0.0)
    assert region.pixel_count == 1
    assert region.mask[2, 2]


def test_invalid_seed_and_nan_excluded() -> None:
    depth = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
    depth[1, 1] = np.nan
    frame = _frame(depth)
    bad = extract_depth_region(frame, seed_x=1, seed_y=1, tolerance=0.2)
    assert bad.pixel_count == 0
    assert bad.warning is not None
    oob = extract_depth_region(frame, seed_x=99, seed_y=0, tolerance=0.2)
    assert oob.pixel_count == 0


def test_valid_mask_applied() -> None:
    depth = np.full((6, 6), 0.5, dtype=np.float32)
    depth[2:5, 2:5] = 0.8
    valid = np.ones((6, 6), dtype=bool)
    valid[3, 3] = False
    frame = _frame(depth, valid_mask=valid)
    region = extract_depth_region(frame, seed_x=2, seed_y=2, tolerance=0.5)
    assert not region.mask[3, 3]


def test_8_connected_excludes_diagonal_only_island_wait_includes_diagonal() -> None:
    # 8-connected: diagonal neighbor IS connected.
    cand = np.zeros((5, 5), dtype=bool)
    cand[1, 1] = True
    cand[2, 2] = True
    out = connected_component_8(cand, seed_x=1, seed_y=1)
    assert out[2, 2]


def test_disconnected_same_depth_island_excluded() -> None:
    depth = np.full((8, 8), 0.1, dtype=np.float32)
    depth[1:3, 1:3] = 0.9
    depth[5:7, 5:7] = 0.9
    frame = _frame(depth)
    region = extract_depth_region(frame, seed_x=1, seed_y=1, tolerance=0.05)
    assert region.mask[1, 1]
    assert not region.mask[6, 6]
    assert region.pixel_count == 4


def test_bbox_pixel_count_coverage_deterministic() -> None:
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[2:5, 3:6] = 1.0
    frame = _frame(depth)
    a = extract_depth_region(frame, seed_x=4, seed_y=3, tolerance=0.2)
    b = extract_depth_region(frame, seed_x=4, seed_y=3, tolerance=0.2)
    assert a.bounding_box == (3, 2, 5, 4)
    assert a.pixel_count == 9
    assert a.coverage == pytest.approx(9 / 100)
    assert np.array_equal(a.mask, b.mask)
    assert a.effective_band == b.effective_band


def test_input_depth_unchanged() -> None:
    depth = np.linspace(0.0, 1.0, 36, dtype=np.float32).reshape(6, 6)
    original = depth.copy()
    frame = _frame(depth)
    extract_depth_region(frame, seed_x=2, seed_y=2, tolerance=0.1)
    np.testing.assert_array_equal(frame.depth, freeze_depth_array(original))


def test_visualization_percentile_and_near_is() -> None:
    depth = np.linspace(0.0, 1.0, 100, dtype=np.float32).reshape(10, 10)
    high = _frame(depth, near_is="high")
    low = _frame(depth, near_is="low")
    g_high = depth_to_grayscale(high, near_white=True)
    g_low = depth_to_grayscale(low, near_white=True)
    assert g_high.dtype == np.uint8
    # Near-high: larger depth brighter; near-low: opposite.
    assert g_high[9, 9] > g_high[0, 0]
    assert g_low[0, 0] > g_low[9, 9]


def test_effective_band_scales_with_tolerance() -> None:
    depth = np.linspace(0.0, 10.0, 100, dtype=np.float32).reshape(10, 10)
    valid = np.ones_like(depth, dtype=bool)
    a = effective_depth_band(depth, valid, 0.1)
    b = effective_depth_band(depth, valid, 0.2)
    assert b == pytest.approx(2 * a)
