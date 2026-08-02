"""Scene-linear range decode for True Scene export (Phase 10A / 10A-2).

Does not use ``decode_frame_range(..., policy=SCENE)`` — that path remains rejected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.ports.scene_frames import SceneFrame

CancelChecker = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


def iter_scene_frames(
    decoder: FrameDecodeService,
    path: Path,
    start: int,
    end: int,
    *,
    should_cancel: CancelChecker | None = None,
    report_progress: ProgressCallback | None = None,
) -> Iterator[SceneFrame]:
    """Yield scene frames one at a time via ``get_scene_frame`` (RawFrameCache).

    Does not buffer the full range. Callers should retain at most the current
    yielded frame (plus RawFrameCache's LRU). Preview / Source caches are unused.
    """
    if end < start:
        raise ValueError(f"Invalid scene range: start={start}, end={end}")
    cancel = should_cancel or (lambda: False)
    report = report_progress or (lambda *_args: None)
    total = end - start + 1
    report(0, total, "Decoding scene frame range")
    for index, frame_number in enumerate(range(start, end + 1), start=1):
        if cancel():
            return
        report(index - 1, total, f"Scene decode frame {frame_number}")
        yield decoder.get_scene_frame(path, frame_number)
        report(index, total, f"Scene decode frame {frame_number} done")


def decode_scene_frame_range(
    decoder: FrameDecodeService,
    path: Path,
    start: int,
    end: int,
    *,
    should_cancel: CancelChecker | None = None,
    report_progress: ProgressCallback | None = None,
) -> dict[int, SceneFrame]:
    """Decode [start, end] ascending into a dict (compatibility helper).

    Prefer :func:`iter_scene_frames` for export / long ranges so memory stays
    bounded. This wrapper still materializes the full dict when used.
    """
    frames: dict[int, SceneFrame] = {}
    for scene in iter_scene_frames(
        decoder,
        path,
        start,
        end,
        should_cancel=should_cancel,
        report_progress=report_progress,
    ):
        frames[scene.frame_number] = scene
    return frames
