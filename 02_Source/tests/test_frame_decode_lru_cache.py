from __future__ import annotations

from pathlib import Path
from time import perf_counter, sleep

import numpy as np

from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.ports.media import MediaInfo, MediaReadError


class CountingReader:
    def __init__(self, *, max_frame: int | None = None) -> None:
        self.calls: list[int] = []
        self._max_frame = max_frame

    def inspect(self, path: Path) -> MediaInfo:
        raise NotImplementedError

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        if self._max_frame is not None and frame_number > self._max_frame:
            raise MediaReadError(f"Frame {frame_number} is outside the media range.")
        self.calls.append(frame_number)
        return np.full((8, 12, 3), frame_number, dtype=np.uint8)


def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = perf_counter() + timeout
    while perf_counter() < deadline:
        if predicate():
            return True
        sleep(0.01)
    return False


def test_read_frame_lru_cache_avoids_second_reader_call(tmp_path: Path) -> None:
    reader = CountingReader()
    service = FrameDecodeService(reader, cache_size=32, prefetch_count=0)
    media = tmp_path / "source.mov"

    first = service.read_frame(media, 7)
    second = service.read_frame(media, 7)

    assert reader.calls == [7]
    assert first.dtype == np.uint8
    assert np.array_equal(first, second)
    assert service.cache_count == 1


def test_replacing_reader_clears_frame_cache(tmp_path: Path) -> None:
    first_reader = CountingReader()
    second_reader = CountingReader()
    service = FrameDecodeService(first_reader, cache_size=8, prefetch_count=0)
    media = tmp_path / "source.mov"

    service.read_frame(media, 3)
    assert service.cache_count == 1

    service.reader = second_reader
    assert service.cache_count == 0

    service.read_frame(media, 3)
    assert first_reader.calls == [3]
    assert second_reader.calls == [3]


def test_prefetch_fills_upcoming_frames(tmp_path: Path) -> None:
    reader = CountingReader()
    service = FrameDecodeService(reader, cache_size=32, prefetch_count=4)
    media = tmp_path / "source.mov"

    service.read_frame(media, 10)
    assert _wait_until(
        lambda: all(service.get_cached(media, frame) is not None for frame in range(10, 15))
    )
    assert set(reader.calls) >= {10, 11, 12, 13, 14}
    assert service.get_cached(media, 10) is not None
    assert service.get_cached(media, 14) is not None


def test_prefetched_frame_does_not_increase_reader_calls(tmp_path: Path) -> None:
    reader = CountingReader()
    service = FrameDecodeService(reader, cache_size=32, prefetch_count=4)
    media = tmp_path / "source.mov"

    service.read_frame(media, 0)
    assert _wait_until(
        lambda: all(service.get_cached(media, frame) is not None for frame in range(0, 5))
    )
    calls_after_prefetch = list(reader.calls)

    again = service.read_frame(media, 3)
    assert np.array_equal(again[0, 0], np.array([3, 3, 3], dtype=np.uint8))
    assert reader.calls == calls_after_prefetch


def test_prefetch_failures_are_swallowed(tmp_path: Path) -> None:
    reader = CountingReader(max_frame=0)
    service = FrameDecodeService(reader, cache_size=32, prefetch_count=4)
    media = tmp_path / "source.mov"

    frame = service.read_frame(media, 0)
    assert frame.shape == (8, 12, 3)
    assert _wait_until(lambda: reader.calls == [0] or len(reader.calls) >= 1)
    sleep(0.05)
    assert reader.calls[0] == 0
    assert service.get_cached(media, 0) is not None
