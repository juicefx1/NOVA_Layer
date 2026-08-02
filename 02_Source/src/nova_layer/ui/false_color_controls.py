"""False Color dock controls (Phase 9D-2)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from nova_layer.app.false_color import (
    FalseColorMode,
    FalseColorSettings,
    legend_for_mode,
)


class FalseColorControlsPanel(QWidget):
    """Mode / opacity / legend controls for Viewer False Color."""

    settings_changed = Signal(object)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("falseColorControlsPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("falseColorModeCombo")
        self.mode_combo.addItem("Off", FalseColorMode.OFF.value)
        self.mode_combo.addItem("Preview Luma", FalseColorMode.PREVIEW_LUMA.value)
        self.mode_combo.addItem("Source Luma", FalseColorMode.SOURCE_LUMA.value)
        self.mode_combo.addItem("Scene Exposure", FalseColorMode.SCENE_EXPOSURE.value)
        self.mode_combo.addItem("Scene Clipping", FalseColorMode.SCENE_CLIPPING.value)
        self.mode_combo.currentIndexChanged.connect(self._emit_settings)
        form.addRow("Mode", self.mode_combo)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("falseColorOpacitySlider")
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setObjectName("falseColorOpacitySpin")
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(1.0)
        self.opacity_slider.valueChanged.connect(self._slider_to_spin)
        self.opacity_spin.valueChanged.connect(self._spin_to_slider)
        opacity_row.addWidget(self.opacity_slider)
        opacity_row.addWidget(self.opacity_spin)
        form.addRow("Opacity", opacity_row)

        self.legend_check = QCheckBox("Show Legend")
        self.legend_check.setObjectName("falseColorLegendCheck")
        self.legend_check.setChecked(True)
        self.legend_check.toggled.connect(self._emit_settings)
        form.addRow("", self.legend_check)
        root.addLayout(form)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("falseColorResetButton")
        self.reset_button.clicked.connect(self._on_reset)
        root.addWidget(self.reset_button)

        legend_box = QGroupBox("Legend")
        legend_layout = QVBoxLayout(legend_box)
        self.legend_label = QLabel("Mode: Off")
        self.legend_label.setObjectName("falseColorLegendLabel")
        self.legend_label.setWordWrap(True)
        self.legend_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        legend_layout.addWidget(self.legend_label)
        root.addWidget(legend_box)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("falseColorStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch()
        self._update_legend_text()

    def current_settings(self) -> FalseColorSettings:
        return FalseColorSettings(
            mode=FalseColorMode(str(self.mode_combo.currentData())),
            opacity=float(self.opacity_spin.value()),
            show_legend=self.legend_check.isChecked(),
        )

    def apply_settings(self, settings: FalseColorSettings) -> None:
        self.mode_combo.blockSignals(True)
        self.opacity_slider.blockSignals(True)
        self.opacity_spin.blockSignals(True)
        self.legend_check.blockSignals(True)
        index = self.mode_combo.findData(settings.mode.value)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.opacity_spin.setValue(float(settings.opacity))
        self.opacity_slider.setValue(int(round(settings.opacity * 100)))
        self.legend_check.setChecked(bool(settings.show_legend))
        self.mode_combo.blockSignals(False)
        self.opacity_slider.blockSignals(False)
        self.opacity_spin.blockSignals(False)
        self.legend_check.blockSignals(False)
        self._update_legend_text()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _slider_to_spin(self, value: int) -> None:
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(value / 100.0)
        self.opacity_spin.blockSignals(False)
        self._emit_settings()

    def _spin_to_slider(self, value: float) -> None:
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(round(value * 100)))
        self.opacity_slider.blockSignals(False)
        self._emit_settings()

    def _on_reset(self) -> None:
        self.apply_settings(FalseColorSettings())
        self.reset_requested.emit()
        self._emit_settings()

    def _emit_settings(self) -> None:
        self._update_legend_text()
        self.settings_changed.emit(self.current_settings())

    def _update_legend_text(self) -> None:
        settings = self.current_settings()
        bands = legend_for_mode(settings.mode)
        if not bands:
            self.legend_label.setText("Mode: Off — original preview")
            return
        lines = [f"Mode: {settings.mode.value}"]
        for band in bands:
            lines.append(f"■ {band.label}")
        self.legend_label.setText("\n".join(lines))
