from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from nova_layer.adapters.color.display_transform import LegacyDisplayTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.media.media_reader_factory import MediaReaderFactory
from nova_layer.adapters.media.pyav_reader import PyAvMediaReader


class RecordingTransform(LegacyDisplayTransform):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[np.ndarray] = []

    def apply(self, image: np.ndarray) -> np.ndarray:
        self.calls.append(np.asarray(image).copy())
        return super().apply(image)


def test_factory_directory_injects_display_transform(tmp_path: Path) -> None:
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(tmp_path / "frame_0001.png")

    transform = RecordingTransform()
    reader = MediaReaderFactory.create(tmp_path, display_transform=transform)
    assert isinstance(reader, ImageSequenceReader)
    assert reader.display_transform is transform


def test_factory_directory_default_is_legacy(tmp_path: Path) -> None:
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(tmp_path / "frame_0001.png")
    reader = MediaReaderFactory.create(tmp_path)
    assert isinstance(reader, ImageSequenceReader)
    assert isinstance(reader.display_transform, LegacyDisplayTransform)


def test_factory_video_file_returns_pyav(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"not-a-real-movie")
    transform = RecordingTransform()
    reader = MediaReaderFactory.create(clip, display_transform=transform)
    assert isinstance(reader, PyAvMediaReader)
