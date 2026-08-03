"""Phase 10D: Smart Layer export jobs — async, progress, cancel, threading."""

from __future__ import annotations

import threading
from pathlib import Path
from threading import Event
from time import sleep

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    ArtistIntent,
    ExtractionPreview,
    MediaReference,
    Sequence,
    Shot,
    SmartLayer,
    SmartLayerRender,
)
from nova_layer.export.smart_layer import ExportFormat, SmartLayerExportError


def _attach_render(controller: ProjectController, frames: int = 3) -> None:
    assert controller._project is not None
    package = controller.package_path
    assert package is not None
    (package / "renders" / "v0001").mkdir(parents=True, exist_ok=True)
    (package / "masks").mkdir(parents=True, exist_ok=True)
    previews: list[ExtractionPreview] = []
    checksums: dict[str, str] = {}
    for index in range(frames):
        reference = f"renders/v0001/frame_{index:06d}.png"
        # Minimal valid-looking PNG bytes are not required when execute is mocked.
        (package / reference).write_bytes(b"png")
        mask_ref = f"masks/frame_{index:06d}.png"
        (package / mask_ref).write_bytes(b"mask")
        previews.append(
            ExtractionPreview(
                frame_number=index,
                image_reference=reference,
                mask_reference=mask_ref,
            )
        )
        checksums[reference] = "unused"
    layer = SmartLayer(
        artist_intent=ArtistIntent(master_frame=0),
        renders=[
            SmartLayerRender(
                version=1,
                frame_start=0,
                frame_end=frames - 1,
                frames=previews,
                checksums=checksums,
            )
        ],
        render_version_counter=1,
    )
    shot = Shot(
        name="Shot",
        media=MediaReference(
            relative_path="media/x",
            source_path=str(package / "media"),
            fingerprint="fp",
            frame_count=max(frames, 1),
            frame_rate=24.0,
            width=2,
            height=2,
        ),
        range_start=0,
        range_end=max(frames - 1, 0),
        master_frame=0,
        smart_layers=[layer],
    )
    controller._project.sequences = [Sequence(name="Seq", shots=[shot])]


def test_sync_export_api_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp: object,
) -> None:
    del qapp
    controller = ProjectController()
    assert controller.create_project("SyncExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller, frames=2)
    dest = tmp_path / "out"
    dest.mkdir()
    sentinel = dest / "NOVA_Smart_Layer_v0001_png_sequence"
    sentinel.mkdir()
    (sentinel / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        controller,
        "verify_smart_layer_render",
        lambda version=None: type("R", (), {"valid": True})(),
    )

    def _fake_execute(*_a, **_k):
        return sentinel

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _fake_execute)
    path = controller.export_smart_layer_render(dest, version=1)
    assert path == sentinel


def test_async_export_progress_and_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("AsyncExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller, frames=3)
    dest = tmp_path / "out"
    dest.mkdir()
    out_path = dest / "done"
    out_path.mkdir()
    progress: list[tuple[int, int]] = []
    worker_ids: list[int] = []
    main_id = threading.get_ident()

    def _execute(
        *_args: object,
        should_cancel=None,
        report_progress=None,
        **_kwargs: object,
    ) -> Path:
        worker_ids.append(threading.get_ident())
        total = 3
        if report_progress is not None:
            report_progress(0, total, "start")
        for index in range(1, total + 1):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("True Scene export cancelled.")
            if report_progress is not None:
                report_progress(index - 1, total, f"frame {index}")
                report_progress(index, total, f"frame {index} done")
            sleep(0.005)
        return out_path

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    controller.processing_progress.connect(
        lambda _n, current, total, _m: progress.append((current, total))
    )

    with qtbot.waitSignal(controller.smart_layer_export_ready, timeout=5000) as ready:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1, format="png_sequence")
        # Event loop stays responsive while export runs.
        for _ in range(5):
            QCoreApplication.processEvents()
            sleep(0.001)

    assert ready.args[0] == str(out_path)
    assert worker_ids and worker_ids[0] != main_id
    assert progress
    assert progress[0][0] == 0
    assert progress[-1] == (3, 3)
    currents = [item[0] for item in progress]
    assert currents == sorted(currents)
    assert not controller._jobs.is_running


