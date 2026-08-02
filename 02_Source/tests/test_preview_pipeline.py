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
from nova_layer.app.preview_pipeline import PreviewPipeline, TransformIdentity
from nova_layer.ports.media import MediaInfo


class CountingUint8Reader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def inspect(self, path: Path) -> MediaInfo:
        raise NotImplementedError

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        self.calls.append(frame_number)
        return np.full((4, 4, 3), frame_number, dtype=np.uint8)


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


def _exr_seq(tmp_path: Path) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    (seq / "frame_0001.exr").write_bytes(b"x")
    (seq / "frame_0002.exr").write_bytes(b"x")
    return seq


def test_exposure_change_reuses_raw_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    base = ViewerDisplayTransform(
        exposure=ExposureTransform(0.0),
        display_transform=LegacyDisplayTransform(),
    )
    pipeline = PreviewPipeline(reader, base, raw_cache_size=4, preview_cache_size=8)

    first = pipeline.read_frame(seq, 0)
    assert len(counter) == 1

    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    second = pipeline.read_frame(seq, 0)
    assert len(counter) == 1
    assert int(second[0, 0, 0]) > int(first[0, 0, 0])
    assert pipeline.raw_cache.count == 1


def test_identical_transform_preview_cache_hit(
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
    pipeline.read_frame(seq, 0)
    pipeline.read_frame(seq, 0)
    assert len(counter) == 1
    assert pipeline.preview_cache_count == 1


def test_png_uses_reader_path(tmp_path: Path) -> None:
    seq = tmp_path / "png"
    seq.mkdir()
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(seq / "a.png")
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    frame = pipeline.read_frame(seq, 0)
    assert frame.dtype == np.uint8
    assert tuple(int(v) for v in frame[0, 0]) == (10, 20, 30)
    assert pipeline.raw_cache.count == 0


def test_video_like_reader_passthrough(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    pipeline = PreviewPipeline(reader, LegacyDisplayTransform())
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    frame = pipeline.read_frame(media, 3)
    assert reader.calls == [3]
    assert frame.dtype == np.uint8


def test_transform_identity_exposure_differs() -> None:
    a = TransformIdentity.from_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    b = TransformIdentity.from_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    assert a != b
    assert a.exposure == pytest.approx(0.0)
    assert b.exposure == pytest.approx(1.0)


def test_prefetch_raw_warms_next_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(ImageSequenceReader(), LegacyDisplayTransform())
    pipeline.read_frame(seq, 0)
    assert len(counter) == 1
    pipeline.prefetch_raw(seq, 0, 1, is_current=lambda: True)
    assert len(counter) == 2
    assert pipeline.raw_cache.contains(seq, 1)

    # Stale generation: should not add more when is_current is False mid-run.
    before = len(counter)
    pipeline.prefetch_raw(seq, 0, 1, is_current=lambda: False)
    assert len(counter) == before
