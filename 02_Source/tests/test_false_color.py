"""Phase 9D-2: pure false-color transforms."""

from __future__ import annotations

import numpy as np
import pytest

from nova_layer.app.false_color import (
    LUMA_BANDS,
    SCENE_CLIPPING_BANDS,
    SCENE_EXPOSURE_BANDS,
    FalseColorMode,
    apply_false_color,
    blend_false_color,
)


def _solid_u8(rgb: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    frame[:, :] = rgb
    return frame


def _solid_f32(rgb: tuple[float, float, float]) -> np.ndarray:
    frame = np.zeros((2, 2, 3), dtype=np.float32)
    frame[:, :] = rgb
    return frame


def test_preview_luma_band_colors() -> None:
    # Mid green band ~50% luma → green palette
    image = _solid_u8((128, 128, 128))
    out = apply_false_color(image, mode=FalseColorMode.PREVIEW_LUMA, opacity=1.0)
    assert tuple(out[0, 0]) == LUMA_BANDS[3].color  # 40–60%


def test_luma_low_and_high_bands() -> None:
    low = apply_false_color(_solid_u8((0, 0, 0)), mode=FalseColorMode.SOURCE_LUMA)
    high = apply_false_color(_solid_u8((255, 255, 255)), mode=FalseColorMode.SOURCE_LUMA)
    assert tuple(low[0, 0]) == LUMA_BANDS[0].color
    assert tuple(high[0, 0]) == LUMA_BANDS[-1].color


def test_scene_exposure_bands() -> None:
    # luma=1 → EV 0 → 0~+2 band
    mid = apply_false_color(_solid_f32((1.0, 1.0, 1.0)), mode=FalseColorMode.SCENE_EXPOSURE)
    assert tuple(mid[0, 0]) == SCENE_EXPOSURE_BANDS[4].color
    bright = apply_false_color(_solid_f32((32.0, 32.0, 32.0)), mode=FalseColorMode.SCENE_EXPOSURE)
    assert tuple(bright[0, 0]) == SCENE_EXPOSURE_BANDS[-1].color
    dark = apply_false_color(_solid_f32((0.0, 0.0, 0.0)), mode=FalseColorMode.SCENE_EXPOSURE)
    assert tuple(dark[0, 0]) == SCENE_EXPOSURE_BANDS[0].color


def test_scene_clipping_priority() -> None:
    over4 = apply_false_color(
        _solid_f32((5.0, 0.5, 0.5)),
        mode=FalseColorMode.SCENE_CLIPPING,
        opacity=1.0,
    )
    assert tuple(over4[0, 0]) == SCENE_CLIPPING_BANDS[0].color
    over1 = apply_false_color(
        _solid_f32((1.5, 0.5, 0.5)),
        mode=FalseColorMode.SCENE_CLIPPING,
        opacity=1.0,
    )
    assert tuple(over1[0, 0]) == SCENE_CLIPPING_BANDS[1].color
    neg = apply_false_color(
        _solid_f32((-0.2, 0.5, 0.5)),
        mode=FalseColorMode.SCENE_CLIPPING,
        opacity=1.0,
    )
    assert tuple(neg[0, 0]) == SCENE_CLIPPING_BANDS[2].color


def test_nan_inf_negative_safe() -> None:
    image = np.array([[[np.nan, np.inf, -np.inf]]], dtype=np.float32)
    out = apply_false_color(image, mode=FalseColorMode.SCENE_EXPOSURE, opacity=1.0)
    assert out.shape == (1, 1, 3)
    assert out.dtype == np.uint8


def test_opacity_blend() -> None:
    base = _solid_u8((0, 0, 0))
    colored = _solid_u8((100, 0, 0))
    assert np.array_equal(blend_false_color(base, colored, opacity=0.0), base)
    assert np.array_equal(blend_false_color(base, colored, opacity=1.0), colored)
    half = blend_false_color(base, colored, opacity=0.5)
    assert int(half[0, 0, 0]) == 50


def test_invalid_shape() -> None:
    with pytest.raises(ValueError):
        apply_false_color(np.zeros((4,), dtype=np.uint8), mode=FalseColorMode.PREVIEW_LUMA)


def test_mode_off_returns_base() -> None:
    base = _solid_u8((11, 22, 33))
    out = apply_false_color(base, mode=FalseColorMode.OFF, base_preview=base)
    assert np.array_equal(out, base)
