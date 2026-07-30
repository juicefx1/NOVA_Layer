from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from nova_layer.adapters.media.pyav_reader import PyAvMediaReader


def create_test_video(path: Path, frame_count: int = 6) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=12)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 12)
        for index in range(frame_count):
            pixels = np.full((48, 64, 3), index * 20, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_pyav_inspection_and_decode(tmp_path: Path) -> None:
    media_path = tmp_path / "sample.mp4"
    create_test_video(media_path)
    reader = PyAvMediaReader()

    info = reader.inspect(media_path)
    frame = reader.read_frame(media_path, 3)

    assert info.frame_count == 6
    assert info.frame_rate == 12.0
    assert (info.width, info.height) == (64, 48)
    assert info.fingerprint.startswith("sha256:")
    assert frame.shape == (48, 64, 3)
