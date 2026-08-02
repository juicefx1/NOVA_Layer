"""Phase 10C-2: OcioColorSpaceConverter + Working PREVIEW opt-in wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    ColorTransformError,
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.ocio_adapter import is_ocio_available
from nova_layer.adapters.color.ocio_color_space_converter import OcioColorSpaceConverter
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.color_pipeline_diagnostics import (
    build_color_pipeline_diagnostics,
    format_color_pipeline_diagnostics,
)
from nova_layer.app.preview_pipeline import PreviewPipeline
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.working_space import (
    WORKING_CONVERTER_VERSION,
    WorkingSpaceSettings,
    resolve_working_source_color_space,
    resolve_working_space,
)
from nova_layer.ports.media import MediaReadError
from nova_layer.ports.scene_frames import SceneFrame

# Reuse minimal OCIO config from adapter tests when OCIO is available.
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


class TrackingConverter:
    """Test double: scales RGB by 2 when source != working; no OCIO."""

    instances: list[TrackingConverter] = []

    def __init__(
        self,
        *,
        config_path: Path | None,
        source_color_space: str,
        working_color_space: str,
    ) -> None:
        self.config_path = config_path
        self.source_color_space = source_color_space
        self.working_color_space = working_color_space
        self.calls: list[np.ndarray] = []
        TrackingConverter.instances.append(self)

    def apply(self, image: np.ndarray) -> np.ndarray:
        arr = np.asarray(image)
        self.calls.append(np.array(arr, copy=True))
        rgb = np.asarray(arr[:, :, :3], dtype=np.float32).copy()
        if self.source_color_space != self.working_color_space:
            rgb = rgb * np.float32(2.0)
        return rgb


def _legacy_with_config(path: Path, *, ics: str = "Linear Rec.709", exposure: float = 0.0):
    return ViewerDisplayTransform(
        exposure=ExposureTransform(exposure),
        display_transform=LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=str(path),
                config_source="explicit",
                display=None,
                view=None,
                input_color_space=ics,
                exposure=0.0,
                fallback_reason=None,
            )
        ),
    )


def _fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    pixels: np.ndarray,
    *,
    attrs: dict[str, Any] | None = None,
    counter: list[int] | None = None,
) -> None:
    class FakeSpec:
        height = int(pixels.shape[0])
        width = int(pixels.shape[1])
        nchannels = int(pixels.shape[2]) if pixels.ndim == 3 else 3
        _attrs = attrs or {}

        def get_string_attribute(self, key: str, default: str = "") -> str:
            return str(self._attrs.get(key, default) or default)

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            if counter is not None:
                counter.append(1)
            return pixels

        def close(self) -> None:
            return None

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(_path: str) -> FakeInput:
                return FakeInput()

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )


def _exr_seq(tmp_path: Path, frames: int = 1) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


@pytest.fixture
def minimal_ocio_config(tmp_path: Path) -> Path:
    path = tmp_path / "minimal.ocio"
    path.write_text(MINIMAL_OCIO_CONFIG, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_converter_source_equals_working_noop(minimal_ocio_config: Path) -> None:
    conv = OcioColorSpaceConverter(
        config_path=minimal_ocio_config,
        source_color_space="Raw",
        working_color_space="Raw",
    )
    pixels = np.array([[[-0.5, 0.25, 2.0]]], dtype=np.float32)
    original = pixels.copy()
    out = conv.apply(pixels)
    assert out.dtype == np.float32
    assert np.array_equal(out, pixels)
    assert np.array_equal(pixels, original)
    assert float(out[0, 0, 0]) == pytest.approx(-0.5)
    assert float(out[0, 0, 2]) == pytest.approx(2.0)


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_converter_dtypes_and_rgba(minimal_ocio_config: Path) -> None:
    conv = OcioColorSpaceConverter(
        config_path=minimal_ocio_config,
        source_color_space="Raw",
        working_color_space="Raw",
    )
    for dtype in (np.float16, np.float32, np.float64):
        rgb = np.ones((2, 2, 3), dtype=dtype) * 0.5
        out = conv.apply(rgb)
        assert out.dtype == np.float32
        assert out.shape == (2, 2, 3)
    rgba = np.ones((1, 1, 4), dtype=np.float32)
    rgba[..., 3] = 0.1
    out = conv.apply(rgba)
    assert out.shape == (1, 1, 3)


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_converter_nan_inf(minimal_ocio_config: Path) -> None:
    conv = OcioColorSpaceConverter(
        config_path=minimal_ocio_config,
        source_color_space="Raw",
        working_color_space="Raw",
    )
    pixels = np.array([[[np.nan, -np.inf, np.inf]]], dtype=np.float32)
    out = conv.apply(pixels)
    assert out[0, 0, 0] == 0.0
    assert out[0, 0, 1] == 0.0
    assert out[0, 0, 2] == np.finfo(np.float32).max


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_converter_missing_colorspace(minimal_ocio_config: Path) -> None:
    with pytest.raises(ColorTransformError, match="not found"):
        OcioColorSpaceConverter(
            config_path=minimal_ocio_config,
            source_color_space="Missing",
            working_color_space="Raw",
        )


def test_converter_missing_ocio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "nova_layer.adapters.color.ocio_color_space_converter.OCIO",
        None,
    )
    with pytest.raises(ColorTransformError, match="PyOpenColorIO"):
        OcioColorSpaceConverter(
            config_path=tmp_path / "x.ocio",
            source_color_space="Raw",
            working_color_space="Raw",
        )


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def test_resolve_working_explicit(tmp_path: Path) -> None:
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    resolved = resolve_working_space(
        WorkingSpaceSettings(enabled=True, working_color_space="ACEScg"),
        ocio_config_path=cfg,
        ocio_config_source="explicit",
    )
    assert resolved.enabled is True
    assert resolved.working_color_space == "ACEScg"
    assert resolved.resolution_source == "explicit"
    assert resolved.ocio_config_identity is not None
    assert "ACEScg" in (resolved.working_color_space or "")


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_resolve_working_scene_linear_role(minimal_ocio_config: Path) -> None:
    resolved = resolve_working_space(
        WorkingSpaceSettings(enabled=True, working_color_space=None),
        ocio_config_path=minimal_ocio_config,
        ocio_config_source="explicit",
    )
    assert resolved.enabled is True
    assert resolved.working_color_space == "Raw"
    assert resolved.resolution_source == "scene_linear_role"


def test_resolve_working_no_config_disables() -> None:
    resolved = resolve_working_space(
        WorkingSpaceSettings(enabled=True, working_color_space="ACEScg"),
        ocio_config_path=None,
        ocio_config_source=None,
    )
    assert resolved.enabled is False
    assert resolved.warnings


def test_resolve_working_source_tag_priority() -> None:
    src, warns = resolve_working_source_color_space("ACEScg", "Linear Rec.709")
    assert src == "ACEScg"
    assert warns


def test_resolve_working_source_interpretation_fallback() -> None:
    src, warns = resolve_working_source_color_space(None, "Linear Rec.709")
    assert src == "Linear Rec.709"
    assert warns


def test_resolve_working_source_unresolved() -> None:
    src, warns = resolve_working_source_color_space(None, None)
    assert src is None
    assert warns


# ---------------------------------------------------------------------------
# PREVIEW / cache / SOURCE
# ---------------------------------------------------------------------------


def test_preview_disabled_matches_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels)
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    transform = _legacy_with_config(cfg)
    baseline = PreviewPipeline(ImageSequenceReader(), transform)
    a = baseline.read_frame(seq, 0)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        transform,
        working_space_settings=WorkingSpaceSettings(enabled=False),
        color_space_converter_cls=TrackingConverter,
    )
    b = pipeline.read_frame(seq, 0)
    assert np.array_equal(a, b)
    assert TrackingConverter.instances == []


def test_preview_enabled_uses_converter_and_working_src(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    transform = _legacy_with_config(cfg, ics="Linear Rec.709")
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        transform,
        working_space_settings=WorkingSpaceSettings(
            enabled=True,
            working_color_space="scene_linear",
        ),
        color_space_converter_cls=TrackingConverter,
    )
    assert pipeline.resolved_working_space.enabled is True
    preview = pipeline.read_frame(seq, 0)
    assert TrackingConverter.instances
    conv = TrackingConverter.instances[0]
    assert conv.source_color_space == "ACEScg"
    assert conv.working_color_space == "scene_linear"
    assert len(conv.calls) == 1
    # Working *2 then Legacy OETF — different from raw 0.25 bake.
    baseline = LegacyDisplayTransform().apply(pixels)
    assert not np.array_equal(preview, baseline)
    assert pipeline.transform_identity.input_color_space == "scene_linear"
    assert pipeline.interpretation_color_space == "Linear Rec.709"

    # Cache hit — no second conversion.
    pipeline.read_frame(seq, 0)
    assert len(conv.calls) == 1
    assert pipeline.working_cache_stats.count == 1
    assert pipeline.working_conversions == 1


def test_exposure_keeps_working_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    counter: list[int] = []
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"}, counter=counter)
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        _legacy_with_config(cfg, exposure=0.0),
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    pipeline.read_frame(seq, 0)
    assert pipeline.working_cache_stats.count == 1
    pipeline.set_display_transform(_legacy_with_config(cfg, exposure=2.0))
    assert pipeline.working_cache_stats.count == 1
    assert pipeline.preview_cache_stats.count == 0
    assert len(counter) == 1
    pipeline.read_frame(seq, 0)
    assert pipeline.working_conversions == 1


def test_working_cs_change_clears_working(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        _legacy_with_config(cfg),
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    pipeline.read_frame(seq, 0)
    pipeline.set_working_space_settings(
        WorkingSpaceSettings(enabled=True, working_color_space="ACEScg")
    )
    assert pipeline.working_cache_stats.count == 0
    assert pipeline.preview_cache_stats.count == 0


def test_source_v1_unaffected_by_working(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    off = PreviewPipeline(ImageSequenceReader(), _legacy_with_config(cfg))
    on = PreviewPipeline(
        ImageSequenceReader(),
        _legacy_with_config(cfg),
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    a = off.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    b = on.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert np.array_equal(a, b)
    assert SOURCE_TRANSFORM_VERSION == "source_legacy_srgb_v1"
    assert TrackingConverter.instances == [] or all(
        not c.calls for c in TrackingConverter.instances
    )


def test_unresolved_source_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    # Display ICS forced empty via diagnostics — interpretation blank.
    transform = ViewerDisplayTransform(
        exposure=ExposureTransform(0.0),
        display_transform=LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=str(cfg),
                config_source="explicit",
                display=None,
                view=None,
                input_color_space=" ",
                exposure=0.0,
                fallback_reason=None,
            )
        ),
    )
    # WorkingSpaceSettings enabled but interpretation normalizes?
    # TransformIdentity uses " " as ICS - WorkingSpaceSettings interpretation from session.
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        transform,
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    # Override interpretation to None path: set display with empty becomes strip?
    # WorkingTransformIdentity interpretation from transform - " " stays as input_color_space.
    # resolve_working_source with tag None and interpretation " " -> normalize to None.
    # session stores input_color_space as " " from diagnostics - _normalize in resolve strips to None.
    with pytest.raises(MediaReadError, match="unresolved"):
        pipeline.read_frame(seq, 0)


def test_diagnostics_runtime_working(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        _legacy_with_config(cfg, ics="Linear Rec.709"),
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    pipeline.read_frame(seq, 0)
    snap = build_color_pipeline_diagnostics(pipeline=pipeline, media_path=seq)
    assert snap.working_enabled is True
    assert snap.resolved_working_color_space == "scene_linear"
    assert snap.working_source_color_space == "ACEScg"
    assert snap.working_conversion_applied is True
    assert snap.working_cache.count == 1
    assert snap.interpretation_color_space == "Linear Rec.709"
    text = format_color_pipeline_diagnostics(snap)
    assert "Conversion applied: True" in text
    assert "Working source: ACEScg" in text


def test_get_working_scene_frame_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    cfg = tmp_path / "c.ocio"
    cfg.write_text("x", encoding="utf-8")
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        _legacy_with_config(cfg),
        working_space_settings=WorkingSpaceSettings(
            enabled=True, working_color_space="scene_linear"
        ),
        color_space_converter_cls=TrackingConverter,
    )
    frame = pipeline.get_working_scene_frame(seq, 0)
    assert frame.pixels.dtype == np.float32
    assert float(frame.pixels[0, 0, 0]) == pytest.approx(0.5)
    assert frame.converter_version == WORKING_CONVERTER_VERSION
    assert isinstance(pipeline.get_scene_frame(seq, 0), SceneFrame)
