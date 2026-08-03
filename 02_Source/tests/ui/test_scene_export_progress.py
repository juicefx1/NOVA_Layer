"""Phase 10D: Workspace export progress / cancel UI."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

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
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.workspace import WorkspaceWindow


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


def test_workspace_shows_progress_and_enables_cancel(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    controller = ProjectController()
    assert (
        controller.create_project("ExportUI", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller)
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    window.render_version.addItem("v0001", 1)
    window.render_version.setCurrentIndex(0)

    gate = Event()
    progress_seen = Event()
    dest = tmp_path / "out"
    dest.mkdir()
    out_path = dest / "done"
    out_path.mkdir()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        if report_progress is not None:
            report_progress(0, 4, "export start")
            report_progress(2, 4, "mid")
            progress_seen.set()
        gate.wait(timeout=2)
        if should_cancel is not None and should_cancel():
            raise SmartLayerExportError("cancelled")
        if report_progress is not None:
            report_progress(4, 4, "done")
        return out_path

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *_a, **_k: ("PNG Sequence", True),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_a, **_k: str(dest),
    )

    with qtbot.waitSignal(controller.processing_started, timeout=2000):  # type: ignore[attr-defined]
        window._request_render_export()

    assert not window.cancel_button.isHidden()
    assert not window.export_button.isEnabled()
    assert not window.processing_progress.isHidden()

    assert progress_seen.wait(timeout=2)
    qtbot.waitUntil(  # type: ignore[attr-defined]
        lambda: window.processing_progress.maximum() >= 1,
        timeout=2000,
    )

    with qtbot.waitSignal(controller.smart_layer_export_ready, timeout=5000):  # type: ignore[attr-defined]
        gate.set()

    assert window.cancel_button.isHidden()
    assert window.export_button.isEnabled()


def test_workspace_cancel_export(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    controller = ProjectController()
    assert (
        controller.create_project("CancelUI", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller)
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    window.render_version.addItem("v0001", 1)
    window.render_version.setCurrentIndex(0)

    started = Event()
    dest = tmp_path / "out"
    dest.mkdir()

    def _execute(*_a, should_cancel=None, report_progress=None, **_k) -> Path:
        if report_progress is not None:
            report_progress(0, 10, "start")
        started.set()
        # Spin until cancel is observed (or timeout) so the UI cancel path is deterministic.
        for _ in range(200):
            if should_cancel is not None and should_cancel():
                raise SmartLayerExportError("cancelled")
            sleep(0.01)
        return dest / "nope"

    monkeypatch.setattr(controller, "_execute_smart_layer_export", _execute)
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *_a, **_k: ("PNG Sequence", True),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_a, **_k: str(dest),
    )

    with qtbot.waitSignal(controller.processing_cancelled, timeout=5000):  # type: ignore[attr-defined]
        window._request_render_export()
        assert started.wait(timeout=2)
        assert not window.cancel_button.isHidden()
        window.cancel_button.click()

    assert "Export cancelled" in window.statusBar().currentMessage()
    assert window.export_button.isEnabled()
    assert window.cancel_button.isHidden()


def test_workspace_blocks_export_while_busy(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    controller = ProjectController()
    assert (
        controller.create_project("BusyUI", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.cancel_button.setVisible(True)
    warnings: list[str] = []

    def _fake_warning(_parent, title, text, *_a, **_k):  # noqa: ANN001
        warnings.append(f"{title}:{text}")
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _fake_warning)
    window._request_render_export()
    assert warnings
    assert "Export Busy" in warnings[0]
