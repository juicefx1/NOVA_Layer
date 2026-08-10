"""Smoke tests for the D3.6 validation harness (no production Depth model required)."""

from __future__ import annotations

import numpy as np

from nova_layer.adapters.capabilities.mock import MockSegmentationCapability
from nova_layer.depth_assist_validation import (
    INTERACTION,
    accept_proxy,
    auto_seed,
    manual_guidance_for_seed,
)
from nova_layer.domain.models import GuidancePoint


def test_interaction_definition_covers_user_actions() -> None:
    required = {
        "analyze",
        "pick",
        "assist",
        "tolerance_adjust",
        "positive_click",
        "negative_click",
        "bbox_draw",
        "refine_click",
    }
    assert required.issubset(INTERACTION.keys())


def test_manual_guidance_budget_is_six_base_interactions() -> None:
    points, bbox, interactions = manual_guidance_for_seed(100, 80, 200, 320)
    assert len(points) == 5
    assert bbox.width > 0 and bbox.height > 0
    assert interactions == 6


def test_auto_seed_prefers_near_finite_peak() -> None:
    depth = np.zeros((40, 60), dtype=np.float32)
    depth[10, 30] = 5.0
    valid = np.ones_like(depth, dtype=bool)
    x, y = auto_seed(depth, valid)
    assert (x, y) == (30, 10)


def test_accept_proxy_rejects_empty_or_huge_masks() -> None:
    empty = np.zeros((32, 32), dtype=np.uint8)
    huge = np.full((32, 32), 255, dtype=np.uint8)
    mid = np.zeros((32, 32), dtype=np.uint8)
    mid[8:24, 8:24] = 255
    assert accept_proxy(0.99, empty, 0.05) is False
    assert accept_proxy(0.99, huge, 0.05) is False
    assert accept_proxy(0.99, mid, 0.05) is True


def test_mock_segmentation_runs_for_manual_points() -> None:
    seg = MockSegmentationCapability()
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    points = [
        GuidancePoint(x=0.4, y=0.5, polarity="positive"),
        GuidancePoint(x=0.1, y=0.1, polarity="negative"),
    ]
    result = seg.predict(
        frame_number=0,
        image=image,
        width=64,
        height=48,
        points=points,
        bounding_region=None,
    )
    assert result.mask.shape == (48, 64)
    assert result.confidence > 0.5
