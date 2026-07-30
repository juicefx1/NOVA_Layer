from __future__ import annotations

from collections import Counter
from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QToolTip

from nova_layer.domain.models import (
    LifecycleState,
    SkeletonCorrection,
    TemporalIdentityObservation,
)

STATE_COLORS = {
    LifecycleState.TRACKED: QColor("#55c98d"),
    LifecycleState.TEMPORARILY_LOST: QColor("#f06c75"),
    LifecycleState.RECOVERED: QColor("#69a7ff"),
}


class LifecycleTimeline(QSlider):
    """Timeline slider with clickable Object Identity lifecycle evidence."""

    shot_range_previewed = Signal(int, int, int)
    marker_hit_radius = 7

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._observations: dict[int, TemporalIdentityObservation] = {}
        self._corrections: dict[int, SkeletonCorrection] = {}
        self._range_start = 0
        self._range_end = 0
        self._master_frame = 0
        self._drag_handle: Literal["start", "end", "master"] | None = None
        self.setMinimumHeight(32)
        self.setMouseTracking(True)

    def set_observations(self, observations: list[TemporalIdentityObservation]) -> None:
        self._observations = {item.frame_number: item for item in observations}
        self.update()

    def set_skeleton_corrections(self, corrections: list[SkeletonCorrection]) -> None:
        self._corrections = {item.frame_number: item for item in corrections}
        self.update()

    def correction_frames(self) -> list[int]:
        return sorted(self._corrections)

    def marker_frames(self, state: LifecycleState | None = None) -> list[int]:
        return sorted(
            frame
            for frame, observation in self._observations.items()
            if state is None or observation.lifecycle_state == state
        )

    def lifecycle_summary(self) -> str:
        counts = Counter(item.lifecycle_state for item in self._observations.values())
        if not counts and not self._corrections:
            return "No tracking evidence"
        summary = (
            f"Tracked {counts[LifecycleState.TRACKED]}  ·  "
            f"Lost {counts[LifecycleState.TEMPORARILY_LOST]}  ·  "
            f"Recovered {counts[LifecycleState.RECOVERED]}"
        )
        if self._corrections:
            summary += f"  ·  Corrected {len(self._corrections)}"
        return summary

    def set_shot_range(self, start: int, end: int, master: int) -> None:
        if not self.minimum() <= start <= master <= end <= self.maximum():
            raise ValueError("Shot Range handles must remain inside the timeline range.")
        self._range_start = start
        self._range_end = end
        self._master_frame = master
        self.update()

    @property
    def shot_range(self) -> tuple[int, int, int]:
        return self._range_start, self._range_end, self._master_frame

    def _groove_rect(self) -> QRect:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )

    def marker_x(self, frame_number: int) -> int:
        groove = self._groove_rect()
        span = max(1, groove.width())
        position = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), frame_number, span
        )
        return groove.left() + position

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        groove = self._groove_rect()
        start_x = self.marker_x(self._range_start)
        end_x = self.marker_x(self._range_end)
        selection = QColor("#5d72f2")
        selection.setAlpha(70)
        painter.fillRect(QRect(start_x, groove.top() - 2, max(1, end_x - start_x), 8), selection)
        for frame, color in (
            (self._range_start, QColor("#d8deea")),
            (self._range_end, QColor("#d8deea")),
            (self._master_frame, QColor("#ffd166")),
        ):
            x = self.marker_x(frame)
            painter.setPen(QPen(color, 3))
            painter.drawLine(QPoint(x, 2), QPoint(x, max(4, groove.top() - 3)))
        marker_top = min(self.height() - 8, groove.bottom() + 4)
        for frame, observation in self._observations.items():
            color = STATE_COLORS.get(observation.lifecycle_state, QColor("#aeb6c5"))
            painter.setPen(QPen(color, 3))
            x = self.marker_x(frame)
            painter.drawLine(QPoint(x, marker_top), QPoint(x, self.height() - 2))
        painter.setPen(QPen(QColor("#ff4fd8"), 3))
        for frame in self._corrections:
            x = self.marker_x(frame)
            painter.drawEllipse(QPoint(x, marker_top - 2), 4, 4)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Handles are painted above the groove; keep a usable top band even when a
        # platform style makes the groove fill the full widget height.
        handle_band = max(10, self._groove_rect().top() + 6)
        if event.position().y() <= handle_band:
            handle = self._nearest_range_handle(round(event.position().x()))
            if handle is not None:
                self._drag_handle = handle
                event.accept()
                return
        marker = self._nearest_marker(round(event.position().x()))
        if marker is not None:
            self.setValue(marker)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_handle is not None:
            frame = self._frame_from_x(round(event.position().x()))
            if self._drag_handle == "start":
                self._range_start = min(frame, self._master_frame)
            elif self._drag_handle == "end":
                self._range_end = max(frame, self._master_frame)
            else:
                self._master_frame = max(self._range_start, min(frame, self._range_end))
                self.setValue(self._master_frame)
            self.shot_range_previewed.emit(self._range_start, self._range_end, self._master_frame)
            self.update()
            event.accept()
            return
        marker = self._nearest_marker(round(event.position().x()))
        if marker is not None:
            observation = self._observations.get(marker)
            correction_detail = " · Artist Pose Correction" if marker in self._corrections else ""
            if observation is None:
                tooltip = f"Frame {marker}{correction_detail}"
            else:
                label = observation.lifecycle_state.value.replace("_", " ").title()
                skeleton_detail = (
                    f" · Skeleton {observation.skeleton_confidence:.0%}"
                    if observation.skeleton_confidence is not None
                    else ""
                )
                tooltip = (
                    f"Frame {marker} · {label} · Identity {observation.confidence:.0%}"
                    f"{skeleton_detail}{correction_detail}"
                )
            QToolTip.showText(
                event.globalPosition().toPoint(),
                tooltip,
                self,
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _nearest_marker(self, x: int) -> int | None:
        frames = set(self._observations) | set(self._corrections)
        if not frames:
            return None
        marker = min(frames, key=lambda frame: abs(self.marker_x(frame) - x))
        return marker if abs(self.marker_x(marker) - x) <= self.marker_hit_radius else None

    def _nearest_range_handle(self, x: int) -> Literal["start", "end", "master"] | None:
        handles: dict[Literal["start", "end", "master"], int] = {
            "start": self._range_start,
            "end": self._range_end,
            "master": self._master_frame,
        }
        handle = min(handles, key=lambda name: abs(self.marker_x(handles[name]) - x))
        return handle if abs(self.marker_x(handles[handle]) - x) <= self.marker_hit_radius else None

    def _frame_from_x(self, x: int) -> int:
        groove = self._groove_rect()
        position = max(0, min(x - groove.left(), max(1, groove.width())))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), position, max(1, groove.width())
        )
