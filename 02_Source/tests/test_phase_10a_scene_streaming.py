"""Phase 10A-2: frame-at-a-time Scene Linear export streaming."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.scene_range_decode import decode_scene_frame_range, iter_scene_frames
from nova_layer.export.smart_layer import (
    ExportFormat,
    SmartLayerExportError,
    export_smart_layer_assets,
)
from nova_layer.ports.scene_frames import SceneFrame

from test_phase_10a_true_scene_export import _fake_oiio, _scene_package


def _mini_exr_media(tmp_path: Path, frames: int) -> Path:
    media = tmp_path / "exr"
    media.mkdir()
    for index in range(1, frames + 1):
        (media / f"frame_{index:04d}.exr").write_bytes(b"x")
    return media


def test_iter_scene_frames_yields_one_at_a_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_oiio(monkeypatch)
    media = _mini_exr_media(tmp_path, 4)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)

    max_held = 0
    held: list[SceneFrame] = []
    seen: list[int] = []
    for scene in iter_scene_frames(decoder, media, 0, 3):
        held.clear()
        held.append(scene)
        max_held = max(max_held, len(held))
        seen.append(scene.frame_number)
    assert seen == [0, 1, 2, 3]
    assert max_held == 1


def test_iter_scene_frames_cancel_and_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_oiio(monkeypatch)
    media = _mini_exr_media(tmp_path, 5)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    progress: list[tuple[int, int, str]] = []
    done_count = {"n": 0}

    def should_cancel() -> bool:
        return done_count["n"] >= 2

    def report(current: int, total: int, message: str) -> None:
        progress.append((current, total, message))
        if "done" in message:
            done_count["n"] += 1

    frames = list(
        iter_scene_frames(
            decoder,
            media,
            0,
            4,
            should_cancel=should_cancel,
            report_progress=report,
        )
    )
    assert [frame.frame_number for frame in frames] == [0, 1]
    assert progress
    assert progress[0][0] == 0


def test_decode_scene_frame_range_still_materializes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_oiio(monkeypatch)
    media = _mini_exr_media(tmp_path, 2)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    frames = decode_scene_frame_range(decoder, media, 0, 1)
    assert set(frames) == {0, 1}


def test_scene_export_does_not_call_decode_scene_frame_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _counter = _scene_package(tmp_path, monkeypatch)

    def _forbidden(*_args: object, **_kwargs: object) -> dict[int, SceneFrame]:
        raise AssertionError("decode_scene_frame_range must not be used for export")

    monkeypatch.setattr(
        "nova_layer.app.scene_range_decode.decode_scene_frame_range",
        _forbidden,
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="stream_out",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        media_fingerprint="fp",
        input_color_space="scene_linear",
    )
    assert (result.path / "frame_000000.exr").is_file()
    assert (result.path / "manifest.json").is_file()


def test_scene_export_calls_writer_per_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _counter = _scene_package(
        tmp_path, monkeypatch, frames=3
    )
    writes: list[str] = []
    from nova_layer.export import scene_exr as scene_exr_mod

    real_write = scene_exr_mod.write_scene_openexr_rgba

    def _tracked(path: Path, rgba: np.ndarray, **kwargs: object) -> None:
        writes.append(path.name)
        real_write(path, rgba, **kwargs)

    monkeypatch.setattr(
        "nova_layer.export.smart_layer.write_scene_openexr_rgba",
        _tracked,
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="writers",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        input_color_space="scene_linear",
    )
    assert writes == [
        "frame_000000.exr",
        "frame_000001.exr",
        "frame_000002.exr",
    ]


def test_scene_export_progress_and_cancel_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _counter = _scene_package(
        tmp_path, monkeypatch, frames=4
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    progress: list[tuple[int, int]] = []
    done_count = {"n": 0}

    def should_cancel() -> bool:
        return done_count["n"] >= 2

    def report(current: int, total: int, message: str) -> None:
        progress.append((current, total))
        if "done" in message:
            done_count["n"] += 1

    export_stem = "cancel_me"
    with pytest.raises(SmartLayerExportError, match="cancelled"):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=destination,
            export_stem=export_stem,
            render=render,
            format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
            project={"id": "p", "name": "Demo"},
            shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
            smart_layer={"id": "l", "name": "Layer"},
            frame_rate=24.0,
            scene_media_path=media,
            scene_decoder=decoder,
            mask_loader=lambda ref: PngMaskStore().load(package, ref),
            input_color_space="scene_linear",
            should_cancel=should_cancel,
            report_progress=report,
        )
    assert not (destination / export_stem).exists()
    assert not list(destination.glob(".cancel_me.staging_*"))
    assert progress
    assert progress[0] == (0, 4)


def test_scene_export_long_range_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    frame_count = 24
    package, media, render, decoder, counter = _scene_package(
        tmp_path, monkeypatch, frames=frame_count
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    get_calls: list[int] = []
    real_get = decoder.get_scene_frame

    def _tracked_get(path: Path, frame_number: int) -> SceneFrame:
        get_calls.append(frame_number)
        return real_get(path, frame_number)

    decoder.get_scene_frame = _tracked_get  # type: ignore[method-assign]
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="long",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        input_color_space="scene_linear",
    )
    assert len(list(result.path.glob("frame_*.exr"))) == frame_count
    assert get_calls == list(range(frame_count))
    assert len(counter) == frame_count
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format_id"] == "scene_openexr_sequence"
    assert manifest["scene_linear"] is True


def test_scene_export_live_scene_frames_stay_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _counter = _scene_package(
        tmp_path, monkeypatch, frames=8
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    outstanding: list[int] = []
    peak = {"v": 0}
    real_get = decoder.get_scene_frame

    class _TrackedScene:
        def __init__(self, wrapped: SceneFrame) -> None:
            self._wrapped = wrapped
            outstanding.append(1)
            peak["v"] = max(peak["v"], len(outstanding))

        def __getattr__(self, name: str) -> object:
            return getattr(self._wrapped, name)

        def __del__(self) -> None:
            if outstanding:
                outstanding.pop()

    def _wrap(path: Path, frame_number: int) -> object:
        return _TrackedScene(real_get(path, frame_number))

    decoder.get_scene_frame = _wrap  # type: ignore[method-assign]
    export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="bounded",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        input_color_space="scene_linear",
    )
    # Export locals keep one wrapper; RawFrameCache may briefly add churn.
    assert peak["v"] <= 3
