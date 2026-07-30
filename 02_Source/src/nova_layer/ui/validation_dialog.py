from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    FrameResult,
    MaturityState,
    ValidationState,
)
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer


def overlay_pixmap(
    frame: NDArray[np.uint8],
    mask: NDArray[np.uint8],
    width: int = 340,
    height: int = 230,
) -> QPixmap:
    rgb = np.asarray(frame, dtype=np.uint8).copy()
    selected = mask > 0
    tint = np.array([104, 134, 255], dtype=np.float32)
    rgb[selected] = (rgb[selected].astype(np.float32) * 0.55 + tint * 0.45).astype(np.uint8)
    contiguous = np.ascontiguousarray(rgb)
    image_height, image_width, channels = contiguous.shape
    image = QImage(
        contiguous.data,
        image_width,
        image_height,
        channels * image_width,
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(image).scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ValidationCard(QFrame):
    def __init__(
        self,
        controller: ProjectController,
        result: FrameResult,
        frame: NDArray[np.uint8],
        mask: NDArray[np.uint8],
        correction_requested: Callable[[int], None],
    ) -> None:
        super().__init__()
        self.setObjectName("validationCard")
        layout = QVBoxLayout(self)
        position = result.direction.upper()
        heading = QLabel(f"{position} · Frame {result.frame_number}")
        heading.setObjectName("validationHeading")
        layout.addWidget(heading)

        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(overlay_pixmap(frame, mask))
        layout.addWidget(preview)

        self.state_label = QLabel(
            f"Confidence {result.confidence:.0%} · {result.validation_state.value}"
        )
        layout.addWidget(self.state_label)

        actions = QHBoxLayout()
        accept = QPushButton("Accept")
        correction = QPushButton("Correction Required")
        accept.clicked.connect(
            lambda: controller.set_validation_state(result.frame_number, ValidationState.ACCEPTED)
        )
        correction.clicked.connect(lambda: correction_requested(result.frame_number))
        actions.addWidget(accept)
        actions.addWidget(correction)
        layout.addLayout(actions)

    def set_state(self, result: FrameResult) -> None:
        self.state_label.setText(
            f"Confidence {result.confidence:.0%} · {result.validation_state.value}"
        )


class ValidationDialog(QDialog):
    def __init__(self, controller: ProjectController) -> None:
        super().__init__()
        self.controller = controller
        self.cards: dict[int, ValidationCard] = {}
        self.preview_data: dict[int, tuple[NDArray[np.uint8], NDArray[np.uint8]]] = {}
        self.correction_dialog: CorrectionDialog | None = None
        self.setWindowTitle("Start / Master / End Validation — NOVA Layer")
        self.resize(1160, 560)
        root = QVBoxLayout(self)

        title = QLabel("Validate the same Object Identity across the Shot Range")
        title.setObjectName("validationTitle")
        root.addWidget(title)
        self.summary = QLabel("Review every frame. Validation requires three accepted results.")
        root.addWidget(self.summary)
        self.extraction_preview_label = QLabel()
        self.extraction_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.extraction_preview_label.setVisible(False)
        root.addWidget(self.extraction_preview_label)

        cards_layout = QHBoxLayout()
        previews = controller.validation_previews()
        for result, frame, mask in previews:
            card = ValidationCard(controller, result, frame, mask, self.open_correction)
            self.cards[result.frame_number] = card
            self.preview_data[result.frame_number] = (frame, mask)
            cards_layout.addWidget(card)
        root.addLayout(cards_layout)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        controller.validation_state_changed.connect(self.update_states)
        controller.correction_applied.connect(self._correction_applied)
        controller.extraction_preview_ready.connect(self._show_extraction_preview)

    def update_states(self, results: list[FrameResult]) -> None:
        for result in results:
            if result.frame_number in self.cards:
                self.cards[result.frame_number].set_state(result)
        shot = self.controller.active_shot
        if shot and shot.smart_layers:
            maturity = shot.smart_layers[0].object_identity.maturity_state
            if maturity == MaturityState.VALIDATED:
                self.summary.setText(
                    "Object Identity Validated · transparent extraction previews generated."
                )

    def _show_extraction_preview(
        self, frame_number: int, rgba: NDArray[np.uint8], reference: str
    ) -> None:
        shot = self.controller.active_shot
        if shot is None or frame_number != shot.master_frame:
            return
        contiguous = np.ascontiguousarray(rgba)
        height, width, channels = contiguous.shape
        image = QImage(
            contiguous.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            440,
            260,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.extraction_preview_label.setPixmap(pixmap)
        self.extraction_preview_label.setToolTip(reference)
        self.extraction_preview_label.setVisible(True)

    def open_correction(self, frame_number: int) -> None:
        shot = self.controller.active_shot
        if shot is None or frame_number == shot.master_frame:
            self.summary.setText("Refine the Master Frame through Object Hypothesis guidance.")
            return
        self.controller.set_validation_state(frame_number, ValidationState.CORRECTION_REQUIRED)
        frame, mask = self.preview_data[frame_number]
        self.correction_dialog = CorrectionDialog(self.controller, frame_number, frame, mask)
        self.correction_dialog.show()

    def _correction_applied(
        self,
        frame_number: int,
        mask: NDArray[np.uint8],
        confidence: float,
    ) -> None:
        frame, _ = self.preview_data[frame_number]
        self.preview_data[frame_number] = (frame, mask)
        if self.correction_dialog is not None:
            self.correction_dialog.accept()
        self.summary.setText(
            f"Frame {frame_number} correction applied at {confidence:.0%}. Review again."
        )


class CorrectionDialog(QDialog):
    def __init__(
        self,
        controller: ProjectController,
        frame_number: int,
        frame: NDArray[np.uint8],
        current_mask: NDArray[np.uint8],
    ) -> None:
        super().__init__()
        self.controller = controller
        self.frame_number = frame_number
        self.setWindowTitle(f"Correct Frame {frame_number} — NOVA Layer")
        self.resize(860, 620)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Add high-priority Artist Guidance for this frame."))
        self.viewer = GuidanceViewer()

        tools = QHBoxLayout()
        for label, mode in (
            ("+ Include", GuidanceMode.POSITIVE),
            ("− Exclude", GuidanceMode.NEGATIVE),
            ("□ Region", GuidanceMode.BOUNDING_REGION),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked, selected=mode: self.viewer.set_mode(selected))
            tools.addWidget(button)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.viewer.clear_guidance)
        tools.addWidget(clear)
        tools.addStretch()
        root.addLayout(tools)

        self.viewer.set_frame(frame)
        self.viewer.set_mask_overlay(current_mask)
        root.addWidget(self.viewer, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        apply_button = QPushButton("Apply Correction")
        apply_button.clicked.connect(self.apply_correction)
        actions.addWidget(cancel)
        actions.addWidget(apply_button)
        root.addLayout(actions)

    def apply_correction(self) -> None:
        self.controller.apply_frame_correction(
            self.frame_number,
            self.viewer.points,
            self.viewer.bounding_region,
        )
