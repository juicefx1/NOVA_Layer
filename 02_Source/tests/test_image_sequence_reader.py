from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.media.image_sequence_reader import (
    ImageSequenceReader,
    list_sequence_files,
    natural_sort_key,
)
from nova_layer.ports.media import MediaReadError


def test_natural_sort_key_orders_numeric_runs() -> None:
    names = ["frame10.png", "frame1.png", "frame2.png"]
    ordered = sorted((Path(name) for name in names), key=natural_sort_key)
    assert [path.name for path in ordered] == [
        "frame1.png",
        "frame2.png",
        "frame10.png",
    ]


def test_natural_sort_key_handles_multiple_numeric_runs() -> None:
    names = [
        "shot01_frame0010.exr",
        "shot01_frame0001.exr",
        "shot01_frame0002.exr",
        "shot02_frame0001.exr",
    ]
    ordered = sorted((Path(name) for name in names), key=natural_sort_key)
    assert [path.name for path in ordered] == [
        "shot01_frame0001.exr",
        "shot01_frame0002.exr",
        "shot01_frame0010.exr",
        "shot02_frame0001.exr",
    ]


def test_natural_sort_key_without_digits_is_stable_lexicographic() -> None:
    names = ["bravo.png", "alpha.png", "charlie.png"]
    ordered = sorted((Path(name) for name in names), key=natural_sort_key)
    assert [path.name for path in ordered] == [
        "alpha.png",
        "bravo.png",
        "charlie.png",
    ]


def test_list_sequence_files_uses_natural_order(tmp_path: Path) -> None:
    for name in ("frame10.png", "frame1.png", "frame2.png"):
        Image.new("RGB", (4, 4), color=(1, 2, 3)).save(tmp_path / name)
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    files = list_sequence_files(tmp_path)
    assert [path.name for path in files] == [
        "frame1.png",
        "frame2.png",
        "frame10.png",
    ]


def test_inspect_and_read_frame_share_natural_order(tmp_path: Path) -> None:
    colors = {
        "frame1.png": (10, 0, 0),
        "frame10.png": (0, 0, 10),
        "frame2.png": (0, 10, 0),
    }
    for name, color in colors.items():
        Image.new("RGB", (2, 2), color=color).save(tmp_path / name)

    reader = ImageSequenceReader()
    info = reader.inspect(tmp_path)
    assert info.frame_count == 3
    assert info.path == tmp_path.resolve()

    first = reader.read_frame(tmp_path, 0)
    second = reader.read_frame(tmp_path, 1)
    tenth = reader.read_frame(tmp_path, 2)
    assert tuple(int(v) for v in first[0, 0]) == (10, 0, 0)
    assert tuple(int(v) for v in second[0, 0]) == (0, 10, 0)
    assert tuple(int(v) for v in tenth[0, 0]) == (0, 0, 10)


def test_inspect_empty_folder_raises(tmp_path: Path) -> None:
    reader = ImageSequenceReader()
    try:
        reader.inspect(tmp_path)
    except MediaReadError as exc:
        assert "No supported image files found" in str(exc)
    else:
        raise AssertionError("expected MediaReadError")


def test_float_rgb_to_preview_u8_supports_float16_and_rgba() -> None:
    from nova_layer.adapters.media.image_sequence_reader import _float_rgb_to_preview_u8

    # Linear mid-gray ~0.18 → sRGB ~118–119
    rgba = np.zeros((1, 1, 4), dtype=np.float16)
    rgba[0, 0, :3] = np.float16(0.18)
    rgba[0, 0, 3] = np.float16(1.0)
    preview = _float_rgb_to_preview_u8(rgba)
    assert preview.dtype == np.uint8
    assert preview.shape == (1, 1, 3)
    assert 110 <= int(preview[0, 0, 0]) <= 130
    assert int(preview[0, 0, 1]) == int(preview[0, 0, 0])

    f32 = np.zeros((1, 1, 3), dtype=np.float32)
    f32[0, 0] = (1.0, 0.0, 0.0)
    assert tuple(int(v) for v in _float_rgb_to_preview_u8(f32)[0, 0]) == (255, 0, 0)


def test_png_path_unaffected_without_openimageio(tmp_path: Path) -> None:
    Image.new("RGB", (3, 3), color=(7, 8, 9)).save(tmp_path / "plate.png")
    reader = ImageSequenceReader()
    info = reader.inspect(tmp_path)
    assert info.frame_count == 1
    frame = reader.read_frame(tmp_path, 0)
    assert frame.dtype == np.uint8
    assert tuple(int(v) for v in frame[0, 0]) == (7, 8, 9)


def test_exr_via_openimageio_when_available(tmp_path: Path) -> None:
    oiio = pytest.importorskip("OpenImageIO")
    path = tmp_path / "linear.exr"
    spec = oiio.ImageSpec(2, 2, 4, oiio.HALF)
    # Linear red = 0.18
    pixels = np.zeros((2, 2, 4), dtype=np.float32)
    pixels[:, :, 0] = 0.18
    pixels[:, :, 3] = 1.0
    buf = oiio.ImageBuf(spec)
    ok = buf.set_pixels(oiio.ROI(0, 2, 0, 2, 0, 1, 0, 4), pixels)
    assert ok
    assert buf.write(str(path))

    reader = ImageSequenceReader()
    info = reader.inspect(tmp_path)
    assert info.frame_count == 1
    assert info.width == 2 and info.height == 2
    frame = reader.read_frame(tmp_path, 0)
    assert frame.shape == (2, 2, 3)
    assert frame.dtype == np.uint8
    assert 110 <= int(frame[0, 0, 0]) <= 130
    assert int(frame[0, 0, 1]) == 0
