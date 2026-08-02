from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    ColorTransformError,
    LegacyDisplayTransform,
    create_display_transform,
)
from nova_layer.adapters.color.ocio_adapter import (
    OcioDisplayTransform,
    is_ocio_available,
    load_ocio_config_options,
    resolve_ocio_config_path,
)


MINIMAL_OCIO_CONFIG = """ocio_profile_version: 2

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
"""


@pytest.fixture
def minimal_ocio_config(tmp_path: Path) -> Path:
    path = tmp_path / "minimal.ocio"
    path.write_text(MINIMAL_OCIO_CONFIG, encoding="utf-8")
    return path


def test_factory_prefer_ocio_false_returns_legacy(minimal_ocio_config: Path) -> None:
    transform = create_display_transform(
        prefer_ocio=False,
        config_path=minimal_ocio_config,
    )
    assert isinstance(transform, LegacyDisplayTransform)
    assert transform.diagnostics.backend == "legacy"
    assert transform.diagnostics.fallback_reason == "prefer_ocio=False"


def test_factory_falls_back_when_ocio_missing(
    monkeypatch: pytest.MonkeyPatch,
    minimal_ocio_config: Path,
) -> None:
    monkeypatch.setattr(
        "nova_layer.adapters.color.ocio_adapter.OCIO",
        None,
    )
    monkeypatch.setattr(
        "nova_layer.adapters.color.ocio_adapter.is_ocio_available",
        lambda: False,
    )
    transform = create_display_transform(
        prefer_ocio=True,
        config_path=minimal_ocio_config,
    )
    assert isinstance(transform, LegacyDisplayTransform)
    assert transform.diagnostics.backend == "legacy"
    assert transform.diagnostics.ocio_available is False
    assert "PyOpenColorIO" in (transform.diagnostics.fallback_reason or "")


def test_ocio_constructor_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nova_layer.adapters.color.ocio_adapter.OCIO", None)
    with pytest.raises(ColorTransformError, match="PyOpenColorIO is not installed"):
        OcioDisplayTransform()


