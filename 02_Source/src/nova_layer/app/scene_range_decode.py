"""Scene-linear range decode for True Scene export (Phase 10A).

Does not use ``decode_frame_range(..., policy=SCENE)`` — that path remains rejected.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.ports.scene_frames import SceneFrame

CancelChecker = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


def decode_scene_frame_range(
    decoder: FrameDecodeService,
    path: Path,
    start: int,
    end: int,
    *,
    should_cancel: CancelChecker | None = None,
    report_progress: ProgressCallback | None = None,
) -> dict[int, SceneFrame]:
    """Decode [start, end] ascending via ``get_scene_frame`` (RawFrameCache).

    Preview / Source caches are not used. Non-EXR / missing OIIO raise MediaReadError
    from the decoder (no Pillow fallback).
    """
    if end < start:
        raise ValueError(f"Invalid scene range: start={start}, end={end}")
    cancel = should_cancel or (lambda: False)
    report = report_progress or (lambda *_args: None)
    total = end - start + 1
    frames: dict[int, SceneFrame] = {}
    report(0, total, "Decoding scene frame range")
    for index, frame_number in enumerate(range(start, end + 1), start=1):
        if cancel():
            break
        report(index - 1, total, f"Scene decode frame {frame_number}")
        frames[frame_number] = decoder.get_scene_frame(path, frame_number)
        report(index, total, f"Scene decode frame {frame_number} done")
    return frames
