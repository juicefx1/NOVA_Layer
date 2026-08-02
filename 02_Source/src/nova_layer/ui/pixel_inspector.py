"""Read-only Pixel Inspector panel (Phase 9C-1)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.color_pipeline_diagnostics import ColorPipelineDiagnostics
from nova_layer.app.pixel_inspection import (
    PixelInspection,
    PixelSample,
    empty_pixel_inspection,
    format_sample_component,
)
from nova_layer.app.processing_frames import ProcessingColorPolicy


def _text(value: object | None, *, empty: str = "—") -> str:
    if value is None:
        return empty
    text = str(value).strip()
    return text if text else empty


def _selectable(label: QLabel) -> QLabel:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class PixelInspectorPanel(QWidget):
    """Small read-only PREVIEW / SOURCE / SCENE hover panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pixelInspectorPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)

        self._pixel_x = QLabel("—")
        self._pixel_y = QLabel("—")
        self._pixel_frame = QLabel("—")
        self._pixel_media = QLabel("—")
        layout.addWidget(
            self._form_group(
                "Pixel",
                [
                    ("X", self._pixel_x),
                    ("Y", self._pixel_y),
                    ("Frame", self._pixel_frame),
                    ("Media", self._pixel_media),
                ],
            )
        )

        self._preview_r = QLabel("—")
        self._preview_g = QLabel("—")
        self._preview_b = QLabel("—")
        self._preview_meta = QLabel("—")
        layout.addWidget(
            self._form_group(
                "PREVIEW",
                [
                    ("R", self._preview_r),
                    ("G", self._preview_g),
                    ("B", self._preview_b),
                    ("dtype/range", self._preview_meta),
                ],
            )
        )

        self._source_r = QLabel("—")
        self._source_g = QLabel("—")
        self._source_b = QLabel("—")
        self._source_meta = QLabel("—")
        layout.addWidget(
            self._form_group(
                "SOURCE",
                [
                    ("R", self._source_r),
                    ("G", self._source_g),
                    ("B", self._source_b),
                    ("dtype/range", self._source_meta),
                ],
            )
        )

        self._scene_r = QLabel("—")
        self._scene_g = QLabel("—")
        self._scene_b = QLabel("—")
        self._scene_meta = QLabel("—")
        layout.addWidget(
            self._form_group(
                "SCENE",
                [
                    ("R", self._scene_r),
                    ("G", self._scene_g),
                    ("B", self._scene_b),
                    ("dtype/range", self._scene_meta),
                ],
            )
        )

        self._ctx_backend = QLabel("—")
        self._ctx_display = QLabel("—")
        self._ctx_view = QLabel("—")
        self._ctx_exposure = QLabel("—")
        layout.addWidget(
            self._form_group(
                "Color Context",
                [
                    ("Backend", self._ctx_backend),
                    ("Display", self._ctx_display),
                    ("View", self._ctx_view),
                    ("Exposure", self._ctx_exposure),
                ],
            )
        )

        self._status = QLabel("Empty")
        self._status.setObjectName("pixelInspectorStatus")
        _selectable(self._status)
        status_box = QGroupBox("Status")
        status_layout = QVBoxLayout(status_box)
        status_layout.addWidget(self._status)
        layout.addWidget(status_box)
        layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll)
        self.clear()

    def _form_group(self, title: str, rows: list[tuple[str, QLabel]]) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for label, widget in rows:
            _selectable(widget)
            form.addRow(label, widget)
        return box

    def clear(self, *, status: str = "No media") -> None:
        self.apply_inspection(
            empty_pixel_inspection(warning=status),
            diagnostics=None,
        )

    def apply_inspection(
        self,
        inspection: PixelInspection | None,
        *,
        diagnostics: ColorPipelineDiagnostics | None = None,
    ) -> None:
        if inspection is None:
            self.clear()
            return
        self._pixel_x.setText(_text(inspection.image_x if inspection.image_x >= 0 else None))
        self._pixel_y.setText(_text(inspection.image_y if inspection.image_y >= 0 else None))
        self._pixel_frame.setText(_text(inspection.frame_number))
        media = inspection.media_path
        self._pixel_media.setText(_text(str(media) if media is not None else None))
        self._apply_sample(
            inspection.preview,
            self._preview_r,
            self._preview_g,
            self._preview_b,
            self._preview_meta,
            policy=ProcessingColorPolicy.PREVIEW.value,
        )
        self._apply_sample(
            inspection.source,
            self._source_r,
            self._source_g,
            self._source_b,
            self._source_meta,
            policy=ProcessingColorPolicy.SOURCE.value,
        )
        self._apply_sample(
            inspection.scene,
            self._scene_r,
            self._scene_g,
            self._scene_b,
            self._scene_meta,
            policy=ProcessingColorPolicy.SCENE.value,
        )
        if diagnostics is not None:
            self._ctx_backend.setText(_text(diagnostics.active_backend))
            self._ctx_display.setText(_text(diagnostics.display))
            self._ctx_view.setText(_text(diagnostics.view))
            self._ctx_exposure.setText(f"{diagnostics.exposure:.4f}")
        else:
            self._ctx_backend.setText("—")
            self._ctx_display.setText("—")
            self._ctx_view.setText("—")
            self._ctx_exposure.setText("—")
        self._status.setText(_text(inspection.warning, empty="Ready"))

    def _apply_sample(
        self,
        sample: PixelSample | None,
        r_label: QLabel,
        g_label: QLabel,
        b_label: QLabel,
        meta_label: QLabel,
        *,
        policy: str,
    ) -> None:
        if sample is None:
            r_label.setText("—")
            g_label.setText("—")
            b_label.setText("—")
            meta_label.setText("—")
            return
        r_label.setText(format_sample_component(sample.rgb[0], policy=policy))
        g_label.setText(format_sample_component(sample.rgb[1], policy=policy))
        b_label.setText(format_sample_component(sample.rgb[2], policy=policy))
        meta_label.setText(f"{sample.dtype} · {sample.value_range}")
