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
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.ports.media import MediaReader

CancelChecker = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class RangeDecodeStats:
    """Range-decode diagnostics.

    ``cache_hits`` counts frames that were already available from the decoder
    for the active ``policy`` before a decode pass (preview cache for PREVIEW,
    source cache for SOURCE). Not limited to preview-only semantics.
    """

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
    policy: ProcessingColorPolicy = ProcessingColorPolicy.PREVIEW,
    should_cancel: CancelChecker | None = None,
    report_progress: ProgressCallback | None = None,
) -> tuple[dict[int, NDArray[np.uint8]], RangeDecodeStats]:
    """Decode [start, end] ascending for the given ``policy``.

    Default ``policy`` is PREVIEW (viewer / export / BG removal).

    PREVIEW:
        PyAv contiguous misses use ``read_frames`` + preview ``put_cached``.
        Other readers use ``get_preview_frame`` (raw + preview caches).

    SOURCE:
        PyAv contiguous misses still use ``read_frames`` (single container),
        but do **not** warm the preview cache. Image sequences use
        ``get_processing_frame(..., SOURCE)`` (raw + source caches).

    SCENE:
        Not supported for range decode — raises MediaReadError.
    """
    if end < start:
        raise MediaReadError(f"Invalid decode range {start}–{end}.")
    if policy is ProcessingColorPolicy.SCENE:
        raise MediaReadError(
            "decode_frame_range does not support ProcessingColorPolicy.SCENE; "
            "use get_scene_frame for single-frame scene access."
        )
    if policy not in (ProcessingColorPolicy.PREVIEW, ProcessingColorPolicy.SOURCE):
        raise MediaReadError(f"Unsupported range decode policy: {policy!r}")

    resolved = path.expanduser().resolve()
    expected = list(range(start, end + 1))
    frames: dict[int, NDArray[np.uint8]] = {}
    cache_hits = 0
    for frame_number in expected:
        if should_cancel is not None and should_cancel():
            break
        if policy is ProcessingColorPolicy.PREVIEW:
            cached = decoder.get_cached(resolved, frame_number)
        else:
            cached = decoder.get_source_cached(resolved, frame_number)
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
                # PREVIEW only: warm preview cache. SOURCE must not pollute it.
                if policy is ProcessingColorPolicy.PREVIEW:
                    decoder.put_cached(
                        resolved, frame_number, image, expand_to_fit=True
                    )
                if report_progress is not None:
                    report_progress(
                        len(frames),
                        len(expected),
                        f"Decoded frame {frame_number}",
                    )
        elif policy is ProcessingColorPolicy.PREVIEW:
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
        else:
            # SOURCE / image-sequence (and non-contiguous stubs)
            for frame_number in missing:
                if should_cancel is not None and should_cancel():
                    break
                decoder_opens += 1
                image = decoder.get_processing_frame(
                    resolved,
                    frame_number,
                    policy=ProcessingColorPolicy.SOURCE,
                )
                if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
                    raise MediaReadError(
                        f"SOURCE range frame {frame_number} must be uint8 RGB, "
                        f"got {type(image).__name__}"
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
