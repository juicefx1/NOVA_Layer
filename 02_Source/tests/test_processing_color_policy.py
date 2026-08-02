"""Phase 8C-2: ProcessingColorPolicy / SOURCE bake / cache isolation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.preview_pipeline import PreviewPipeline
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.ports.media import MediaInfo, MediaReadError
from nova_layer.ports.scene_frames import SceneFrame


class CountingUint8Reader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def inspect(self, path: Path) -> MediaInfo:
        raise NotImplementedError

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        self.calls.append(frame_number)
        return np.full((4, 4, 3), frame_number % 256, dtype=np.uint8)


def _fake_oiio(monkeypatch: pytest.MonkeyPatch, counter: list[int]) -> None:
    class FakeSpec:
        height = 1
        width = 1
        nchannels = 3

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            counter.append(1)
            return np.array([[[0.25, 0.25, 0.25]]], dtype=np.float32)

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


def _exr_seq(tmp_path: Path, frames: int = 2) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


def _png_seq(tmp_path: Path, frames: int = 2) -> Path:
    seq = tmp_path / "png"
    seq.mkdir()
    for index in range(frames):
        Image.new("RGB", (4, 4), color=(10 * (index + 1), 20, 30)).save(
            seq / f"frame_{index:04d}.png"
        )
    return seq


def test_preview_policy_bit_identical_to_get_preview_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    service = FrameDecodeService(
        ImageSequenceReader(),
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    a = service.get_preview_frame(seq, 0, schedule_prefetch=False)
    b = service.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.PREVIEW)
    assert isinstance(b, np.ndarray)
    np.testing.assert_array_equal(a, b)
    assert b.dtype == np.uint8


def test_scene_policy_returns_float32(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    scene = service.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SCENE)
    assert isinstance(scene, SceneFrame)
    assert scene.pixels.dtype == np.float32


def test_source_policy_uint8_rgb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    frame = service.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert isinstance(frame, np.ndarray)
    assert frame.dtype == np.uint8
    assert frame.shape == (1, 1, 3)


def test_source_stable_across_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    source_a = pipeline.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    preview_a = pipeline.read_frame(seq, 0)
    assert isinstance(source_a, np.ndarray)
    assert len(counter) == 1

    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    assert pipeline.preview_cache_stats.count == 0
    assert pipeline.source_cache_stats.count >= 1
    assert pipeline.raw_cache_stats.count >= 1

    source_b = pipeline.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    preview_b = pipeline.read_frame(seq, 0)
    assert isinstance(source_b, np.ndarray)
    np.testing.assert_array_equal(source_a, source_b)
    assert not np.array_equal(preview_a, preview_b)
    assert len(counter) == 1  # raw reuse; no extra OIIO


def test_source_stable_across_display_view_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)

    class TaggedLegacy(LegacyDisplayTransform):
        def __init__(self, tag: int) -> None:
            super().__init__()
            self.tag = tag
            # Distinct diagnostics so TransformIdentity differs.
            self.diagnostics = self.diagnostics.__class__(
                backend="legacy",
                ocio_available=False,
                config_path=None,
                config_source=None,
                display=f"disp{tag}",
                view=f"view{tag}",
                input_color_space="scene_linear",
                exposure=0.0,
            )

        def apply(self, image: np.ndarray) -> np.ndarray:
            base = super().apply(image)
            # Tint preview path only (SOURCE uses fixed Legacy instance).
            out = base.copy()
            out[..., 0] = np.clip(out[..., 0].astype(np.int16) + self.tag * 10, 0, 255).astype(
                np.uint8
            )
            return out

    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=TaggedLegacy(1),
        ),
    )
    source_a = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=TaggedLegacy(5),
        )
    )
    source_b = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert isinstance(source_a, np.ndarray) and isinstance(source_b, np.ndarray)
    np.testing.assert_array_equal(source_a, source_b)
    assert len(counter) == 1


def test_source_cache_hit_no_extra_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    hits_before = pipeline.source_cache_stats.hits
    pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert pipeline.source_cache_stats.hits == hits_before + 1
    assert len(counter) == 1


def test_source_and_preview_caches_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        ),
        preview_cache_size=8,
    )
    source = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    preview = pipeline.read_frame(seq, 0)
    assert isinstance(source, np.ndarray)
    assert not np.array_equal(source, preview)
    assert pipeline.source_cache_stats.count == 1
    assert pipeline.preview_cache_stats.count == 1
    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    assert pipeline.preview_cache_stats.count == 0
    assert pipeline.source_cache_stats.count == 1


def test_png_source_uses_reader_uint8(tmp_path: Path) -> None:
    seq = _png_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(3.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    frame = pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    assert isinstance(frame, np.ndarray)
    assert tuple(int(v) for v in frame[0, 0]) == (10, 20, 30)


def test_video_like_source(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    pipeline = PreviewPipeline(reader, LegacyDisplayTransform())
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    frame = pipeline.get_processing_frame(media, 2, policy=ProcessingColorPolicy.SOURCE)
    assert isinstance(frame, np.ndarray)
    assert reader.calls == [2]
    assert frame.dtype == np.uint8


def test_scene_non_exr_raises(tmp_path: Path) -> None:
    seq = _png_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    with pytest.raises(MediaReadError, match="EXR"):
        service.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SCENE)


def test_scene_without_oiio_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: None,
    )
    seq = _exr_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    with pytest.raises(MediaReadError):
        service.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SCENE)


def test_source_without_oiio_uses_pillow_or_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: None,
    )
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())

    def _fail_pillow(_path: Path) -> np.ndarray:
        raise MediaReadError("pillow unavailable")

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._read_exr_pillow",
        _fail_pillow,
    )
    with pytest.raises(MediaReadError):
        pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
