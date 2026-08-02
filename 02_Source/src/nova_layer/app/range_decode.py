"""Application range-decode helpers on top of MediaReader + FrameDecodeService cache."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.media.pyav_reader import MediaReadError, PyAvMediaReader
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.ports.media import MediaReader

CancelChecker = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class RangeDecodeStats:
    range_size: int
    cache_hits: int
    decoder_opens: int
    decoded_frames: int
    decode_seconds: float
    frame_order: tuple[int, ...]


def decode_frame_range(
    decoder: FrameDecodeService,
    reader: MediaReader,
    path: Path,
    start: int,
    end: int,
    *,
    should_cancel: CancelChecker | None = None,
    report_progress: ProgressCallback | None = None,
) -> tuple[dict[int, NDArray[np.uint8]], RangeDecodeStats]:
    """Decode [start, end] ascending, reusing cache and a single reader session when possible.

    PyAv contiguous misses use ``read_frames`` batch + preview ``put_cached``.
    Other readers (image sequences, stubs) use ``get_preview_frame`` so EXR
    hits share the PreviewPipeline raw + preview caches (no double put /
    double transform).
    """
    if end < start:
        raise MediaReadError(f"Invalid decode range {start}–{end}.")
    resolved = path.expanduser().resolve()
    expected = list(range(start, end + 1))
    frames: dict[int, NDArray[np.uint8]] = {}
    cache_hits = 0
    for frame_number in expected:
        if should_cancel is not None and should_cancel():
            break
        cached = decoder.get_cached(resolved, frame_number)
        if cached is not None:
            frames[frame_number] = cached
            cache_hits += 1
    missing = [frame_number for frame_number in expected if frame_number not in frames]
    decoder_opens = 0
    decoded_frames = 0
    started = perf_counter()
    if missing and (should_cancel is None or not should_cancel()):
        miss_start = missing[0]
        miss_end = missing[-1]
        contiguous = missing == list(range(miss_start, miss_end + 1))
        if isinstance(reader, PyAvMediaReader) and contiguous:
            decoder_opens = 1
            batch = reader.read_frames(resolved, miss_start, miss_end)
            for frame_number in missing:
                if should_cancel is not None and should_cancel():
                    break
                image = batch[frame_number]
                frames[frame_number] = image
                decoded_frames += 1
                # Video path bypasses PreviewPipeline; warm preview once.
                decoder.put_cached(resolved, frame_number, image, expand_to_fit=True)
                if report_progress is not None:
                    report_progress(
                        len(frames),
                        len(expected),
                        f"Decoded frame {frame_number}",
                    )
        else:
            # Image sequences / stubs: pipeline owns decode + preview put.
            for frame_number in missing:
                if should_cancel is not None and should_cancel():
                    break
                decoder_opens += 1
                image = decoder.get_preview_frame(
                    resolved,
                    frame_number,
                    expand_to_fit=True,
                    schedule_prefetch=False,
                )
                frames[frame_number] = image
                decoded_frames += 1
                if report_progress is not None:
                    report_progress(
                        len(frames),
                        len(expected),
                        f"Decoded frame {frame_number}",
                    )
    elapsed = perf_counter() - started
    order = tuple(sorted(frames))
    stats = RangeDecodeStats(
        range_size=len(expected),
        cache_hits=cache_hits,
        decoder_opens=decoder_opens,
        decoded_frames=decoded_frames,
        decode_seconds=elapsed,
        frame_order=order,
    )
    if should_cancel is not None and should_cancel():
        return frames, stats
    still_missing = [frame_number for frame_number in expected if frame_number not in frames]
    if still_missing:
        preview = ", ".join(str(item) for item in still_missing[:8])
        raise MediaReadError(f"Failed to decode required frames: {preview}")
    return frames, stats
