from pathlib import Path

from PySide6.QtCore import Qt

from nova_layer.app.project_controller import ProjectController
from nova_layer.ui.main_window import MainWindow


def test_welcome_actions_are_visible(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()

    assert window.welcome.create_button.isVisible()
    assert window.welcome.open_button.isVisible()


def test_controller_creates_project_and_opens_workspace(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController()
    window = MainWindow(controller)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()

    project = controller.create_project("Vertical Slice", tmp_path)

    assert project is not None
    assert (tmp_path / "Vertical_Slice.nova" / "manifest.json").exists()
    assert window.workspace is not None
    assert window.workspace.windowTitle() == "Vertical Slice — NOVA Layer"
    window.workspace.close()


def test_create_button_emits_request(qtbot: object) -> None:
    window = MainWindow()
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.welcome.create_requested.disconnect(window._request_create_project)
    with qtbot.waitSignal(window.welcome.create_requested):  # type: ignore[attr-defined]
        qtbot.mouseClick(window.welcome.create_button, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
