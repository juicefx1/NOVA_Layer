from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pytestqt.qtbot import QtBot

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.domain.models import GuidancePoint
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer
from nova_layer.ui.object_workflow_window import ObjectWorkflowWindow
from nova_layer.ui.welcome import WelcomePage


def _png_bytes(width: int, height: int, fill: int = 128) -> bytes:
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend([fill] * width)
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def test_registry_driven_provider_combo(qtbot: QtBot) -> None:
    window = ObjectWorkflowWindow()
    qtbot.addWidget(window)
    assert window.provider_combo.count() >= 2
    assert window.provider_combo.itemData(0) == "mock"
    assert "Mock" in window.provider_combo.itemText(0)
    assert window.provider_details_label.text()
    assert window.controller.view_state().core_inference_provider == "mock"
    assert window.extraction_provider_combo.count() >= 2
    assert window.extraction_provider_combo.itemData(0) == "mock"
    assert window.extraction_details_label.text()
    assert window.controller.view_state().precision_extraction_provider == "mock"


def test_welcome_exposes_object_workflow_entry(qtbot: QtBot) -> None:
    page = WelcomePage()
    qtbot.addWidget(page)
    assert page.object_workflow_button.isEnabled()
    with qtbot.waitSignal(page.object_workflow_requested):
        page.object_workflow_button.click()


def test_button_enablement_and_update_intent_flow(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)

    assert not window.generate_button.isEnabled()
    assert not window.confirm_button.isEnabled()
    assert not window.save_button.isEnabled()
    assert not window.cancel_edit_button.isEnabled()

    controller.create_project("ui-slice")
    assert window.load_source_button.isEnabled()

    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "plate.png"
        source.write_bytes(_png_bytes(64, 48))
        controller.load_source(source)
        assert window.apply_intent_button.isEnabled()
        assert window.positive_mode_button.isEnabled()
        assert window.negative_mode_button.isEnabled()
        assert not window.cancel_edit_button.isEnabled()

        controller.apply_artist_intent(
            positive_points=[(0.4, 0.5)],
            bounding_box=(0.2, 0.2, 0.3, 0.3),
        )
        assert window.generate_button.isEnabled()
        assert window.cancel_edit_button.isEnabled()
        assert controller.view_state().active_intent_revision == 1

        controller.generate_hypothesis()
        assert window.confirm_button.isEnabled() is False
        assert controller.view_state().workflow_state == "candidate_set_ready"
        candidates = controller.list_candidates()
        assert len(candidates) == 3
        controller.select_candidate(candidates[0].id)
        assert window.confirm_button.isEnabled()
        assert controller.mask_overlay is not None

        controller.apply_artist_intent(
            positive_points=[(0.7, 0.7)],
            bounding_box=None,
        )
        assert controller.view_state().workflow_state == "intent_provided"
        assert controller.view_state().active_intent_revision == 2
        assert controller.mask_overlay is None
        assert window.generate_button.isEnabled()
        assert not window.confirm_button.isEnabled()
        revisions = controller.list_intent_revisions()
        assert [item.revision for item in revisions] == [1, 2]
        assert revisions[1].is_active

        controller.generate_hypothesis()
        candidates = controller.list_candidates()
        controller.select_candidate(candidates[0].id)
        controller.confirm_hypothesis()
        assert window.save_button.isEnabled()
        assert window.extract_button.isEnabled()
        assert controller.view_state().workflow_state == "object_confirmed"

        controller.generate_extraction()
        assert controller.view_state().workflow_state == "extraction_ready"
        assert controller.extraction_preview is not None
        assert controller.extraction_preview.shape[2] == 4
        assert window.extract_button.isEnabled()
        assert window.save_button.isEnabled()
        assert window.extraction_preview.pixmap() is not None
        assert not window.extraction_preview.pixmap().isNull()


def test_cancel_editing_restores_active_revision(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("cancel")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(40, 40))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.25, 0.25)], bounding_box=None)
        window.viewer.set_guidance(
            [GuidancePoint(x=0.9, y=0.9, polarity="positive")],
            None,
        )
        assert window.viewer.points[0].x == 0.9
        window.cancel_edit_button.click()
        assert window.viewer.points[0].x == 0.25
        assert controller.view_state().active_intent_revision == 1
        assert len(controller.list_intent_revisions()) == 1