def test_duplicate_export_job_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("DupExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    gate = Event()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        if report_progress is not None:
            report_progress(0, 1, "hold")
        gate.wait(timeout=2)
        if should_cancel is not None and should_cancel():
            raise SmartLayerExportError("cancelled")
        return dest / "x"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    assert controller.start_smart_layer_export(dest, version=1)
    assert controller.start_smart_layer_export(dest, version=1) is False
    gate.set()
    with qtbot.waitSignal(controller.processing_finished, timeout=5000):  # type: ignore[attr-defined]
        pass


def test_cancel_export_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("CancelExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    started = Event()
    writes: list[int] = []

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        total = 20
        if report_progress is not None:
            report_progress(0, total, "start")
        started.set()
        for index in range(1, total + 1):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("True Scene export cancelled.")
            writes.append(index)
            if report_progress is not None:
                report_progress(index, total, f"wrote {index}")
            sleep(0.05)
        return dest / "should_not_exist"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    with qtbot.waitSignal(controller.processing_cancelled, timeout=5000) as cancelled:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
        assert started.wait(timeout=2)
        assert controller.cancel_smart_layer_export()
    assert cancelled.args[0] == "smart_layer_export"
    assert len(writes) < 20
    assert not (dest / "should_not_exist").exists()
    assert not controller._jobs.is_running


def test_export_failure_emits_processing_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("FailExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()

    def _execute(*_a, **_k) -> Path:
        raise SmartLayerExportError("destination already exists")

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    with qtbot.waitSignal(controller.processing_failed, timeout=5000) as failed:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
    assert failed.args[0] == "smart_layer_export"
    assert "destination already exists" in failed.args[1]
    assert not controller._jobs.is_running


def test_long_range_mock_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("LongExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    out_path = dest / "long"
    out_path.mkdir()
    live = {"peak": 0, "now": 0}

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        total = 1000
        for index in range(1, total + 1):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("cancelled")
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            # Simulate one live frame buffer released each iteration.
            live["now"] -= 1
            if report_progress is not None and index % 100 == 0:
                report_progress(index, total, f"{index}/{total}")
        if report_progress is not None:
            report_progress(total, total, "done")
        return out_path

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    with qtbot.waitSignal(controller.smart_layer_export_ready, timeout=10_000):  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
    assert live["peak"] <= 1


def test_cancel_reaches_scene_exporter_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct sync cancel path still wipes staging (exporter contract)."""
    from nova_layer.adapters.persistence.mask_store import PngMaskStore
    from nova_layer.export.smart_layer import export_smart_layer_assets

    from test_phase_10a_true_scene_export import _scene_package

    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _ = _scene_package(tmp_path, monkeypatch, frames=6)
    destination = tmp_path / "exports"
    destination.mkdir()
    done = {"n": 0}

    def should_cancel() -> bool:
        return done["n"] >= 2

    def report(current: int, total: int, message: str) -> None:
        if "done" in message:
            done["n"] += 1

    stem = "cancel_job"
    with pytest.raises(SmartLayerExportError, match="cancelled"):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=destination,
            export_stem=stem,
            render=render,
            format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
            project={"id": "p", "name": "Demo"},
            shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
            smart_layer={"id": "l", "name": "Layer"},
            frame_rate=24.0,
            scene_media_path=media,
            scene_decoder=decoder,
            mask_loader=lambda ref: PngMaskStore().load(package, ref),
            should_cancel=should_cancel,
            report_progress=report,
        )
    assert not (destination / stem).exists()
    assert not list(destination.glob(f".{stem}.staging_*"))


def test_preview_cache_untouched_during_mocked_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert controller.create_project("CacheExport", (tmp_path / "proj").mkdir() or tmp_path / "proj") is not None
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    out_path = dest / "ok"
    out_path.mkdir()
    before_preview = controller._frame_decoder.preview_cache_stats.count
    before_source = controller._frame_decoder.source_cache_stats.count
    before_raw = controller._frame_decoder.raw_cache_stats.count

    def _execute(*_a, report_progress=None, **_k) -> Path:
        if report_progress is not None:
            report_progress(1, 1, "done")
        return out_path

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    with qtbot.waitSignal(controller.smart_layer_export_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
    assert controller._frame_decoder.preview_cache_stats.count == before_preview
    assert controller._frame_decoder.source_cache_stats.count == before_source
    assert controller._frame_decoder.raw_cache_stats.count == before_raw


def test_concurrent_preview_request_during_export_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    """Export worker + GUI-thread event processing must not deadlock."""
    controller = ProjectController()
    assert (
        controller.create_project("ConcurrentExport", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    out_path = dest / "ok"
    out_path.mkdir()
    gate = Event()
    preview_hits = {"n": 0}

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        if report_progress is not None:
            report_progress(0, 5, "hold")
        gate.wait(timeout=2)
        for index in range(1, 6):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("cancelled")
            if report_progress is not None:
                report_progress(index, 5, f"{index}")
            sleep(0.005)
        return out_path

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)

    def _on_progress(_name: str, current: int, _total: int, _message: str) -> None:
        # Mimic viewer/preview work on the GUI thread while export progress arrives.
        preview_hits["n"] += 1
        QCoreApplication.processEvents()
        _ = controller._frame_decoder.preview_cache_stats
        if current >= 1:
            gate.set()

    controller.processing_progress.connect(_on_progress)
    with qtbot.waitSignal(controller.smart_layer_export_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
        for _ in range(20):
            QCoreApplication.processEvents()
            sleep(0.001)
    assert preview_hits["n"] >= 1
    assert not controller._jobs.is_running


def test_shutdown_cancels_running_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert (
        controller.create_project("ShutdownExport", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    started = Event()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        started.set()
        for _ in range(200):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("cancelled")
            sleep(0.01)
        return dest / "nope"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    with qtbot.waitSignal(controller.processing_cancelled, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1)
        assert started.wait(timeout=2)
        controller.shutdown()
    assert not controller._jobs.is_running
