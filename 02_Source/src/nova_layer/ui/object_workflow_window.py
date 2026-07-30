from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.app.user_facing_errors import format_user_error
from nova_layer.domain.models import BoundingRegion, GuidancePoint
from nova_layer.ui.candidate_strip import CandidateStripWidget
from nova_layer.ui.generation_history_strip import GenerationHistoryWidget
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer


class ObjectWorkflowWindow(QMainWindow):
    """Interactive UI for iterative ArtistIntent editing over ObjectWorkflowService."""

    def __init__(self, controller: ObjectWorkflowController | None = None) -> None:
        super().__init__()
        self.controller = controller or ObjectWorkflowController()
        self._syncing_guidance = False
        self._edit_dirty = False
        self.setObjectName("objectWorkflowWindow")
        self.setWindowTitle("NOVA Layer · Object Workflow")
        self.resize(1100, 720)
        self.setMinimumSize(820, 560)
        self._apply_restored_geometry()
        self._maybe_prompt_workspace_recovery()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("Object Workflow")
        header.setObjectName("projectHeading")
        layout.addWidget(header)

        self.status_label = QLabel()
        self.status_label.setObjectName("workspacePlaceholder")
        layout.addWidget(self.status_label)

        workspace_row = QHBoxLayout()
        self.recent_projects_list = QListWidget()
        self.recent_projects_list.setObjectName("recentProjectsList")
        self.recent_projects_list.setMaximumHeight(72)
        workspace_row.addWidget(self.recent_projects_list, 1)
        self.reopen_last_button = QPushButton("Reopen Last")
        self.reopen_last_button.setObjectName("reopenLastButton")
        self.restore_layout_button = QPushButton("Restore Layout")
        self.restore_layout_button.setObjectName("restoreLayoutButton")
        self.reset_workspace_button = QPushButton("Reset Workspace")
        self.reset_workspace_button.setObjectName("resetWorkspaceButton")
        workspace_row.addWidget(self.reopen_last_button)
        workspace_row.addWidget(self.restore_layout_button)
        workspace_row.addWidget(self.reset_workspace_button)
        layout.addLayout(workspace_row)
        self._refresh_recent_projects()

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Core Inference"))
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("coreInferenceProvider")
        self.provider_device_label = QLabel("device: n/a")
        self.provider_device_label.setObjectName("coreInferenceDevice")
        provider_row.addWidget(self.provider_combo)
        provider_row.addWidget(self.provider_device_label)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        self.provider_details_label = QLabel("")
        self.provider_details_label.setObjectName("coreInferenceDetails")
        self.provider_details_label.setWordWrap(True)
        layout.addWidget(self.provider_details_label)

        self._rebuild_provider_combo()

        extraction_row = QHBoxLayout()
        extraction_row.addWidget(QLabel("Precision Extraction"))
        self.extraction_provider_combo = QComboBox()
        self.extraction_provider_combo.setObjectName("precisionExtractionProvider")
        extraction_row.addWidget(self.extraction_provider_combo)
        extraction_row.addWidget(QLabel("feather"))
        self.feather_spin = QDoubleSpinBox()
        self.feather_spin.setObjectName("extractionFeather")
        self.feather_spin.setRange(0.0, 32.0)
        self.feather_spin.setSingleStep(0.5)
        extraction_row.addWidget(self.feather_spin)
        extraction_row.addWidget(QLabel("blur"))
        self.edge_blur_spin = QDoubleSpinBox()
        self.edge_blur_spin.setObjectName("extractionEdgeBlur")
        self.edge_blur_spin.setRange(0.0, 32.0)
        self.edge_blur_spin.setSingleStep(0.5)
        extraction_row.addWidget(self.edge_blur_spin)
        extraction_row.addWidget(QLabel("cleanup"))
        self.cleanup_spin = QSpinBox()
        self.cleanup_spin.setObjectName("extractionCleanup")
        self.cleanup_spin.setRange(0, 16)
        extraction_row.addWidget(self.cleanup_spin)
        extraction_row.addWidget(QLabel("expand"))
        self.expand_spin = QSpinBox()
        self.expand_spin.setObjectName("extractionExpandContract")
        self.expand_spin.setRange(-16, 16)
        extraction_row.addWidget(self.expand_spin)
        extraction_row.addStretch()
        layout.addLayout(extraction_row)

        matting_row = QHBoxLayout()
        matting_row.addWidget(QLabel("Backend"))
        self.matting_backend_combo = QComboBox()
        self.matting_backend_combo.setObjectName("mattingBackend")
        self.matting_backend_combo.addItem("Color Affinity", "color_affinity")
        self.matting_backend_combo.addItem("Neural ONNX", "neural_onnx")
        matting_row.addWidget(self.matting_backend_combo)
        matting_row.addWidget(QLabel("Unknown Edge"))
        self.matting_unknown_spin = QSpinBox()
        self.matting_unknown_spin.setObjectName("mattingUnknownRadius")
        self.matting_unknown_spin.setRange(0, 64)
        matting_row.addWidget(self.matting_unknown_spin)
        matting_row.addWidget(QLabel("Refine"))
        self.matting_strength_spin = QDoubleSpinBox()
        self.matting_strength_spin.setObjectName("mattingRefinementStrength")
        self.matting_strength_spin.setRange(0.0, 1.0)
        self.matting_strength_spin.setSingleStep(0.1)
        matting_row.addWidget(self.matting_strength_spin)
        self.matting_preserve_check = QCheckBox("Preserve Known Regions")
        self.matting_preserve_check.setObjectName("mattingPreserveKnownRegions")
        matting_row.addWidget(self.matting_preserve_check)
        matting_row.addStretch()
        layout.addLayout(matting_row)
        self.neural_matting_status_label = QLabel("")
        self.neural_matting_status_label.setObjectName("neuralMattingStatus")
        self.neural_matting_status_label.setWordWrap(True)
        layout.addWidget(self.neural_matting_status_label)

        self.extraction_details_label = QLabel("")
        self.extraction_details_label.setObjectName("precisionExtractionDetails")
        self.extraction_details_label.setWordWrap(True)
        layout.addWidget(self.extraction_details_label)
        self.confirmed_extraction_summary_label = QLabel("No confirmed candidate")
        self.confirmed_extraction_summary_label.setObjectName("confirmedExtractionSummary")
        self.confirmed_extraction_summary_label.setWordWrap(True)
        layout.addWidget(self.confirmed_extraction_summary_label)

        delivery_heading = QLabel("Delivery")
        delivery_heading.setObjectName("workspacePlaceholder")
        layout.addWidget(delivery_heading)
        delivery_row = QHBoxLayout()
        self.export_png_button = QPushButton("Export PNG")
        self.export_png_button.setObjectName("exportExtractionButton")
        self.reveal_asset_button = QPushButton("Reveal Asset")
        self.reveal_asset_button.setObjectName("revealExtractionButton")
        self.copy_path_button = QPushButton("Copy Path")
        self.copy_path_button.setObjectName("copyExtractionPathButton")
        self.copy_uri_button = QPushButton("Copy File URI")
        self.copy_uri_button.setObjectName("copyExtractionUriButton")
        delivery_row.addWidget(self.export_png_button)
        delivery_row.addWidget(self.reveal_asset_button)
        delivery_row.addWidget(self.copy_path_button)
        delivery_row.addWidget(self.copy_uri_button)
        delivery_row.addStretch()
        layout.addLayout(delivery_row)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host"))
        self.host_adapter_combo = QComboBox()
        self.host_adapter_combo.setObjectName("hostAdapterCombo")
        host_row.addWidget(self.host_adapter_combo)
        host_row.addWidget(QLabel("Action"))
        self.host_action_combo = QComboBox()
        self.host_action_combo.setObjectName("hostActionCombo")
        host_row.addWidget(self.host_action_combo)
        self.deliver_host_button = QPushButton("Send to Host")
        self.deliver_host_button.setObjectName("deliverToHostButton")
        host_row.addWidget(self.deliver_host_button)
        host_row.addStretch()
        layout.addLayout(host_row)
        self.host_availability_label = QLabel("")
        self.host_availability_label.setObjectName("hostAvailabilityLabel")
        self.host_availability_label.setWordWrap(True)
        layout.addWidget(self.host_availability_label)
        self.delivery_summary_label = QLabel("No delivery yet")
        self.delivery_summary_label.setObjectName("deliverySummaryLabel")
        self.delivery_summary_label.setWordWrap(True)
        layout.addWidget(self.delivery_summary_label)
        self._rebuild_host_adapter_combo()

        plugins_heading = QLabel("Plugins")
        plugins_heading.setObjectName("workspacePlaceholder")
        layout.addWidget(plugins_heading)
        self.plugins_summary_label = QLabel("No plugins discovered")
        self.plugins_summary_label.setObjectName("pluginsSummary")
        self.plugins_summary_label.setWordWrap(True)
        layout.addWidget(self.plugins_summary_label)

        batch_heading = QLabel("Batch")
        batch_heading.setObjectName("workspacePlaceholder")
        layout.addWidget(batch_heading)
        batch_row = QHBoxLayout()
        self.batch_add_button = QPushButton("Add Images")
        self.batch_add_button.setObjectName("batchAddImagesButton")
        self.batch_start_button = QPushButton("Start Batch")
        self.batch_start_button.setObjectName("batchStartButton")
        self.batch_cancel_button = QPushButton("Cancel Batch")
        self.batch_cancel_button.setObjectName("batchCancelButton")
        self.batch_retry_button = QPushButton("Retry Failed")
        self.batch_retry_button.setObjectName("batchRetryFailedButton")
        batch_row.addWidget(self.batch_add_button)
        batch_row.addWidget(self.batch_start_button)
        batch_row.addWidget(self.batch_cancel_button)
        batch_row.addWidget(self.batch_retry_button)
        self.batch_auto_confirm_check = QCheckBox("Automatic confirmation")
        self.batch_auto_confirm_check.setObjectName("batchAutomaticConfirmation")
        self.batch_auto_confirm_check.setToolTip(
            "Opt-in only. When enabled, batch may auto-select and confirm_hypothesis()."
        )
        batch_row.addWidget(self.batch_auto_confirm_check)
        batch_row.addStretch()
        layout.addLayout(batch_row)
        self.batch_summary_label = QLabel("No batch queued")
        self.batch_summary_label.setObjectName("batchSummary")
        self.batch_summary_label.setWordWrap(True)
        layout.addWidget(self.batch_summary_label)

        self._rebuild_extraction_provider_combo()

        toolbar = QHBoxLayout()
        self.create_button = QPushButton("Create Project")
        self.create_button.setObjectName("createProjectButton")
        self.load_source_button = QPushButton("Load Source")
        self.positive_mode_button = QPushButton("+ Point")
        self.positive_mode_button.setObjectName("positivePointMode")
        self.negative_mode_button = QPushButton("− Point")
        self.negative_mode_button.setObjectName("negativePointMode")
        self.move_point_button = QPushButton("Move Point")
        self.move_point_button.setObjectName("movePointMode")
        self.remove_point_button = QPushButton("Remove Point")
        self.remove_point_button.setObjectName("removePointMode")
        self.box_mode_button = QPushButton("Box Mode")
        self.remove_box_button = QPushButton("Remove Box")
        self.clear_points_button = QPushButton("Clear Points")
        self.clear_points_button.setObjectName("clearPointsButton")
        self.apply_intent_button = QPushButton("Apply")
        self.cancel_edit_button = QPushButton("Cancel")
        self.generate_button = QPushButton("Generate")
        self.reject_generation_button = QPushButton("Reject Generation")
        self.generate_again_button = QPushButton("Generate Again")
        self.confirm_button = QPushButton("Confirm")
        self.extract_button = QPushButton("Extract")
        self.cancel_operation_button = QPushButton("Cancel Operation")
        self.cancel_operation_button.setObjectName("cancelOperationButton")
        self.save_button = QPushButton("Save")
        self.load_project_button = QPushButton("Load Project")
        for button in (
            self.create_button,
            self.load_source_button,
            self.positive_mode_button,
            self.negative_mode_button,
            self.move_point_button,
            self.remove_point_button,
            self.box_mode_button,
            self.remove_box_button,
            self.clear_points_button,
            self.apply_intent_button,
            self.cancel_edit_button,
            self.generate_button,
            self.reject_generation_button,
            self.generate_again_button,
            self.confirm_button,
            self.extract_button,
            self.cancel_operation_button,
            self.save_button,
            self.load_project_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("operationProgress")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("operationBusyLabel")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.busy_label)
        layout.addLayout(progress_row)

        self.candidate_strip_widget = CandidateStripWidget(self.controller)
        self.candidate_scroll = self.candidate_strip_widget.scroll_area
        layout.addWidget(self.candidate_strip_widget)

        self.generation_history_widget = GenerationHistoryWidget(self.controller)
        layout.addWidget(self.generation_history_widget)

        viewers = QHBoxLayout()
        self.viewer = GuidanceViewer()
        self.viewer.setText("Create a project and load a PNG or JPEG source")
        self.viewer.set_mode(GuidanceMode.POSITIVE)
        viewers.addWidget(self.viewer, 2)

        preview_column = QVBoxLayout()
        preview_heading = QLabel("Extraction Preview")
        preview_heading.setObjectName("workspacePlaceholder")
        preview_column.addWidget(preview_heading)
        self.extraction_preview = QLabel("No extraction yet")
        self.extraction_preview.setObjectName("extractionPreview")
        self.extraction_preview.setMinimumSize(240, 180)
        self.extraction_preview.setAlignment(self.viewer.alignment())
        preview_column.addWidget(self.extraction_preview, 1)
        viewers.addLayout(preview_column, 1)
        layout.addLayout(viewers, 1)

        self.setCentralWidget(root)

        self.create_button.clicked.connect(self._create_project)
        self.load_source_button.clicked.connect(self._load_source)
        self.positive_mode_button.clicked.connect(
            lambda: self.viewer.set_mode(GuidanceMode.POSITIVE)
        )
        self.negative_mode_button.clicked.connect(
            lambda: self.viewer.set_mode(GuidanceMode.NEGATIVE)
        )
        self.move_point_button.clicked.connect(
            lambda: self.viewer.set_mode(GuidanceMode.MOVE_POINT)
        )
        self.remove_point_button.clicked.connect(
            lambda: self.viewer.set_mode(GuidanceMode.REMOVE_POINT)
        )
        self.box_mode_button.clicked.connect(
            lambda: self.viewer.set_mode(GuidanceMode.BOUNDING_REGION)
        )
        self.remove_box_button.clicked.connect(self._remove_box)
        self.clear_points_button.clicked.connect(self._clear_points)
        self.apply_intent_button.clicked.connect(self._apply_intent)
        self.cancel_edit_button.clicked.connect(self._cancel_edit)
        self.generate_button.clicked.connect(self.controller.start_generate_hypothesis)
        self.reject_generation_button.clicked.connect(self.controller.reject_active_generation)
        self.generate_again_button.clicked.connect(self.controller.retry_generation)
        self.confirm_button.clicked.connect(self.controller.confirm_hypothesis)
        self.extract_button.clicked.connect(self.controller.start_generate_extraction)
        self.cancel_operation_button.clicked.connect(self.controller.cancel_running_operation)
        self.save_button.clicked.connect(self._save_project)
        self.load_project_button.clicked.connect(self._load_project)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.extraction_provider_combo.currentTextChanged.connect(
            self._on_extraction_provider_changed
        )
        self.feather_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.edge_blur_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.cleanup_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.expand_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.matting_unknown_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.matting_strength_spin.editingFinished.connect(self._on_extraction_settings_changed)
        self.matting_preserve_check.toggled.connect(self._on_extraction_settings_changed)
        self.matting_backend_combo.currentIndexChanged.connect(self._on_extraction_settings_changed)
        self.export_png_button.clicked.connect(self._export_extraction)
        self.reveal_asset_button.clicked.connect(self.controller.reveal_committed_extraction)
        self.copy_path_button.clicked.connect(self.controller.copy_extraction_path)
        self.copy_uri_button.clicked.connect(self.controller.copy_extraction_file_uri)
        self.deliver_host_button.clicked.connect(self._deliver_to_host)
        self.host_adapter_combo.currentTextChanged.connect(self._on_host_adapter_changed)
        self.host_action_combo.currentTextChanged.connect(self._on_host_action_changed)
        self.batch_add_button.clicked.connect(self._batch_add_images)
        self.batch_start_button.clicked.connect(self.controller.start_batch)
        self.batch_cancel_button.clicked.connect(self.controller.cancel_batch)
        self.batch_retry_button.clicked.connect(self.controller.retry_batch_failed)
        self.batch_auto_confirm_check.toggled.connect(self._on_batch_auto_confirm_toggled)
        self.viewer.guidance_changed.connect(self._on_guidance_changed)

        self.controller.state_changed.connect(self._refresh)
        self.controller.error_occurred.connect(self._show_error)
        self.reopen_last_button.clicked.connect(self._reopen_last_project)
        self.restore_layout_button.clicked.connect(self._restore_layout)
        self.reset_workspace_button.clicked.connect(self._reset_workspace)
        self.recent_projects_list.itemDoubleClicked.connect(self._open_recent_project)
        self._restore_active_project_on_startup()
        self._refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        geometry = self.geometry()
        self.controller.persist_window_geometry(
            {
                "x": geometry.x(),
                "y": geometry.y(),
                "w": geometry.width(),
                "h": geometry.height(),
            }
        )
        self.controller.persist_dock_layout(
            {
                "sidebar_visible": True,
                "recent_panel_height": self.recent_projects_list.height(),
            }
        )
        self.controller.shutdown()
        super().closeEvent(event)

    def _apply_restored_geometry(self) -> None:
        geometry = self.controller.restore_window_geometry()
        if not geometry:
            return
        try:
            self.setGeometry(
                int(geometry.get("x", self.x())),
                int(geometry.get("y", self.y())),
                int(geometry.get("w", self.width())),
                int(geometry.get("h", self.height())),
            )
        except (TypeError, ValueError):
            return

    def _refresh_recent_projects(self) -> None:
        self.recent_projects_list.clear()
        for path in self.controller.recent_projects():
            self.recent_projects_list.addItem(path)

    def _restore_active_project_on_startup(self) -> None:
        self.controller.restore_active_project()
        self._refresh_recent_projects()

    def _reopen_last_project(self) -> None:
        self.controller.reopen_last_project()
        self._refresh_recent_projects()

    def _open_recent_project(self, item: object) -> None:
        text = getattr(item, "text", lambda: "")()
        if not text:
            return
        self.controller.load_project(Path(str(text)))
        self._refresh_recent_projects()

    def _restore_layout(self) -> None:
        self._apply_restored_geometry()
        layout = self.controller.restore_dock_layout() or {}
        height = layout.get("recent_panel_height")
        if isinstance(height, int) and height > 40:
            self.recent_projects_list.setMaximumHeight(height)
        self.status_label.setText("Layout restored from Workspace.")

    def _reset_workspace(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset Workspace",
            "Clear application workspace preferences and recent projects?\n"
            "Project files on disk will not be deleted.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset_workspace_session()
        self._refresh_recent_projects()

    def _on_provider_changed(self, _label: str) -> None:
        provider_id = self.provider_combo.currentData()
        if not provider_id:
            return
        if provider_id == self.controller.view_state().core_inference_provider:
            return
        self.controller.set_core_inference_provider(str(provider_id))

    def _on_extraction_provider_changed(self, _label: str) -> None:
        provider_id = self.extraction_provider_combo.currentData()
        if not provider_id:
            return
        if provider_id == self.controller.view_state().precision_extraction_provider:
            return
        self.controller.set_precision_extraction_provider(str(provider_id))

    def _on_extraction_settings_changed(self) -> None:
        state = self.controller.view_state()
        backend_id = self.matting_backend_combo.currentData()
        if (
            abs(self.feather_spin.value() - state.precision_extraction_feather_radius) < 1e-9
            and abs(self.edge_blur_spin.value() - state.precision_extraction_edge_blur_radius)
            < 1e-9
            and self.cleanup_spin.value() == state.precision_extraction_cleanup_radius
            and self.expand_spin.value() == state.precision_extraction_expand_contract_pixels
            and self.matting_unknown_spin.value()
            == state.precision_extraction_matting_unknown_radius
            and abs(
                self.matting_strength_spin.value()
                - state.precision_extraction_matting_refinement_strength
            )
            < 1e-9
            and self.matting_preserve_check.isChecked()
            == state.precision_extraction_matting_preserve_known_regions
            and backend_id == state.precision_extraction_matting_backend
        ):
            return
        self.controller.set_extraction_refinement(
            feather_radius=float(self.feather_spin.value()),
            edge_blur_radius=float(self.edge_blur_spin.value()),
            cleanup_radius=int(self.cleanup_spin.value()),
            expand_contract_pixels=int(self.expand_spin.value()),
            matting_unknown_radius=int(self.matting_unknown_spin.value()),
            matting_refinement_strength=float(self.matting_strength_spin.value()),
            matting_preserve_known_regions=bool(self.matting_preserve_check.isChecked()),
            matting_backend=str(backend_id) if backend_id else None,
        )

    def _rebuild_provider_combo(self) -> None:
        selected = self.controller.view_state().core_inference_provider
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        for descriptor in self.controller.list_core_inference_providers():
            suffix = "" if descriptor.availability == "available" else " (unavailable)"
            label = f"{descriptor.display_name}{suffix}"
            self.provider_combo.addItem(label, descriptor.provider_id)
        index = self.provider_combo.findData(selected)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        self.provider_combo.blockSignals(False)

    def _rebuild_extraction_provider_combo(self) -> None:
        selected = self.controller.view_state().precision_extraction_provider
        self.extraction_provider_combo.blockSignals(True)
        self.extraction_provider_combo.clear()
        for descriptor in self.controller.list_precision_extraction_providers():
            suffix = "" if descriptor.availability == "available" else " (unavailable)"
            label = f"{descriptor.display_name}{suffix}"
            self.extraction_provider_combo.addItem(label, descriptor.provider_id)
        index = self.extraction_provider_combo.findData(selected)
        if index >= 0:
            self.extraction_provider_combo.setCurrentIndex(index)
        self.extraction_provider_combo.blockSignals(False)

    def _rebuild_host_adapter_combo(self) -> None:
        selected = self.controller.view_state().host_adapter_id
        self.host_adapter_combo.blockSignals(True)
        self.host_adapter_combo.clear()
        for descriptor in self.controller.list_host_adapters():
            if descriptor.adapter_id in {"filesystem", "reveal"}:
                continue
            suffix = "" if descriptor.availability == "available" else " (unavailable)"
            label = f"{descriptor.display_name}{suffix}"
            self.host_adapter_combo.addItem(label, descriptor.adapter_id)
        index = self.host_adapter_combo.findData(selected)
        if index >= 0:
            self.host_adapter_combo.setCurrentIndex(index)
        self.host_adapter_combo.blockSignals(False)

    def _rebuild_host_action_combo(self) -> None:
        selected = self.controller.view_state().host_action
        adapter_id = self.controller.view_state().host_adapter_id
        self.host_action_combo.blockSignals(True)
        self.host_action_combo.clear()
        for action in self.controller.available_host_actions(adapter_id):
            self.host_action_combo.addItem(action.replace("_", " "), action)
        index = self.host_action_combo.findData(selected)
        if index >= 0:
            self.host_action_combo.setCurrentIndex(index)
        self.host_action_combo.blockSignals(False)

    def _on_host_adapter_changed(self, _label: str) -> None:
        adapter_id = self.host_adapter_combo.currentData()
        if not adapter_id:
            return
        if adapter_id == self.controller.view_state().host_adapter_id:
            return
        self.controller.set_host_adapter(str(adapter_id))

    def _on_host_action_changed(self, _label: str) -> None:
        action = self.host_action_combo.currentData()
        if not action:
            return
        if action == self.controller.view_state().host_action:
            return
        self.controller.set_host_action(str(action))

    def _export_extraction(self) -> None:
        suggested = self.controller.suggested_export_filename() or "nova_extraction.png"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Committed Extraction",
            suggested,
            filter="PNG Image (*.png)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".png":
            destination = destination.with_suffix(".png")
        allow_overwrite = False
        if destination.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite Export?",
                f"File already exists:\n{destination}\n\nOverwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            allow_overwrite = True
        self.controller.export_confirmed_extraction(
            destination,
            allow_overwrite=allow_overwrite,
        )

    def _deliver_to_host(self) -> None:
        self.controller.deliver_to_host()

    def _create_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "Create Project", "Project name:")
        if accepted and name.strip():
            self.controller.create_project(name)
            self._edit_dirty = False
            self.viewer.clear_guidance()

    def _load_source(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Load Source Image",
            filter="Images (*.png *.jpg *.jpeg)",
        )
        if path:
            self.controller.load_source(Path(path))
            self._edit_dirty = False
            self.viewer.clear_guidance()

    def _batch_add_images(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "Add Batch Images",
            filter="Images (*.png *.jpg *.jpeg)",
        )
        if not paths:
            return
        export_dir = QFileDialog.getExistingDirectory(self, "Batch Export Directory (optional)")
        self.controller.create_batch_job(
            paths,
            export_directory=export_dir or None,
        )

    def _on_batch_auto_confirm_toggled(self, enabled: bool) -> None:
        if enabled:
            self.controller.set_batch_confirmation_mode(
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
                selection_policy="highest_confidence",
            )
        else:
            self.controller.set_batch_confirmation_mode(
                confirmation_mode="interactive",
                enable_automatic_confirmation=False,
            )

    def _on_guidance_changed(self, *_args: object) -> None:
        if self._syncing_guidance:
            return
        self._edit_dirty = True
        self._refresh_status_only()

    def _clear_points(self) -> None:
        region = self.viewer.bounding_region
        self.viewer.set_guidance([], region)
        self._edit_dirty = True

    def _remove_box(self) -> None:
        self.viewer.remove_bounding_region()
        self._edit_dirty = True

    def _apply_intent(self) -> None:
        points = [(point.x, point.y, point.polarity) for point in self.viewer.points]
        region = self.viewer.bounding_region
        box = None
        if region is not None:
            box = (region.x, region.y, region.width, region.height)
        self._edit_dirty = False
        self.controller.apply_artist_intent(points=points, bounding_box=box)

    def _cancel_edit(self) -> None:
        self.controller.cancel_pending_edits()
        self._edit_dirty = False
        self._sync_guidance_from_controller()

    def _save_project(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Object Workflow Project",
            filter="NOVA Project (*.nova)",
        )
        if not path:
            return
        package = Path(path)
        if package.suffix != ".nova":
            package = package.with_suffix(".nova")
        self.controller.save_project(package)

    def _load_project(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Open Object Workflow Project (.nova)",
            options=QFileDialog.Option.ShowDirsOnly,
        )
        if path:
            self.controller.load_project(Path(path))
            self._refresh_recent_projects()

    def _refresh(self) -> None:
        state = self.controller.view_state()
        revision_text = (
            f"rev {state.active_intent_revision}/{state.intent_revision_count}"
            if state.active_intent_revision is not None
            else "no intent"
        )
        dirty_text = " · editing" if self._edit_dirty else ""
        busy_text = " · busy" if state.is_busy else ""
        progress_text = (
            f" · {state.progress_message} ({state.progress_current}/{state.progress_total})"
            if state.is_busy and state.progress_message
            else ""
        )
        self.status_label.setText(
            f"{state.project_name or 'No project'} · {state.workflow_state} · "
            f"{revision_text} · {state.prompt_summary}{dirty_text}{busy_text}"
            f"{progress_text} · {state.status_message}"
        )
        index = self.provider_combo.findData(state.core_inference_provider)
        if index < 0 or self.provider_combo.count() != len(
            self.controller.list_core_inference_providers()
        ):
            self._rebuild_provider_combo()
            index = self.provider_combo.findData(state.core_inference_provider)
        if index >= 0 and self.provider_combo.currentIndex() != index:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(index)
            self.provider_combo.blockSignals(False)
        self.provider_combo.setEnabled(not state.is_busy)
        self.provider_device_label.setText(f"device: {state.core_inference_device}")
        availability = "available" if state.core_inference_available else "unavailable"
        model_flag = "model required" if state.core_inference_requires_model else "no model"
        self.provider_details_label.setText(
            f"{state.core_inference_provider_display_name} · "
            f"v{state.core_inference_provider_version} · {availability} · {model_flag} · "
            f"{state.core_inference_capability_summary}"
            + (
                f" · {state.core_inference_availability_message}"
                if not state.core_inference_available
                else ""
            )
        )
        if self.extraction_provider_combo.count() != len(
            self.controller.list_precision_extraction_providers()
        ):
            self._rebuild_extraction_provider_combo()
        extraction_index = self.extraction_provider_combo.findData(
            state.precision_extraction_provider
        )
        if (
            extraction_index >= 0
            and self.extraction_provider_combo.currentIndex() != extraction_index
        ):
            self.extraction_provider_combo.blockSignals(True)
            self.extraction_provider_combo.setCurrentIndex(extraction_index)
            self.extraction_provider_combo.blockSignals(False)
        self.extraction_provider_combo.setEnabled(not state.is_busy)
        for spin in (self.feather_spin, self.edge_blur_spin, self.cleanup_spin, self.expand_spin):
            spin.setEnabled(not state.is_busy)
        matting_enabled = (not state.is_busy) and state.precision_extraction_supports_matting
        self.matting_backend_combo.setEnabled(matting_enabled)
        self.matting_unknown_spin.setEnabled(matting_enabled)
        self.matting_strength_spin.setEnabled(matting_enabled)
        self.matting_preserve_check.setEnabled(matting_enabled)
        self.feather_spin.blockSignals(True)
        self.edge_blur_spin.blockSignals(True)
        self.cleanup_spin.blockSignals(True)
        self.expand_spin.blockSignals(True)
        self.matting_backend_combo.blockSignals(True)
        self.matting_unknown_spin.blockSignals(True)
        self.matting_strength_spin.blockSignals(True)
        self.matting_preserve_check.blockSignals(True)
        self.feather_spin.setValue(state.precision_extraction_feather_radius)
        self.edge_blur_spin.setValue(state.precision_extraction_edge_blur_radius)
        self.cleanup_spin.setValue(state.precision_extraction_cleanup_radius)
        self.expand_spin.setValue(state.precision_extraction_expand_contract_pixels)
        backend_index = self.matting_backend_combo.findData(
            state.precision_extraction_matting_backend
        )
        if backend_index >= 0:
            self.matting_backend_combo.setCurrentIndex(backend_index)
        self.matting_unknown_spin.setValue(state.precision_extraction_matting_unknown_radius)
        self.matting_strength_spin.setValue(
            state.precision_extraction_matting_refinement_strength
        )
        self.matting_preserve_check.setChecked(
            state.precision_extraction_matting_preserve_known_regions
        )
        self.feather_spin.blockSignals(False)
        self.edge_blur_spin.blockSignals(False)
        self.cleanup_spin.blockSignals(False)
        self.expand_spin.blockSignals(False)
        self.matting_backend_combo.blockSignals(False)
        self.matting_unknown_spin.blockSignals(False)
        self.matting_strength_spin.blockSignals(False)
        self.matting_preserve_check.blockSignals(False)
        if state.precision_extraction_matting_backend == "neural_onnx":
            availability = (
                "available" if state.neural_matting_available else "unavailable"
            )
            self.neural_matting_status_label.setText(
                f"Neural ONNX · {availability} · {state.neural_matting_availability_message}"
            )
        elif state.precision_extraction_supports_matting:
            self.neural_matting_status_label.setText(
                f"Neural ONNX probe · {state.neural_matting_availability_message}"
            )
        else:
            self.neural_matting_status_label.setText("")
        extraction_availability = (
            "available" if state.precision_extraction_available else "unavailable"
        )
        extraction_model = (
            "model required" if state.precision_extraction_requires_model else "no model"
        )
        self.extraction_details_label.setText(
            f"{state.precision_extraction_provider_display_name} · "
            f"v{state.precision_extraction_provider_version} · {extraction_availability} · "
            f"{extraction_model}"
            + (
                f" · {state.precision_extraction_availability_message}"
                if not state.precision_extraction_available
                else ""
            )
        )
        self.confirmed_extraction_summary_label.setText(
            f"Extraction source: {state.confirmed_extraction_summary}"
        )
        self.export_png_button.setEnabled(state.can_export_extraction)
        self.reveal_asset_button.setEnabled(state.can_reveal_extraction)
        self.copy_path_button.setEnabled(state.can_copy_extraction_reference)
        self.copy_uri_button.setEnabled(state.can_copy_extraction_reference)
        self.deliver_host_button.setEnabled(state.can_deliver_to_host)
        self.host_adapter_combo.setEnabled(state.can_export_extraction)
        self.host_action_combo.setEnabled(state.can_deliver_to_host)
        self._rebuild_host_adapter_combo()
        self._rebuild_host_action_combo()
        availability = (
            "available" if state.host_adapter_available else "unavailable"
        )
        self.host_availability_label.setText(
            f"{state.host_adapter_display_name}: {availability}"
            + (
                f" — {state.host_adapter_availability_message}"
                if not state.host_adapter_available
                else ""
            )
        )
        self.delivery_summary_label.setText(state.delivery_summary)
        self.plugins_summary_label.setText(state.plugin_summary)
        self.batch_summary_label.setText(state.batch_summary)
        self.batch_add_button.setEnabled(not state.is_busy and not state.batch_running)
        self.batch_start_button.setEnabled(state.can_start_batch)
        self.batch_cancel_button.setEnabled(state.can_cancel_batch)
        self.batch_retry_button.setEnabled(state.can_retry_batch_failed)
        self.batch_auto_confirm_check.blockSignals(True)
        self.batch_auto_confirm_check.setChecked(
            state.batch_confirmation_mode == "automatic"
        )
        self.batch_auto_confirm_check.setEnabled(not state.batch_running)
        self.batch_auto_confirm_check.blockSignals(False)
        self.create_button.setEnabled(state.can_create_project)
        self.load_source_button.setEnabled(state.can_load_source)
        self.apply_intent_button.setEnabled(state.can_apply_intent)
        self.cancel_edit_button.setEnabled(state.can_cancel_edit)
        self.generate_button.setEnabled(state.can_generate)
        self.reject_generation_button.setEnabled(state.can_reject_generation)
        self.generate_again_button.setEnabled(state.can_retry_generation)
        self.confirm_button.setEnabled(state.can_confirm)
        self.extract_button.setEnabled(state.can_extract)
        self.cancel_operation_button.setEnabled(state.can_cancel_operation)
        self.save_button.setEnabled(state.can_save)
        self.load_project_button.setEnabled(state.can_load_project)
        guidance_enabled = state.can_edit_guidance
        self.positive_mode_button.setEnabled(guidance_enabled)
        self.negative_mode_button.setEnabled(guidance_enabled)
        self.move_point_button.setEnabled(guidance_enabled)
        self.remove_point_button.setEnabled(guidance_enabled)
        self.box_mode_button.setEnabled(guidance_enabled)
        self.remove_box_button.setEnabled(guidance_enabled)
        self.clear_points_button.setEnabled(guidance_enabled)

        self.progress_bar.setMaximum(max(state.progress_total, 1))
        self.progress_bar.setValue(state.progress_current if state.is_busy else 0)
        self.progress_bar.setEnabled(state.is_busy)
        self.busy_label.setText(state.progress_message if state.is_busy else "")
        self.candidate_strip_widget.rebuild(
            self.controller.list_candidates(),
            enabled=not state.is_busy,
        )
        self.generation_history_widget.refresh()

        frame = self.controller.source_frame
        if frame is None:
            self.viewer.setText("Create a project and load a PNG or JPEG source")
            self.viewer.set_mask_overlay(None)
            self.extraction_preview.setText("No extraction yet")
            self.extraction_preview.setPixmap(QPixmap())
            return
        self.viewer.set_frame(frame)
        self.viewer.set_mask_overlay(self.controller.mask_overlay)
        self._update_extraction_preview(self.controller.extraction_preview)
        if not self._edit_dirty and state.workflow_state in {
            "intent_provided",
            "candidate_set_ready",
            "hypothesis_ready",
            "object_confirmed",
            "extraction_ready",
        }:
            self._sync_guidance_from_controller()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._text_entry_has_focus():
            if (
                event.modifiers() & Qt.KeyboardModifier.AltModifier
                and event.key() == Qt.Key.Key_Left
                and not event.isAutoRepeat()
            ):
                self.controller.select_previous_generation()
                event.accept()
                return
            if (
                event.modifiers() & Qt.KeyboardModifier.AltModifier
                and event.key() == Qt.Key.Key_Right
                and not event.isAutoRepeat()
            ):
                self.controller.select_next_generation()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self.candidate_strip_widget.handle_space_press():
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self.candidate_strip_widget.handle_space_release():
                event.accept()
                return
        super().keyReleaseEvent(event)

    def _refresh_status_only(self) -> None:
        state = self.controller.view_state()
        revision_text = (
            f"rev {state.active_intent_revision}/{state.intent_revision_count}"
            if state.active_intent_revision is not None
            else "no intent"
        )
        dirty_text = " · editing" if self._edit_dirty else ""
        self.status_label.setText(
            f"{state.project_name or 'No project'} · {state.workflow_state} · "
            f"{revision_text} · {state.prompt_summary}{dirty_text} · {state.status_message}"
        )

    def _update_extraction_preview(self, rgba: np.ndarray | None) -> None:
        if rgba is None:
            self.extraction_preview.setText("No extraction yet")
            self.extraction_preview.setPixmap(QPixmap())
            return
        height, width, channels = rgba.shape
        assert channels == 4
        contiguous = np.ascontiguousarray(rgba)
        image = QImage(
            contiguous.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            max(self.extraction_preview.width(), 240),
            max(self.extraction_preview.height(), 180),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.extraction_preview.setPixmap(pixmap)
        self.extraction_preview.setText("")

    def _sync_guidance_from_controller(self) -> None:
        if self._syncing_guidance:
            return
        self._syncing_guidance = True
        try:
            points = [
                GuidancePoint(x=point.x, y=point.y, polarity=point.polarity)  # type: ignore[arg-type]
                for point in self.controller.prompt_points
            ]
            region = None
            box = self.controller.intent_box
            if box is not None:
                region = BoundingRegion(x=box[0], y=box[1], width=box[2], height=box[3])
            self.viewer.set_guidance(points, region)
        finally:
            self._syncing_guidance = False

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Object Workflow", format_user_error(message))

    def _maybe_prompt_workspace_recovery(self) -> None:
        error = self.controller.workspace_manager.load_error
        if not error:
            return
        answer = QMessageBox.warning(
            self,
            "Workspace Recovery",
            "The saved workspace could not be loaded and was reset to defaults.\n\n"
            f"Details: {error}\n\n"
            "Projects on disk were not modified. Reset workspace preferences now?",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Ignore,
            QMessageBox.StandardButton.Ignore,
        )
        if answer == QMessageBox.StandardButton.Reset:
            self.controller.reset_workspace_session()
            self.statusBar().showMessage("Workspace preferences reset.", 5000)
        self.controller.workspace_manager.clear_load_error()

    def _text_entry_has_focus(self) -> bool:
        focused = QApplication.focusWidget()
        return isinstance(
            focused,
            (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox),
        )
