from __future__ import annotations

import numpy as np

from nova_layer.adapters.color.display_transform import (
    DisplayTransform,
    LegacyDisplayTransform,
    linear_to_srgb,
)


def _legacy_linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    """Historical ImageSequenceReader formula (finite values only)."""
    value = np.asarray(linear, dtype=np.float32)
    value = np.clip(value, 0.0, None)
    a = 0.055
    return np.where(
        value <= 0.0031308,
        12.92 * value,
        (1.0 + a) * np.power(value, 1.0 / 2.4) - a,
    ).astype(np.float32)


def _legacy_float_rgb_to_preview_u8(pixels: np.ndarray) -> np.ndarray:
    array = np.asarray(pixels)
    rgb = np.asarray(array[:, :, :3], dtype=np.float32)
    srgb = _legacy_linear_to_srgb(rgb)
    return np.asarray(np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5, dtype=np.uint8)


def test_linear_zero_and_one() -> None:
    transform = DisplayTransform()
    zero = transform.apply(np.zeros((1, 1, 3), dtype=np.float32))
    one = transform.apply(np.ones((1, 1, 3), dtype=np.float32))
    assert zero.dtype == np.uint8
    assert one.dtype == np.uint8
    assert tuple(int(v) for v in zero[0, 0]) == (0, 0, 0)
    assert tuple(int(v) for v in one[0, 0]) == (255, 255, 255)


def test_mid_gray_matches_legacy_formula() -> None:
    transform = LegacyDisplayTransform()
    linear = np.full((2, 2, 3), 0.18, dtype=np.float32)
    assert np.array_equal(transform.apply(linear), _legacy_float_rgb_to_preview_u8(linear))

    sample = np.array(
        [[[0.0, 0.0031308, 0.5], [0.18, 1.0, 2.0]]],
        dtype=np.float32,
    )
    assert np.array_equal(transform.apply(sample), _legacy_float_rgb_to_preview_u8(sample))
    assert np.allclose(
        linear_to_srgb(sample),
        _legacy_linear_to_srgb(sample),
        rtol=0.0,
        atol=0.0,
        equal_nan=False,
    )


def test_float16_and_float32_inputs() -> None:
    transform = DisplayTransform()
    f16 = np.zeros((1, 1, 3), dtype=np.float16)
    f16[0, 0] = (1.0, 0.0, 0.0)
    f32 = np.zeros((1, 1, 3), dtype=np.float32)
    f32[0, 0] = (1.0, 0.0, 0.0)
    assert tuple(int(v) for v in transform.apply(f16)[0, 0]) == (255, 0, 0)
    assert tuple(int(v) for v in transform.apply(f32)[0, 0]) == (255, 0, 0)


def test_rgba_uses_rgb_only() -> None:
    transform = DisplayTransform()
    rgba = np.zeros((1, 1, 4), dtype=np.float32)
    rgba[0, 0] = (1.0, 0.0, 0.0, 0.25)
    preview = transform.apply(rgba)
    assert preview.shape == (1, 1, 3)
    assert tuple(int(v) for v in preview[0, 0]) == (255, 0, 0)


def test_nan_and_inf_are_safe() -> None:
    transform = DisplayTransform()
    pixels = np.array(
        [[[np.nan, -np.inf, np.inf]]],
        dtype=np.float32,
    )
    preview = transform.apply(pixels)
    assert preview.dtype == np.uint8
    assert preview.shape == (1, 1, 3)
    assert int(preview[0, 0, 0]) == 0  # NaN → 0
    assert int(preview[0, 0, 1]) == 0  # -Inf → 0
    assert int(preview[0, 0, 2]) == 255  # +Inf → clipped to 1 after transfer


def test_display_transform_alias_is_legacy() -> None:
    assert DisplayTransform is LegacyDisplayTransform


def test_legacy_via_exposure_zero_matches_bare() -> None:
    from nova_layer.adapters.color.exposure_transform import ExposureTransform
    from nova_layer.adapters.color.display_transform import ViewerDisplayTransform

    linear = np.full((2, 2, 3), 0.18, dtype=np.float32)
    bare = LegacyDisplayTransform().apply(linear)
    composed = ViewerDisplayTransform(
        exposure=ExposureTransform(0.0),
        display_transform=LegacyDisplayTransform(),
    ).apply(linear)
    assert np.array_equal(bare, composed)


def test_legacy_via_exposure_plus_one_brightens() -> None:
    from nova_layer.adapters.color.exposure_transform import ExposureTransform
    from nova_layer.adapters.color.display_transform import ViewerDisplayTransform

    pixel = np.array([[[0.18, 0.18, 0.18]]], dtype=np.float32)
    base = ViewerDisplayTransform(
        exposure=ExposureTransform(0.0),
        display_transform=LegacyDisplayTransform(),
    ).apply(pixel)
    bright = ViewerDisplayTransform(
        exposure=ExposureTransform(1.0),
        display_transform=LegacyDisplayTransform(),
    ).apply(pixel)
    assert int(bright[0, 0, 0]) > int(base[0, 0, 0])