def test_async_generate_shows_busy_state_and_cancel(qtbot: QtBot) -> None:
    executor = MockOperationExecutor(step_delay_seconds=0.05)
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
        executor=executor,
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)

    controller.create_project("busy")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "plate.png"
        source.write_bytes(_png_bytes(48, 36))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.5, 0.5)], bounding_box=None)

        with qtbot.waitSignal(controller.operation_finished, timeout=5000):
            controller.start_generate_hypothesis()
            qtbot.waitUntil(lambda: controller.view_state().is_busy, timeout=2000)
            qtbot.waitUntil(lambda: window.cancel_operation_button.isEnabled(), timeout=2000)
            state = controller.view_state()
            assert state.is_busy
            assert state.can_cancel_operation
            assert not state.can_generate
            assert not window.generate_button.isEnabled()
            assert window.cancel_operation_button.isEnabled()
            assert window.progress_bar.isEnabled()

        qtbot.waitUntil(lambda: not controller.view_state().is_busy, timeout=2000)
        assert controller.view_state().workflow_state == "candidate_set_ready"
        assert controller.mask_overlay is None
        assert not window.cancel_operation_button.isEnabled()
        candidates = controller.list_candidates()
        assert len(candidates) >= 1
        controller.select_candidate(candidates[0].id)
        assert controller.view_state().workflow_state == "hypothesis_ready"
        assert controller.mask_overlay is not None
    executor.shutdown(wait=True)


def test_interactive_prompt_modes_and_no_mutation_before_apply(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("prompts")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(40, 40))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.2, 0.2)], bounding_box=None)
        assert controller.view_state().active_intent_revision == 1
        assert controller.view_state().prompt_summary == "+1/-0/no-box"

        window.negative_mode_button.click()
        assert window.viewer._mode == GuidanceMode.NEGATIVE
        window.viewer.set_guidance(
            [
                GuidancePoint(x=0.2, y=0.2, polarity="positive"),
                GuidancePoint(x=0.8, y=0.8, polarity="negative"),
            ],
            None,
        )
        assert window._edit_dirty
        assert controller.view_state().active_intent_revision == 1
        assert len(controller.list_intent_revisions()) == 1

        window.apply_intent_button.click()
        assert not window._edit_dirty
        assert controller.view_state().active_intent_revision == 2
        polarities = [p.polarity for p in controller.prompt_points]
        assert polarities == ["positive", "negative"]
        assert controller.view_state().prompt_summary == "+1/-1/no-box"

        window.clear_points_button.click()
        assert window._edit_dirty
        window.cancel_edit_button.click()
        assert not window._edit_dirty
        assert len(window.viewer.points) == 2


def test_generate_disabled_for_unsupported_negative(qtbot: QtBot) -> None:
    from nova_layer.object_workflow.ports.provider_registry import ProviderCapabilities

    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        inference_capabilities=ProviderCapabilities(
            supports_positive_point=True,
            supports_bounding_box=True,
            supports_negative_point=False,
            supports_cpu=True,
        ),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("caps")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(32, 32))
        controller.load_source(source)
        controller.apply_artist_intent(
            points=[(0.4, 0.4, "positive"), (0.6, 0.6, "negative")],
            bounding_box=None,
        )
        assert not window.generate_button.isEnabled()
        assert not controller.view_state().can_generate


def test_editing_blocked_while_generate_running(qtbot: QtBot) -> None:
    executor = MockOperationExecutor(step_delay_seconds=0.05)
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        executor=executor,
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("busy-edit")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(32, 32))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.5, 0.5)], bounding_box=None)
        with qtbot.waitSignal(controller.operation_finished, timeout=5000):
            controller.start_generate_hypothesis()
            qtbot.waitUntil(lambda: controller.view_state().is_busy, timeout=2000)
            assert not window.positive_mode_button.isEnabled()
            assert not window.apply_intent_button.isEnabled()
            assert not window.negative_mode_button.isEnabled()
    executor.shutdown(wait=True)


