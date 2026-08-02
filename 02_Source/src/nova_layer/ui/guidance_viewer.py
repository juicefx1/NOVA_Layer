from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QLabel

from nova_layer.domain.models import (
    BoundingRegion,
    GuidancePoint,
    SkeletonBone,
    SkeletonGuidance,
    SkeletonJoint,
)


class GuidanceMode(StrEnum):
    NAVIGATE = "navigate"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MOVE_POINT = "move_point"
    REMOVE_POINT = "remove_point"
    BOUNDING_REGION = "bounding_region"
    SKELETON = "skeleton"
    SKELETON_CORRECTION = "skeleton_correction"


class GuidanceViewer(QLabel):
    guidance_changed = Signal(object, object, object)
    skeleton_correction_changed = Signal(object)
    skeleton_joint_label_requested = Signal(object, object)
    pixel_hovered = Signal(int, int)
    pixel_hover_cleared = Signal()

    def __init__(self) -> None:
        super().__init__("Import a video to create the first Shot")
        self.setObjectName("mediaViewer")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self._frame: NDArray[np.uint8] | None = None
        self._false_color_frame: NDArray[np.uint8] | None = None
        self._false_color_legend: list[tuple[str, tuple[int, int, int]]] = []
        self._show_false_color_legend = False
        self._image: QImage | None = None
        self._mask_overlay: QImage | None = None
        self._display_rect = QRect()
        self._mode = GuidanceMode.NAVIGATE
        self._points: list[GuidancePoint] = []
        self._bounding_region: BoundingRegion | None = None
        self._skeleton_guidance = SkeletonGuidance()
        self._tracked_skeleton: SkeletonGuidance | None = None
        self._correction_skeleton: SkeletonGuidance | None = None
        self._detected_skeleton: SkeletonGuidance | None = None
        self._fused_skeleton: SkeletonGuidance | None = None
        self._fusion_joint_depths: dict[str, float] = {}
        self._fusion_depth_confidences: dict[str, float] = {}
        self._drag_joint_id: UUID | None = None
        self._drag_point_index: int | None = None
        self._drag_start: QPoint | None = None
        self._last_hover_pixel: tuple[int, int] | None = None

    @property
    def points(self) -> list[GuidancePoint]:
        return list(self._points)

    @property
    def bounding_region(self) -> BoundingRegion | None:
        return self._bounding_region

    @property
    def skeleton_guidance(self) -> SkeletonGuidance:
        return self._skeleton_guidance.model_copy(deep=True)

    def set_mode(self, mode: GuidanceMode) -> None:
        self._mode = mode
        cursor = (
            Qt.CursorShape.CrossCursor
            if mode != GuidanceMode.NAVIGATE
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)

    def set_guidance(
        self,
        points: list[GuidancePoint],
        bounding_region: BoundingRegion | None,
        skeleton_guidance: SkeletonGuidance | None = None,
    ) -> None:
        self._points = list(points)
        self._bounding_region = bounding_region
        self._skeleton_guidance = (skeleton_guidance or SkeletonGuidance()).model_copy(deep=True)
        self._emit_guidance()
        self.update()

    def apply_skeleton_preset(self, skeleton: SkeletonGuidance) -> None:
        self._skeleton_guidance = skeleton.model_copy(deep=True)
        self._emit_guidance()
        self.update()

    def clear_guidance(self) -> None:
        self._points.clear()
        self._bounding_region = None
        self._skeleton_guidance = SkeletonGuidance()
        self._emit_guidance()
        self.update()

    def remove_bounding_region(self) -> None:
        if self._bounding_region is None:
            return
        self._bounding_region = None
        self._emit_guidance()
        self.update()

    def remove_nearest_point(self, x: float, y: float, *, radius: float = 0.04) -> bool:
        if not self._points:
            return False
        nearest_index = min(
            range(len(self._points)),
            key=lambda index: (self._points[index].x - x) ** 2 + (self._points[index].y - y) ** 2,
        )
        point = self._points[nearest_index]
        if (point.x - x) ** 2 + (point.y - y) ** 2 > radius**2:
            return False
        del self._points[nearest_index]
        self._emit_guidance()
        self.update()
        return True

    def set_frame(self, frame: NDArray[np.uint8]) -> None:
        """Store the original PREVIEW buffer; display may use false-color overlay."""
        self._frame = np.ascontiguousarray(frame)
        self._rebuild_display_image()
        self._update_display_rect()
        self.update()

    @property
    def original_frame(self) -> NDArray[np.uint8] | None:
        """Untouched preview buffer (never holds false-color pixels)."""
        if self._frame is None:
            return None
        return np.ascontiguousarray(self._frame)

    def set_false_color_frame(
        self,
        frame: NDArray[np.uint8] | None,
        *,
        legend: list[tuple[str, tuple[int, int, int]]] | None = None,
        show_legend: bool = False,
    ) -> None:
        """Set viewer-only false-color display buffer (does not replace ``_frame``)."""
        if frame is None:
            self._false_color_frame = None
        else:
            self._false_color_frame = np.ascontiguousarray(frame)
        self._false_color_legend = list(legend or [])
        self._show_false_color_legend = bool(show_legend) and bool(self._false_color_legend)
        self._rebuild_display_image()
        self._update_display_rect()
        self.update()

    def clear_false_color(self) -> None:
        self.set_false_color_frame(None, legend=None, show_legend=False)

    def _rebuild_display_image(self) -> None:
        display = (
            self._false_color_frame
            if self._false_color_frame is not None
            else self._frame
        )
        if display is None:
            self._image = None
            return
        height, width, channels = display.shape
        self._image = QImage(
            display.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()

    def widget_to_image_coordinates(
        self,
        position: QPointF,
    ) -> tuple[int, int] | None:
        """Map widget position to 0-based image pixels, or None if outside.

        Uses KeepAspectRatio fit (letterboxing). Does not clamp — outside the
        displayed image area returns ``None``.
        """
        self._update_display_rect()
        if self._image is None or self._display_rect.isEmpty():
            return None
        left = self._display_rect.left()
        top = self._display_rect.top()
        display_w = self._display_rect.width()
        display_h = self._display_rect.height()
        if display_w <= 0 or display_h <= 0:
            return None
        fx = (position.x() - left) / float(display_w)
        fy = (position.y() - top) / float(display_h)
        if fx < 0.0 or fy < 0.0 or fx >= 1.0 or fy >= 1.0:
            return None
        image_w = self._image.width()
        image_h = self._image.height()
        ix = int(fx * image_w)
        iy = int(fy * image_h)
        if ix < 0 or iy < 0 or ix >= image_w or iy >= image_h:
            return None
        return ix, iy

    def _update_display_rect(self) -> None:
        """Recompute letterboxed display rect from current widget / image size."""
        if self._image is None or self.width() <= 0 or self.height() <= 0:
            self._display_rect = QRect()
            return
        image_size = self._image.size()
        image_size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - image_size.width()) // 2
        y = (self.height() - image_size.height()) // 2
        self._display_rect = QRect(x, y, image_size.width(), image_size.height())

    def set_mask_overlay(self, mask: NDArray[np.uint8] | None) -> None:
        if mask is None:
            self._mask_overlay = None
            self.update()
            return
        alpha = np.asarray(mask, dtype=np.uint8)
        height, width = alpha.shape
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[:, :, 0] = 104
        rgba[:, :, 1] = 134
        rgba[:, :, 2] = 255
        rgba[:, :, 3] = (alpha.astype(np.float32) * 0.42).astype(np.uint8)
        rgba = np.ascontiguousarray(rgba)
        self._mask_overlay = QImage(
            rgba.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self.update()

    def set_tracked_skeleton(self, skeleton: SkeletonGuidance | None) -> None:
        self._tracked_skeleton = skeleton.model_copy(deep=True) if skeleton is not None else None
        self.update()

    def begin_skeleton_correction(self, skeleton: SkeletonGuidance) -> None:
        self._correction_skeleton = skeleton.model_copy(deep=True)
        self.set_mode(GuidanceMode.SKELETON_CORRECTION)
        self.update()

    def end_skeleton_correction(self) -> None:
        self._correction_skeleton = None
        self._drag_joint_id = None
        self.set_mode(GuidanceMode.NAVIGATE)
        self.update()

    def set_fusion_preview(
        self,
        detected: SkeletonGuidance | None,
        fused: SkeletonGuidance | None,
        *,
        joint_depths: dict[str, float] | None = None,
        depth_confidences: dict[str, float] | None = None,
    ) -> None:
        self._detected_skeleton = detected.model_copy(deep=True) if detected else None
        self._fused_skeleton = fused.model_copy(deep=True) if fused else None
        self._fusion_joint_depths = dict(joint_depths or {}) if detected else {}
        self._fusion_depth_confidences = dict(depth_confidences or {}) if detected else {}
        self.update()

    @property
    def correction_skeleton(self) -> SkeletonGuidance | None:
        if self._correction_skeleton is None:
            return None
        return self._correction_skeleton.model_copy(deep=True)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._image is None:
            return
        painter = QPainter(self)
        self._update_display_rect()
        pixmap = QPixmap.fromImage(self._image).scaled(
            self._display_rect.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(self._display_rect, pixmap)
        if self._mask_overlay is not None:
            overlay = QPixmap.fromImage(self._mask_overlay).scaled(
                self._display_rect.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(self._display_rect, overlay)
        if self._show_false_color_legend and self._false_color_legend:
            self._paint_false_color_legend(painter)
        self._paint_guidance(painter)

    def _paint_false_color_legend(self, painter: QPainter) -> None:
        if self._display_rect.isEmpty():
            return
        x = self._display_rect.left() + 8
        y = self._display_rect.top() + 8
        row_h = 16
        box = 10
        painter.setPen(QPen(QColor("#111318"), 1))
        bg = QColor(17, 19, 24, 180)
        height = 8 + len(self._false_color_legend) * row_h
        painter.fillRect(QRect(x - 4, y - 4, 168, height), bg)
        for label, color in self._false_color_legend:
            painter.fillRect(x, y + 2, box, box, QColor(*color))
            painter.setPen(QColor("#e8ecf4"))
            painter.drawText(x + box + 6, y + box, label)
            y += row_h

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_display_rect()

    def _paint_guidance(self, painter: QPainter) -> None:
        if self._tracked_skeleton is not None:
            self._paint_skeleton(
                painter,
                self._tracked_skeleton,
                bone_color=QColor("#49d7ff"),
                joint_color=QColor("#a5efff"),
            )
        if self._correction_skeleton is not None:
            self._paint_skeleton(
                painter,
                self._correction_skeleton,
                bone_color=QColor("#ff4fd8"),
                joint_color=QColor("#ffb3ee"),
            )
        if self._detected_skeleton is not None:
            self._paint_skeleton(
                painter,
                self._detected_skeleton,
                bone_color=QColor("#ff9f43"),
                joint_color=QColor("#ffd09a"),
                joint_depths=self._fusion_joint_depths,
                depth_confidences=self._fusion_depth_confidences,
            )
        if self._fused_skeleton is not None:
            self._paint_skeleton(
                painter,
                self._fused_skeleton,
                bone_color=QColor("#67e480"),
                joint_color=QColor("#b8f7c3"),
            )
        self._paint_skeleton(
            painter,
            self._skeleton_guidance,
            bone_color=QColor("#f5c451"),
            joint_color=QColor("#ffe29a"),
        )

        for index, point in enumerate(self._points):
            position = self._from_normalized(point.x, point.y)
            color = QColor("#58d68d") if point.polarity == "positive" else QColor("#ff6376")
            painter.setPen(QPen(QColor("#111318"), 5))
            painter.drawEllipse(position, 7, 7)
            painter.setPen(QPen(color, 4))
            painter.drawEllipse(position, 7, 7)
            painter.drawLine(position.x() - 4, position.y(), position.x() + 4, position.y())
            if point.polarity == "positive":
                painter.drawLine(position.x(), position.y() - 4, position.x(), position.y() + 4)
            if self._drag_point_index == index:
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawEllipse(position, 10, 10)

        if self._bounding_region is not None:
            box = self._bounding_region
            top_left = self._from_normalized(box.x, box.y)
            bottom_right = self._from_normalized(box.x + box.width, box.y + box.height)
            painter.setPen(QPen(QColor("#8ea8ff"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRect(top_left, bottom_right).normalized())

    def _paint_skeleton(
        self,
        painter: QPainter,
        skeleton: SkeletonGuidance,
        *,
        bone_color: QColor,
        joint_color: QColor,
        joint_depths: dict[str, float] | None = None,
        depth_confidences: dict[str, float] | None = None,
    ) -> None:
        joints = {joint.id: joint for joint in skeleton.joints}
        painter.setPen(QPen(bone_color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for bone in skeleton.bones:
            start = joints[bone.start_joint_id]
            end = joints[bone.end_joint_id]
            painter.drawLine(
                self._from_normalized(start.x, start.y),
                self._from_normalized(end.x, end.y),
            )
        for joint in skeleton.joints:
            position = self._from_normalized(joint.x, joint.y)
            painter.setPen(QPen(QColor("#111318"), 6))
            painter.drawEllipse(position, 6, 6)
            painter.setPen(QPen(joint_color, 3))
            painter.drawEllipse(position, 6, 6)
            if joint.label:
                painter.drawText(position + QPoint(9, -7), joint.label)
                depth = (joint_depths or {}).get(joint.label)
                confidence = (depth_confidences or {}).get(joint.label)
                if depth is not None or confidence is not None:
                    parts = []
                    if depth is not None:
                        parts.append(f"z {depth:.3f}")
                    if confidence is not None:
                        parts.append(f"dc {confidence:.2f}")
                    painter.drawText(position + QPoint(9, 9), " · ".join(parts))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        normalized = self._to_normalized(event.position().toPoint())
        if normalized is None:
            return
        x, y = normalized
        if event.button() == Qt.MouseButton.RightButton:
            if self._mode in (
                GuidanceMode.POSITIVE,
                GuidanceMode.NEGATIVE,
                GuidanceMode.MOVE_POINT,
                GuidanceMode.REMOVE_POINT,
            ):
                self.remove_nearest_point(x, y)
            elif self._mode == GuidanceMode.BOUNDING_REGION:
                self.remove_bounding_region()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._mode == GuidanceMode.REMOVE_POINT:
            self.remove_nearest_point(x, y)
            return
        if self._mode == GuidanceMode.MOVE_POINT:
            nearest_index = self._nearest_point_index(x, y)
            if nearest_index is not None:
                self._drag_point_index = nearest_index
            return
        if self._mode in (GuidanceMode.POSITIVE, GuidanceMode.NEGATIVE):
            nearest_index = self._nearest_point_index(x, y)
            if nearest_index is not None:
                self._drag_point_index = nearest_index
                return
            polarity: Literal["positive", "negative"] = (
                "positive" if self._mode == GuidanceMode.POSITIVE else "negative"
            )
            self._points.append(GuidancePoint(x=x, y=y, polarity=polarity))
            self._emit_guidance()
            self.update()
        elif self._mode == GuidanceMode.SKELETON_CORRECTION:
            if self._correction_skeleton is None:
                return
            nearest = min(
                self._correction_skeleton.joints,
                key=lambda joint: (joint.x - x) ** 2 + (joint.y - y) ** 2,
                default=None,
            )
            if nearest is not None and (nearest.x - x) ** 2 + (nearest.y - y) ** 2 <= 0.035**2:
                self._drag_joint_id = nearest.id
        elif self._mode in (GuidanceMode.BOUNDING_REGION, GuidanceMode.SKELETON):
            self._drag_start = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._emit_pixel_hover(event.position())
        if self._drag_point_index is None:
            return super().mouseMoveEvent(event)
        normalized = self._to_normalized(event.position().toPoint())
        if normalized is None:
            return
        x, y = normalized
        point = self._points[self._drag_point_index]
        self._points[self._drag_point_index] = point.model_copy(update={"x": x, "y": y})
        self.update()

    def leaveEvent(self, event: QEvent) -> None:
        self._clear_pixel_hover()
        super().leaveEvent(event)

    def _emit_pixel_hover(self, position: QPointF) -> None:
        coords = self.widget_to_image_coordinates(position)
        if coords is None:
            self._clear_pixel_hover()
            return
        if coords == self._last_hover_pixel:
            return
        self._last_hover_pixel = coords
        self.pixel_hovered.emit(coords[0], coords[1])

    def _clear_pixel_hover(self) -> None:
        if self._last_hover_pixel is None:
            return
        self._last_hover_pixel = None
        self.pixel_hover_cleared.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_point_index is not None:
            self._drag_point_index = None
            self._emit_guidance()
            self.update()
            return
        if self._mode == GuidanceMode.SKELETON_CORRECTION:
            normalized = self._to_normalized(event.position().toPoint())
            joint_id = self._drag_joint_id
            self._drag_joint_id = None
            if normalized is not None and joint_id is not None:
                self._move_correction_joint(joint_id, normalized)
            return
        if self._mode not in (GuidanceMode.BOUNDING_REGION, GuidanceMode.SKELETON):
            return
        if self._drag_start is None:
            return
        start = self._to_normalized(self._drag_start)
        end = self._to_normalized(event.position().toPoint())
        self._drag_start = None
        if start is None or end is None:
            return
        if self._mode == GuidanceMode.SKELETON:
            self._add_skeleton_bone(start, end)
            return
        x1, y1 = start
        x2, y2 = end
        x, y = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        if width < 0.005 or height < 0.005:
            return
        self._bounding_region = BoundingRegion(x=x, y=y, width=width, height=height)
        self._emit_guidance()
        self.update()

    def _nearest_point_index(self, x: float, y: float, *, radius: float = 0.035) -> int | None:
        if not self._points:
            return None
        nearest_index = min(
            range(len(self._points)),
            key=lambda index: (self._points[index].x - x) ** 2 + (self._points[index].y - y) ** 2,
        )
        point = self._points[nearest_index]
        if (point.x - x) ** 2 + (point.y - y) ** 2 > radius**2:
            return None
        return nearest_index

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._mode != GuidanceMode.SKELETON:
            return super().mouseDoubleClickEvent(event)
        normalized = self._to_normalized(event.position().toPoint())
        if normalized is None:
            return
        x, y = normalized
        nearest = min(
            self._skeleton_guidance.joints,
            key=lambda joint: (joint.x - x) ** 2 + (joint.y - y) ** 2,
            default=None,
        )
        if nearest is None or (nearest.x - x) ** 2 + (nearest.y - y) ** 2 > 0.035**2:
            return
        self.skeleton_joint_label_requested.emit(nearest.id, nearest.label)
        event.accept()

    def set_skeleton_joint_label(self, joint_id: UUID, label: str | None) -> bool:
        if all(joint.id != joint_id for joint in self._skeleton_guidance.joints):
            return False
        try:
            joints = [
                joint.model_copy(update={"label": label}) if joint.id == joint_id else joint
                for joint in self._skeleton_guidance.joints
            ]
            updated = SkeletonGuidance(
                joints=joints,
                bones=self._skeleton_guidance.bones,
            )
        except ValueError:
            return False
        self._skeleton_guidance = updated
        self._emit_guidance()
        self.update()
        return True

    def _move_correction_joint(
        self,
        joint_id: UUID,
        position: tuple[float, float],
    ) -> None:
        if self._correction_skeleton is None:
            return
        joints = [
            joint.model_copy(update={"x": position[0], "y": position[1]})
            if joint.id == joint_id
            else joint
            for joint in self._correction_skeleton.joints
        ]
        if all(joint.id != joint_id for joint in self._correction_skeleton.joints):
            return
        self._correction_skeleton = self._correction_skeleton.model_copy(update={"joints": joints})
        self.skeleton_correction_changed.emit(self.correction_skeleton)
        self.update()

    def _add_skeleton_bone(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if (start[0] - end[0]) ** 2 + (start[1] - end[1]) ** 2 < 0.0001:
            return
        joints = list(self._skeleton_guidance.joints)
        bones = list(self._skeleton_guidance.bones)

        def snapped(position: tuple[float, float]) -> SkeletonJoint:
            nearest = min(
                joints,
                key=lambda joint: (joint.x - position[0]) ** 2 + (joint.y - position[1]) ** 2,
                default=None,
            )
            if nearest is not None:
                distance = (nearest.x - position[0]) ** 2 + (nearest.y - position[1]) ** 2
                if distance <= 0.025**2:
                    return nearest
            joint = SkeletonJoint(x=position[0], y=position[1])
            joints.append(joint)
            return joint

        start_joint = snapped(start)
        end_joint = snapped(end)
        if start_joint.id == end_joint.id:
            return
        connection = frozenset((start_joint.id, end_joint.id))
        if any(frozenset((bone.start_joint_id, bone.end_joint_id)) == connection for bone in bones):
            return
        bones.append(SkeletonBone(start_joint_id=start_joint.id, end_joint_id=end_joint.id))
        self._skeleton_guidance = SkeletonGuidance(joints=joints, bones=bones)
        self._emit_guidance()
        self.update()

    def _emit_guidance(self) -> None:
        self.guidance_changed.emit(
            self.points,
            self._bounding_region,
            self.skeleton_guidance,
        )

    def _to_normalized(self, point: QPoint) -> tuple[float, float] | None:
        if self._display_rect.isEmpty() or not self._display_rect.contains(point):
            return None
        x = (point.x() - self._display_rect.left()) / self._display_rect.width()
        y = (point.y() - self._display_rect.top()) / self._display_rect.height()
        return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

    def _from_normalized(self, x: float, y: float) -> QPoint:
        return QPoint(
            self._display_rect.left() + round(x * self._display_rect.width()),
            self._display_rect.top() + round(y * self._display_rect.height()),
        )
