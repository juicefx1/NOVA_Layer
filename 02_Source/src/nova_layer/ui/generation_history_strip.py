from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.object_workflow_controller import ObjectWorkflowController


class GenerationHistoryWidget(QWidget):
    """Compact generation history strip."""

    generation_selected = Signal(object)

    def __init__(self, controller: ObjectWorkflowController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("generationHistory")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        heading = QLabel("Generation History")
        heading.setObjectName("generationHistoryHeading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self.reject_button = QPushButton("Reject")
        self.reject_button.setObjectName("rejectGenerationButton")
        self.retry_button = QPushButton("Generate Again")
        self.retry_button.setObjectName("retryGenerationButton")
        self.reactivate_button = QPushButton("Reactivate")
        self.reactivate_button.setObjectName("reactivateGenerationButton")
        for button in (self.reject_button, self.retry_button, self.reactivate_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("generationHistoryList")
        layout.addWidget(self.list_widget)

        self.reject_button.clicked.connect(self._controller.reject_active_generation)
        self.retry_button.clicked.connect(self._controller.retry_generation)
        self.reactivate_button.clicked.connect(self._on_reactivate)
        self.list_widget.itemClicked.connect(self._on_item_clicked)

    def refresh(self) -> None:
        state = self._controller.view_state()
        self.reject_button.setEnabled(state.can_reject_generation)
        self.retry_button.setEnabled(state.can_retry_generation)
        self.reactivate_button.setEnabled(state.can_reactivate_generation)

        selected_id: UUID | None = None
        current = self.list_widget.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)

        self.list_widget.clear()
        for item in self._controller.list_generation_history():
            label = (
                f"#{item.sequence_number} · intent r{item.artist_intent_revision} · "
                f"{item.provider_display_name} · {item.candidate_count} candidates · "
                f"{item.status}"
            )
            if item.active_candidate_confidence is not None:
                label += f" · sel {item.active_candidate_confidence:.2f}"
            if item.is_active:
                label += " · active"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item.generation_id)
            if item.status == "rejected":
                list_item.setForeground(Qt.GlobalColor.darkRed)
            elif item.status == "confirmed":
                list_item.setForeground(Qt.GlobalColor.darkGreen)
            self.list_widget.addItem(list_item)
            if selected_id == item.generation_id:
                self.list_widget.setCurrentItem(list_item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        generation_id = item.data(Qt.ItemDataRole.UserRole)
        if generation_id is not None:
            self._controller.restore_generation(generation_id)
            self.generation_selected.emit(generation_id)

    def _on_reactivate(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            for entry in self._controller.list_generation_history():
                if entry.is_active and entry.status == "rejected":
                    self._controller.reactivate_generation(entry.generation_id)
                    return
            return
        generation_id = item.data(Qt.ItemDataRole.UserRole)
        if generation_id is not None:
            self._controller.reactivate_generation(generation_id)
