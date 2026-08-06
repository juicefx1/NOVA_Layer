"""H2: ProcessingJobService / controller bounded shutdown."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

import pytest
from PySide6.QtCore import QCoreApplication

from nova_layer.app.job_service import ProcessingJobService, ProgressCallback
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
from nova_layer.export.smart_layer import SmartLayerExportError


def test_shutdown_with_no_active_job_returns_true() -> None:
    service = ProcessingJobService()
    assert service.shutdown(timeout_ms=100) is True
    assert not service.is_running
    assert service.is_shutting_down
    assert service.start("x", lambda *_a: None) is False


def test_shutdown_cancels_and_waits(qtbot: object) -> None:
    service = ProcessingJobService()
    started = Event()

    def operation(cancel: Event, report: ProgressCallback) -> object:
        report(0, 1, "start")
        started.set()
        while not cancel.is_set():
            sleep(0.005)
        return None

    with qtbot.waitSignal(service.cancelled, timeout=3000):  # type: ignore[attr-defined]
        assert service.start("cancelable", operation)
        assert started.wait(timeout=2)
        assert service.shutdown(timeout_ms=2000) is True
    assert not service.is_running
    assert service.thread_pool.activeThreadCount() == 0


def test_shutdown_timeout_on_stuck_job() -> None:
    service = ProcessingJobService()
    entered = Event()

    def operation(cancel: Event, report: ProgressCallback) -> object:
        del cancel, report
        entered.set()
        sleep(2.0)  # ignores cancel
        return ["late"]

    assert service.start("stuck", operation)
    assert entered.wait(timeout=2)
    assert service.shutdown(timeout_ms=150) is False
    # Leave process: wait for stuck job so the suite can exit cleanly.
    assert service.thread_pool.waitForDone(5_000)
    QCoreApplication.processEvents()
    service._clear_active()


def test_active_cleared_after_complete_fail_cancel(qtbot: object) -> None:
    service = ProcessingJobService()

    def ok(cancel: Event, report: ProgressCallback) -> object:
        del cancel
        report(1, 1, "done")
        return 1

    with qtbot.waitSignal(service.completed, timeout=2000):  # type: ignore[attr-defined]
        assert service.start("ok", ok)
    assert not service.is_running

    def boom(cancel: Event, report: ProgressCallback) -> object:
        del cancel, report
        raise RuntimeError("boom")

    with qtbot.waitSignal(service.failed, timeout=2000):  # type: ignore[attr-defined]
        assert service.start("fail", boom)
    assert not service.is_running

    started = Event()

    def cancelable(cancel: Event, report: ProgressCallback) -> object:
        started.set()
        while not cancel.is_set():
            sleep(0.005)
        return None

    with qtbot.waitSignal(service.cancelled, timeout=2000):  # type: ignore[attr-defined]
        assert service.start("c", cancelable)
        assert started.wait(timeout=2)
        assert service.cancel()
    assert not service.is_running


def test_shutdown_rejects_new_jobs() -> None:
    service = ProcessingJobService()
    assert service.shutdown(timeout_ms=50) is True
    assert service.start("after", lambda *_: None) is False


def test_repeated_shutdown_idempotent() -> None:
    service = ProcessingJobService()
    assert service.shutdown(timeout_ms=50) is True
    assert service.shutdown(timeout_ms=50) is True


def _attach_render(controller: ProjectController) -> None:
    assert controller._project is not None
    package = controller.package_path
    assert package is not None
    (package / "renders" / "v0001").mkdir(parents=True, exist_ok=True)
    reference = "renders/v0001/frame_000000.png"
    (package / reference).write_bytes(b"png")
    layer = SmartLayer(
        artist_intent=ArtistIntent(master_frame=0),
        renders=[
            SmartLayerRender(
                version=1,
                frame_start=0,
                frame_end=0,
                frames=[
                    ExtractionPreview(
                        frame_number=0,
                        image_reference=reference,
                        mask_reference="masks/x.png",
                    )
                ],
                checksums={reference: "x"},
            )
        ],
        render_version_counter=1,
    )
    shot = Shot(
        name="Shot",
        media=MediaReference(
            relative_path="media/x",
            source_path=str(package),
            fingerprint="fp",
            frame_count=1,
            frame_rate=24.0,
            width=2,
            height=2,
        ),
        range_start=0,
        range_end=0,
        master_frame=0,
        smart_layers=[layer],
    )
    controller._project.sequences = [Sequence(name="Seq", shots=[shot])]


def test_controller_shutdown_waits_for_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: object,
) -> None:
    controller = ProjectController()
    assert (
        controller.create_project("H2Shut", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller)
    dest = tmp_path / "out"
    dest.mkdir()
    started = Event()
    cancelled_seen = Event()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        del report_progress
        started.set()
        for _ in range(500):
            if should_cancel is not None and should_cancel():
                cancelled_seen.set()
                raise SmartLayerExportError("cancelled")
            sleep(0.005)
        return dest / "nope"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    monkeypatch.setattr(
        controller,
        "verify_smart_layer_render",
        lambda version=None: type("R", (), {"valid": True})(),
    )
    assert controller.start_smart_layer_export(dest, version=1)
    assert started.wait(timeout=2)
    assert controller.shutdown(timeout_ms=3000) is True
    assert cancelled_seen.wait(timeout=1)
    assert not controller._jobs.is_running
    assert controller.start_smart_layer_export(dest, version=1) is False
    QCoreApplication.processEvents()


def test_controller_shutdown_idempotent(tmp_path: Path) -> None:
    controller = ProjectController()
    assert (
        controller.create_project("H2Idem", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    assert controller.shutdown(timeout_ms=100) is True
    assert controller.shutdown(timeout_ms=100) is True