def test_candidate_strip_selection_updates_preview(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("strip")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(40, 40))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.5, 0.5)], bounding_box=None)
        controller.generate_hypothesis()
        assert window.candidate_scroll.objectName() == "candidateStrip"
        candidates = controller.list_candidates()
        assert len(candidates) == 3
        assert not window.confirm_button.isEnabled()
        controller.select_candidate(candidates[1].id)
        assert window.confirm_button.isEnabled()
        assert controller.mask_overlay is not None
        assert controller.view_state().workflow_state == "hypothesis_ready"
        # Reselect another candidate without regenerating.
        controller.select_candidate(candidates[2].id)
        assert controller.list_candidates()[2].is_active


def test_candidate_hover_preview_and_keyboard(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    controller.create_project("keys")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(40, 40))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.4, 0.4)], bounding_box=None)
        controller.generate_hypothesis()
        candidates = controller.list_candidates()
        controller.select_candidate(candidates[0].id)
        assert controller.committed_mask_overlay is not None

        controller.preview_candidate(candidates[2].id)
        assert controller.preview_candidate_id == candidates[2].id
        assert controller.list_candidates()[2].is_previewed
        assert controller.list_candidates()[0].is_active
        assert controller.view_state().can_confirm
        controller.clear_candidate_preview()
        assert controller.preview_candidate_id is None
        assert controller.committed_mask_overlay is not None

        # Keyboard navigation semantics (Option A): focus/preview then Enter commits.
        controller.focus_next_candidate()
        assert controller.focused_candidate_id == candidates[1].id
        assert controller.preview_candidate_id == candidates[1].id
        controller.commit_focused_or_previewed_candidate()
        assert controller.list_candidates()[1].is_active
        assert controller.preview_candidate_id is None

        controller.select_candidate_by_index(2)
        assert controller.list_candidates()[2].is_active

        controller.focus_previous_candidate()
        assert controller.focused_candidate_id == candidates[1].id
        controller.focus_previous_candidate()
        controller.focus_previous_candidate()
        assert controller.focused_candidate_id == candidates[0].id  # clamp

        chips = list(window.candidate_strip_widget._chips.values())
        assert chips[0].accessibleName()
        assert "Candidate" in chips[0].accessibleName()
        assert window.candidate_strip_widget.compare_button.isEnabled()


def test_candidate_preview_cleared_on_intent_edit_and_generate(qtbot: QtBot) -> None:
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
    )
    controller = ObjectWorkflowController(service)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)
    controller.create_project("clear")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "a.png"
        source.write_bytes(_png_bytes(32, 32))
        controller.load_source(source)
        controller.apply_artist_intent(positive_points=[(0.5, 0.5)], bounding_box=None)
        controller.generate_hypothesis()
        candidates = controller.list_candidates()
        controller.preview_candidate(candidates[1].id)
        assert controller.preview_candidate_id is not None
        controller.apply_artist_intent(positive_points=[(0.2, 0.2)], bounding_box=None)
        assert controller.preview_candidate_id is None
        controller.generate_hypothesis()
        candidates = controller.list_candidates()
        controller.preview_candidate(candidates[0].id)
        controller.generate_hypothesis()
        assert controller.preview_candidate_id is None
        assert window.candidate_strip_widget.compare_button.objectName() == "candidateCompareToggle"


