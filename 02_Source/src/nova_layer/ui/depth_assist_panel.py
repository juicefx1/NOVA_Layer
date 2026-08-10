"""Depth Assist dock panel (Phase D2) — Analyze Scene → Overlay → Pick Region."""

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

    def set_empty_state(self, message: str = "No project/media — import a shot first.") -> None:
        self.set_analyzing(False)
        self.set_depth_available(False)
        self.clear_region_stats()
        self.set_status(message)

    def clear_region_stats(self) -> None:
        self.seed_depth_label.setText("—")
        self.pixel_count_label.setText("—")
        self.coverage_label.setText("—")
        self.bbox_label.setText("—")
        self.clear_region_button.setEnabled(False)

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
        if region.warning:
            self.set_status(region.warning)

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
