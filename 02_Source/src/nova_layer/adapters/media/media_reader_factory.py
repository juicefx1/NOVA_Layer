from __future__ import annotations

from pathlib import Path

from nova_layer.adapters.color.display_transform import DisplayTransformProtocol
from nova_layer.ports.media import MediaReader

from .image_sequence_reader import ImageSequenceReader
from .pyav_reader import PyAvMediaReader


class MediaReaderFactory:
    @staticmethod
    def create(
        path: Path,
        *,
        display_transform: DisplayTransformProtocol | None = None,
    ) -> MediaReader:
        resolved = path.expanduser().resolve()

        if resolved.is_dir():
            return ImageSequenceReader(display_transform=display_transform)

        return PyAvMediaReader()
