"""Phase 9D-1: pure histogram analysis (NumPy, no Qt)."""

from __future__ import annotations

import numpy as np
import pytest

from nova_layer.app.histogram_analysis import (
    compute_frame_histogram,
    downsample_rgb,
)
from nova_layer.app.processing_frames import ProcessingColorPolicy


def test_uint8_rgb_bins_and_stats() -> None:
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    image[0, 0] = (0, 10, 20)
    image[0, 1] = (255, 10, 20)
    image[1, 0] = (128, 10, 20)
    image[1, 1] = (128, 10, 20)
    data = compute_frame_histogram(image, policy=ProcessingColorPolicy.PREVIEW)
    assert data.bins == 256
    assert data.value_range == (0.0, 255.0)
    assert data.sample_count == 4
    assert int(data.red.bins[0]) == 1
    assert int(data.red.bins[128]) == 2
    assert int(data.red.bins[255]) == 1
    assert data.red.clipped_low == 1
    assert data.red.clipped_high == 1
    assert data.red.minimum == 0.0
    assert data.red.maximum == 255.0
    assert data.red.mean == pytest.approx((0 + 255 + 128 + 128) / 4)
    assert data.red.median == pytest.approx(128.0)


def test_scene_float_bins_clipped_and_unclipped_stats() -> None:
    image = np.array(
        [
            [[-0.5, 0.0, 0.0], [1.0, 1.0, 1.0]],
            [[2.5, 2.5, 2.5], [5.0, 5.0, 5.0]],
        ],
        dtype=np.float32,
    )
    data = compute_frame_histogram(image, policy=ProcessingColorPolicy.SCENE)
    assert data.bins == 256
    assert data.value_range == (0.0, 4.0)
    assert data.red.clipped_low == 1
    assert data.red.clipped_high == 1
    assert data.red.minimum == pytest.approx(-0.5)
    assert data.red.maximum == pytest.approx(5.0)
    assert data.red.mean == pytest.approx((-0.5 + 1.0 + 2.5 + 5.0) / 4)


def test_luminance_rec709() -> None:
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    image[0, 0] = (100, 50, 25)
    data = compute_frame_histogram(image, policy=ProcessingColorPolicy.SOURCE)
    expected = 0.2126 * 100 + 0.7152 * 50 + 0.0722 * 25
    assert data.luminance.mean == pytest.approx(expected)


def test_invalid_shape_raises() -> None:
    with pytest.raises(ValueError):
        compute_frame_histogram(np.zeros((4,), dtype=np.uint8), policy="preview")
    with pytest.raises(ValueError):
        compute_frame_histogram(np.zeros((0, 4, 3), dtype=np.uint8), policy="preview")


def test_downsample_sample_count() -> None:
    image = np.zeros((2000, 2000, 3), dtype=np.uint8)
    sampled, count = downsample_rgb(image, max_samples=10_000)
    assert count == sampled.shape[0] * sampled.shape[1]
    assert count <= 10_000 + sampled.shape[1]  # stride quantization slack
    data = compute_frame_histogram(
        image,
        policy=ProcessingColorPolicy.PREVIEW,
        max_samples=10_000,
    )
    assert data.sample_count == count
    assert data.sample_count < 2000 * 2000
