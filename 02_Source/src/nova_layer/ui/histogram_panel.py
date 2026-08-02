"""Read-only Histogram dock panel (Phase 9D-1).

Viewer diagnostics only — may downsample large frames for UI responsiveness.
No external plotting libraries.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.histogram_analysis import (
    ChannelHistogram,
    FrameHistogram,
    empty_frame_histogram,
)
from nova_layer.app.processing_frames import ProcessingColorPolicy


class HistogramChannelMode(StrEnum):
    RGB = "rgb"
    LUMINANCE = "luminance"


def _text(value: object | None, *, empty: str = "—") -> str:
    if value is None:
        return empty
    text = str(value).strip()
    return text if text else empty


def _fmt_stat(value: float, *, scene: bool) -> str:
    if value != value:  # NaN
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "+Inf" if value > 0 else "-Inf"
    if scene:
        return f"{value:.4f}"
    return f"{value:.2f}"


class HistogramGraphWidget(QWidget):
    """Custom QPainter histogram (RGB curves or luminance)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("histogramGraph")
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._histogram: FrameHistogram | None = None
        self._mode = HistogramChannelMode.RGB

    def set_histogram(
        self,
        histogram: FrameHistogram | None,
        *,
        mode: HistogramChannelMode,
    ) -> None:
        self._histogram = histogram
        self._mode = mode
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1d24"))
        margin_l, margin_r, margin_t, margin_b = 28, 12, 12, 28
        plot = self.rect().adjusted(margin_l, margin_t, -margin_r, -margin_b)
        painter.setPen(QPen(QColor("#3a4150"), 1))
        painter.drawRect(plot)

        histogram = self._histogram
        if histogram is None or histogram.sample_count <= 0:
            painter.setPen(QColor("#8b93a7"))
            painter.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), "No histogram")
            self._draw_axis_labels(painter, plot, histogram)
            return

        series: list[tuple[ChannelHistogram, QColor]]
        if self._mode is HistogramChannelMode.LUMINANCE:
            series = [(histogram.luminance, QColor("#d7dde8"))]
        else:
            series = [
                (histogram.red, QColor("#e26868")),
                (histogram.green, QColor("#5cb87a")),
                (histogram.blue, QColor("#6ea0ef")),
            ]

        peak = 1
        for channel, _ in series:
            if channel.bins.size:
                peak = max(peak, int(channel.bins.max()))

        for channel, color in series:
            self._draw_channel(painter, plot, channel.bins, peak, color)

        self._draw_axis_labels(painter, plot, histogram)

    def _draw_channel(
        self,
        painter: QPainter,
        plot,
        bins,
        peak: int,
        color: QColor,
    ) -> None:
        count = int(bins.size)
        if count <= 0 or plot.width() <= 1 or plot.height() <= 1:
            return
        pen = QPen(color, 1)
        painter.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(70)
        width = float(plot.width())
        height = float(plot.height())
        bottom = float(plot.bottom())
        left = float(plot.left())
        for index, value in enumerate(bins):
            x0 = left + (index / count) * width
            x1 = left + ((index + 1) / count) * width
            normalized = float(value) / float(peak)
            y = bottom - normalized * height
            painter.fillRect(
                int(x0),
                int(y),
                max(1, int(x1 - x0)),
                max(1, int(bottom - y)),
                fill,
            )
            painter.drawLine(int(x0), int(y), int(x1), int(y))

    def _draw_axis_labels(self, painter: QPainter, plot, histogram: FrameHistogram | None) -> None:
        painter.setPen(QColor("#8b93a7"))
        if histogram is not None and histogram.policy == ProcessingColorPolicy.SCENE.value:
            labels = ["0", "1", "2", "3", "4"]
        else:
            labels = ["0", "64", "128", "192", "255"]
        for index, label in enumerate(labels):
            x = plot.left() + int(index / (len(labels) - 1) * plot.width())
            painter.drawText(x - 10, plot.bottom() + 16, label)


