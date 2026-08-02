"""End-to-end integration for image-sequence Smart Layer media path (no GUI windows)."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import numpy as np
from PIL import Image

from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.media.media_reader_factory import MediaReaderFactory
from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import MediaLinkState


def _write_png(path: Path, *, color: tuple[int, int, int], size: tuple[int, int] = (16, 8)) -> None:
    Image.new("RGB", size, color=color).save(path)


def _make_sequence(
    folder: Path,
    *,
    colors: dict[str, tuple[int, int, int]] | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    palette = colors or {
        "frame_0001.png": (10, 0, 0),
        "frame_0002.png": (0, 20, 0),
        "frame_0010.png": (0, 0, 30),
    }
    for name, color in palette.items():
        _write_png(folder / name, color=color)
    return folder


def _wait_until(predicate: Any, *, timeout: float = 2.0) -> bool:
    deadline = perf_counter() + timeout
    while perf_counter() < deadline:
        if predicate():
            return True
        sleep(0.01)
    return False


def _install_read_counter(reader: ImageSequenceReader) -> list[int]:
    calls: list[int] = []
    original = reader.read_frame

    def counted(path: Path, frame_number: int) -> np.ndarray:
        calls.append(frame_number)
        return original(path, frame_number)

    reader.read_frame = counted  # type: ignore[method-assign]
    return calls


def test_media_reader_factory_selects_image_sequence_for_directory(tmp_path: Path) -> None:
    sequence = _make_sequence(tmp_path / "seq")
    assert isinstance(MediaReaderFactory.create(sequence), ImageSequenceReader)
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"not-a-real-mov")
    assert isinstance(MediaReaderFactory.create(clip), PyAvMediaReader)


def test_image_sequence_import_decode_cache_prefetch_validate_relink(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    sequence = _make_sequence(tmp_path / "plates")
    relink_sequence = _make_sequence(
        tmp_path / "plates_relink",
        colors={
            "frame_0001.png": (40, 0, 0),
            "frame_0002.png": (0, 50, 0),
            "frame_0010.png": (0, 0, 60),
            "frame_0011.png": (70, 70, 70),
        },
    )

    errors: list[str] = []
    controller = ProjectController()
    controller.error_occurred.connect(errors.append)

    assert controller.create_project("Sequence E2E", project_root) is not None

    shot = controller.import_media(sequence)
    assert shot is not None
    assert errors == []
    assert isinstance(controller._media_reader, ImageSequenceReader)

    assert shot.media.frame_count == 3
    assert shot.media.width == 16
    assert shot.media.height == 8
    assert shot.media.source_path is not None
    assert Path(shot.media.source_path).resolve() == sequence.resolve()
    assert shot.media.link_state == MediaLinkState.LINKED
    assert shot.master_frame == 1
    assert shot.range_start == 0
    assert shot.range_end == 2

    # Natural order: 0001, 0002, 0010 → RGB markers match file colors.
    media_path = Path(shot.media.source_path)
    decoder = controller._frame_decoder
    frame0 = decoder.read_frame(media_path, 0)
    frame1 = decoder.read_frame(media_path, 1)
    frame2 = decoder.read_frame(media_path, 2)
    assert tuple(int(v) for v in frame0[0, 0]) == (10, 0, 0)
    assert tuple(int(v) for v in frame1[0, 0]) == (0, 20, 0)
    assert tuple(int(v) for v in frame2[0, 0]) == (0, 0, 30)

    # Master-frame decode path used by import_media / request_frame.
    master = decoder.read_frame(media_path, shot.master_frame)
    assert tuple(int(v) for v in master[0, 0]) == (0, 20, 0)

    # LRU + Prefetch: count real ImageSequenceReader.read_frame calls.
    reader = controller._media_reader
    assert isinstance(reader, ImageSequenceReader)
    calls = _install_read_counter(reader)
    decoder.reader = reader  # clears cache; same reader instance keeps the counter hook

    first = decoder.read_frame(media_path, 0)
    second = decoder.read_frame(media_path, 0)
    assert np.array_equal(first, second)
    assert calls.count(0) == 1

    # Prefetch (+1..+4 from frame 0) should warm frame 1 and 2 (3/4 out of range → ignored).
    assert _wait_until(
        lambda: decoder.get_cached(media_path, 1) is not None
        and decoder.get_cached(media_path, 2) is not None
    )
    calls_after_prefetch = list(calls)
    warmed = decoder.read_frame(media_path, 2)
    assert tuple(int(v) for v in warmed[0, 0]) == (0, 0, 30)
    assert calls == calls_after_prefetch

    assert controller.validate_media_link() == MediaLinkState.LINKED
    assert controller.active_shot is not None
    assert controller.active_shot.media.link_state == MediaLinkState.LINKED

    assert controller.relink_media(relink_sequence) is False
    assert controller.active_shot.media.link_state == MediaLinkState.CHANGED
    assert controller.relink_media(relink_sequence, accept_changed=True) is True
    assert controller.active_shot.media.link_state == MediaLinkState.LINKED
    assert Path(controller.active_shot.media.source_path).resolve() == relink_sequence.resolve()
    assert isinstance(controller._media_reader, ImageSequenceReader)
    assert controller.active_shot.media.frame_count == 4


def test_import_empty_or_unsupported_folder_emits_user_error(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    controller = ProjectController()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)
    parent = tmp_path / "proj"
    parent.mkdir(parents=True, exist_ok=True)
    assert controller.create_project("Bad Sequence", parent) is not None

    empty = tmp_path / "empty"
    empty.mkdir()
    assert controller.import_media(empty) is None
    assert errors
    assert any("No supported image files found" in message for message in errors)

    errors.clear()
    unsupported = tmp_path / "unsupported"
    unsupported.mkdir()
    (unsupported / "notes.txt").write_text("not an image", encoding="utf-8")
    (unsupported / "data.bin").write_bytes(b"\x00\x01")
    assert controller.import_media(unsupported) is None
    assert errors
    assert any("No supported image files found" in message for message in errors)
