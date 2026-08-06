"""H2: WorkspaceWindow closeEvent waits for job shutdown."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from nova_layer.app.project_controller import ProjectController
from nova_layer.export.smart_layer import SmartLayerExportError
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.workspace import WorkspaceWindow


def _window(tmp_path: Path) -> tuple[WorkspaceWindow, ProjectController]:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    controller = ProjectController()
    assert (
        controller.create_project("CloseUI", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    window = WorkspaceWindow(controller, workspace=workspace)
    return window, controller


def test_close_with_no_job_accepted(qtbot: object, tmp_path: Path) -> None:
    window, _controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_close_with_cancellable_job_waits_then_accepts(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    started = Event()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        del report_progress
        started.set()
        for _ in range(400):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("cancelled")
            sleep(0.005)
        return tmp_path / "nope"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    monkeypatch.setattr(
        controller,
        "verify_smart_layer_render",
        lambda version=None: type("R", (), {"valid": True})(),
    )
    # Minimal render attachment for start_smart_layer_export validation.
    from nova_layer.domain.models import (
        ArtistIntent,
        ExtractionPreview,
        MediaReference,
        Sequence,
        Shot,
        SmartLayer,
        SmartLayerRender,
    )

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
    assert controller._project is not None
    controller._project.sequences = [
        Sequence(
            name="Seq",
            shots=[
                Shot(
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
            ],
        )
    ]
    dest = tmp_path / "out"
    dest.mkdir()
    assert controller.start_smart_layer_export(dest, version=1)
    assert started.wait(timeout=2)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert not controller._jobs.is_running


def test_close_timeout_ignores_event(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(tmp_path)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    entered = Event()

    def _stuck(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        del should_cancel, report_progress
        entered.set()
        sleep(2.0)
        return tmp_path / "late"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _stuck)
    monkeypatch.setattr(
        controller,
        "verify_smart_layer_render",
        lambda version=None: type("R", (), {"valid": True})(),
    )
    from nova_layer.domain.models import (
        ArtistIntent,
        ExtractionPreview,
        MediaReference,
        Sequence,
        Shot,
        SmartLayer,
        SmartLayerRender,
    )

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
    assert controller._project is not None
    controller._project.sequences = [
        Sequence(
            name="Seq",
            shots=[
                Shot(
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
            ],
        )
    ]
    dest = tmp_path / "out"
    dest.mkdir()
    assert controller.start_smart_layer_export(dest, version=1)
    assert entered.wait(timeout=2)

    # Force a short wait so closeEvent ignores without a multi-second hang.
    monkeypatch.setattr(
        controller,
        "shutdown",
        lambda *, timeout_ms=5000: controller._jobs.shutdown(timeout_ms=100),
    )
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is False
    assert "cancelling" in window.statusBar().currentMessage().casefold()
    # Drain stuck worker for clean process exit.
    assert controller._jobs.thread_pool.waitForDone(5_000)
    QApplication.processEvents()
    controller._jobs._clear_active()
