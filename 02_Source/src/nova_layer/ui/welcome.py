from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


class WelcomePage(QWidget):
    create_requested = Signal()
    open_requested = Signal()
    diagnostics_requested = Signal()
    object_workflow_requested = Signal()
    recent_project_requested = Signal(str)
    reopen_last_requested = Signal()
    reset_workspace_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("welcomePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(64, 48, 64, 48)
        root.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        card = QFrame()
        card.setObjectName("welcomeCard")
        card.setMaximumWidth(680)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(48, 44, 48, 44)
        card_layout.setSpacing(18)

        brand = QLabel("NOVA LAYER")
        brand.setObjectName("brandLabel")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(brand)

        title = QLabel("Object understanding for visual production")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        card_layout.addWidget(title)

        subtitle = QLabel(
            "Create a project or restore an existing Smart Layer workspace. "
            "Phase 1 validates one object in one shot. "
            "Object Workflow opens the schema 2.0 interactive slice."
        )
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        card_layout.addWidget(subtitle)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.create_button = QPushButton("Create Project")
        self.create_button.setObjectName("createProjectButton")
        self.create_button.clicked.connect(self.create_requested)
        self.open_button = QPushButton("Open Project")
        self.open_button.setObjectName("openProjectButton")
        self.open_button.clicked.connect(self.open_requested)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.open_button)
        card_layout.addLayout(buttons)

        self.object_workflow_button = QPushButton("Object Workflow")
        self.object_workflow_button.setObjectName("objectWorkflowButton")
        self.object_workflow_button.clicked.connect(self.object_workflow_requested)
        card_layout.addWidget(self.object_workflow_button)

        recent_label = QLabel("Recent Projects")
        recent_label.setObjectName("recentProjectsLabel")
        card_layout.addWidget(recent_label)
        self.recent_projects_list = QListWidget()
        self.recent_projects_list.setObjectName("welcomeRecentProjects")
        self.recent_projects_list.setMaximumHeight(110)
        self.recent_projects_list.itemDoubleClicked.connect(self._emit_recent)
        card_layout.addWidget(self.recent_projects_list)

        workspace_row = QHBoxLayout()
        self.reopen_last_button = QPushButton("Reopen Last Workspace")
        self.reopen_last_button.setObjectName("reopenLastWorkspaceButton")
        self.reopen_last_button.clicked.connect(self.reopen_last_requested)
        self.reset_workspace_button = QPushButton("Reset Workspace")
        self.reset_workspace_button.setObjectName("resetWorkspaceWelcomeButton")
        self.reset_workspace_button.clicked.connect(self.reset_workspace_requested)
        workspace_row.addWidget(self.reopen_last_button)
        workspace_row.addWidget(self.reset_workspace_button)
        card_layout.addLayout(workspace_row)

        diagnostics_row = QHBoxLayout()
        self.diagnostics_summary = QLabel("Checking application capabilities…")
        self.diagnostics_summary.setObjectName("diagnosticsSummary")
        diagnostics_row.addWidget(self.diagnostics_summary, 1)
        self.diagnostics_button = QPushButton("Details")
        self.diagnostics_button.setObjectName("diagnosticsButton")
        self.diagnostics_button.clicked.connect(self.diagnostics_requested)
        diagnostics_row.addWidget(self.diagnostics_button)
        card_layout.addLayout(diagnostics_row)

        centered = QHBoxLayout()
        centered.addStretch()
        centered.addWidget(card)
        centered.addStretch()
        root.addLayout(centered)
        root.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

    def set_diagnostics_summary(self, message: str, blocking: bool) -> None:
        prefix = "Setup required" if blocking else "Prototype mode"
        self.diagnostics_summary.setText(f"{prefix} · {message}")
        self.create_button.setEnabled(not blocking)
        self.open_button.setEnabled(not blocking)
        self.object_workflow_button.setEnabled(not blocking)
        self.reopen_last_button.setEnabled(not blocking)

    def set_recent_projects(self, paths: list[str]) -> None:
        self.recent_projects_list.clear()
        for path in paths:
            self.recent_projects_list.addItem(path)
        self.reopen_last_button.setEnabled(bool(paths))

    def _emit_recent(self, item: object) -> None:
        text = getattr(item, "text", lambda: "")()
        if text:
            self.recent_project_requested.emit(str(text))
