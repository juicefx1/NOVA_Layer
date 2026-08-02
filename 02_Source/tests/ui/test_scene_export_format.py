"""Phase 10A-2: Export UI format labels for dual OpenEXR paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import MediaReference, Sequence, Shot
from nova_layer.export.smart_layer import (
    EXPORT_FORMAT_CHOICES,
    SCENE_LINEAR_EXPORT_DESCRIPTION,
    ExportFormat,
    SmartLayerExportError,
)
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.workspace import WorkspaceWindow


def _ensure_active_shot(controller: ProjectController, tmp_path: Path) -> Shot:
    media_dir = tmp_path / "media_png"
    media_dir.mkdir(exist_ok=True)
    (media_dir / "frame_0001.png").write_bytes(b"not-a-real-png")
    shot = Shot(
        name="Shot",
        media=MediaReference(
            relative_path="media/frame_0001.png",
            source_path=str(media_dir),
            fingerprint="ui-test",
            frame_count=1,
            frame_rate=24.0,
            width=4,
            height=4,
        ),
        range_start=0,
        range_end=0,
        master_frame=0,
    )
    assert controller._project is not None
    controller._project.sequences = [Sequence(name="Seq", shots=[shot])]
    return shot


def test_export_format_choices_expose_both_openexr_ids() -> None:
    by_label = {label: (fid, desc) for label, fid, desc in EXPORT_FORMAT_CHOICES}
    assert "OpenEXR — Current Render Look" in by_label
    assert "OpenEXR — Scene Linear" in by_label
    assert by_label["OpenEXR — Current Render Look"][0] == "openexr_sequence"
    assert by_label["OpenEXR — Scene Linear"][0] == "scene_openexr_sequence"
    assert by_label["OpenEXR — Current Render Look"][0] != by_label[
        "OpenEXR — Scene Linear"
    ][0]
    assert "scene float" in by_label["OpenEXR — Scene Linear"][1].casefold()
    assert "OpenImageIO" in by_label["OpenEXR — Scene Linear"][1]
    assert SCENE_LINEAR_EXPORT_DESCRIPTION == by_label["OpenEXR — Scene Linear"][1]
    assert ExportFormat.OPENEXR_SEQUENCE.value == "openexr_sequence"
    assert ExportFormat.SCENE_OPENEXR_SEQUENCE.value == "scene_openexr_sequence"


def test_workspace_export_dialog_lists_both_openexr_labels(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Export Labels", root) is not None
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    captured: dict[str, object] = {}

    def _fake_get_item(_parent, _title, _label, items, *_args, **_kwargs):  # noqa: ANN001
        captured["items"] = list(items)
        captured["label"] = str(_label)
        return "PNG Sequence", False

    monkeypatch.setattr(QInputDialog, "getItem", _fake_get_item)
    window._request_render_export()
    items = captured["items"]
    assert isinstance(items, list)
    assert "OpenEXR — Current Render Look" in items
    assert "OpenEXR — Scene Linear" in items
    assert "OpenEXR Sequence" not in items
    prompt = str(captured["label"])
    assert "Current Render Look" in prompt
    assert "Scene Linear" in prompt
    assert "OpenImageIO" in prompt


def test_workspace_scene_linear_prevalidates_before_export(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Scene Validate", root) is not None
    _ensure_active_shot(controller, tmp_path)
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    warnings: list[str] = []

    def _fake_get_item(_parent, _title, _label, items, *_args, **_kwargs):  # noqa: ANN001
        del items
        return "OpenEXR — Scene Linear", True

    def _fake_warning(_parent, title, text, *_args, **_kwargs):  # noqa: ANN001
        warnings.append(f"{title}\n{text}")
        return QMessageBox.StandardButton.Ok

    def _fail_validate(_shot) -> None:  # noqa: ANN001
        raise SmartLayerExportError(
            "True Scene export unavailable: sequence is not OpenEXR "
            "(first file suffix='.png')."
        )

    monkeypatch.setattr(QInputDialog, "getItem", _fake_get_item)
    monkeypatch.setattr(QMessageBox, "warning", _fake_warning)
    monkeypatch.setattr(
        controller,
        "_validate_true_scene_export_ready",
        _fail_validate,
    )
    export_calls: list[object] = []
    monkeypatch.setattr(
        controller,
        "export_smart_layer_render",
        lambda *args, **kwargs: export_calls.append((args, kwargs)),
    )
    file_dialog_calls: list[int] = []

    def _no_dir(*_args, **_kwargs):  # noqa: ANN001
        file_dialog_calls.append(1)
        return ""

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", _no_dir)
    window._request_render_export()
    assert warnings
    assert "Scene Linear Export Unavailable" in warnings[0]
    assert "not OpenEXR" in warnings[0]
    assert export_calls == []
    assert file_dialog_calls == []


def test_workspace_scene_linear_exports_when_supported(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    WorkspaceManager.reset_shared_for_tests()
    workspace = WorkspaceManager(tmp_path / "workspace.json")
    workspace.load()
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Scene OK", root) is not None
    _ensure_active_shot(controller, tmp_path)
    window = WorkspaceWindow(controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.render_version.addItem("v0001", 1)
    window.render_version.setCurrentIndex(0)

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *_a, **_k: ("OpenEXR — Scene Linear", True),
    )
    monkeypatch.setattr(
        controller,
        "_validate_true_scene_export_ready",
        lambda _shot: None,
    )
    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_a, **_k: str(dest),
    )
    calls: list[tuple[object, ...]] = []

    def _export(directory, version=None, format=None):  # noqa: ANN001
        calls.append((directory, version, format))
        return None

    monkeypatch.setattr(controller, "export_smart_layer_render", _export)
    window._request_render_export()
    assert len(calls) == 1
    assert calls[0][0] == dest
    assert calls[0][1] == 1
    assert calls[0][2] == ExportFormat.SCENE_OPENEXR_SEQUENCE.value
