from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.ports.media import MediaReadError


class FakeSpec:
    height = 2
    width = 3
    nchannels = 4


class FakeInput:
    def __init__(self, pixels: np.ndarray) -> None:
        self._pixels = pixels

    def spec(self) -> FakeSpec:
        return FakeSpec()

    def read_image(self, _fmt: object) -> np.ndarray:
        return self._pixels

    def close(self) -> None:
        return None


def _install_fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    pixels: np.ndarray,
    *,
    counter: list[int] | None = None,
) -> None:
    class CountingInput(FakeInput):
        def read_image(self, fmt: object) -> np.ndarray:
            if counter is not None:
                counter.append(1)
            return super().read_image(fmt)

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(_path: str) -> CountingInput:
                return CountingInput(pixels)

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )


def test_read_scene_frame_returns_float32_rgb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = tmp_path / "seq"
    seq.mkdir()
    (seq / "frame_0001.exr").write_bytes(b"x")
    rgba = np.zeros((2, 3, 4), dtype=np.float32)
    rgba[:, :, 0] = 0.5
    rgba[:, :, 3] = 0.25
    _install_fake_oiio(monkeypatch, rgba)

    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.pixels.dtype == np.float32
    assert frame.pixels.shape == (2, 3, 3)
    assert frame.width == 3
    assert frame.height == 2
    assert frame.channels == 3
    assert frame.pixel_format == "float32_rgb"
    assert float(frame.pixels[0, 0, 0]) == pytest.approx(0.5)
    assert frame.pixels.shape[2] == 3


def test_read_scene_frame_natural_sort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = tmp_path / "seq"
    seq.mkdir()
    for name in ("frame10.exr", "frame2.exr", "frame1.exr"):
        (seq / name).write_bytes(b"x")

    calls: list[str] = []

    class TrackingInput(FakeInput):
        def __init__(self, path: str, pixels: np.ndarray) -> None:
            super().__init__(pixels)
            calls.append(Path(path).name)

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(path: str) -> TrackingInput:
                return TrackingInput(path, np.ones((1, 1, 3), dtype=np.float32))

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )
    ImageSequenceReader().read_scene_frame(seq, 0)
    assert calls == ["frame1.exr"]


def test_read_scene_frame_png_unsupported(tmp_path: Path) -> None:
    from PIL import Image

    seq = tmp_path / "seq"
    seq.mkdir()
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(seq / "a.png")
    with pytest.raises(MediaReadError, match="only supported for EXR"):
        ImageSequenceReader().read_scene_frame(seq, 0)


def test_read_scene_frame_without_oiio_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = tmp_path / "seq"
    seq.mkdir()
    (seq / "a.exr").write_bytes(b"x")
    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: None,
    )
    with pytest.raises(MediaReadError, match="OpenImageIO is required"):
        ImageSequenceReader().read_scene_frame(seq, 0)


def test_nan_inf_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = tmp_path / "seq"
    seq.mkdir()
    (seq / "a.exr").write_bytes(b"x")
    pixels = np.array([[[np.nan, -np.inf, np.inf]]], dtype=np.float32)
    _install_fake_oiio(monkeypatch, pixels)
    frame = ImageSequenceReader().read_scene_frame(seq, 0)
    assert frame.pixels[0, 0, 0] == 0.0
    assert frame.pixels[0, 0, 1] == 0.0
    assert frame.pixels[0, 0, 2] == np.finfo(np.float32).max
