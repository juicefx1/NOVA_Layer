"""Depth Assist dock panel (Phase D2/D3) — Analyze → Pick → Assist with Depth."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.depth_guidance import (
    NEGATIVE_FULL_MIN_COVERAGE,
    REDUCED_NEGATIVE_STATUS,
    DepthGuidanceProposal,
)
from nova_layer.app.depth_region import DEFAULT_DEPTH_TOLERANCE, DepthRegion


class DepthAssistPanel(QWidget):
    """Session-only Depth Assist controls. Does not create mattes or run SAM."""

    analyze_requested = Signal()
    cancel_requested = Signal()
    overlay_toggled = Signal(bool)
    opacity_changed = Signal(float)
    pick_toggled = Signal(bool)
    tolerance_changed = Signal(float)
    clear_region_requested = Signal()
    assist_requested = Signal()
    clear_depth_guidance_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("depthAssistPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        actions = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze Scene")
        self.analyze_button.setObjectName("depthAnalyzeButton")
        self.analyze_button.clicked.connect(self.analyze_requested.emit)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("depthCancelButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        form = QFormLayout()
        self.overlay_check = QCheckBox("Depth Overlay")
        self.overlay_check.setObjectName("depthOverlayCheck")
        self.overlay_check.setEnabled(False)
        self.overlay_check.toggled.connect(self.overlay_toggled.emit)
        form.addRow("", self.overlay_check)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("depthOpacitySlider")
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(55)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setObjectName("depthOpacitySpin")
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(0.55)
        self.opacity_slider.valueChanged.connect(self._slider_to_opacity)
        self.opacity_spin.valueChanged.connect(self._opacity_to_slider)
        opacity_row.addWidget(self.opacity_slider)
        opacity_row.addWidget(self.opacity_spin)
        form.addRow("Opacity", opacity_row)

        self.pick_button = QPushButton("Pick Region")
        self.pick_button.setObjectName("depthPickButton")
        self.pick_button.setCheckable(True)
        self.pick_button.setEnabled(False)
        self.pick_button.toggled.connect(self.pick_toggled.emit)
        form.addRow("", self.pick_button)

        tol_row = QHBoxLayout()
        self.tolerance_slider = QSlider(Qt.Orientation.Horizontal)
        self.tolerance_slider.setObjectName("depthToleranceSlider")
        self.tolerance_slider.setRange(0, 100)
        self.tolerance_slider.setValue(int(round(DEFAULT_DEPTH_TOLERANCE * 100)))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setObjectName("depthToleranceSpin")
        self.tolerance_spin.setRange(0.0, 1.0)
        self.tolerance_spin.setSingleStep(0.01)
        self.tolerance_spin.setDecimals(2)
        self.tolerance_spin.setValue(DEFAULT_DEPTH_TOLERANCE)
        self.tolerance_slider.valueChanged.connect(self._slider_to_tolerance)
        self.tolerance_spin.valueChanged.connect(self._tolerance_to_slider)
        tol_row.addWidget(self.tolerance_slider)
        tol_row.addWidget(self.tolerance_spin)
        form.addRow("Depth Tolerance", tol_row)
        root.addLayout(form)

        stats = QGroupBox("Depth Region")
        stats_form = QFormLayout(stats)
        self.seed_depth_label = QLabel("—")
        self.seed_depth_label.setObjectName("depthSeedLabel")
        self.pixel_count_label = QLabel("—")
        self.pixel_count_label.setObjectName("depthPixelCountLabel")
        self.coverage_label = QLabel("—")
        self.coverage_label.setObjectName("depthCoverageLabel")
        self.bbox_label = QLabel("—")
        self.bbox_label.setObjectName("depthBBoxLabel")
        for widget in (
            self.seed_depth_label,
            self.pixel_count_label,
            self.coverage_label,
            self.bbox_label,
        ):
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        stats_form.addRow("Seed depth", self.seed_depth_label)
        stats_form.addRow("Pixels", self.pixel_count_label)
        stats_form.addRow("Coverage", self.coverage_label)
        stats_form.addRow("Bounding box", self.bbox_label)
        root.addWidget(stats)

        self.clear_region_button = QPushButton("Clear Region")
        self.clear_region_button.setObjectName("depthClearRegionButton")
        self.clear_region_button.setEnabled(False)
        self.clear_region_button.clicked.connect(self.clear_region_requested.emit)
        root.addWidget(self.clear_region_button)

        guidance = QGroupBox("Depth → Guidance")
        guidance_form = QFormLayout(guidance)
        assist_row = QHBoxLayout()
        self.assist_button = QPushButton("Assist with Depth")
        self.assist_button.setObjectName("depthAssistButton")
        self.assist_button.setEnabled(False)
        self.assist_button.clicked.connect(self.assist_requested.emit)
        self.clear_depth_guidance_button = QPushButton("Clear Depth Guidance")
        self.clear_depth_guidance_button.setObjectName("depthClearGuidanceButton")
        self.clear_depth_guidance_button.setEnabled(False)
        self.clear_depth_guidance_button.clicked.connect(
            self.clear_depth_guidance_requested.emit
        )
        assist_row.addWidget(self.assist_button)
        assist_row.addWidget(self.clear_depth_guidance_button)
        guidance_form.addRow(assist_row)
        self.guidance_positive_label = QLabel("—")
        self.guidance_positive_label.setObjectName("depthGuidancePositiveLabel")
        self.guidance_negative_label = QLabel("—")
        self.guidance_negative_label.setObjectName("depthGuidanceNegativeLabel")
        self.guidance_bbox_label = QLabel("—")
        self.guidance_bbox_label.setObjectName("depthGuidanceBBoxLabel")
        for widget in (
            self.guidance_positive_label,
            self.guidance_negative_label,
            self.guidance_bbox_label,
        ):
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        guidance_form.addRow("Positive points", self.guidance_positive_label)
        guidance_form.addRow("Negative points", self.guidance_negative_label)
        guidance_form.addRow("Bounding box", self.guidance_bbox_label)
        root.addWidget(guidance)

        self.status_label = QLabel(
            "Depth Assist builds Depth Regions (spatial priors), not object mattes."
        )
        self.status_label.setObjectName("depthAssistStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_analyzing(self, analyzing: bool) -> None:
        self.analyze_button.setEnabled(not analyzing)
        self.cancel_button.setEnabled(analyzing)

    def set_depth_available(self, available: bool) -> None:
        self.overlay_check.setEnabled(available)
        self.pick_button.setEnabled(available)
        if not available:
            self.overlay_check.blockSignals(True)
            self.overlay_check.setChecked(False)
            self.overlay_check.blockSignals(False)
            self.pick_button.blockSignals(True)
            self.pick_button.setChecked(False)
            self.pick_button.blockSignals(False)
            self.set_assist_enabled(False)

    def set_assist_enabled(self, enabled: bool) -> None:
        self.assist_button.setEnabled(bool(enabled))

    def set_empty_state(self, message: str = "No project/media — import a shot first.") -> None:
        self.set_analyzing(False)
        self.set_depth_available(False)
        self.clear_region_stats()
        self.clear_guidance_summary()
        self.set_status(message)

    def clear_region_stats(self) -> None:
        self.seed_depth_label.setText("—")
        self.pixel_count_label.setText("—")
        self.coverage_label.setText("—")
        self.bbox_label.setText("—")
        self.clear_region_button.setEnabled(False)
        self.set_assist_enabled(False)

    def clear_guidance_summary(self) -> None:
        self.guidance_positive_label.setText("—")
        self.guidance_negative_label.setText("—")
        self.guidance_bbox_label.setText("—")
        self.clear_depth_guidance_button.setEnabled(False)

    def apply_region(self, region: DepthRegion | None) -> None:
        if region is None:
            self.clear_region_stats()
            return
        self.seed_depth_label.setText(f"{region.seed_depth:.4f}")
        self.pixel_count_label.setText(str(region.pixel_count))
        self.coverage_label.setText(f"{region.coverage * 100.0:.2f}%")
        if region.bounding_box is None:
            self.bbox_label.setText("—")
        else:
            x0, y0, x1, y1 = region.bounding_box
            self.bbox_label.setText(f"({x0},{y0})–({x1},{y1})")
        self.clear_region_button.setEnabled(region.pixel_count > 0)
        self.set_assist_enabled(region.pixel_count > 0)
        status_parts: list[str] = []
        if region.warning:
            status_parts.append(region.warning)
        elif (
            region.pixel_count > 0
            and float(region.coverage) < NEGATIVE_FULL_MIN_COVERAGE
        ):
            status_parts.append(REDUCED_NEGATIVE_STATUS)
        if status_parts:
            self.set_status(" ".join(dict.fromkeys(status_parts)))
        else:
            self.set_status(
                "Depth Region ready — Assist with Depth generates SAM guidance points."
            )

    def apply_guidance_proposal(self, proposal: DepthGuidanceProposal | None) -> None:
        if proposal is None:
            self.clear_guidance_summary()
            return
        self.guidance_positive_label.setText(str(len(proposal.positive_points)))
        self.guidance_negative_label.setText(str(len(proposal.negative_points)))
        self.guidance_bbox_label.setText(
            "yes" if proposal.bounding_region is not None else "no"
        )
        self.clear_depth_guidance_button.setEnabled(
            bool(
                proposal.positive_points
                or proposal.negative_points
                or proposal.bounding_region
            )
        )
        if proposal.warning:
            self.set_status(proposal.warning)
        else:
            self.set_status(
                "Depth Assist guidance added — refine with +/- points, then Generate Hypothesis."
            )

    def current_tolerance(self) -> float:
        return float(self.tolerance_spin.value())

    def current_opacity(self) -> float:
        return float(self.opacity_spin.value())

    def _slider_to_opacity(self, value: int) -> None:
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(value / 100.0)
        self.opacity_spin.blockSignals(False)
        self.opacity_changed.emit(value / 100.0)

    def _opacity_to_slider(self, value: float) -> None:
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(round(value * 100)))
        self.opacity_slider.blockSignals(False)
        self.opacity_changed.emit(float(value))

    def _slider_to_tolerance(self, value: int) -> None:
        self.tolerance_spin.blockSignals(True)
        self.tolerance_spin.setValue(value / 100.0)
        self.tolerance_spin.blockSignals(False)
        self.tolerance_changed.emit(value / 100.0)

    def _tolerance_to_slider(self, value: float) -> None:
        self.tolerance_slider.blockSignals(True)
        self.tolerance_slider.setValue(int(round(value * 100)))
        self.tolerance_slider.blockSignals(False)
        self.tolerance_changed.emit(float(value))
