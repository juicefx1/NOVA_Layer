from __future__ import annotations

from uuid import UUID

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.object_workflow_controller import CandidateViewItem, ObjectWorkflowController


class CandidateChip(QToolButton):
    """Focusable candidate card with distinct active / preview / focus states."""

    hovered = Signal(object)
    unhovered = Signal(object)
    activated = Signal(object)

    def __init__(self, item: CandidateViewItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.candidate_id = item.id
        self._icon_dims: tuple[int, int] | None = None
        self.setObjectName("candidateChip")
        self.setCheckable(True)
        self.setAutoRaise(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(104, 92)
        self.setToolTip(
            "Click to select · Hover to preview · ←/→ browse · Enter select · "
            "1–9 jump · Esc clear preview · Space compare"
        )
        self.apply_item(item)
        self.clicked.connect(lambda _checked=False: self.activated.emit(self.candidate_id))

    def apply_item(self, item: CandidateViewItem) -> None:
        self.candidate_id = item.id
        self.setChecked(item.is_active)
        self.setProperty("active", "true" if item.is_active else "false")
        self.setProperty("previewed", "true" if item.is_previewed else "false")
        self.setProperty("focused", "true" if item.is_focused else "false")
        conf = item.confidence_label if item.confidence is not None else "—"
        self.setText(f"#{item.index + 1}\n{conf}")
        self.setAccessibleName(item.accessible_name)
        self.setAccessibleDescription(
            "Active candidate" if item.is_active else "Segmentation candidate"
        )
        if item.thumbnail_mask is not None:
            thumb = item.thumbnail_mask
            height, width = thumb.shape
            icon_dims = (width, height)
            if self.icon().isNull() or self._icon_dims != icon_dims:
                rgba = np.zeros((height, width, 4), dtype=np.uint8)
                rgba[:, :, 0] = 104
                rgba[:, :, 1] = 134
                rgba[:, :, 2] = 255
                rgba[:, :, 3] = (thumb.astype(np.float32) * 0.85).astype(np.uint8)
                contiguous = np.ascontiguousarray(rgba)
                image = QImage(
                    contiguous.data,
                    width,
                    height,
                    width * 4,
                    QImage.Format.Format_RGBA8888,
                ).copy()
                pixmap = QPixmap.fromImage(image).scaled(
                    72,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.setIcon(QIcon(pixmap))
                self.setIconSize(pixmap.size())
                self._icon_dims = icon_dims
        else:
            self.setIcon(QIcon())
            self._icon_dims = None
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.hovered.emit(self.candidate_id)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.unhovered.emit(self.candidate_id)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.hovered.emit(self.candidate_id)
        super().focusInEvent(event)


class CandidateStripWidget(QWidget):
    """Horizontal Candidate Strip with hover preview and keyboard navigation."""

    def __init__(
        self,
        controller: ObjectWorkflowController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._chips: dict[UUID, CandidateChip] = {}
        self._space_compare = False
        self._enabled = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Candidates")
        title.setObjectName("workspacePlaceholder")
        header.addWidget(title)
        self.compare_button = QToolButton()
        self.compare_button.setObjectName("candidateCompareToggle")
        self.compare_button.setText("Compare")
        self.compare_button.setCheckable(True)
        self.compare_button.setToolTip(
            "Toggle comparison between active and focused candidate"
        )
        self.compare_button.clicked.connect(self.controller.toggle_candidate_comparison)
        header.addWidget(self.compare_button)
        header.addStretch()
        root.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("candidateStrip")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFixedHeight(118)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QFrame()
        self.host.setObjectName("candidateStripHost")
        self.strip = QHBoxLayout(self.host)
        self.strip.setContentsMargins(4, 4, 4, 4)
        self.strip.setSpacing(8)
        self.scroll_area.setWidget(self.host)
        root.addWidget(self.scroll_area)

        self.setStyleSheet(
            """
            QToolButton#candidateChip {
                border: 1px solid #4a5160;
                border-radius: 6px;
                padding: 4px;
                background: #1c212b;
                color: #d7dbe3;
                text-align: center;
            }
            QToolButton#candidateChip[focused="true"] {
                border: 2px solid #8ea8ff;
            }
            QToolButton#candidateChip[previewed="true"] {
                background: #243044;
            }
            QToolButton#candidateChip[active="true"] {
                border: 2px solid #58d68d;
                background: #1e2a24;
            }
            """
        )
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        bindings: list[tuple[str, object]] = [
            ("Left", self._on_left),
            ("Right", self._on_right),
            ("Return", self._on_enter),
            ("Enter", self._on_enter),
            ("Escape", self._on_escape),
        ]
        for key, slot in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)
        for digit in range(1, 10):
            shortcut = QShortcut(QKeySequence(str(digit)), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda d=digit: self._on_digit(d))

    def set_interaction_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.compare_button.setEnabled(enabled)
        for chip in self._chips.values():
            chip.setEnabled(enabled)

    def rebuild(self, candidates: list[CandidateViewItem], *, enabled: bool) -> None:
        self._enabled = enabled
        self.compare_button.setEnabled(enabled and bool(candidates))
        self.compare_button.setChecked(self.controller.comparison_mode)

        if not candidates:
            while self.strip.count():
                item = self.strip.takeAt(0)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.deleteLater()
            self._chips.clear()
            empty = QLabel("No candidates — Generate to produce a set")
            empty.setObjectName("workspacePlaceholder")
            self.strip.addWidget(empty)
            self.strip.addStretch()
            return

        candidate_set = {c.id for c in candidates}
        for existing_id in list(self._chips.keys()):
            if existing_id not in candidate_set:
                chip_to_remove = self._chips.pop(existing_id)
                chip_to_remove.deleteLater()

        # Update/create chips in-place.
        for candidate in candidates:
            chip = self._chips.get(candidate.id)
            if chip is None:
                chip = CandidateChip(candidate)
                chip.activated.connect(self._on_activated)
                chip.hovered.connect(self._on_hovered)
                chip.unhovered.connect(self._on_unhovered)
                self._chips[candidate.id] = chip
            chip.setEnabled(enabled)
            chip.apply_item(candidate)

        # Reorder widgets to match the current candidate ordering.
        while self.strip.count():
            item = self.strip.takeAt(0)
            # Keep widgets; just remove them from the layout.
            _ = item.widget() if item is not None else None
        scroll_target: CandidateChip | None = None
        for candidate in candidates:
            chip = self._chips[candidate.id]
            self.strip.addWidget(chip)
            if candidate.is_active:
                scroll_target = chip
            elif candidate.is_focused and scroll_target is None:
                scroll_target = chip

        self.strip.addStretch()
        if scroll_target is not None:
            self.scroll_area.ensureWidgetVisible(scroll_target, 24, 0)

    def _text_input_focused(self) -> bool:
        focus = QApplication.focusWidget()
        return isinstance(
            focus,
            (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox),
        )

    def _on_left(self) -> None:
        if not self._enabled or self._text_input_focused():
            return
        self.controller.focus_previous_candidate()

    def _on_right(self) -> None:
        if not self._enabled or self._text_input_focused():
            return
        self.controller.focus_next_candidate()

    def _on_enter(self) -> None:
        if not self._enabled or self._text_input_focused():
            return
        self.controller.commit_focused_or_previewed_candidate()

    def _on_escape(self) -> None:
        if not self._enabled or self._text_input_focused():
            return
        self.controller.clear_candidate_preview()

    def _on_digit(self, digit: int) -> None:
        if not self._enabled or self._text_input_focused():
            return
        self.controller.select_candidate_by_index(digit - 1)

    def _on_activated(self, candidate_id: object) -> None:
        if not self._enabled:
            return
        self.controller.select_candidate(UUID(str(candidate_id)))

    def _on_hovered(self, candidate_id: object) -> None:
        if not self._enabled or self._space_compare:
            return
        self.controller.preview_candidate(UUID(str(candidate_id)))

    def _on_unhovered(self, candidate_id: object) -> None:
        if not self._enabled or self._space_compare or self.controller.comparison_mode:
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, CandidateChip):
            return
        self.controller.clear_candidate_preview()

    def handle_space_press(self) -> bool:
        if not self._enabled or self._text_input_focused():
            return False
        focus_id = self.controller.focused_candidate_id or self.controller.preview_candidate_id
        if focus_id is None:
            return False
        self._space_compare = True
        self.controller.preview_candidate(focus_id)
        return True

    def handle_space_release(self) -> bool:
        if not self._space_compare:
            return False
        self._space_compare = False
        if not self.controller.comparison_mode:
            self.controller.clear_candidate_preview()
        return True
