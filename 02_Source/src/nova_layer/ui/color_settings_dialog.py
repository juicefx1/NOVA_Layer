from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
    LegacyDisplayTransform,
    create_display_transform,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

_BACKEND_LEGACY = "Legacy"
_BACKEND_OCIO = "OCIO"

# Stored under WorkspaceManager.preferences (workspace.json).
COLOR_SETTINGS_PREFERENCE_KEY = "smart_layer_color_settings"

BackendPreference = Literal["legacy", "ocio"]


@dataclass(frozen=True)
class ColorSettingsPreference:
    backend: BackendPreference = "legacy"
    config_path: str = ""
    input_color_space: str = "scene_linear"
    display: str = ""
    view: str = ""
    exposure: float = 0.0


def format_diagnostics_text(diagnostics: DisplayTransformDiagnostics | None) -> str:
    if diagnostics is None:
        return "No display-transform diagnostics available."
    lines = [
        f"backend: {diagnostics.backend}",
        f"config path: {diagnostics.config_path or '—'}",
        f"config source: {diagnostics.config_source or '—'}",
        f"input color space: {diagnostics.input_color_space}",
        f"display: {diagnostics.display or '—'}",
        f"view: {diagnostics.view or '—'}",
        f"exposure: {diagnostics.exposure:g}",
        f"fallback reason: {diagnostics.fallback_reason or '—'}",
    ]
    return "\n".join(lines)


def _parse_exposure(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value != value:  # NaN
        return 0.0
    return max(-10.0, min(10.0, value))


def _normalize_backend(raw: Any) -> BackendPreference:
    text = str(raw or "").strip().casefold()
    if text in {"ocio", "opencolorio"}:
        return "ocio"
    return "legacy"


def config_path_from_stored(raw: str | None) -> Path | None:
    text = (raw or "").strip()
    if not text:
        return None
    return Path(text).expanduser()


def load_color_settings_preference(
    workspace: WorkspaceManager,
) -> ColorSettingsPreference | None:
    raw = workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY, None)
    if not isinstance(raw, dict):
        return None
    return ColorSettingsPreference(
        backend=_normalize_backend(raw.get("backend")),
        config_path=str(raw.get("config_path") or ""),
        input_color_space=str(raw.get("input_color_space") or "scene_linear").strip()
        or "scene_linear",
        display=str(raw.get("display") or ""),
        view=str(raw.get("view") or ""),
        exposure=_parse_exposure(raw.get("exposure", 0.0)),
    )


def save_color_settings_preference(
    workspace: WorkspaceManager,
    preference: ColorSettingsPreference,
) -> None:
    workspace.set_preference(
        COLOR_SETTINGS_PREFERENCE_KEY,
        {
            "backend": preference.backend,
            "config_path": preference.config_path,
            "input_color_space": preference.input_color_space,
            "display": preference.display,
            "view": preference.view,
            "exposure": float(preference.exposure),
        },
    )


def build_display_transform_from_preference(
    preference: ColorSettingsPreference | None,
) -> DisplayTransformProtocol:
    """Build a transform from persisted prefs. Missing prefs → Legacy default.

    Invalid OCIO config falls back via create_display_transform (no raise).
    """
    if preference is None or preference.backend == "legacy":
        return LegacyDisplayTransform()

    display = preference.display.strip() or None
    view = preference.view.strip() or None
    return create_display_transform(
        prefer_ocio=True,
        config_path=config_path_from_stored(preference.config_path),
        input_color_space=preference.input_color_space or "scene_linear",
        display=display,
        view=view,
        exposure=float(preference.exposure),
    )


def restore_color_settings(
    controller: ProjectController,
    workspace: WorkspaceManager,
) -> DisplayTransformProtocol:
    """Apply persisted Color Settings to the controller without UI warnings."""
    preference = load_color_settings_preference(workspace)
    transform = build_display_transform_from_preference(preference)
    controller.set_display_transform(transform)
    return transform


