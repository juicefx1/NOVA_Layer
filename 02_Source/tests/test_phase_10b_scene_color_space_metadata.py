"""Phase 10B: SceneFrame color-space tags, SOURCE warnings, True Scene metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.app.color_pipeline_diagnostics import (
    build_color_pipeline_diagnostics,
    format_color_pipeline_diagnostics,
)
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.preview_pipeline import PreviewPipeline
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.raw_frame_cache import RawFrameCache
from nova_layer.app.render_color_metadata import (
    build_render_color_metadata,
    write_render_color_metadata,
)
from nova_layer.app.scene_color_space import source_transform_warning
from nova_layer.domain.models import ExtractionPreview, SmartLayerRender
from nova_layer.export.scene_exr import build_scene_export_manifest_fields
from nova_layer.export.smart_layer import ExportFormat, export_smart_layer_assets
from nova_layer.ports.scene_frames import SceneFrame


class _RecordingDisplay:
    """Records apply() source tags; returns Legacy bake of pixels."""

    def __init__(self, *, label: str = "rec") -> None:
        self.label = label
        self.calls: list[np.ndarray] = []
        self.src_requests: list[str] = []
        self._legacy = LegacyDisplayTransform()
        self.diagnostics = DisplayTransformDiagnostics(
            backend="legacy",
            ocio_available=False,
            config_path=None,
            config_source=None,
            input_color_space=label,
            display="sRGB",
            view="Raw",
            exposure=0.0,
            fallback_reason=None,
        )

    def apply(self, pixels: np.ndarray) -> np.ndarray:
        self.calls.append(np.array(pixels, copy=True))
        self.src_requests.append(self.label)
        return self._legacy.apply(pixels)


class _AttrSpec:
    def __init__(
        self,
        *,
        height: int = 2,
        width: int = 2,
        nchannels: int = 3,
        attrs: dict[str, Any] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self.height = height
        self.width = width
        self.nchannels = nchannels
        self._attrs = attrs or {}
        self._raise_on = raise_on

    def get_string_attribute(self, key: str, default: str = "") -> str:
        if self._raise_on == key:
            raise RuntimeError("malformed attribute")
        value = self._attrs.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            # Malformed non-string: coerce path used by production probe.
            return str(value)
        return value


def _install_fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    pixels: np.ndarray,
    *,
    attrs: dict[str, Any] | None = None,
    raise_on: str | None = None,
    counter: list[int] | None = None,
) -> None:
    class FakeInput:
        def spec(self) -> _AttrSpec:
            return _AttrSpec(
                height=int(pixels.shape[0]),
                width=int(pixels.shape[1]),
                nchannels=int(pixels.shape[2]) if pixels.ndim == 3 else 3,
                attrs=attrs,
                raise_on=raise_on,
            )

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


def _scene_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attrs: dict[str, Any] | None = None,
    frames: int = 1,
) -> tuple[Path, Path, SmartLayerRender, FrameDecodeService]:
    pixels = np.full((2, 2, 3), 0.4, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs=attrs)
    media = _exr_seq(tmp_path, frames=frames)
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    mask_store = PngMaskStore()
    render_frames: list[ExtractionPreview] = []
    checksums: dict[str, str] = {}
    for index in range(frames):
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        rgba[..., :3] = 40
        rgba[..., 3] = 200
        ref = f"renders/v0001/frame_{index:06d}.png"
        mask_ref = f"masks/frame_{index:06d}.png"
        store.save(package, ref, rgba)
        mask_store.save(package, mask_ref, np.full((2, 2), 200, dtype=np.uint8))
        render_frames.append(
            ExtractionPreview(
                frame_number=index,
                image_reference=ref,
                mask_reference=mask_ref,
            )
        )
        checksums[ref] = "x"
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=frames - 1,
        frames=render_frames,
        checksums=checksums,
    )
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    return package, media, render, decoder


# ---------------------------------------------------------------------------
# SceneFrame tags
# ---------------------------------------------------------------------------


def test_scene_frame_default_tags() -> None:
    frame = SceneFrame(
        path=Path("/tmp"),
        frame_number=0,
        pixels=np.zeros((1, 1, 3), dtype=np.float32),
        width=1,
        height=1,
    )
    assert frame.color_space is None
    assert frame.color_space_source == "unspecified"


def test_scene_frame_tagged_roundtrip() -> None:
    frame = SceneFrame(
        path=Path("/tmp"),
        frame_number=0,
        pixels=np.ones((1, 1, 3), dtype=np.float32),
        width=1,
        height=1,
        color_space="ACEScg",
        color_space_source="oiio",
    )
    assert frame.color_space == "ACEScg"
    assert frame.color_space_source == "oiio"


def test_raw_cache_preserves_tags() -> None:
    cache = RawFrameCache(max_entries=2, max_bytes=10_000)
    original = SceneFrame(
        path=Path("/tmp/seq").resolve(),
        frame_number=0,
        pixels=np.full((2, 2, 3), 0.5, dtype=np.float32),
        width=2,
        height=2,
        color_space="ACEScg",
        color_space_source="oiio",
    )
    assert cache.put(original) is True
    got = cache.get(original.path, 0)
    assert got is not None
    assert got.color_space == "ACEScg"
    assert got.color_space_source == "oiio"
    assert got.pixels is not original.pixels
    got.pixels[0, 0, 0] = 0.0
    again = cache.get(original.path, 0)
    assert again is not None
    assert float(again.pixels[0, 0, 0]) == pytest.approx(0.5)
    assert again.color_space == "ACEScg"


# ---------------------------------------------------------------------------
# OIIO probe
# ---------------------------------------------------------------------------


def test_oiio_colorspace_primary_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.color_space == "ACEScg"
    assert frame.color_space_source == "oiio"


def test_oiio_colorspace_fallback_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"ColorSpace": "Linear Rec.709"})
    seq = _exr_seq(tmp_path)
    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.color_space == "Linear Rec.709"
    assert frame.color_space_source == "oiio"


def test_oiio_no_metadata_unspecified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={})
    seq = _exr_seq(tmp_path)
    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.color_space is None
    assert frame.color_space_source == "unspecified"


def test_oiio_malformed_metadata_still_decodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.33, dtype=np.float32)
    _install_fake_oiio(
        monkeypatch,
        pixels,
        attrs={"oiio:ColorSpace": "should-not-win"},
        raise_on="oiio:ColorSpace",
    )
    # Primary key raises; fallback empty → unspecified, pixels still ok.
    seq = _exr_seq(tmp_path)
    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.pixels.dtype == np.float32
    assert float(frame.pixels[0, 0, 0]) == pytest.approx(0.33)
    assert frame.color_space_source == "unspecified"


# ---------------------------------------------------------------------------
# PREVIEW / SOURCE behaviour
# ---------------------------------------------------------------------------


def test_preview_uses_input_color_space_not_scene_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    transform = _RecordingDisplay(label="Linear Rec.709")
    pipeline = PreviewPipeline(ImageSequenceReader(), transform)
    pipeline.read_frame(seq, 0)
    scene = pipeline.get_scene_frame(seq, 0)
    assert scene.color_space == "ACEScg"
    assert transform.src_requests == ["Linear Rec.709"]
    assert transform.diagnostics.input_color_space == "Linear Rec.709"


def test_source_warning_acescg() -> None:
    warn = source_transform_warning("ACEScg")
    assert warn is not None
    assert "ACEScg" in warn


def test_source_warning_rec709_none() -> None:
    assert source_transform_warning("Linear Rec.709") is None
    assert source_transform_warning("Utility - Linear - sRGB") is None
    assert source_transform_warning("scene_linear") is None
    assert source_transform_warning(None) is None


def test_source_pixels_bit_identical_with_aces_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    tagged = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    expected = LegacyDisplayTransform().apply(pixels)
    assert np.array_equal(tagged, expected)
    assert pipeline.source_color_space_warning(seq, 0) is not None


def test_source_pixels_same_as_untagged_rec709(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq_a = _exr_seq(tmp_path / "a")
    pipe_a = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    a = pipe_a.get_processing_frame(seq_a, 0, policy=ProcessingColorPolicy.SOURCE)

    other = tmp_path / "other"
    other.mkdir()
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear Rec.709"})
    seq_b = _exr_seq(other)
    pipe_b = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    b = pipe_b.get_processing_frame(seq_b, 0, policy=ProcessingColorPolicy.SOURCE)
    assert np.array_equal(a, b)


def test_source_independent_of_exposure_with_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    first = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(3.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    second = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert np.array_equal(first, second)


def test_ics_change_keeps_raw_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    counter: list[int] = []
    _install_fake_oiio(
        monkeypatch,
        pixels,
        attrs={"oiio:ColorSpace": "ACEScg"},
        counter=counter,
    )
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        _RecordingDisplay(label="scene_linear"),
    )
    pipeline.read_frame(seq, 0)
    raw_count = pipeline.raw_cache_stats.count
    raw_bytes = pipeline.raw_cache_stats.current_bytes
    assert raw_count == 1
    assert len(counter) == 1
    tagged = pipeline.get_scene_frame(seq, 0)
    assert tagged.color_space == "ACEScg"
    pipeline.set_display_transform(_RecordingDisplay(label="Raw"))
    assert pipeline.raw_cache_stats.count == raw_count
    assert pipeline.raw_cache_stats.current_bytes == raw_bytes
    assert pipeline.preview_cache_stats.count == 0
    again = pipeline.get_scene_frame(seq, 0)
    assert again.color_space == "ACEScg"
    assert len(counter) == 1


# ---------------------------------------------------------------------------
# True Scene export metadata
# ---------------------------------------------------------------------------


def test_true_scene_manifest_source_vs_interpretation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder = _scene_package(
        tmp_path,
        monkeypatch,
        attrs={"oiio:ColorSpace": "ACEScg"},
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="scene_meta",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        media_fingerprint="fp",
        input_color_space="Linear Rec.709",
        config_path="/tmp/config.ocio",
        config_source="env",
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_color_space"] == "ACEScg"
    assert manifest["source_color_space_source"] == "oiio"
    assert manifest["interpretation_color_space"] == "Linear Rec.709"
    assert manifest["export_color_space"] == "ACEScg"
    assert manifest["working_color_space"] is None
    assert manifest["color_transform_applied"] is False
    assert manifest["scene_display_transformed"] is False
    assert manifest["scene_linear"] is True
    assert manifest["pixel_encoding"] == "file_native_scene_half"
    assert manifest["render_source"] == "scene"
    assert manifest["ocio_config_identity"] == {
        "config_path": "/tmp/config.ocio",
        "config_source": "env",
    }
    policy = manifest["color_policy"]
    assert policy["source_color_space"] == "ACEScg"
    assert policy["interpretation_color_space"] == "Linear Rec.709"
    assert policy["export_color_space"] == "ACEScg"
    assert policy["input_color_space"] == "Linear Rec.709"


def test_true_scene_unknown_source_not_equal_interpretation() -> None:
    fields = build_scene_export_manifest_fields(
        source_color_space=None,
        source_color_space_source="unspecified",
        interpretation_color_space="ACEScg",
        frame_start=0,
        frame_end=0,
    )
    assert fields["source_color_space"] == "unspecified"
    assert fields["interpretation_color_space"] == "ACEScg"
    assert fields["export_color_space"] == "unspecified"
    assert fields["source_color_space"] != fields["interpretation_color_space"]
    assert fields["color_transform_applied"] is False
    assert fields["pixel_encoding"] == "file_native_scene_half"


def test_legacy_openexr_manifest_differs_from_true_scene(
    tmp_path: Path,
) -> None:
    pytest.importorskip("OpenEXR")
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., :3] = 64
    rgba[..., 3] = 255
    reference = "renders/v0001/frame_000000.png"
    store.save(package, reference, rgba)
    write_render_color_metadata(
        package / "renders" / "v0001",
        build_render_color_metadata(ProcessingColorPolicy.SOURCE),
    )
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference=reference,
                mask_reference="masks/x.png",
            )
        ],
        checksums={reference: "x"},
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="u8_exr",
        render=render,
        format=ExportFormat.OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scene_linear"] is False
    assert manifest["pixel_encoding"] == "display_or_source_uint8_scaled"
    assert "source_color_space" not in manifest or manifest.get("export_mode") != "compose_scene"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_exposes_source_interpretation_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "ACEScg"})
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    pipeline.get_scene_frame(seq, 0)
    snap = build_color_pipeline_diagnostics(
        pipeline=pipeline,
        transform_diagnostics=DisplayTransformDiagnostics(
            backend="legacy",
            ocio_available=False,
            config_path=None,
            config_source=None,
            input_color_space="Linear Rec.709",
            display=None,
            view=None,
            exposure=0.0,
            fallback_reason=None,
        ),
        media_path=seq,
    )
    assert snap.active_source_color_space == "ACEScg"
    assert snap.source_color_space_source == "oiio"
    assert snap.interpretation_color_space == "Linear Rec.709"
    assert snap.source_transform_warning is not None
    text = format_color_pipeline_diagnostics(snap)
    assert "ACEScg" in text
    assert "Linear Rec.709" in text
    assert "SOURCE transform warning" in text


def test_diagnostics_no_active_frame_safe() -> None:
    snap = build_color_pipeline_diagnostics()
    assert snap.active_source_color_space is None
    assert snap.source_color_space_source is None
    assert snap.source_transform_warning is None
    assert snap.interpretation_color_space is None
    text = format_color_pipeline_diagnostics(snap)
    assert "Active source color space" in text