def test_viewport_scaling_preserves_source_coordinates(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    import numpy as np

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    viewer.set_frame(frame)
    viewer.set_mode(GuidanceMode.POSITIVE)
    viewer.set_guidance([GuidancePoint(x=0.25, y=0.5, polarity="positive")], None)
    stored = (viewer.points[0].x, viewer.points[0].y)
    for size in ((800, 600), (320, 240), (1200, 400)):
        viewer.resize(*size)
        # Source-relative coordinates must not change with viewport scaling.
        assert (viewer.points[0].x, viewer.points[0].y) == stored
        assert viewer.points[0].x == 0.25
        assert viewer.points[0].y == 0.5


def test_delivery_controls_require_committed_extraction(qtbot: QtBot) -> None:
    clipboard = _MemoryClipboard()
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
        include_fake_host=True,
        clipboard=clipboard,
    )
    controller = ObjectWorkflowController(service, include_fake_host=True)
    window = ObjectWorkflowWindow(controller)
    qtbot.addWidget(window)

    assert not window.export_png_button.isEnabled()
    assert not window.reveal_asset_button.isEnabled()
    assert not window.deliver_host_button.isEnabled()
    assert "No delivery yet" in window.delivery_summary_label.text()

    controller.create_project("delivery-ui")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "src.png"
        source.write_bytes(_png_bytes(8, 6))
        controller.load_source(source)
        controller.apply_artist_intent(
            positive_points=[(0.5, 0.5)],
            bounding_box=(0.2, 0.2, 0.4, 0.4),
        )
        controller.generate_hypothesis()
        candidates = controller.list_candidates()
        controller.select_candidate(candidates[0].id)
        controller.confirm_hypothesis()
        controller.generate_extraction()
        window._refresh()

        assert window.export_png_button.isEnabled()
        assert window.reveal_asset_button.isEnabled()
        assert window.copy_path_button.isEnabled()
        assert window.host_adapter_combo.count() >= 1
        suggested = controller.suggested_export_filename()
        assert suggested.endswith(".png")
        destination = Path(tmp) / suggested
        assert controller.export_confirmed_extraction(destination, allow_overwrite=False)
        assert destination.is_file()
        window._refresh()
        assert "Exported" in controller.view_state().delivery_summary
        preview_before = controller.extraction_preview
        assert preview_before is not None
        assert controller.deliver_to_host("fake_host", "import_as_layer")
        window._refresh()
        assert "Fake Host" in controller.view_state().delivery_summary or "import_as_layer" in (
            controller.last_delivery_summary().action
            if controller.last_delivery_summary()
            else ""
        )
        assert controller.extraction_preview is not None
        assert controller.extraction_preview.shape == preview_before.shape


class _MemoryClipboard:
    def __init__(self) -> None:
        self.text = ""

    def write_text(self, text: str) -> None:
        self.text = text


def test_workspace_manager_api_returns_manager_instance() -> None:
    """Controller contract: workspace_manager is a method returning WorkspaceManager."""
    from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "workspace.json"
        workspace = WorkspaceManager(path)
        workspace.load()
        controller = ObjectWorkflowController(service, workspace=workspace)
        manager = controller.workspace_manager()
        assert isinstance(manager, WorkspaceManager)
        assert manager is workspace
        assert manager.load_error is None


def test_workspace_recovery_skips_dialog_when_load_error_none(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "workspace.json"
        workspace = WorkspaceManager(path)
        workspace.load()
        assert workspace.load_error is None
        controller = ObjectWorkflowController(service, workspace=workspace)
        prompts: list[str] = []

        def _fake_warning(*_a, **_k):  # noqa: ANN001
            prompts.append("prompted")
            return QMessageBox.StandardButton.Ignore

        monkeypatch.setattr(QMessageBox, "warning", _fake_warning)
        window = ObjectWorkflowWindow(controller)
        qtbot.addWidget(window)
        assert prompts == []
        assert controller.workspace_manager().load_error is None


def test_workspace_recovery_prompts_when_load_error_set(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "workspace.json"
        path.write_text("{not-json", encoding="utf-8")
        workspace = WorkspaceManager(path)
        workspace.load()
        assert workspace.load_error is not None
        controller = ObjectWorkflowController(service, workspace=workspace)
        prompts: list[str] = []

        def _fake_warning(_parent, _title, text, *_a, **_k):  # noqa: ANN001
            prompts.append(text)
            return QMessageBox.StandardButton.Ignore

        monkeypatch.setattr(QMessageBox, "warning", _fake_warning)
        window = ObjectWorkflowWindow(controller)
        qtbot.addWidget(window)
        assert len(prompts) == 1
        assert "could not be loaded" in prompts[0]
        assert controller.workspace_manager().load_error is None
