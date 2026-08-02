"""Phase 9B-2: Color Pipeline Diagnostics dialog UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
)
from nova_layer.adapters.color.settings import ResolvedColorSettings
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.color_pipeline_diagnostics_dialog import (
    ColorPipelineDiagnosticsDialog,
)
from nova_layer.ui.workspace import WorkspaceWindow


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceManager:
    WorkspaceManager.reset_shared_for_tests()
    manager = WorkspaceManager(tmp_path / "workspace.json")
    manager.load()
    return manager


@pytest.fixture
def project_controller(tmp_path: Path) -> ProjectController:
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Diag UI", root) is not None
    return controller


def test_menu_action_exists(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    assert window.color_pipeline_diagnostics_action is not None
    assert (
        window.color_pipeline_diagnostics_action.text()
        == "Color Pipeline Diagnostics…"
    )


def test_dialog_opens_without_project(qtbot: object) -> None:
    controller = ProjectController()
    dialog = ColorPipelineDiagnosticsDialog(controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.project_label.text() == "None"
    assert dialog.shot_label.text() == "None"
    assert dialog.media_label.text() == "None"
    assert dialog.frame_label.text() == "None"
    assert "0.0" in dialog.raw_cache_labels["bytes"].text()  # type: ignore[index]
    assert dialog.warnings_label.text() == "None"
    dialog.refresh()


def test_dialog_fields_and_refresh(
    qtbot: object,
    project_controller: ProjectController,
) -> None:
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.backend_label.text() == "legacy"
    assert dialog.viewer_policy_label.text() == "PREVIEW"
    assert dialog.processing_policy_label.text() == "SOURCE"
    assert dialog.render_policy_label.text() == "PREVIEW"
    assert "source_legacy" in dialog.source_version_label.text()
    assert "entries" in dialog.preview_cache_label.text()
    assert dialog.last_render_policy_label.text() == "None"

    project_controller.set_display_transform(
        LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=None,
                config_source=None,
                display="dispA",
                view="viewA",
                input_color_space="scene_linear",
                exposure=1.25,
                fallback_reason="test fallback",
            )
        )
    )
    dialog.refresh()
    assert dialog.display_label.text() == "dispA"
    assert dialog.view_label.text() == "viewA"
    assert dialog.exposure_label.text() == "1.25"
    assert dialog.fallback_label.text() == "test fallback"
    assert "test fallback" in dialog.warnings_label.text()
    assert dialog.fallback_warnings_label.text() == "test fallback"


def test_provenance_and_cache_details(
    qtbot: object,
    project_controller: ProjectController,
) -> None:
    project_controller.record_resolved_color_settings(
        ResolvedColorSettings(
            backend="legacy",
            config_path=None,
            config_source=None,
            input_color_space="scene_linear",
            display=None,
            view=None,
            exposure=0.0,
            source_backend="project",
            source_config="workspace",
            source_input_color_space="session",
            source_display="default",
            source_view="none",
            source_exposure="environment",
            warnings=("workspace preference note",),
        )
    )
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert dialog.prov_backend_label.text() == "project"
    assert dialog.prov_config_label.text() == "workspace"
    assert dialog.prov_input_label.text() == "session"
    assert "workspace preference note" in dialog.resolve_warnings_label.text()
    assert "Hits" not in dialog.raw_cache_labels["hits"].text()  # type: ignore[index]
    assert dialog.raw_cache_labels["hits"].text().isdigit()  # type: ignore[index]
    assert "MiB" in dialog.raw_cache_labels["bytes"].text()  # type: ignore[index]
    assert dialog.raw_cache_labels["hit_rate"].text()  # type: ignore[index]


def test_refresh_does_not_change_cache_hits(
    qtbot: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_controller: ProjectController,
) -> None:
    import numpy as np

    class FakeSpec:
        height = 2
        width = 2
        nchannels = 3

        def get_string_attribute(self, key: str, default: str = "") -> str:
            return default

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> object:
            return np.full((2, 2, 3), 0.2, dtype=np.float32)

        def close(self) -> None:
            return None

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(_path: str) -> FakeInput:
                return FakeInput()

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )
    seq = tmp_path / "exr"
    seq.mkdir()
    (seq / "frame_0001.exr").write_bytes(b"x")
    shot = project_controller.import_media(seq)
    assert shot is not None
    path = Path(shot.media.source_path)
    decoder = project_controller._frame_decoder
    decoder._prefetch_count = 0
    with decoder._lock:
        decoder._prefetch_generation += 1
    decoder.get_preview_frame(path, 0, schedule_prefetch=False)
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(2000)

    before = decoder.pipeline.raw_cache_stats
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog.refresh()
    dialog.refresh()
    after = decoder.pipeline.raw_cache_stats
    assert after.hits == before.hits
    assert after.misses == before.misses


def test_copy_report_uses_display_safe_identity(
    qtbot: object,
    project_controller: ProjectController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_cfg = str(Path.home() / "studio.ocio")
    project_controller.set_display_transform(
        LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="ocio",
                ocio_available=True,
                config_path=home_cfg,
                config_source="explicit",
                display="sRGB",
                view="ACES",
                input_color_space="ACEScg",
                exposure=0.0,
                fallback_reason=None,
            )
        )
    )
    dialog = ColorPipelineDiagnosticsDialog(project_controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert "~" in dialog.identity_label.text() or "studio.ocio" in dialog.identity_label.text()

    captured: list[str] = []

    class FakeClipboard:
        def setText(self, text: str) -> None:
            captured.append(text)

    monkeypatch.setattr(
        "nova_layer.ui.color_pipeline_diagnostics_dialog.QGuiApplication.clipboard",
        lambda: FakeClipboard(),
    )
    dialog.copy_to_clipboard()
    assert captured
    report = captured[0]
    assert "NOVA Layer Color Pipeline Diagnostics" in report
    assert "Backend:" in report
    assert Path.home().as_posix() not in report.replace("\\", "/")
    assert dialog.status_label.text() == "Report copied to clipboard"
    assert dialog.copy_text() == report


def test_long_identity_does_not_crash(qtbot: object) -> None:
    controller = ProjectController()
    long_path = "/" + ("a" * 400) + "/very/long/config.ocio"
    controller.set_display_transform(
        LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=long_path,
                config_source="explicit",
                display="sRGB",
                view="Raw",
                input_color_space="scene_linear",
                exposure=0.0,
                fallback_reason=None,
            )
        )
    )
    dialog = ColorPipelineDiagnosticsDialog(controller)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    assert len(dialog.identity_label.text()) > 0
    dialog.refresh()
    _ = dialog.copy_text()


def test_open_action_shows_dialog(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    opened: list[object] = []

    def _fake_exec(self: ColorPipelineDiagnosticsDialog) -> int:
        opened.append(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ColorPipelineDiagnosticsDialog, "exec", _fake_exec)
    window.color_pipeline_diagnostics_action.trigger()
    assert len(opened) == 1
    assert isinstance(opened[0], ColorPipelineDiagnosticsDialog)


def test_show_alias(
    qtbot: object,
    project_controller: ProjectController,
    workspace: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = WorkspaceWindow(project_controller, workspace=workspace)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    called: list[int] = []

    def _fake_open(self: WorkspaceWindow) -> None:
        del self
        called.append(1)

    monkeypatch.setattr(
        WorkspaceWindow, "_open_color_pipeline_diagnostics", _fake_open
    )
    window._show_color_pipeline_diagnostics()
    assert called == [1]