class HistogramPanel(QWidget):
    """Histogram dock content: policy, channels, stats, refresh controls."""

    policy_changed = Signal(str)
    channel_mode_changed = Signal(str)
    refresh_requested = Signal()
    auto_refresh_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("histogramPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Policy"))
        self.policy_combo = QComboBox()
        self.policy_combo.setObjectName("histogramPolicyCombo")
        self.policy_combo.addItem("PREVIEW", ProcessingColorPolicy.PREVIEW.value)
        self.policy_combo.addItem("SOURCE", ProcessingColorPolicy.SOURCE.value)
        self.policy_combo.addItem("SCENE", ProcessingColorPolicy.SCENE.value)
        self.policy_combo.currentIndexChanged.connect(self._emit_policy)
        controls.addWidget(self.policy_combo)

        controls.addWidget(QLabel("Channels"))
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("histogramChannelCombo")
        self.channel_combo.addItem("RGB", HistogramChannelMode.RGB.value)
        self.channel_combo.addItem("Luminance", HistogramChannelMode.LUMINANCE.value)
        self.channel_combo.currentIndexChanged.connect(self._emit_channel_mode)
        controls.addWidget(self.channel_combo)
        controls.addStretch()
        root.addLayout(controls)

        self.graph = HistogramGraphWidget()
        root.addWidget(self.graph, stretch=1)

        stats = QGroupBox("Statistics")
        form = QFormLayout(stats)
        self.min_label = QLabel("—")
        self.max_label = QLabel("—")
        self.mean_label = QLabel("—")
        self.median_label = QLabel("—")
        self.clipped_low_label = QLabel("—")
        self.clipped_high_label = QLabel("—")
        self.sample_count_label = QLabel("—")
        for name, widget in (
            ("Min", self.min_label),
            ("Max", self.max_label),
            ("Mean", self.mean_label),
            ("Median", self.median_label),
            ("Clipped Low", self.clipped_low_label),
            ("Clipped High", self.clipped_high_label),
            ("Samples", self.sample_count_label),
        ):
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(name, widget)
        root.addWidget(stats)

        footer = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("histogramRefreshButton")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        footer.addWidget(self.refresh_button)

        self.auto_refresh_check = QCheckBox("Auto Refresh")
        self.auto_refresh_check.setObjectName("histogramAutoRefresh")
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.toggled.connect(self.auto_refresh_changed.emit)
        footer.addWidget(self.auto_refresh_check)
        footer.addStretch()
        root.addLayout(footer)

        self.status_label = QLabel("No media")
        self.status_label.setObjectName("histogramStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self._histogram: FrameHistogram | None = None
        self.clear()

    @property
    def auto_refresh(self) -> bool:
        return self.auto_refresh_check.isChecked()

    def current_policy(self) -> ProcessingColorPolicy:
        return ProcessingColorPolicy(str(self.policy_combo.currentData()))

    def current_channel_mode(self) -> HistogramChannelMode:
        return HistogramChannelMode(str(self.channel_combo.currentData()))

    def clear(self, *, status: str = "No media") -> None:
        self.apply_histogram(
            empty_frame_histogram(
                policy=self.current_policy().value,
                warning=status,
            )
        )

    def apply_histogram(self, histogram: FrameHistogram | None) -> None:
        self._histogram = histogram
        mode = self.current_channel_mode()
        self.graph.set_histogram(histogram, mode=mode)
        if histogram is None or histogram.sample_count <= 0:
            for label in (
                self.min_label,
                self.max_label,
                self.mean_label,
                self.median_label,
                self.clipped_low_label,
                self.clipped_high_label,
                self.sample_count_label,
            ):
                label.setText("—")
            self.status_label.setText(
                _text(None if histogram is None else histogram.warning, empty="Empty")
            )
            return

        channel = (
            histogram.luminance
            if mode is HistogramChannelMode.LUMINANCE
            else histogram.red
        )
        scene = histogram.policy == ProcessingColorPolicy.SCENE.value
        self.min_label.setText(_fmt_stat(channel.minimum, scene=scene))
        self.max_label.setText(_fmt_stat(channel.maximum, scene=scene))
        self.mean_label.setText(_fmt_stat(channel.mean, scene=scene))
        self.median_label.setText(_fmt_stat(channel.median, scene=scene))
        self.clipped_low_label.setText(str(channel.clipped_low))
        self.clipped_high_label.setText(str(channel.clipped_high))
        self.sample_count_label.setText(str(histogram.sample_count))
        self.status_label.setText(_text(histogram.warning, empty="Ready"))

    def _emit_policy(self) -> None:
        self.policy_changed.emit(self.current_policy().value)
        if self._histogram is not None:
            self.apply_histogram(self._histogram)

    def _emit_channel_mode(self) -> None:
        self.channel_mode_changed.emit(self.current_channel_mode().value)
        self.apply_histogram(self._histogram)
