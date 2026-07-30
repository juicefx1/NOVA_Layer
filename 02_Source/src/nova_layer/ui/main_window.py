from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
)

from nova_layer.app.capability_selection import (
    select_interactive_segmentation,
    select_skeleton_detection,
    select_skeleton_tracking,
    select_temporal_propagation,
)
from nova_layer.app.diagnostics import DiagnosticReport, StartupDiagnostics
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.user_facing_errors import format_user_error
from nova_layer.domain.models import Project
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.ui.diagnostics_dialog import DiagnosticsDialog
from nova_layer.ui.object_workflow_window import ObjectWorkflowWindow
from nova_layer.ui.welcome import WelcomePage
from nova_layer.ui.workspace import WorkspaceWindow

APP_STYLESHEET = """
QMainWindow, QWidget#welcomePage {
    background: #111318;
    color: #f2f4f8;
}
QFrame#welcomeCard {
    background: #1a1e26;
    border: 1px solid #303744;
    border-radius: 18px;
}
QLabel#brandLabel {
    color: #8ea8ff;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
}
QLabel#welcomeTitle {
    color: #ffffff;
    font-size: 30px;
    font-weight: 650;
}
QLabel#welcomeSubtitle {
    color: #aeb6c5;
    font-size: 15px;
}
QPushButton {
    min-height: 42px;
    padding: 0 22px;
    border-radius: 8px;
    border: 1px solid #3a4352;
    background: #242a35;
    color: #f5f7fa;
    font-weight: 600;
}
QPushButton:hover { background: #303849; }
QPushButton#createProjectButton {
    background: #5d72f2;
    border-color: #7184f7;
}
QPushButton#createProjectButton:hover { background: #6d80f5; }
QLabel#projectHeading {
    color: #ffffff;
    font-size: 24px;
    font-weight: 650;
}
QLabel#workspacePlaceholder { color: #8f99aa; font-size: 15px; }
QStatusBar { background: #171a20; color: #9ea7b6; }
"""


class MainWindow(QMainWindow):
    def __init__(self, controller: ProjectController | None = None) -> None:
        super().__init__()
        if controller is None:
            selection = select_interactive_segmentation()
            propagation = select_temporal_propagation()
            skeleton_tracking = select_skeleton_tracking()
            skeleton_detection = select_skeleton_detection()
            controller = ProjectController(
                segmentation=selection.capability,
                propagation=propagation.capability,
                skeleton_tracking=skeleton_tracking.capability,
                skeleton_detection=skeleton_detection.capability,
            )
        self.controller = controller
        self.workspace: WorkspaceWindow | None = None
        self.object_workflow_window: ObjectWorkflowWindow | None = None
        self.diagnostics_report: DiagnosticReport = StartupDiagnostics().run()
        self.diagnostics_dialog: DiagnosticsDialog | None = None
        self.setObjectName("mainWindow")
        self.setWindowTitle("NOVA Layer")
        self.resize(1100, 720)
        self.setMinimumSize(820, 560)
        self.setStyleSheet(APP_STYLESHEET)

        self.welcome = WelcomePage()
        self.setCentralWidget(self.welcome)
        self.welcome.create_requested.connect(self._request_create_project)
        self.welcome.open_requested.connect(self._request_open_project)
        self.welcome.diagnostics_requested.connect(self._show_diagnostics)
        self.welcome.object_workflow_requested.connect(self._show_object_workflow)
        self.welcome.recent_project_requested.connect(self._open_recent_object_workflow)
        self.welcome.reopen_last_requested.connect(self._reopen_last_object_workflow)
        self.welcome.reset_workspace_requested.connect(self._reset_shared_workspace)
        self.welcome.set_diagnostics_summary(
            self.diagnostics_report.summary,
            self.diagnostics_report.has_failures,
        )
        self._refresh_welcome_recent_projects()
        self.controller.project_changed.connect(self._show_workspace)
        self.controller.error_occurred.connect(self._show_error)

    def _shared_workspace(self) -> WorkspaceManager:
        return WorkspaceManager.shared()

    def _refresh_welcome_recent_projects(self) -> None:
        workspace = self._shared_workspace()
        if workspace.load_error:
            self._prompt_workspace_recovery(workspace.load_error)
        self.welcome.set_recent_projects(workspace.recent_projects())

    def _prompt_workspace_recovery(self, error: str) -> None:
        answer = QMessageBox.warning(
            self,
            "Workspace Recovery",
            "The saved workspace could not be loaded and was reset to defaults.\n\n"
            f"Details: {error}\n\n"
            "Projects on disk were not modified. Clear remaining workspace preferences?",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Ignore,
            QMessageBox.StandardButton.Ignore,
        )
        if answer == QMessageBox.StandardButton.Reset:
            self._shared_workspace().reset_workspace()
            self.statusBar().showMessage("Workspace preferences reset.")
        else:
            self.statusBar().showMessage(f"Workspace recovered after load error: {error}")
        self._shared_workspace().clear_load_error()

    def _request_create_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "Create Project", "Project name:")
        if not accepted or not name.strip():
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose Project Location")
        if directory:
            self.controller.create_project(name, Path(directory))

    def _request_open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Open NOVA Project",
            options=QFileDialog.Option.ShowDirsOnly,
        )
        if directory:
            self.controller.open_project(Path(directory))

    def _show_workspace(self, project: Project) -> None:
        self.workspace = WorkspaceWindow(self.controller)
        self.workspace.setStyleSheet(APP_STYLESHEET)
        self.workspace.show()
        self.close()

    def _show_object_workflow(self) -> None:
        self.object_workflow_window = ObjectWorkflowWindow()
        self.object_workflow_window.setStyleSheet(APP_STYLESHEET)
        self.object_workflow_window.show()

    def _open_recent_object_workflow(self, package_path: str) -> None:
        self._show_object_workflow()
        assert self.object_workflow_window is not None
        self.object_workflow_window.controller.load_project(Path(package_path))
        self._refresh_welcome_recent_projects()

    def _reopen_last_object_workflow(self) -> None:
        self._show_object_workflow()
        assert self.object_workflow_window is not None
        opened = self.object_workflow_window.controller.reopen_last_project()
        if not opened:
            QMessageBox.information(self, "NOVA Layer", "No recent Object Workflow projects.")
        self._refresh_welcome_recent_projects()

    def _reset_shared_workspace(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset Workspace",
            "Clear application workspace preferences and recent projects?\n"
            "Project files on disk will not be deleted.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._shared_workspace().reset_workspace()
        self._refresh_welcome_recent_projects()
        self.statusBar().showMessage("Workspace reset.")

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "NOVA Layer", format_user_error(message))

    def _show_diagnostics(self) -> None:
        self.diagnostics_dialog = DiagnosticsDialog(self.diagnostics_report)
        self.diagnostics_dialog.setStyleSheet(APP_STYLESHEET)
        self.diagnostics_dialog.show()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
