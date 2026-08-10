"""Phase D3 Depth Region → Artist Guidance helper tests."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from nova_layer.app.depth_guidance import (
    build_depth_guidance_proposal,
    depth_bbox_to_bounding_region,
)
from nova_layer.app.depth_region import DepthRegion, freeze_bool_mask


def _region(
    mask: np.ndarray,
    *,
    seed_x: int,
    seed_y: int,
    frame_number: int = 0,
    coverage: float | None = None,
    warning: str | None = None,
) -> DepthRegion:
    mask_b = freeze_bool_mask(np.asarray(mask, dtype=bool))
    ys, xs = np.nonzero(mask_b)
    if ys.size:
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        count = int(ys.size)
    else:
        bbox = None
        count = 0
    h, w = mask_b.shape
    return DepthRegion(
        frame_number=frame_number,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_depth=0.5,
        tolerance=0.1,
        mask=mask_b,
        bounding_box=bbox,
        pixel_count=count,
        coverage=float(coverage if coverage is not None else (count / float(h * w))),
        warning=warning,
        effective_band=0.05,
    )


def test_seed_and_centroid_positive() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True
    region = _region(mask, seed_x=6, seed_y=6)
    proposal = build_depth_guidance_proposal(region, image_width=20, image_height=20)
    assert len(proposal.positive_points) >= 1
    # Seed maps near (6.5/20, 6.5/20)
    seed = proposal.positive_points[0]
    assert seed.polarity == "positive"
    assert seed.x == pytest.approx((6 + 0.5) / 20.0)
    assert seed.y == pytest.approx((6 + 0.5) / 20.0)
    assert any(p.polarity == "positive" for p in proposal.positive_points)


def test_dedupe_close_positives() -> None:
    mask = np.zeros((10, 10), dtype=bool)
    mask[4:6, 4:6] = True
    region = _region(mask, seed_x=4, seed_y=4)
    proposal = build_depth_guidance_proposal(region, image_width=10, image_height=10)
    keys = {(round(p.x, 6), round(p.y, 6), p.polarity) for p in proposal.positive_points}
    assert len(keys) == len(proposal.positive_points)


def test_bbox_conversion_padding_clamp() -> None:
    mask = np.zeros((50, 50), dtype=bool)
    mask[0:2, 0:2] = True
    region = _region(mask, seed_x=0, seed_y=0, coverage=0.0001)
    bbox = depth_bbox_to_bounding_region(
        region, image_width=50, image_height=50, bbox_padding_fraction=0.02
    )
    assert bbox is not None
    assert bbox.x >= 0.0 and bbox.y >= 0.0
    assert bbox.x + bbox.width <= 1.0 + 1e-9
    assert bbox.y + bbox.height <= 1.0 + 1e-9


def test_negative_four_sides_not_inside_region() -> None:
    mask = np.zeros((40, 40), dtype=bool)
    mask[10:30, 10:30] = True
    region = _region(mask, seed_x=15, seed_y=15)
    proposal = build_depth_guidance_proposal(
        region, image_width=40, image_height=40, include_negative_points=True
    )
    assert len(proposal.negative_points) >= 1
    for point in proposal.negative_points:
        assert point.polarity == "negative"
        px = int(round(point.x * 40 - 0.5))
        py = int(round(point.y * 40 - 0.5))
        px = max(0, min(39, px))
        py = max(0, min(39, py))
        assert not bool(mask[py, px])


def test_tiny_region_and_no_bbox() -> None:
    mask = np.zeros((12, 12), dtype=bool)
    mask[3, 3] = True
    region = _region(mask, seed_x=3, seed_y=3, coverage=1.0 / 144.0)
    proposal = build_depth_guidance_proposal(region, image_width=12, image_height=12)
    assert proposal.positive_points
    assert proposal.bounding_region is not None

    empty = _region(np.zeros((8, 8), dtype=bool), seed_x=1, seed_y=1)
    empty_prop = build_depth_guidance_proposal(empty, image_width=8, image_height=8)
    assert empty_prop.bounding_region is None
    assert empty_prop.positive_points == ()
    assert empty_prop.warning


def test_deterministic_and_region_unchanged() -> None:
    mask = np.zeros((30, 30), dtype=bool)
    mask[8:22, 8:22] = True
    region = _region(mask, seed_x=10, seed_y=12)
    before = copy.deepcopy(np.array(region.mask))
    a = build_depth_guidance_proposal(region, image_width=30, image_height=30)
    b = build_depth_guidance_proposal(region, image_width=30, image_height=30)
    assert a.positive_points == b.positive_points
    assert a.negative_points == b.negative_points
    assert a.bounding_region == b.bounding_region
    np.testing.assert_array_equal(np.array(region.mask), before)


def test_image_bounds_and_no_negatives_option() -> None:
    mask = np.zeros((16, 16), dtype=bool)
    mask[:, :] = True
    region = _region(mask, seed_x=8, seed_y=8, coverage=1.0)
    proposal = build_depth_guidance_proposal(
        region, image_width=16, image_height=16, include_negative_points=False
    )
    assert proposal.negative_points == ()
    for point in [*proposal.positive_points]:
        assert 0.0 <= point.x <= 1.0
        assert 0.0 <= point.y <= 1.0
