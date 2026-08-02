from pathlib import Path

import numpy as np

from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.ports.media import MediaInfo


class CountingReader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def inspect(self, path: Path) -> MediaInfo:
        raise NotImplementedError

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        self.calls.append(frame_number)
        return np.full((8, 12, 3), frame_number, dtype=np.uint8)


def test_frame_decoder_uses_lru_cache(qtbot: object, tmp_path: Path) -> None:
    reader = CountingReader()
    service = FrameDecodeService(reader, cache_size=2, prefetch_count=0)
    media = tmp_path / "source.mov"

    with qtbot.waitSignal(service.frame_ready):  # type: ignore[attr-defined]
        service.request(media, 4)
    with qtbot.waitSignal(service.frame_ready):  # type: ignore[attr-defined]
        service.request(media, 4)

    assert reader.calls == [4]
    assert service.cache_count == 1


def test_lru_cache_is_bounded(qtbot: object, tmp_path: Path) -> None:
    reader = CountingReader()
    service = FrameDecodeService(reader, cache_size=2, prefetch_count=0)
    media = tmp_path / "source.mov"

    for frame_number in (1, 2, 3):
        with qtbot.waitSignal(service.frame_ready):  # type: ignore[attr-defined]
            service.request(media, frame_number)

    assert service.cache_count == 2
    with qtbot.waitSignal(service.frame_ready):  # type: ignore[attr-defined]
        service.request(media, 1)
    assert reader.calls == [1, 2, 3, 1]