class ColorSettingsDialog(QDialog):
    """Minimal Color Settings entry for Legacy / OCIO display transforms."""

    def __init__(
        self,
        controller: ProjectController,
        parent: QWidget | None = None,
        *,
        workspace: WorkspaceManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._workspace = workspace or WorkspaceManager.shared()
        self.setObjectName("colorSettingsDialog")
        self.setWindowTitle("Color Settings — NOVA Layer")
        self.resize(520, 420)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.backend_combo = QComboBox()
        self.backend_combo.setObjectName("colorBackendCombo")
        self.backend_combo.addItems([_BACKEND_LEGACY, _BACKEND_OCIO])
        self.backend_combo.currentTextChanged.connect(self._sync_field_enabled)
        form.addRow("Backend", self.backend_combo)

        config_row = QHBoxLayout()
        self.config_path_edit = QLineEdit()
        self.config_path_edit.setObjectName("ocioConfigPathEdit")
        self.config_path_edit.setPlaceholderText("Path to .ocio config (or leave empty for $OCIO)")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setObjectName("ocioConfigBrowseButton")
        self.browse_button.clicked.connect(self._browse_config)
        config_row.addWidget(self.config_path_edit, 1)
        config_row.addWidget(self.browse_button)
        form.addRow("OCIO Config Path", config_row)

        self.input_color_space_edit = QLineEdit()
        self.input_color_space_edit.setObjectName("ocioInputColorSpaceEdit")
        self.input_color_space_edit.setText("scene_linear")
        form.addRow("Input Color Space", self.input_color_space_edit)

        self.display_edit = QLineEdit()
        self.display_edit.setObjectName("ocioDisplayEdit")
        self.display_edit.setPlaceholderText("Default display when empty")
        form.addRow("Display", self.display_edit)

        self.view_edit = QLineEdit()
        self.view_edit.setObjectName("ocioViewEdit")
        self.view_edit.setPlaceholderText("Default view when empty")
        form.addRow("View", self.view_edit)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setObjectName("ocioExposureSpin")
        self.exposure_spin.setRange(-10.0, 10.0)
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setSingleStep(0.1)
        self.exposure_spin.setValue(0.0)
        form.addRow("Exposure", self.exposure_spin)

        root.addLayout(form)

        note = QLabel(
            "Color Settings apply to EXR image-sequence previews. "
            "Video decode paths are unchanged."
        )
        note.setWordWrap(True)
        note.setObjectName("colorSettingsNote")
        root.addWidget(note)

        self.diagnostics_label = QLabel()
        self.diagnostics_label.setObjectName("colorDiagnosticsLabel")
        self.diagnostics_label.setWordWrap(True)
        self.diagnostics_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.diagnostics_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("colorSettingsButtons")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_ui()
        self._sync_field_enabled(self.backend_combo.currentText())

    def _load_ui(self) -> None:
        preference = load_color_settings_preference(self._workspace)
        if preference is not None:
            self._populate_from_preference(preference)
        else:
            self._populate_from_diagnostics(self.controller.display_transform_diagnostics)
        self.diagnostics_label.setText(
            format_diagnostics_text(self.controller.display_transform_diagnostics)
        )

    def _populate_from_preference(self, preference: ColorSettingsPreference) -> None:
        self.backend_combo.setCurrentText(
            _BACKEND_OCIO if preference.backend == "ocio" else _BACKEND_LEGACY
        )
        self.config_path_edit.setText(preference.config_path)
        self.input_color_space_edit.setText(preference.input_color_space or "scene_linear")
        self.display_edit.setText(preference.display)
        self.view_edit.setText(preference.view)
        self.exposure_spin.setValue(float(preference.exposure))

    def _populate_from_diagnostics(
        self,
        diagnostics: DisplayTransformDiagnostics | None,
    ) -> None:
        if diagnostics is None:
            self.backend_combo.setCurrentText(_BACKEND_LEGACY)
            return

        self.backend_combo.setCurrentText(
            _BACKEND_OCIO if diagnostics.backend == "ocio" else _BACKEND_LEGACY
        )
        if diagnostics.config_path:
            self.config_path_edit.setText(diagnostics.config_path)
        self.input_color_space_edit.setText(diagnostics.input_color_space or "scene_linear")
        if diagnostics.display:
            self.display_edit.setText(diagnostics.display)
        if diagnostics.view:
            self.view_edit.setText(diagnostics.view)
        self.exposure_spin.setValue(float(diagnostics.exposure))

    def _preference_from_form(self) -> ColorSettingsPreference:
        backend: BackendPreference = (
            "ocio" if self.backend_combo.currentText() == _BACKEND_OCIO else "legacy"
        )
        return ColorSettingsPreference(
            backend=backend,
            config_path=self.config_path_edit.text().strip(),
            input_color_space=self.input_color_space_edit.text().strip() or "scene_linear",
            display=self.display_edit.text().strip(),
            view=self.view_edit.text().strip(),
            exposure=_parse_exposure(self.exposure_spin.value()),
        )

    def _sync_field_enabled(self, backend: str) -> None:
        ocio = backend == _BACKEND_OCIO
        for widget in (
            self.config_path_edit,
            self.browse_button,
            self.input_color_space_edit,
            self.display_edit,
            self.view_edit,
            self.exposure_spin,
        ):
            widget.setEnabled(ocio)

    def _browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select OCIO Config",
            self.config_path_edit.text().strip() or "",
            "OCIO Config (*.ocio);;All Files (*)",
        )
        if path:
            self.config_path_edit.setText(path)

    def _on_accept(self) -> None:
        if self.apply_settings():
            self.accept()

    def apply_settings(self) -> bool:
        """Apply Color Settings to the controller and persist on success."""
        preference = self._preference_from_form()
        try:
            if preference.backend == "legacy":
                transform = LegacyDisplayTransform()
            else:
                transform = create_display_transform(
                    prefer_ocio=True,
                    config_path=config_path_from_stored(preference.config_path),
                    input_color_space=preference.input_color_space,
                    display=preference.display or None,
                    view=preference.view or None,
                    exposure=float(preference.exposure),
                )
        except Exception as exc:  # noqa: BLE001 - surface to UI without crashing
            QMessageBox.warning(
                self,
                "Color Settings",
                f"Could not apply color settings.\n\n{exc}",
            )
            return False

        self.controller.set_display_transform(transform)
        save_color_settings_preference(self._workspace, preference)

        diagnostics = getattr(transform, "diagnostics", None)
        self.diagnostics_label.setText(format_diagnostics_text(diagnostics))

        if (
            preference.backend == "ocio"
            and diagnostics is not None
            and diagnostics.fallback_reason
        ):
            QMessageBox.warning(
                self,
                "Color Settings",
                "OCIO could not be used; falling back to Legacy preview.\n\n"
                f"{diagnostics.fallback_reason}",
            )
        return True
