from __future__ import annotations

from pathlib import Path

from nova_layer.ports.media import MediaReader

from .image_sequence_reader import ImageSequenceReader
from .pyav_reader import PyAvMediaReader


class MediaReaderFactory:
    @staticmethod
    def create(path: Path) -> MediaReader:
        resolved = path.expanduser().resolve()

        if resolved.is_dir():
            return ImageSequenceReader()

        return PyAvMediaReader()
