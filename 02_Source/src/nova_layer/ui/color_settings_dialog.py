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
    ColorTransformError,
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
    LegacyDisplayTransform,
    create_display_transform,
)
from nova_layer.adapters.color.ocio_adapter import (
    OcioConfigOptions,
    is_ocio_available,
    load_ocio_config_options,
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


def _combo_text(combo: QComboBox) -> str:
    return combo.currentText().strip()


def _set_editable_combo_items(
    combo: QComboBox,
    items: tuple[str, ...] | list[str],
    preferred: str | None,
    *,
    default: str | None = None,
) -> str | None:
    """Populate an editable combo and select preferred/default/unknown preserved."""
    warnings: list[str] = []
    combo.blockSignals(True)
    try:
        combo.clear()
        for item in items:
            combo.addItem(item)

        choice = (preferred or "").strip()
        if choice and choice in items:
            combo.setCurrentText(choice)
        elif choice:
            combo.addItem(choice)
            combo.setCurrentText(choice)
            warnings.append(f"{combo.objectName() or 'field'}: {choice!r} not in config list")
        elif default and default in items:
            combo.setCurrentText(default)
        elif items:
            combo.setCurrentIndex(0)
        else:
            combo.setCurrentText("")
    finally:
        combo.blockSignals(False)
    return "; ".join(warnings) if warnings else None


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
        self._ocio_options: OcioConfigOptions | None = None
        self._options_message: str | None = None
        self._selection_warnings: list[str] = []
        self.setObjectName("colorSettingsDialog")
        self.setWindowTitle("Color Settings — NOVA Layer")
        self.resize(520, 460)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.backend_combo = QComboBox()
        self.backend_combo.setObjectName("colorBackendCombo")
        self.backend_combo.addItems([_BACKEND_LEGACY, _BACKEND_OCIO])
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        form.addRow("Backend", self.backend_combo)

        config_row = QHBoxLayout()
        self.config_path_edit = QLineEdit()
        self.config_path_edit.setObjectName("ocioConfigPathEdit")
        self.config_path_edit.setPlaceholderText("Path to .ocio config (or leave empty for $OCIO)")
        self.config_path_edit.editingFinished.connect(self._reload_ocio_options)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setObjectName("ocioConfigBrowseButton")
        self.browse_button.clicked.connect(self._browse_config)
        config_row.addWidget(self.config_path_edit, 1)
        config_row.addWidget(self.browse_button)
        form.addRow("OCIO Config Path", config_row)

        self.input_color_space_combo = QComboBox()
        self.input_color_space_combo.setObjectName("ocioInputColorSpaceCombo")
        self.input_color_space_combo.setEditable(True)
        self.input_color_space_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("Input Color Space", self.input_color_space_combo)

        self.display_combo = QComboBox()
        self.display_combo.setObjectName("ocioDisplayCombo")
        self.display_combo.setEditable(True)
        self.display_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.display_combo.currentTextChanged.connect(self._on_display_changed)
        form.addRow("Display", self.display_combo)

        self.view_combo = QComboBox()
        self.view_combo.setObjectName("ocioViewCombo")
        self.view_combo.setEditable(True)
        self.view_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("View", self.view_combo)

        # Backward-compatible aliases used by earlier tests.
        self.input_color_space_edit = self.input_color_space_combo
        self.display_edit = self.display_combo
        self.view_edit = self.view_combo

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
        self._reload_ocio_options()
        self._refresh_diagnostics_label()

    def _populate_from_preference(self, preference: ColorSettingsPreference) -> None:
        self.backend_combo.setCurrentText(
            _BACKEND_OCIO if preference.backend == "ocio" else _BACKEND_LEGACY
        )
        self.config_path_edit.setText(preference.config_path)
        self._pending_input = preference.input_color_space or "scene_linear"
        self._pending_display = preference.display
        self._pending_view = preference.view
        self.exposure_spin.setValue(float(preference.exposure))

    def _populate_from_diagnostics(
        self,
        diagnostics: DisplayTransformDiagnostics | None,
    ) -> None:
        self._pending_input = "scene_linear"
        self._pending_display = ""
        self._pending_view = ""
        if diagnostics is None:
            self.backend_combo.setCurrentText(_BACKEND_LEGACY)
            return

        self.backend_combo.setCurrentText(
            _BACKEND_OCIO if diagnostics.backend == "ocio" else _BACKEND_LEGACY
        )
        if diagnostics.config_path:
            self.config_path_edit.setText(diagnostics.config_path)
        self._pending_input = diagnostics.input_color_space or "scene_linear"
        self._pending_display = diagnostics.display or ""
        self._pending_view = diagnostics.view or ""
        self.exposure_spin.setValue(float(diagnostics.exposure))

    def _preference_from_form(self) -> ColorSettingsPreference:
        backend: BackendPreference = (
            "ocio" if self.backend_combo.currentText() == _BACKEND_OCIO else "legacy"
        )
        return ColorSettingsPreference(
            backend=backend,
            config_path=self.config_path_edit.text().strip(),
            input_color_space=_combo_text(self.input_color_space_combo) or "scene_linear",
            display=_combo_text(self.display_combo),
            view=_combo_text(self.view_combo),
            exposure=_parse_exposure(self.exposure_spin.value()),
        )

    def _on_backend_changed(self, backend: str) -> None:
        self._sync_field_enabled(backend)
        if backend == _BACKEND_OCIO:
            self._reload_ocio_options()
        self._refresh_diagnostics_label()

    def _sync_field_enabled(self, backend: str) -> None:
        ocio = backend == _BACKEND_OCIO
        for widget in (
            self.config_path_edit,
            self.browse_button,
            self.input_color_space_combo,
            self.display_combo,
            self.view_combo,
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
            self._reload_ocio_options()

    def _reload_ocio_options(self) -> None:
        """Reload Input/Display/View lists from the current config path / $OCIO."""
        self._selection_warnings = []
        preferred_input = getattr(self, "_pending_input", None) or _combo_text(
            self.input_color_space_combo
        )
        preferred_display = getattr(self, "_pending_display", None)
        if preferred_display is None or preferred_display == "":
            preferred_display = _combo_text(self.display_combo)
        preferred_view = getattr(self, "_pending_view", None)
        if preferred_view is None or preferred_view == "":
            preferred_view = _combo_text(self.view_combo)

        # Consume one-shot pending values from preference/diagnostics load.
        self._pending_input = preferred_input
        self._pending_display = preferred_display
        self._pending_view = preferred_view

        if self.backend_combo.currentText() != _BACKEND_OCIO:
            self._ocio_options = None
            self._options_message = None
            return

        if not is_ocio_available():
            self._ocio_options = None
            self._options_message = (
                "PyOpenColorIO is not installed; install nova-layer[color] to browse "
                "OCIO color spaces / displays / views."
            )
            self._apply_options_to_combos(
                None,
                preferred_input=preferred_input,
                preferred_display=preferred_display,
                preferred_view=preferred_view,
            )
            self._refresh_diagnostics_label()
            return

        config_path = config_path_from_stored(self.config_path_edit.text())
        try:
            options = load_ocio_config_options(config_path)
        except ColorTransformError as exc:
            self._ocio_options = None
            self._options_message = str(exc)
            self._apply_options_to_combos(
                None,
                preferred_input=preferred_input,
                preferred_display=preferred_display,
                preferred_view=preferred_view,
            )
            self._refresh_diagnostics_label()
            return

        self._ocio_options = options
        self._options_message = (
            f"config: {options.config_path} ({options.config_source}); "
            f"{len(options.color_spaces)} color spaces, {len(options.displays)} displays"
        )
        self._apply_options_to_combos(
            options,
            preferred_input=preferred_input,
            preferred_display=preferred_display,
            preferred_view=preferred_view,
        )
        self._pending_input = None
        self._pending_display = None
        self._pending_view = None
        self._refresh_diagnostics_label()

    def _apply_options_to_combos(
        self,
        options: OcioConfigOptions | None,
        *,
        preferred_input: str | None,
        preferred_display: str | None,
        preferred_view: str | None,
    ) -> None:
        if options is None:
            # Keep editable user values when options cannot be loaded.
            for combo, preferred in (
                (self.input_color_space_combo, preferred_input or "scene_linear"),
                (self.display_combo, preferred_display or ""),
                (self.view_combo, preferred_view or ""),
            ):
                combo.blockSignals(True)
                try:
                    combo.clear()
                    if preferred:
                        combo.addItem(preferred)
                        combo.setCurrentText(preferred)
                finally:
                    combo.blockSignals(False)
            return

        warn = _set_editable_combo_items(
            self.input_color_space_combo,
            options.color_spaces,
            preferred_input,
            default="scene_linear" if "scene_linear" in options.color_spaces else options.color_spaces[0],
        )
        if warn:
            self._selection_warnings.append(warn)

        warn = _set_editable_combo_items(
            self.display_combo,
            options.displays,
            preferred_display,
            default=options.default_display,
        )
        if warn:
            self._selection_warnings.append(warn)

        self._refresh_views_for_display(
            _combo_text(self.display_combo),
            preferred_view=preferred_view,
            options=options,
        )

    def _on_display_changed(self, display: str) -> None:
        if self._ocio_options is None:
            return
        preferred = _combo_text(self.view_combo)
        views = self._ocio_options.views_for(display.strip())
        if preferred and preferred not in views:
            # Previous view is not valid for the new display — pick defaults.
            preferred = None
        self._refresh_views_for_display(
            display,
            preferred_view=preferred,
            options=self._ocio_options,
        )
        self._refresh_diagnostics_label()

    def _refresh_views_for_display(
        self,
        display: str,
        *,
        preferred_view: str | None,
        options: OcioConfigOptions,
    ) -> None:
        views = options.views_for(display.strip())
        default_view = None
        if display.strip() == (options.default_display or ""):
            default_view = options.default_view
        elif views:
            default_view = views[0]
        warn = _set_editable_combo_items(
            self.view_combo,
            views,
            preferred_view,
            default=default_view,
        )
        if warn:
            self._selection_warnings.append(warn)

    def _refresh_diagnostics_label(self) -> None:
        runtime = format_diagnostics_text(self.controller.display_transform_diagnostics)
        extras: list[str] = [runtime]
        if self._options_message:
            extras.append(f"options: {self._options_message}")
        if self._selection_warnings:
            extras.append("warnings: " + " | ".join(self._selection_warnings))
        self.diagnostics_label.setText("\n".join(extras))

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
        self._refresh_diagnostics_label()
        # Prefer showing applied runtime diagnostics prominently after apply.
        applied = format_diagnostics_text(diagnostics)
        extras: list[str] = [applied]
        if self._options_message:
            extras.append(f"options: {self._options_message}")
        if self._selection_warnings:
            extras.append("warnings: " + " | ".join(self._selection_warnings))
        self.diagnostics_label.setText("\n".join(extras))

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
