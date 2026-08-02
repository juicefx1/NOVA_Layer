from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
    create_display_transform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.ocio_adapter import is_ocio_available


def test_plus_one_stop_doubles() -> None:
    transform = ExposureTransform(1.0)
    pixel = np.array([[[0.25, 0.5, 1.0]]], dtype=np.float32)
    out = transform.apply(pixel)
    assert out.dtype == np.float32
    assert np.allclose(out, [[[0.5, 1.0, 2.0]]])


def test_minus_one_stop_halves() -> None:
    transform = ExposureTransform(-1.0)
    pixel = np.array([[[0.5, 1.0, 2.0]]], dtype=np.float32)
    out = transform.apply(pixel)
    assert np.allclose(out, [[[0.25, 0.5, 1.0]]])


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_float_dtypes(dtype: type) -> None:
    transform = ExposureTransform(1.0)
    pixel = np.array([[[0.25, 0.25, 0.25]]], dtype=dtype)
    out = transform.apply(pixel)
    assert out.dtype == np.float32
    assert np.allclose(out, 0.5, atol=1e-3)


def test_rgba_uses_rgb_only() -> None:
    transform = ExposureTransform(1.0)
    rgba = np.array([[[0.25, 0.0, 0.0, 0.9]]], dtype=np.float32)
    out = transform.apply(rgba)
    assert out.shape == (1, 1, 3)
    assert np.allclose(out[0, 0], [0.5, 0.0, 0.0])


def test_nan_neg_inf_pos_inf() -> None:
    transform = ExposureTransform(0.0)
    pixels = np.array([[[np.nan, -np.inf, np.inf]]], dtype=np.float32)
    out = transform.apply(pixels)
    assert out[0, 0, 0] == 0.0
    assert out[0, 0, 1] == 0.0
    assert np.isposinf(out[0, 0, 2])


def test_input_not_mutated() -> None:
    transform = ExposureTransform(2.0)
    pixel = np.array([[[0.25, 0.25, 0.25]]], dtype=np.float32)
    original = pixel.copy()
    transform.apply(pixel)
    assert np.array_equal(pixel, original)


def test_legacy_exposure_zero_bit_compatible() -> None:
    linear = np.array(
        [[[0.0, 0.0031308, 0.5], [0.18, 1.0, 2.0]]],
        dtype=np.float32,
    )
    bare = LegacyDisplayTransform().apply(linear)
    wrapped = ViewerDisplayTransform(
        exposure=ExposureTransform(0.0),
        display_transform=LegacyDisplayTransform(),
    ).apply(linear)
    assert np.array_equal(bare, wrapped)


def test_legacy_exposure_plus_one_changes_preview() -> None:
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


def test_factory_returns_viewer_wrapper() -> None:
    transform = create_display_transform(prefer_ocio=False, exposure=1.25)
    assert isinstance(transform, ViewerDisplayTransform)
    assert isinstance(transform.display_transform, LegacyDisplayTransform)
    assert transform.diagnostics.exposure == pytest.approx(1.25)
    assert transform.diagnostics.backend == "legacy"
    assert transform.exposure.stops == pytest.approx(1.25)


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_factory_ocio_exposure_matches_prior_gain(tmp_path: Path) -> None:
    config = tmp_path / "minimal.ocio"
    config.write_text(
        """ocio_profile_version: 2

environment:
  {}

search_path: ""

roles:
  default: Raw
  scene_linear: Raw
  data: Raw

file_rules:
  - !<Rule> {name: Default, colorspace: default}

displays:
  sRGB:
    - !<View> {name: Raw, colorspace: Raw}

active_displays: [sRGB]
active_views: [Raw]

colorspaces:
  - !<ColorSpace>
    name: Raw
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
""",
        encoding="utf-8",
    )
    pixel = np.array([[[0.25, 0.25, 0.25]]], dtype=np.float32)
    # Historical OCIO path applied gain before the CPU processor.
    from nova_layer.adapters.color.ocio_adapter import OcioDisplayTransform

    display = OcioDisplayTransform(config_path=config, exposure=0.0)
    historical = display.apply(pixel * np.float32(2.0))
    factory = create_display_transform(
        prefer_ocio=True,
        config_path=config,
        exposure=1.0,
    )
    assert isinstance(factory, ViewerDisplayTransform)
    assert factory.diagnostics.exposure == pytest.approx(1.0)
    assert np.array_equal(factory.apply(pixel), historical)