def test_resolve_config_path_prefers_explicit(
    minimal_ocio_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_config = tmp_path / "from_env.ocio"
    env_config.write_text(MINIMAL_OCIO_CONFIG, encoding="utf-8")
    monkeypatch.setenv("OCIO", str(env_config))

    path, source = resolve_ocio_config_path(minimal_ocio_config)
    assert path == minimal_ocio_config.resolve()
    assert source == "explicit"


def test_resolve_config_path_uses_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_config = tmp_path / "from_env.ocio"
    env_config.write_text(MINIMAL_OCIO_CONFIG, encoding="utf-8")
    monkeypatch.setenv("OCIO", str(env_config))

    path, source = resolve_ocio_config_path(None)
    assert path == env_config.resolve()
    assert source == "env"


def test_resolve_config_path_missing_explicit_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ocio"
    with pytest.raises(ColorTransformError, match="not found"):
        resolve_ocio_config_path(missing)


def test_resolve_config_path_no_source_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCIO", raising=False)
    with pytest.raises(ColorTransformError, match="No OCIO config available"):
        resolve_ocio_config_path(None)


def test_factory_falls_back_on_bad_config(tmp_path: Path) -> None:
    if not is_ocio_available():
        # Without OCIO the factory falls back earlier with install message.
        transform = create_display_transform(
            prefer_ocio=True,
            config_path=tmp_path / "nope.ocio",
        )
        assert isinstance(transform, LegacyDisplayTransform)
        assert transform.diagnostics.fallback_reason is not None
        return

    bad = tmp_path / "broken.ocio"
    bad.write_text("not a valid ocio config\n", encoding="utf-8")
    transform = create_display_transform(prefer_ocio=True, config_path=bad)
    assert isinstance(transform, LegacyDisplayTransform)
    assert transform.diagnostics.backend == "legacy"
    assert transform.diagnostics.fallback_reason is not None


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_ocio_float_rgb_to_uint8(minimal_ocio_config: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    transform = OcioDisplayTransform(
        config_path=minimal_ocio_config,
        input_color_space="scene_linear",
    )
    assert transform.diagnostics.backend == "ocio"
    assert transform.diagnostics.config_source == "explicit"
    assert transform.diagnostics.display == "sRGB"
    assert transform.diagnostics.view == "Raw"

    pixel = np.array([[[0.5, 0.0, 0.0]]], dtype=np.float32)
    preview = transform.apply(pixel)
    assert preview.dtype == np.uint8
    assert preview.shape == (1, 1, 3)
    # Raw view is passthrough → ≈127–128 after quantize.
    assert abs(int(preview[0, 0, 0]) - 128) <= 1
    assert int(preview[0, 0, 1]) == 0


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_ocio_exposure_plus_one_stop(minimal_ocio_config: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    base = OcioDisplayTransform(config_path=minimal_ocio_config, exposure=0.0)
    bright = OcioDisplayTransform(config_path=minimal_ocio_config, exposure=1.0)
    pixel = np.array([[[0.25, 0.25, 0.25]]], dtype=np.float32)
    base_u8 = int(base.apply(pixel)[0, 0, 0])
    bright_u8 = int(bright.apply(pixel)[0, 0, 0])
    # +1 stop doubles linear → 0.25→0.5, so ~64 → ~128
    assert abs(base_u8 - 64) <= 1
    assert abs(bright_u8 - 128) <= 1
    assert bright_u8 > base_u8


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_ocio_rgba_uses_rgb_only(minimal_ocio_config: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    transform = OcioDisplayTransform(config_path=minimal_ocio_config)
    rgba = np.array([[[1.0, 0.0, 0.0, 0.1]]], dtype=np.float32)
    preview = transform.apply(rgba)
    assert preview.shape == (1, 1, 3)
    assert int(preview[0, 0, 0]) == 255
    assert int(preview[0, 0, 1]) == 0


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_ocio_unknown_input_colorspace_raises(minimal_ocio_config: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    with pytest.raises(ColorTransformError, match="input color space not found"):
        OcioDisplayTransform(
            config_path=minimal_ocio_config,
            input_color_space="not_a_real_space",
        )


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_factory_selects_ocio_when_available(minimal_ocio_config: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    transform = create_display_transform(
        prefer_ocio=True,
        config_path=minimal_ocio_config,
    )
    assert isinstance(transform, OcioDisplayTransform)
    assert transform.diagnostics.backend == "ocio"
    assert transform.diagnostics.fallback_reason is None


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_ocio_uses_env_config(
    monkeypatch: pytest.MonkeyPatch,
    minimal_ocio_config: Path,
) -> None:
    pytest.importorskip("PyOpenColorIO")
    monkeypatch.setenv("OCIO", str(minimal_ocio_config))
    transform = OcioDisplayTransform()
    assert transform.diagnostics.config_source == "env"
    assert Path(transform.diagnostics.config_path or "") == minimal_ocio_config.resolve()


MULTI_DISPLAY_OCIO_CONFIG = """ocio_profile_version: 2

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
    - !<View> {name: Linear, colorspace: LinearCS}
  Rec709:
    - !<View> {name: Film, colorspace: LinearCS}

active_displays: [sRGB, Rec709]
active_views: [Raw, Linear, Film]

colorspaces:
  - !<ColorSpace>
    name: Raw
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
  - !<ColorSpace>
    name: LinearCS
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
"""


def test_load_ocio_config_options_requires_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nova_layer.adapters.color.ocio_adapter.OCIO", None)
    with pytest.raises(ColorTransformError, match="PyOpenColorIO is not installed"):
        load_ocio_config_options()


def test_load_ocio_config_options_missing_path(tmp_path: Path) -> None:
    if not is_ocio_available():
        with pytest.raises(ColorTransformError):
            load_ocio_config_options(tmp_path / "nope.ocio")
        return
    with pytest.raises(ColorTransformError, match="not found"):
        load_ocio_config_options(tmp_path / "nope.ocio")


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_load_ocio_config_options_enumerates(tmp_path: Path) -> None:
    pytest.importorskip("PyOpenColorIO")
    path = tmp_path / "multi.ocio"
    path.write_text(MULTI_DISPLAY_OCIO_CONFIG, encoding="utf-8")
    options = load_ocio_config_options(path)
    assert options.config_source == "explicit"
    assert Path(options.config_path) == path.resolve()
    assert "Raw" in options.color_spaces
    assert "scene_linear" in options.color_spaces
    assert options.displays == ("sRGB", "Rec709") or set(options.displays) >= {"sRGB", "Rec709"}
    assert "Raw" in options.views_for("sRGB")
    assert "Linear" in options.views_for("sRGB")
    assert options.views_for("Rec709") == ("Film",) or "Film" in options.views_for("Rec709")
    assert options.default_display == "sRGB"
    assert options.default_view == "Raw"
