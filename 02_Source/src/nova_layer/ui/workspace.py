from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    BoundingRegion,
    GuidancePoint,
    MaturityState,
    Project,
    Shot,
    SkeletonFusionCandidate,
    SkeletonGuidance,
    SmartLayerRender,
)
from nova_layer.domain.skeleton_presets import openpose_body_25_preset
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer
from nova_layer.ui.lifecycle_timeline import LifecycleTimeline
from nova_layer.ui.validation_dialog import ValidationDialog


class WorkspaceWindow(QMainWindow):
    def __init__(self, controller: ProjectController) -> None:
        super().__init__()
        project = controller.project
        if project is None:
            raise ValueError("Workspace requires an active project")
        self.controller = controller
        self.validation_dialog: ValidationDialog | None = None
        self._pending_frame = 0
        self._current_frame = 0
        self._pending_skeleton_correction: SkeletonGuidance | None = None
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setSingleShot(True)
        self._scrub_timer.setInterval(45)
        self._scrub_timer.timeout.connect(self._request_pending_frame)
        self.setObjectName("workspaceWindow")
        self.setWindowTitle(f"{project.name} — NOVA Layer")
        self.resize(1280, 820)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(14)

        outer.addLayout(self._build_header(project))
        outer.addLayout(self._build_content())
        outer.addWidget(self._build_timeline())
        self.setCentralWidget(root)

        status = QStatusBar()
        status.showMessage("Ready — import media to begin")
        self.setStatusBar(status)

        controller.shot_changed.connect(self.set_shot)
        controller.frame_ready.connect(self.set_frame)
        controller.hypothesis_ready.connect(self._show_hypothesis)
        controller.hypothesis_state_changed.connect(self._set_hypothesis_state)
        controller.validation_ready.connect(self._show_validation_ready)
        controller.validation_state_changed.connect(self._validation_state_changed)
        controller.smart_layer_render_ready.connect(self._smart_layer_render_ready)
        controller.background_removal_preview_ready.connect(self._background_removal_preview_ready)
        controller.smart_layer_export_ready.connect(self._smart_layer_export_ready)
        controller.production_ready_changed.connect(self._production_ready_changed)
        controller.render_integrity_ready.connect(self._render_integrity_ready)
        controller.render_protection_changed.connect(self._render_protection_changed)
        controller.render_comparison_ready.connect(self._render_comparison_ready)
        controller.render_deleted.connect(self._render_deleted)
        controller.benchmark_case_exported.connect(self._benchmark_case_exported)
        controller.depth_pose_case_exported.connect(self._depth_pose_case_exported)
        controller.skeleton_tracking_ready.connect(self._skeleton_tracking_ready)
        controller.skeleton_correction_applied.connect(self._skeleton_correction_applied)
        controller.skeleton_correction_removed.connect(self._skeleton_correction_removed)
        controller.skeleton_retracking_ready.connect(self._skeleton_retracking_ready)
        controller.skeleton_fusion_candidate_ready.connect(self._review_skeleton_fusion)
        controller.skeleton_fusion_reviewed.connect(self._skeleton_fusion_reviewed)
        controller.processing_started.connect(self._processing_started)
        controller.processing_progress.connect(self._processing_progress)
        controller.processing_finished.connect(self._processing_finished)
        controller.processing_cancelled.connect(self._processing_cancelled)
        controller.media_link_state_changed.connect(self._media_link_state_changed)
        controller.recovery_available.connect(self._recovery_available)
        controller.project_recovered.connect(self._project_recovered)
        controller.project_migrated.connect(self._project_migrated)
        if controller.active_shot is not None:
            self.set_shot(controller.active_shot)

    def _build_header(self, project: Project) -> QHBoxLayout:
        layout = QHBoxLayout()
        heading = QLabel(project.name)
        heading.setObjectName("projectHeading")
        layout.addWidget(heading)
        layout.addStretch()
        self.import_button = QPushButton("Import Media")
        self.import_button.setObjectName("importMediaButton")
        self.import_button.clicked.connect(self._request_import)
        layout.addWidget(self.import_button)
        self.media_link_label = QLabel()
        self.media_link_label.setObjectName("mediaLinkWarning")
        self.media_link_label.setVisible(False)
        layout.addWidget(self.media_link_label)
        self.relink_button = QPushButton("Relink Media")
        self.relink_button.setVisible(False)
        self.relink_button.clicked.connect(self._request_relink)
        layout.addWidget(self.relink_button)
        self.processing_progress = QProgressBar()
        self.processing_progress.setFixedWidth(190)
        self.processing_progress.setVisible(False)
        layout.addWidget(self.processing_progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.controller.cancel_processing)
        layout.addWidget(self.cancel_button)
        return layout

    def _build_content(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(14)

        viewer_column = QVBoxLayout()
        self.viewer = GuidanceViewer()
        self.viewer.setFrameShape(QFrame.Shape.StyledPanel)
        self.viewer.guidance_changed.connect(self._save_guidance)
        self.viewer.skeleton_correction_changed.connect(self._stage_skeleton_correction)
        self.viewer.skeleton_joint_label_requested.connect(self._label_skeleton_joint)
        viewer_column.addLayout(self._build_guidance_toolbar())
        viewer_column.addWidget(self.viewer, 1)
        layout.addLayout(viewer_column, 1)

        inspector = QFrame()
        inspector.setObjectName("shotInspector")
        inspector.setFixedWidth(280)
        form = QFormLayout(inspector)
        self.media_name = QLabel("No media")
        self.media_details = QLabel("—")
        self.media_details.setWordWrap(True)
        self.range_start = QSpinBox()
        self.range_end = QSpinBox()
        self.master_frame = QSpinBox()
        self.apply_button = QPushButton("Apply Shot Settings")
        self.apply_button.clicked.connect(self._apply_shot_settings)
        for spinbox in (self.range_start, self.range_end, self.master_frame):
            spinbox.setEnabled(False)
        self.apply_button.setEnabled(False)
        form.addRow("Media", self.media_name)
        form.addRow("Properties", self.media_details)
        form.addRow("Range Start", self.range_start)
        form.addRow("Range End", self.range_end)
        form.addRow("Master Frame", self.master_frame)
        form.addRow(self.apply_button)
        layout.addWidget(inspector)
        return layout

    def _build_guidance_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        title = QLabel("ARTIST GUIDANCE")
        layout.addWidget(title)
        self.guidance_buttons: dict[GuidanceMode, QToolButton] = {}
        for mode, label in (
            (GuidanceMode.POSITIVE, "+ Include"),
            (GuidanceMode.NEGATIVE, "− Exclude"),
            (GuidanceMode.BOUNDING_REGION, "□ Region"),
            (GuidanceMode.SKELETON, "⌁ Bone"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setEnabled(False)
            button.clicked.connect(
                lambda checked, selected=mode: self._select_guidance_mode(selected, checked)
            )
            self.guidance_buttons[mode] = button
            layout.addWidget(button)
        self.clear_guidance_button = QToolButton()
        self.clear_guidance_button.setText("Clear")
        self.clear_guidance_button.setEnabled(False)
        self.clear_guidance_button.clicked.connect(self.viewer.clear_guidance)
        layout.addWidget(self.clear_guidance_button)
        self.body_25_button = QToolButton()
        self.body_25_button.setText("BODY_25")
        self.body_25_button.setEnabled(False)
        self.body_25_button.clicked.connect(self._apply_body_25_preset)
        layout.addWidget(self.body_25_button)
        self.auto_fuse_pose_button = QPushButton("Auto Fuse Pose")
        self.auto_fuse_pose_button.setEnabled(False)
        self.auto_fuse_pose_button.clicked.connect(
            lambda: self.controller.start_skeleton_fusion_detection(self._current_frame)
        )
        layout.addWidget(self.auto_fuse_pose_button)
        self.correct_pose_button = QToolButton()
        self.correct_pose_button.setText("✦ Correct Pose")
        self.correct_pose_button.setCheckable(True)
        self.correct_pose_button.setEnabled(False)
        self.correct_pose_button.clicked.connect(self._toggle_skeleton_correction)
        layout.addWidget(self.correct_pose_button)
        self.save_pose_button = QPushButton("Save Pose")
        self.save_pose_button.setVisible(False)
        self.save_pose_button.clicked.connect(self._save_skeleton_correction)
        layout.addWidget(self.save_pose_button)
        self.remove_pose_button = QPushButton("Remove Correction")
        self.remove_pose_button.setVisible(False)
        self.remove_pose_button.clicked.connect(self._remove_skeleton_correction)
        layout.addWidget(self.remove_pose_button)
        self.retrack_pose_button = QPushButton("Update Pose Track")
        self.retrack_pose_button.setVisible(False)
        self.retrack_pose_button.clicked.connect(self.controller.start_skeleton_retracking)
        layout.addWidget(self.retrack_pose_button)
        layout.addStretch()
        self.guidance_summary = QLabel("No guidance")
        layout.addWidget(self.guidance_summary)
        self.generate_button = QPushButton("Generate Hypothesis")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self.controller.start_hypothesis)
        layout.addWidget(self.generate_button)
        self.accept_button = QPushButton("Accept")
        self.accept_button.setObjectName("acceptHypothesisButton")
        self.accept_button.clicked.connect(self.controller.accept_hypothesis)
        self.reject_button = QPushButton("Reject")
        self.reject_button.clicked.connect(self.controller.reject_hypothesis)
        self.refine_button = QPushButton("Refine")
        self.refine_button.clicked.connect(self._refine_hypothesis)
        for review_button in (self.accept_button, self.reject_button, self.refine_button):
            review_button.setVisible(False)
            layout.addWidget(review_button)
        self.propagate_button = QPushButton("Propagate to Range Ends")
        self.propagate_button.setVisible(False)
        self.propagate_button.clicked.connect(self.controller.start_propagation)
        layout.addWidget(self.propagate_button)
        self.render_button = QPushButton("Render Smart Layer")
        self.render_button.setVisible(False)
        self.render_button.clicked.connect(self.controller.start_smart_layer_render)
        layout.addWidget(self.render_button)
        self.bg_removal_preview_button = QPushButton("Run Background Removal")
        self.bg_removal_preview_button.setObjectName("backgroundRemovalPreviewButton")
        self.bg_removal_preview_button.setVisible(False)
        self.bg_removal_preview_button.setToolTip(
            "Extract the current frame with the Background Removal plugin"
        )
        self.bg_removal_preview_button.clicked.connect(self._request_background_removal_preview)
        layout.addWidget(self.bg_removal_preview_button)
        self.bg_removal_clip_button = QPushButton("Process Clip (BG Removal)")
        self.bg_removal_clip_button.setObjectName("backgroundRemovalClipButton")
        self.bg_removal_clip_button.setVisible(True)
        self.bg_removal_clip_button.setEnabled(False)
        self.bg_removal_clip_button.setToolTip(
            "Requires validated Start/Master/End and one mask per frame in the shot range"
        )
        self.bg_removal_clip_button.clicked.connect(self._request_background_removal_clip)
        layout.addWidget(self.bg_removal_clip_button)
        self.benchmark_export_button = QPushButton("Add Benchmark Case")
        self.benchmark_export_button.setVisible(False)
        self.benchmark_export_button.clicked.connect(self._request_benchmark_export)
        layout.addWidget(self.benchmark_export_button)
        self.depth_pose_export_button = QPushButton("Add Pose QA Case")
        self.depth_pose_export_button.setVisible(False)
        self.depth_pose_export_button.clicked.connect(self._request_depth_pose_export)
        layout.addWidget(self.depth_pose_export_button)
        self.render_version = QComboBox()
        self.render_version.setVisible(False)
        self.render_version.currentIndexChanged.connect(self._render_version_changed)
        layout.addWidget(self.render_version)
        self.protect_render_button = QPushButton("Protect Version")
        self.protect_render_button.setCheckable(True)
        self.protect_render_button.setVisible(False)
        self.protect_render_button.clicked.connect(self._toggle_render_protection)
        layout.addWidget(self.protect_render_button)
        self.compare_render_button = QPushButton("Compare Previous")
        self.compare_render_button.setVisible(False)
        self.compare_render_button.clicked.connect(self._compare_previous_render)
        layout.addWidget(self.compare_render_button)
        self.render_details_button = QPushButton("Render Details")
        self.render_details_button.setVisible(False)
        self.render_details_button.clicked.connect(self._show_render_details)
        layout.addWidget(self.render_details_button)
        self.delete_render_button = QPushButton("Delete Version")
        self.delete_render_button.setVisible(False)
        self.delete_render_button.clicked.connect(self._delete_selected_render)
        layout.addWidget(self.delete_render_button)
        self.export_button = QPushButton("Export Render…")
        self.export_button.setVisible(False)
        self.export_button.clicked.connect(self._request_render_export)
        layout.addWidget(self.export_button)
        self.promote_production_button = QPushButton("Mark Production Ready")
        self.promote_production_button.setVisible(False)
        self.promote_production_button.clicked.connect(self._request_production_ready)
        layout.addWidget(self.promote_production_button)
        self.verify_render_button = QPushButton("Verify Render")
        self.verify_render_button.setVisible(False)
        self.verify_render_button.clicked.connect(self._verify_selected_render)
        layout.addWidget(self.verify_render_button)
        return layout

    def _build_timeline(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("timelinePanel")
        layout = QVBoxLayout(panel)
        labels = QHBoxLayout()
        timeline_title = QLabel("TIMELINE")
        self.frame_label = QLabel("Frame —")
        labels.addWidget(timeline_title)
        labels.addStretch()
        self.lifecycle_legend = QLabel("No tracking evidence")
        self.lifecycle_legend.setToolTip("Green: Tracked · Red: Lost · Blue: Recovered")
        labels.addWidget(self.lifecycle_legend)
        labels.addWidget(self.frame_label)
        layout.addLayout(labels)
        self.timeline = LifecycleTimeline()
        self.timeline.setEnabled(False)
        self.timeline.valueChanged.connect(self._timeline_changed)
        self.timeline.shot_range_previewed.connect(self._timeline_range_previewed)
        layout.addWidget(self.timeline)
        return panel

    def _request_import(self) -> None:
        choice = QMessageBox(self)
        choice.setWindowTitle("Import Media")
        choice.setText("Choose the media type to import.")
        video_button = choice.addButton("Video File…", QMessageBox.ButtonRole.AcceptRole)
        sequence_button = choice.addButton(
            "Image Sequence Folder…",
            QMessageBox.ButtonRole.ActionRole,
        )
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()
        clicked = choice.clickedButton()

        if clicked == video_button:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Import Media",
                filter="Video Files (*.mov *.mp4 *.m4v *.avi *.mkv);;All Files (*)",
            )
            if not path:
                return
            media_path = Path(path)
        elif clicked == sequence_button:
            directory = QFileDialog.getExistingDirectory(
                self,
                "Import Image Sequence",
                options=QFileDialog.Option.ShowDirsOnly,
            )
            if not directory:
                return
            media_path = Path(directory)
        else:
            return

        self.statusBar().showMessage("Inspecting media…")
        self.controller.import_media(media_path)

    def _request_relink(self) -> None:
        choice = QMessageBox(self)
        choice.setWindowTitle("Relink Source Media")
        choice.setText("Choose the media type to relink.")
        video_button = choice.addButton("Video File…", QMessageBox.ButtonRole.AcceptRole)
        sequence_button = choice.addButton(
            "Image Sequence Folder…",
            QMessageBox.ButtonRole.ActionRole,
        )
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()
        clicked = choice.clickedButton()

        if clicked == video_button:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Relink Source Media",
                filter="Video Files (*.mov *.mp4 *.m4v *.avi *.mkv);;All Files (*)",
            )
            if not path:
                return
            replacement = Path(path)
        elif clicked == sequence_button:
            directory = QFileDialog.getExistingDirectory(
                self,
                "Relink Image Sequence",
                options=QFileDialog.Option.ShowDirsOnly,
            )
            if not directory:
                return
            replacement = Path(directory)
        else:
            return

        if self.controller.relink_media(replacement):
            return
        shot = self.controller.active_shot
        if shot is None or shot.media.link_state.value != "changed":
            return
        answer = QMessageBox.question(
            self,
            "Confirm Changed Media",
            "The selected media differs from the original. Replace the source reference and "
            "invalidate assumptions based on the previous media?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.relink_media(replacement, accept_changed=True)

    def set_shot(self, shot: Shot) -> None:
        maximum = shot.media.frame_count - 1
        self.media_name.setText(shot.name)
        self.media_details.setText(
            f"{shot.media.width} × {shot.media.height}\n"
            f"{shot.media.frame_rate:.3f} fps\n{shot.media.frame_count} frames"
        )
        for spinbox in (self.range_start, self.range_end, self.master_frame):
            spinbox.setRange(0, maximum)
            spinbox.setEnabled(True)
        self.range_start.setValue(shot.range_start)
        self.range_end.setValue(shot.range_end)
        self.master_frame.setValue(shot.master_frame)
        self.timeline.setRange(0, maximum)
        self.timeline.set_shot_range(shot.range_start, shot.range_end, shot.master_frame)
        self.timeline.setValue(shot.master_frame)
        self.timeline.setEnabled(True)
        self.apply_button.setEnabled(True)
        for button in self.guidance_buttons.values():
            button.setEnabled(True)
        self.clear_guidance_button.setEnabled(True)
        self.body_25_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        if shot.smart_layers:
            layer = shot.smart_layers[0]
            intent = layer.artist_intent
            self.viewer.set_guidance(
                intent.points,
                intent.bounding_region,
                intent.skeleton_guidance,
            )
            self._update_guidance_summary(
                intent.points,
                intent.bounding_region,
                intent.skeleton_guidance,
            )
            self.timeline.set_observations(layer.temporal_observations)
            self.timeline.set_skeleton_corrections(layer.skeleton_corrections)
            self.retrack_pose_button.setVisible(bool(layer.skeleton_corrections))
            self.render_button.setVisible(
                layer.object_identity.maturity_state
                in {MaturityState.VALIDATED, MaturityState.PRODUCTION_READY}
            )
            self.bg_removal_preview_button.setVisible(bool(layer.frame_results))
            self._refresh_background_removal_clip_controls()
            self.benchmark_export_button.setVisible(
                layer.object_identity.maturity_state
                in {MaturityState.VALIDATED, MaturityState.PRODUCTION_READY}
            )
            self.depth_pose_export_button.setVisible(self._pose_export_available(shot))
            self._refresh_render_controls(layer.renders)
            self._refresh_production_ready_button(layer)
        else:
            self.timeline.set_observations([])
            self.timeline.set_skeleton_corrections([])
            self.retrack_pose_button.setVisible(False)
            self.render_button.setVisible(False)
            self.bg_removal_preview_button.setVisible(False)
            self._refresh_background_removal_clip_controls()
            self.benchmark_export_button.setVisible(False)
            self.depth_pose_export_button.setVisible(False)
            self.promote_production_button.setVisible(False)
            self._refresh_render_controls([])
        self.lifecycle_legend.setText(self.timeline.lifecycle_summary())
        self.statusBar().showMessage("Media ready — choose Shot Range and Master Frame")

    def set_frame(self, frame_number: int, frame: NDArray[np.uint8]) -> None:
        self._discard_skeleton_correction()
        self._current_frame = frame_number
        self.viewer.set_frame(frame)
        tracked_skeleton = None
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers and frame_number != shot.master_frame:
            observation = next(
                (
                    item
                    for item in shot.smart_layers[0].temporal_skeleton_observations
                    if item.frame_number == frame_number
                ),
                None,
            )
            if observation is not None:
                tracked_skeleton = observation.skeleton
        self.viewer.set_tracked_skeleton(tracked_skeleton)
        self.correct_pose_button.setEnabled(tracked_skeleton is not None)
        has_correction = bool(
            shot
            and shot.smart_layers
            and any(
                item.frame_number == frame_number
                for item in shot.smart_layers[0].skeleton_corrections
            )
        )
        self.remove_pose_button.setVisible(has_correction)
        self.frame_label.setText(f"Frame {frame_number}")

    def _timeline_changed(self, frame_number: int) -> None:
        self._discard_skeleton_correction()
        self.correct_pose_button.setEnabled(False)
        self.remove_pose_button.setVisible(False)
        self.frame_label.setText(f"Frame {frame_number}")
        self._pending_frame = frame_number
        self._scrub_timer.start()

    def _request_pending_frame(self) -> None:
        self.controller.request_frame(self._pending_frame)

    def _timeline_range_previewed(self, start: int, end: int, master: int) -> None:
        self.range_start.setValue(start)
        self.range_end.setValue(end)
        self.master_frame.setValue(master)
        self.statusBar().showMessage(
            f"Shot Range preview: {start}–{end} · Master Frame {master} · Apply to save"
        )

    def _apply_shot_settings(self) -> None:
        if self.controller.update_shot_selection(
            self.range_start.value(),
            self.range_end.value(),
            self.master_frame.value(),
        ):
            self.timeline.set_shot_range(
                self.range_start.value(), self.range_end.value(), self.master_frame.value()
            )
            self.timeline.setValue(self.master_frame.value())
            self.statusBar().showMessage("Shot Range and Master Frame saved")
            self._refresh_background_removal_clip_controls()

    def _select_guidance_mode(self, mode: GuidanceMode, checked: bool) -> None:
        self._discard_skeleton_correction()
        for candidate, button in self.guidance_buttons.items():
            if candidate != mode:
                button.setChecked(False)
        self.viewer.set_mode(mode if checked else GuidanceMode.NAVIGATE)

    def _toggle_skeleton_correction(self, checked: bool) -> None:
        for button in self.guidance_buttons.values():
            button.setChecked(False)
        if not checked:
            self._discard_skeleton_correction()
            return
        shot = self.controller.active_shot
        if shot is None or not shot.smart_layers:
            self._discard_skeleton_correction()
            return
        layer = shot.smart_layers[0]
        observation = next(
            (
                item
                for item in layer.temporal_skeleton_observations
                if item.frame_number == self._current_frame
            ),
            None,
        )
        if observation is None:
            self._discard_skeleton_correction()
            return
        self._pending_skeleton_correction = observation.skeleton.model_copy(deep=True)
        self.viewer.begin_skeleton_correction(self._pending_skeleton_correction)
        self.statusBar().showMessage("Pose correction — drag magenta joints, then choose Save Pose")

    def _stage_skeleton_correction(self, skeleton: SkeletonGuidance) -> None:
        self._pending_skeleton_correction = skeleton.model_copy(deep=True)
        self.save_pose_button.setVisible(True)
        self.statusBar().showMessage("Pose correction changed · Save Pose to commit")

    def _save_skeleton_correction(self) -> None:
        skeleton = self._pending_skeleton_correction
        if skeleton is None:
            return
        self.controller.apply_skeleton_correction(self._current_frame, skeleton)

    def _skeleton_correction_applied(
        self,
        frame_number: int,
        skeleton: SkeletonGuidance,
    ) -> None:
        if frame_number == self._current_frame:
            self.viewer.set_tracked_skeleton(skeleton)
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self.timeline.set_skeleton_corrections(shot.smart_layers[0].skeleton_corrections)
            self.lifecycle_legend.setText(self.timeline.lifecycle_summary())
            self.depth_pose_export_button.setVisible(self._pose_export_available(shot))
        self._discard_skeleton_correction()
        self.correct_pose_button.setEnabled(True)
        self.remove_pose_button.setVisible(True)
        self.retrack_pose_button.setVisible(True)
        self.statusBar().showMessage(f"Artist pose correction saved · Frame {frame_number}")

    def _remove_skeleton_correction(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove Pose Correction",
            f"Restore the model-tracked pose on Frame {self._current_frame}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.remove_skeleton_correction(self._current_frame)

    def _skeleton_correction_removed(
        self,
        frame_number: int,
        restored_skeleton: SkeletonGuidance | None,
    ) -> None:
        if frame_number == self._current_frame:
            self.viewer.set_tracked_skeleton(restored_skeleton)
            self.correct_pose_button.setEnabled(restored_skeleton is not None)
        self.remove_pose_button.setVisible(False)
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self.timeline.set_skeleton_corrections(shot.smart_layers[0].skeleton_corrections)
            self.lifecycle_legend.setText(self.timeline.lifecycle_summary())
            self.retrack_pose_button.setVisible(bool(shot.smart_layers[0].skeleton_corrections))
            self.depth_pose_export_button.setVisible(self._pose_export_available(shot))
        self.statusBar().showMessage(f"Pose correction removed · Frame {frame_number}")

    def _skeleton_retracking_ready(self, observations: list[object]) -> None:
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            layer = shot.smart_layers[0]
            self.timeline.set_observations(layer.temporal_observations)
            self.timeline.set_skeleton_corrections(layer.skeleton_corrections)
            self.lifecycle_legend.setText(self.timeline.lifecycle_summary())
            current = next(
                (
                    item
                    for item in layer.temporal_skeleton_observations
                    if item.frame_number == self._current_frame
                ),
                None,
            )
            self.viewer.set_tracked_skeleton(current.skeleton if current is not None else None)
        self.statusBar().showMessage(
            f"Pose track updated from artist anchors · {len(observations)} frames"
        )

    def _review_skeleton_fusion(self, candidate: SkeletonFusionCandidate) -> None:
        self.viewer.set_fusion_preview(
            candidate.detected_skeleton,
            candidate.fused_skeleton,
            joint_depths=candidate.joint_depths,
            depth_confidences=candidate.depth_confidences,
        )
        conflicts = ", ".join(candidate.conflict_labels) if candidate.conflict_labels else "none"
        depth_values = list(candidate.joint_depths.values())
        depth_summary = (
            f"{len(depth_values)} samples · {min(depth_values):.3f}–{max(depth_values):.3f}"
            if depth_values
            else "no sampled depth"
        )
        answer = QMessageBox.question(
            self,
            "Review Artist-Guided Skeleton Fusion",
            "Orange: automatic detection\n"
            "Green: fused proposal\n"
            "Yellow: artist guidance\n\n"
            f"Matched joints: {len(candidate.joint_confidences)}\n"
            f"Depth evidence: {depth_summary}\n"
            f"Conflicts kept at artist positions: {conflicts}\n\n"
            "Accept the fused skeleton?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self.controller.review_skeleton_fusion(
            candidate.id,
            accept=answer == QMessageBox.StandardButton.Yes,
        )

    def _skeleton_fusion_reviewed(self, candidate: SkeletonFusionCandidate) -> None:
        self.viewer.set_fusion_preview(None, None)
        shot = self.controller.active_shot
        if candidate.status == "accepted" and shot is not None and shot.smart_layers:
            layer = shot.smart_layers[0]
            if candidate.frame_number == shot.master_frame:
                self.viewer.set_guidance(
                    layer.artist_intent.points,
                    layer.artist_intent.bounding_region,
                    layer.artist_intent.skeleton_guidance,
                )
            elif candidate.frame_number == self._current_frame:
                self.viewer.set_tracked_skeleton(candidate.fused_skeleton)
        if shot is not None:
            self.depth_pose_export_button.setVisible(self._pose_export_available(shot))
        self.statusBar().showMessage(
            f"Skeleton fusion {candidate.status} · Frame {candidate.frame_number}"
        )

    def _discard_skeleton_correction(self) -> None:
        self._pending_skeleton_correction = None
        if hasattr(self, "save_pose_button"):
            self.save_pose_button.setVisible(False)
        if hasattr(self, "correct_pose_button"):
            self.correct_pose_button.setChecked(False)
        if hasattr(self, "viewer"):
            self.viewer.end_skeleton_correction()

    def _save_guidance(
        self,
        points: list[GuidancePoint],
        bounding_region: BoundingRegion | None,
        skeleton_guidance: SkeletonGuidance,
    ) -> None:
        layer = self.controller.update_artist_guidance(
            points,
            bounding_region,
            skeleton_guidance,
        )
        if layer is not None:
            self._update_guidance_summary(points, bounding_region, skeleton_guidance)
            self.statusBar().showMessage("Artist Guidance saved")

    def _apply_body_25_preset(self) -> None:
        if self.viewer.skeleton_guidance.joints:
            answer = QMessageBox.question(
                self,
                "Replace Skeleton Guidance",
                "Replace the current skeleton with a neutral OpenPose BODY_25-compatible preset?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.viewer.apply_skeleton_preset(openpose_body_25_preset())
        self.guidance_buttons[GuidanceMode.SKELETON].setChecked(True)
        self._select_guidance_mode(GuidanceMode.SKELETON, True)
        self.statusBar().showMessage(
            "BODY_25-compatible skeleton added · drag additional bones or relabel joints"
        )

    def _label_skeleton_joint(self, joint_id: UUID, current_label: str | None) -> None:
        label, accepted = QInputDialog.getText(
            self,
            "Label Skeleton Joint",
            "Semantic label (for example: left_shoulder)",
            text=current_label or "",
        )
        if not accepted:
            return
        normalized = label.strip().lower().replace("-", "_").replace(" ", "_")
        semantic_label = normalized or None
        if self.viewer.set_skeleton_joint_label(joint_id, semantic_label):
            self.statusBar().showMessage(
                f"Skeleton joint label saved · {semantic_label or 'unlabeled'}"
            )
            return
        QMessageBox.warning(
            self,
            "Invalid Joint Label",
            "Use a unique snake_case label beginning with a letter, such as left_shoulder.",
        )

    def _show_hypothesis(
        self,
        frame_number: int,
        mask: NDArray[np.uint8],
        confidence: float,
    ) -> None:
        self.viewer.set_mask_overlay(mask)
        self.frame_label.setText(f"Frame {frame_number} · Hypothesis {confidence:.0%}")
        self._show_review_controls(True)
        self.statusBar().showMessage("Review Object Hypothesis — Accept, Reject, or Refine")

    def _set_hypothesis_state(self, state: str) -> None:
        if state == "confirmed":
            self._show_review_controls(False)
            self.propagate_button.setVisible(True)
            self.bg_removal_preview_button.setVisible(True)
            self.statusBar().showMessage("Object Identity confirmed")
        elif state == "rejected":
            self.viewer.set_mask_overlay(None)
            self._show_review_controls(False)
            self.bg_removal_preview_button.setVisible(False)
            self.statusBar().showMessage("Hypothesis rejected — refine Artist Guidance")

    def _show_validation_ready(self, frame_results: list[object]) -> None:
        self.propagate_button.setVisible(False)
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self.timeline.set_observations(shot.smart_layers[0].temporal_observations)
            self.timeline.set_skeleton_corrections(shot.smart_layers[0].skeleton_corrections)
            self.lifecycle_legend.setText(self.timeline.lifecycle_summary())
        self.statusBar().showMessage(
            f"Propagation complete — {len(frame_results)} validation frames ready"
        )
        self.validation_dialog = ValidationDialog(self.controller)
        self.validation_dialog.setStyleSheet(self.styleSheet())
        self.validation_dialog.show()

    def _validation_state_changed(self, frame_results: list[object]) -> None:
        del frame_results
        shot = self.controller.active_shot
        layer = shot.smart_layers[0] if shot and shot.smart_layers else None
        renderable = bool(
            layer
            and layer.object_identity.maturity_state
            in {MaturityState.VALIDATED, MaturityState.PRODUCTION_READY}
        )
        self.render_button.setVisible(renderable)
        self._refresh_background_removal_clip_controls()
        if layer is not None:
            self.bg_removal_preview_button.setVisible(
                bool(layer.frame_results) or renderable
            )
        self.benchmark_export_button.setVisible(renderable)
        if shot is not None:
            self.depth_pose_export_button.setVisible(self._pose_export_available(shot))
        if layer is not None:
            self._refresh_production_ready_button(layer)
        else:
            self.promote_production_button.setVisible(False)

    @staticmethod
    def _pose_export_available(shot: Shot) -> bool:
        if not shot.smart_layers:
            return False
        layer = shot.smart_layers[0]
        if not layer.artist_intent.skeleton_guidance.semantic_joint_map():
            return False
        return any(
            correction.frame_number == shot.master_frame
            for correction in layer.skeleton_corrections
        ) or any(
            candidate.frame_number == shot.master_frame and candidate.status == "accepted"
            for candidate in layer.skeleton_fusion_candidates
        )

    def _request_benchmark_export(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Real-Footage Benchmark Dataset",
        )
        if not directory:
            return
        case_id, accepted = QInputDialog.getText(
            self,
            "Add Benchmark Case",
            "Case ID (for example: human-closeup-01)",
        )
        if accepted and case_id.strip():
            self.controller.export_benchmark_case(Path(directory), case_id.strip())

    def _benchmark_case_exported(self, case_id: str, manifest_path: str) -> None:
        self.statusBar().showMessage(
            f"Benchmark candidate '{case_id}' added · human QA required · {manifest_path}"
        )

    def _request_depth_pose_export(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose Depth/Pose QA Dataset")
        if not directory:
            return
        case_id, accepted = QInputDialog.getText(
            self,
            "Add Pose QA Case",
            "Case ID (for example: standing-person-front-01)",
        )
        if accepted and case_id.strip():
            self.controller.export_depth_pose_case(Path(directory), case_id.strip())

    def _depth_pose_case_exported(
        self, case_id: str, manifest_path: str, ground_truth_source: str
    ) -> None:
        source = ground_truth_source.replace("_", " ")
        self.statusBar().showMessage(
            f"Pose QA candidate '{case_id}' added from {source} · human QA required · "
            f"{manifest_path}"
        )

    def _skeleton_tracking_ready(self, observations: list[object]) -> None:
        self.statusBar().showMessage(
            f"Skeleton tracking complete · {len(observations)} temporal pose frames"
        )

    def _smart_layer_render_ready(self, render: object) -> None:
        version = getattr(render, "version", "—")
        frame_start = getattr(render, "frame_start", "—")
        frame_end = getattr(render, "frame_end", "—")
        self.statusBar().showMessage(
            f"Smart Layer render v{version} ready · frames {frame_start}–{frame_end}"
        )
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self._refresh_render_controls(shot.smart_layers[0].renders)
            index = self.render_version.findData(version)
            if index >= 0:
                self.render_version.setCurrentIndex(index)

    def _refresh_render_controls(self, renders: Sequence[SmartLayerRender]) -> None:
        current = self.render_version.currentData()
        self.render_version.blockSignals(True)
        self.render_version.clear()
        for render in renders:
            label = f"Render v{render.version:04d}"
            if render.protected:
                label += " · Protected"
            self.render_version.addItem(label, render.version)
        if current is not None:
            index = self.render_version.findData(current)
            if index >= 0:
                self.render_version.setCurrentIndex(index)
        self.render_version.blockSignals(False)
        available = self.render_version.count() > 0
        self.render_version.setVisible(available)
        self.protect_render_button.setVisible(available)
        self.compare_render_button.setVisible(self.render_version.count() > 1)
        self.render_details_button.setVisible(available)
        self.delete_render_button.setVisible(available)
        self.export_button.setVisible(available)
        self.verify_render_button.setVisible(available)
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self._refresh_production_ready_button(shot.smart_layers[0])
        else:
            self.promote_production_button.setVisible(False)
        self._render_version_changed()

    def _refresh_production_ready_button(self, layer: object) -> None:
        maturity = getattr(getattr(layer, "object_identity", None), "maturity_state", None)
        has_renders = bool(getattr(layer, "renders", ()))
        eligible = maturity == MaturityState.VALIDATED and has_renders
        already = maturity == MaturityState.PRODUCTION_READY
        self.promote_production_button.setVisible(eligible or already)
        self.promote_production_button.setEnabled(eligible)
        self.promote_production_button.setText(
            "Production Ready" if already else "Mark Production Ready"
        )

    def _request_production_ready(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Mark Production Ready",
            "Promote this validated Smart Layer to production_ready maturity?",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.controller.promote_to_production_ready()

    def _production_ready_changed(self, layer: object) -> None:
        self._refresh_production_ready_button(layer)
        self.render_button.setVisible(True)
        self.bg_removal_preview_button.setVisible(True)
        self._refresh_background_removal_clip_controls()
        self.benchmark_export_button.setVisible(True)
        self.statusBar().showMessage("Smart Layer marked production ready")

    def _selected_render(self) -> SmartLayerRender | None:
        version = self.render_version.currentData()
        shot = self.controller.active_shot
        if not isinstance(version, int) or shot is None or not shot.smart_layers:
            return None
        return next(
            (render for render in shot.smart_layers[0].renders if render.version == version),
            None,
        )

    def _render_version_changed(self, index: int = -1) -> None:
        del index
        render = self._selected_render()
        protected = bool(render and render.protected)
        self.protect_render_button.blockSignals(True)
        self.protect_render_button.setChecked(protected)
        self.protect_render_button.setText("Protected" if protected else "Protect Version")
        self.protect_render_button.blockSignals(False)
        self.delete_render_button.setEnabled(render is not None and not protected)
        current_version = render.version if render is not None else None
        has_previous = (
            any(
                isinstance(self.render_version.itemData(item), int)
                and self.render_version.itemData(item) < current_version
                for item in range(self.render_version.count())
            )
            if current_version is not None
            else False
        )
        self.compare_render_button.setEnabled(has_previous)

    def _toggle_render_protection(self, protected: bool) -> None:
        render = self._selected_render()
        if render is None or not self.controller.set_render_protected(render.version, protected):
            self._render_version_changed()

    def _compare_previous_render(self) -> None:
        render = self._selected_render()
        if render is None:
            return
        previous_versions = [
            version
            for item in range(self.render_version.count())
            if isinstance((version := self.render_version.itemData(item)), int)
            and version < render.version
        ]
        if previous_versions:
            self.controller.compare_render_versions(max(previous_versions), render.version)

    def _render_protection_changed(self, version: int, protected: bool) -> None:
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self._refresh_render_controls(shot.smart_layers[0].renders)
            index = self.render_version.findData(version)
            if index >= 0:
                self.render_version.setCurrentIndex(index)
        state = "protected" if protected else "unprotected"
        self.statusBar().showMessage(f"Render v{version:04d} {state}")

    def _render_comparison_ready(self, report: object) -> None:
        base = getattr(report, "base_version", 0)
        target = getattr(report, "target_version", 0)
        shared = getattr(report, "shared_frames", 0)
        if bool(getattr(report, "identical", False)):
            self.statusBar().showMessage(
                f"Render v{base:04d} and v{target:04d} are identical · {shared} shared frames"
            )
            return
        changed = len(getattr(report, "changed_frames", ()))
        added = len(getattr(report, "added_frames", ()))
        removed = len(getattr(report, "removed_frames", ()))
        self.statusBar().showMessage(
            f"Render v{base:04d} → v{target:04d}: "
            f"{changed} changed · {added} added · {removed} removed"
        )

    def _delete_selected_render(self) -> None:
        render = self._selected_render()
        if render is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Render Version",
            f"Delete Smart Layer render v{render.version:04d} and all of its PNG frames?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.delete_smart_layer_render(render.version)

    def _show_render_details(self) -> None:
        render = self._selected_render()
        if render is None:
            return
        report = self.controller.inspect_smart_layer_render(render.version)
        if report is None:
            return
        integrity = "Valid" if report.integrity_valid else "Failed"
        protection = "Protected" if report.protected else "Unprotected"
        size = self._format_byte_size(report.storage_bytes)
        details = (
            f"Render version: v{report.version:04d}\n"
            f"Source Smart Layer: v{report.source_layer_version}\n"
            f"Created: {report.created_at}\n"
            f"Frame range: {report.frame_start}–{report.frame_end} "
            f"({report.frame_count} frames)\n"
            f"Storage: {size}\n"
            f"Protection: {protection}\n"
            f"Integrity: {integrity}"
        )
        if report.issues:
            details += "\n\nIssues:\n" + "\n".join(f"• {issue}" for issue in report.issues)
        QMessageBox.information(self, "Smart Layer Render Details", details)

    @staticmethod
    def _format_byte_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def _render_deleted(self, version: int) -> None:
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self._refresh_render_controls(shot.smart_layers[0].renders)
        else:
            self._refresh_render_controls([])
        self.statusBar().showMessage(f"Render v{version:04d} deleted")

    def _request_background_removal_preview(self) -> None:
        self.controller.start_background_removal_preview(self._current_frame)

    def _request_background_removal_clip(self) -> None:
        readiness = self.controller.background_removal_clip_readiness()
        if not readiness.ready:
            QMessageBox.warning(
                self,
                "Background Removal Not Ready",
                readiness.reason,
            )
            self.statusBar().showMessage(readiness.reason)
            self._refresh_background_removal_clip_controls()
            return
        self.controller.start_background_removal_clip()

    def _refresh_background_removal_clip_controls(self) -> None:
        readiness = self.controller.background_removal_clip_readiness()
        self.bg_removal_clip_button.setVisible(True)
        busy = self.cancel_button.isVisible()
        self.bg_removal_clip_button.setEnabled(readiness.ready and not busy)
        if readiness.ready:
            self.bg_removal_clip_button.setToolTip(
                "Run Background Removal across the shot range, then Export"
            )
        else:
            self.bg_removal_clip_button.setToolTip(readiness.reason)

    def _background_removal_preview_ready(
        self,
        frame_number: int,
        rgba: NDArray[np.uint8],
    ) -> None:
        rgb = np.ascontiguousarray(rgba[:, :, :3])
        alpha = np.ascontiguousarray(rgba[:, :, 3])
        self.viewer.set_frame(rgb)
        self.viewer.set_mask_overlay(alpha)
        self.frame_label.setText(f"Frame {frame_number} · Background Removal preview")
        self.statusBar().showMessage(
            f"Background Removal preview ready — frame {frame_number} "
            "(use Process Clip then Export for a full range)"
        )

    def _request_render_export(self) -> None:
        format_labels = {
            "PNG Sequence": "png_sequence",
            "OpenEXR Sequence": "openexr_sequence",
            "RGBA QuickTime (.mov)": "rgba_mov",
        }
        label, accepted = QInputDialog.getItem(
            self,
            "Export Smart Layer Render",
            "Production format:",
            list(format_labels),
            0,
            False,
        )
        if not accepted:
            return
        directory = QFileDialog.getExistingDirectory(self, "Export Smart Layer Render")
        if not directory:
            return
        version = self.render_version.currentData()
        if not isinstance(version, int):
            QMessageBox.warning(
                self,
                "Export Render",
                "No Smart Layer render is selected. Process Clip (Background Removal) "
                "or Render Smart Layer first, then export.",
            )
            return
        self.controller.export_smart_layer_render(
            Path(directory),
            version,
            format=format_labels[label],
        )

    def _smart_layer_export_ready(self, export_path: str) -> None:
        self.statusBar().showMessage(f"Smart Layer exported: {export_path}")

    def _verify_selected_render(self) -> None:
        version = self.render_version.currentData()
        if isinstance(version, int):
            self.controller.verify_smart_layer_render(version)

    def _render_integrity_ready(self, report: object) -> None:
        valid = bool(getattr(report, "valid", False))
        version = getattr(report, "version", "—")
        checked = getattr(report, "checked_files", 0)
        issues = getattr(report, "issues", ())
        if valid:
            self.statusBar().showMessage(
                f"Render v{version:04d} verified · {checked} frame checksums valid"
            )
        else:
            detail = issues[0] if issues else "Unknown integrity failure"
            self.statusBar().showMessage(f"Render verification failed: {detail}")

    def _processing_started(self, name: str) -> None:
        self.processing_progress.setRange(0, 0)
        self.processing_progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.import_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.propagate_button.setEnabled(False)
        self.render_button.setEnabled(False)
        self.bg_removal_preview_button.setEnabled(False)
        self.bg_removal_clip_button.setEnabled(False)
        self.benchmark_export_button.setEnabled(False)
        self.depth_pose_export_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.promote_production_button.setEnabled(False)
        self.verify_render_button.setEnabled(False)
        self.protect_render_button.setEnabled(False)
        self.compare_render_button.setEnabled(False)
        self.render_details_button.setEnabled(False)
        self.delete_render_button.setEnabled(False)
        self.retrack_pose_button.setEnabled(False)
        self.auto_fuse_pose_button.setEnabled(False)
        self.statusBar().showMessage(f"Processing: {name}")

    def _processing_progress(
        self,
        name: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        del name
        self.processing_progress.setRange(0, max(1, total))
        self.processing_progress.setValue(current)
        self.statusBar().showMessage(message)

    def _processing_finished(self, name: str) -> None:
        self._reset_processing_ui()
        self.statusBar().showMessage(f"Completed: {name}")

    def _processing_cancelled(self, name: str) -> None:
        self._reset_processing_ui()
        self.propagate_button.setVisible(True)
        self.statusBar().showMessage(f"Cancelled: {name} — no partial results committed")

    def _reset_processing_ui(self) -> None:
        self.processing_progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.import_button.setEnabled(True)
        self.generate_button.setEnabled(self.controller.active_shot is not None)
        self.propagate_button.setEnabled(True)
        self.render_button.setEnabled(True)
        self.bg_removal_preview_button.setEnabled(True)
        self.bg_removal_clip_button.setEnabled(True)
        self.benchmark_export_button.setEnabled(True)
        self.depth_pose_export_button.setEnabled(True)
        self.export_button.setEnabled(True)
        shot = self.controller.active_shot
        if shot is not None and shot.smart_layers:
            self._refresh_production_ready_button(shot.smart_layers[0])
        self.verify_render_button.setEnabled(True)
        self.protect_render_button.setEnabled(True)
        self.render_details_button.setEnabled(True)
        self.retrack_pose_button.setEnabled(True)
        shot = self.controller.active_shot
        self.auto_fuse_pose_button.setEnabled(
            bool(
                shot
                and shot.smart_layers
                and shot.smart_layers[0].artist_intent.skeleton_guidance.semantic_joint_map()
            )
        )
        self._render_version_changed()
        self._refresh_background_removal_clip_controls()

    def _media_link_state_changed(self, state: str, message: str) -> None:
        linked = state == "linked"
        self.media_link_label.setText(message)
        self.media_link_label.setVisible(not linked)
        self.relink_button.setVisible(not linked)
        self.timeline.setEnabled(linked and self.controller.active_shot is not None)
        self.generate_button.setEnabled(linked and self.controller.active_shot is not None)
        if not linked:
            self.statusBar().showMessage(message)

    def _recovery_available(self, journal_path: str) -> None:
        answer = QMessageBox.question(
            self,
            "Recovery Data Found",
            "NOVA Layer found an autosave journal from an interrupted session.\n\n"
            f"{journal_path}\n\nRestore the autosaved state? Selecting No discards it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.restore_recovery()
        else:
            self.controller.discard_recovery()

    def _project_recovered(self, project: Project) -> None:
        self.setWindowTitle(f"{project.name} — NOVA Layer")
        if self.controller.active_shot is not None:
            self.set_shot(self.controller.active_shot)
        self.statusBar().showMessage("Autosave recovery restored")

    def _project_migrated(self, steps: list[str]) -> None:
        self.statusBar().showMessage(
            f"Project loaded through schema migration: {', '.join(steps)}. "
            "The original package remains unchanged until the next save."
        )

    def _show_review_controls(self, visible: bool) -> None:
        self.accept_button.setVisible(visible)
        self.reject_button.setVisible(visible)
        self.refine_button.setVisible(visible)

    def _refine_hypothesis(self) -> None:
        self.viewer.set_mask_overlay(None)
        self._show_review_controls(False)
        self.statusBar().showMessage("Refine Artist Guidance and generate again")

    def _update_guidance_summary(
        self,
        points: list[GuidancePoint],
        bounding_region: BoundingRegion | None,
        skeleton_guidance: SkeletonGuidance | None = None,
    ) -> None:
        positive = sum(point.polarity == "positive" for point in points)
        negative = sum(point.polarity == "negative" for point in points)
        region = "region set" if bounding_region else "no region"
        skeleton = skeleton_guidance or SkeletonGuidance()
        self.auto_fuse_pose_button.setEnabled(bool(skeleton.semantic_joint_map()))
        self.guidance_summary.setText(
            f"+{positive}  −{negative}  · {region} · "
            f"{len(skeleton.joints)} joints/{len(skeleton.bones)} bones"
        )
