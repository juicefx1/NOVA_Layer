from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
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
from nova_layer.app.effective_color_settings import (
    COLOR_SETTINGS_PREFERENCE_KEY,
    EffectiveColorApplication,
    apply_effective_color_settings,
    format_resolved_provenance,
    resolve_effective_color_settings,
    to_package_relative_config_value,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import ProjectColorSettings
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

_BACKEND_LEGACY = "Legacy"
_BACKEND_OCIO = "OCIO"

_SCOPE_WORKSPACE = "Workspace Defaults"
_SCOPE_PROJECT = "Project Settings"

_KIND_ENV = "Environment"
_KIND_PACKAGE = "Project Relative"
_KIND_ABSOLUTE = "Absolute Path"
_KIND_NAMED = "Named"

_KIND_TO_SCHEMA: dict[str, str] = {
    _KIND_ENV: "env",
    _KIND_PACKAGE: "package_relative",
    _KIND_ABSOLUTE: "absolute",
    _KIND_NAMED: "named",
}
_SCHEMA_TO_KIND: dict[str, str] = {v: k for k, v in _KIND_TO_SCHEMA.items()}

BackendPreference = Literal["legacy", "ocio"]
SettingsScope = Literal["workspace", "project"]


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
    """Build a transform from workspace preference only (no project merge).

    Prefer :func:`apply_effective_color_settings` for runtime application.
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
    """Apply effective (project + workspace) color settings without UI warnings."""
    return apply_effective_color_settings(controller, workspace).transform


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
    """Color Settings for Workspace defaults and optional Project overrides."""

    def __init__(
        self,
        controller: ProjectController,
        parent: QWidget | None = None,
        *,
        workspace: WorkspaceManager | None = None,
        apply_effective: Callable[[], EffectiveColorApplication] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._workspace = workspace or WorkspaceManager.shared()
        self._apply_effective = apply_effective
        self._ocio_options: OcioConfigOptions | None = None
        self._options_message: str | None = None
        self._selection_warnings: list[str] = []
        self._pending_input: str | None = None
        self._pending_display: str | None = None
        self._pending_view: str | None = None
        self.setObjectName("colorSettingsDialog")
        self.setWindowTitle("Color Settings — NOVA Layer")
        self.resize(560, 560)

        root = QVBoxLayout(self)

        scope_row = QHBoxLayout()
        scope_label = QLabel("Settings Scope")
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("colorSettingsScopeCombo")
        self.scope_combo.addItem(_SCOPE_WORKSPACE, "workspace")
        self.scope_combo.addItem(_SCOPE_PROJECT, "project")
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_row.addWidget(scope_label)
        scope_row.addWidget(self.scope_combo, 1)
        root.addLayout(scope_row)

        self.scope_status_label = QLabel()
        self.scope_status_label.setObjectName("colorSettingsScopeStatus")
        self.scope_status_label.setWordWrap(True)
        root.addWidget(self.scope_status_label)

        form = QFormLayout()

        self.backend_combo = QComboBox()
        self.backend_combo.setObjectName("colorBackendCombo")
        self.backend_combo.addItems([_BACKEND_LEGACY, _BACKEND_OCIO])
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        form.addRow("Backend", self.backend_combo)

        self.config_kind_combo = QComboBox()
        self.config_kind_combo.setObjectName("ocioConfigKindCombo")
        self.config_kind_combo.addItems(
            [_KIND_ENV, _KIND_PACKAGE, _KIND_ABSOLUTE, _KIND_NAMED]
        )
        self.config_kind_combo.currentTextChanged.connect(self._on_config_kind_changed)
        self._config_kind_row_label = QLabel("Config Source")
        form.addRow(self._config_kind_row_label, self.config_kind_combo)

        config_row = QHBoxLayout()
        self.config_path_edit = QLineEdit()
        self.config_path_edit.setObjectName("ocioConfigPathEdit")
        self.config_path_edit.setPlaceholderText(
            "Path to .ocio config (or leave empty for $OCIO)"
        )
        self.config_path_edit.editingFinished.connect(self._reload_ocio_options)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setObjectName("ocioConfigBrowseButton")
        self.browse_button.clicked.connect(self._browse_config)
        config_row.addWidget(self.config_path_edit, 1)
        config_row.addWidget(self.browse_button)
        self._config_value_row_label = QLabel("OCIO Config Path")
        form.addRow(self._config_value_row_label, config_row)

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

        self.pin_display_view_checkbox = QCheckBox("Pin Display and View to Project")
        self.pin_display_view_checkbox.setObjectName("colorPinDisplayViewCheckbox")
        form.addRow("", self.pin_display_view_checkbox)

        root.addLayout(form)

        self.exposure_hint_label = QLabel(
            "Project exposure is used only when no workspace/session exposure "
            "overrides it."
        )
        self.exposure_hint_label.setObjectName("colorProjectExposureHint")
        self.exposure_hint_label.setWordWrap(True)
        root.addWidget(self.exposure_hint_label)

        self.use_workspace_defaults_button = QPushButton("Use Workspace Defaults")
        self.use_workspace_defaults_button.setObjectName("colorUseWorkspaceDefaultsButton")
        self.use_workspace_defaults_button.clicked.connect(self._use_workspace_defaults)
        root.addWidget(self.use_workspace_defaults_button)

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

        has_project = self.controller.project is not None
        scope_model = self.scope_combo.model()
        if isinstance(scope_model, QStandardItemModel):
            project_item = scope_model.item(1)
            if project_item is not None:
                project_item.setEnabled(has_project)
        if not has_project:
            self.scope_combo.setCurrentIndex(0)
            self.scope_status_label.setText(
                "No project open — only Workspace Defaults can be edited."
            )

        self._load_ui_for_scope(self._current_scope())
        self._sync_scope_chrome()
        self._sync_field_enabled(self.backend_combo.currentText())

    def _current_scope(self) -> SettingsScope:
        data = self.scope_combo.currentData()
        return "project" if data == "project" else "workspace"

    def _on_scope_changed(self, _index: int = 0) -> None:
        self._load_ui_for_scope(self._current_scope())
        self._sync_scope_chrome()
        self._sync_field_enabled(self.backend_combo.currentText())

    def _sync_scope_chrome(self) -> None:
        project_mode = self._current_scope() == "project"
        self.config_kind_combo.setVisible(project_mode)
        self._config_kind_row_label.setVisible(project_mode)
        self.pin_display_view_checkbox.setVisible(project_mode)
        self.exposure_hint_label.setVisible(project_mode)
        self.use_workspace_defaults_button.setVisible(project_mode)
        if project_mode:
            self._config_value_row_label.setText("Config Value")
            self._on_config_kind_changed(self.config_kind_combo.currentText())
        else:
            self._config_value_row_label.setText("OCIO Config Path")
            self.config_path_edit.setPlaceholderText(
                "Path to .ocio config (or leave empty for $OCIO)"
            )
            self.browse_button.setEnabled(self.backend_combo.currentText() == _BACKEND_OCIO)

    def _load_ui(self) -> None:
        """Compatibility: load the active scope (defaults to workspace)."""
        self._load_ui_for_scope(self._current_scope())

    def _load_ui_for_scope(self, scope: SettingsScope) -> None:
        if scope == "workspace":
            preference = load_color_settings_preference(self._workspace)
            if preference is not None:
                self._populate_from_preference(preference)
            else:
                self._populate_from_diagnostics(
                    self.controller.display_transform_diagnostics
                )
            if self.controller.project is not None:
                self.scope_status_label.setText("Editing workspace defaults.")
            self.config_kind_combo.setCurrentText(_KIND_ABSOLUTE)
            self.pin_display_view_checkbox.setChecked(False)
        else:
            project = self.controller.project
            override = None if project is None else project.color_settings
            if override is None:
                preference = load_color_settings_preference(self._workspace)
                if preference is not None:
                    self._populate_from_preference(preference)
                else:
                    self._populate_from_diagnostics(
                        self.controller.display_transform_diagnostics
                    )
                self.config_kind_combo.setCurrentText(_KIND_ABSOLUTE)
                self.pin_display_view_checkbox.setChecked(False)
                self.scope_status_label.setText("No project override")
            else:
                self._populate_from_project(override)
                self.scope_status_label.setText("Editing project color settings.")
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

    def _populate_from_project(self, settings: ProjectColorSettings) -> None:
        backend = settings.backend or "legacy"
        self.backend_combo.setCurrentText(
            _BACKEND_OCIO if backend == "ocio" else _BACKEND_LEGACY
        )
        kind = settings.config_kind or "absolute"
        self.config_kind_combo.setCurrentText(
            _SCHEMA_TO_KIND.get(kind, _KIND_ABSOLUTE)
        )
        value = settings.config_value or ""
        if kind == "env" and not value:
            value = "OCIO"
        self.config_path_edit.setText(value)
        self._pending_input = settings.input_color_space or "scene_linear"
        self._pending_display = settings.display or ""
        self._pending_view = settings.view or ""
        self.exposure_spin.setValue(
            float(settings.exposure) if settings.exposure is not None else 0.0
        )
        self.pin_display_view_checkbox.setChecked(bool(settings.pin_display_view))

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

    def _project_settings_from_form(self) -> ProjectColorSettings:
        backend: BackendPreference = (
            "ocio" if self.backend_combo.currentText() == _BACKEND_OCIO else "legacy"
        )
        kind_label = self.config_kind_combo.currentText()
        kind = _KIND_TO_SCHEMA.get(kind_label, "absolute")
        value = self.config_path_edit.text().strip()
        if kind == "env" and not value:
            value = "OCIO"
        exposure = _parse_exposure(self.exposure_spin.value())
        return ProjectColorSettings(
            backend=backend,
            config_kind=kind,  # type: ignore[arg-type]
            config_value=value or None,
            input_color_space=_combo_text(self.input_color_space_combo) or None,
            display=_combo_text(self.display_combo) or None,
            view=_combo_text(self.view_combo) or None,
            exposure=exposure,
            pin_display_view=self.pin_display_view_checkbox.isChecked(),
        )

    def _on_backend_changed(self, backend: str) -> None:
        self._sync_field_enabled(backend)
        if backend == _BACKEND_OCIO:
            self._reload_ocio_options()
        self._refresh_diagnostics_label()

    def _on_config_kind_changed(self, kind_label: str) -> None:
        if self._current_scope() != "project":
            return
        ocio = self.backend_combo.currentText() == _BACKEND_OCIO
        if kind_label == _KIND_ENV:
            self.config_path_edit.setPlaceholderText("Environment variable name (default: OCIO)")
            if not self.config_path_edit.text().strip():
                self.config_path_edit.setText("OCIO")
            self.browse_button.setEnabled(False)
        elif kind_label == _KIND_NAMED:
            self.config_path_edit.setPlaceholderText("Named config identifier")
            self.browse_button.setEnabled(False)
        elif kind_label == _KIND_PACKAGE:
            self.config_path_edit.setPlaceholderText(
                "Path relative to the project .nova package"
            )
            self.browse_button.setEnabled(ocio)
        else:
            self.config_path_edit.setPlaceholderText("Absolute path to .ocio config")
            self.browse_button.setEnabled(ocio)
        if ocio:
            self._reload_ocio_options()

    def _sync_field_enabled(self, backend: str) -> None:
        ocio = backend == _BACKEND_OCIO
        project_mode = self._current_scope() == "project"
        for widget in (
            self.config_path_edit,
            self.input_color_space_combo,
            self.display_combo,
            self.view_combo,
            self.exposure_spin,
            self.config_kind_combo,
        ):
            widget.setEnabled(ocio)
        # Pin applies regardless of backend; only meaningful in project scope.
        self.pin_display_view_checkbox.setEnabled(project_mode)
        if project_mode and ocio:
            self._on_config_kind_changed(self.config_kind_combo.currentText())
        elif project_mode:
            self.browse_button.setEnabled(False)
        else:
            self.browse_button.setEnabled(ocio)

    def _browse_config(self) -> None:
        if self._current_scope() == "project":
            self._browse_project_config()
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select OCIO Config",
            self.config_path_edit.text().strip() or "",
            "OCIO Config (*.ocio);;All Files (*)",
        )
        if path:
            self.config_path_edit.setText(path)
            self._reload_ocio_options()

    def _browse_project_config(self) -> None:
        kind = self.config_kind_combo.currentText()
        if kind in {_KIND_ENV, _KIND_NAMED}:
            return

        start = self.config_path_edit.text().strip()
        root = self.controller.package_path
        if kind == _KIND_PACKAGE and root is not None:
            if start:
                candidate = (root / start).resolve()
                start_dir = str(candidate.parent if candidate.exists() else root)
            else:
                start_dir = str(root)
        else:
            start_dir = start or (str(root) if root is not None else "")

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select OCIO Config",
            start_dir,
            "OCIO Config (*.ocio);;All Files (*)",
        )
        if not path:
            return

        selected = Path(path)
        if kind == _KIND_PACKAGE:
            if root is None:
                QMessageBox.warning(
                    self,
                    "Color Settings",
                    "No project package is open; cannot store a project-relative path.",
                )
                return
            try:
                relative = to_package_relative_config_value(selected, root)
            except ValueError as exc:
                QMessageBox.warning(self, "Color Settings", str(exc))
                return
            self.config_path_edit.setText(relative)
        else:
            self.config_path_edit.setText(str(selected.expanduser().resolve()))
        self._reload_ocio_options()

    def _config_path_for_options(self) -> Path | None:
        """Resolve the path used to load OCIO option lists for the form."""
        raw = self.config_path_edit.text().strip()
        if self._current_scope() != "project":
            return config_path_from_stored(raw)

        kind = _KIND_TO_SCHEMA.get(self.config_kind_combo.currentText(), "absolute")
        root = self.controller.package_path
        if kind == "absolute":
            return config_path_from_stored(raw)
        if kind == "package_relative" and root is not None and raw:
            return (root / raw).resolve()
        if kind == "env":
            return None  # load_ocio_config_options uses $OCIO when path is None
        return None

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
            self._apply_options_to_combos(
                None,
                preferred_input=preferred_input,
                preferred_display=preferred_display,
                preferred_view=preferred_view,
            )
            self._pending_input = None
            self._pending_display = None
            self._pending_view = None
            self._refresh_diagnostics_label()
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

        config_path = self._config_path_for_options()
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
        try:
            resolved = resolve_effective_color_settings(
                self.controller,
                self._workspace,
                project_root=self.controller.package_path,
            )
            extras.append(format_resolved_provenance(resolved))
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            extras.append(f"resolve error: {exc}")
        if self._options_message:
            extras.append(f"options: {self._options_message}")
        if self._selection_warnings:
            extras.append("warnings: " + " | ".join(self._selection_warnings))
        self.diagnostics_label.setText("\n".join(extras))

    def _run_effective_apply(self) -> EffectiveColorApplication:
        if self._apply_effective is not None:
            return self._apply_effective()
        return apply_effective_color_settings(
            self.controller,
            self._workspace,
            project_root=self.controller.package_path,
        )

    def _update_diagnostics_after_apply(
        self,
        application: EffectiveColorApplication,
    ) -> None:
        transform = application.transform
        diagnostics = getattr(transform, "diagnostics", None)
        applied = format_diagnostics_text(diagnostics)
        extras: list[str] = [applied, format_resolved_provenance(application.resolved)]
        if self._options_message:
            extras.append(f"options: {self._options_message}")
        if self._selection_warnings:
            extras.append("warnings: " + " | ".join(self._selection_warnings))
        self.diagnostics_label.setText("\n".join(extras))

    def _on_accept(self) -> None:
        if self.apply_settings():
            self.accept()

    def apply_settings(self) -> bool:
        """Persist the active scope, then apply effective project+workspace merge."""
        if self._current_scope() == "project":
            return self._apply_project_settings()
        return self._apply_workspace_settings()

    def _apply_workspace_settings(self) -> bool:
        preference = self._preference_from_form()
        try:
            save_color_settings_preference(self._workspace, preference)
            application = self._run_effective_apply()
        except Exception as exc:  # noqa: BLE001 - surface to UI without crashing
            QMessageBox.warning(
                self,
                "Color Settings",
                f"Could not apply color settings.\n\n{exc}",
            )
            return False

        self._update_diagnostics_after_apply(application)
        self._warn_ocio_fallback(preference.backend == "ocio", application)
        return True

    def _apply_project_settings(self) -> bool:
        project = self.controller.project
        if project is None:
            QMessageBox.warning(
                self,
                "Color Settings",
                "No project is open; cannot save project color settings.",
            )
            return False

        previous = (
            None
            if project.color_settings is None
            else project.color_settings.model_copy(deep=True)
        )
        project.color_settings = self._project_settings_from_form()
        if not self.controller.save_current_project():
            project.color_settings = previous
            QMessageBox.warning(
                self,
                "Color Settings",
                "Could not save project color settings to the .nova package.",
            )
            return False

        try:
            application = self._run_effective_apply()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Color Settings",
                f"Project settings were saved, but transform apply failed.\n\n{exc}",
            )
            return False

        self.scope_status_label.setText("Editing project color settings.")
        self._update_diagnostics_after_apply(application)
        self._warn_ocio_fallback(
            project.color_settings is not None
            and project.color_settings.backend == "ocio",
            application,
        )
        return True

    def _use_workspace_defaults(self) -> None:
        project = self.controller.project
        if project is None:
            return
        previous = (
            None
            if project.color_settings is None
            else project.color_settings.model_copy(deep=True)
        )
        project.color_settings = None
        if not self.controller.save_current_project():
            project.color_settings = previous
            QMessageBox.warning(
                self,
                "Color Settings",
                "Could not clear project color settings in the .nova package.",
            )
            return
        try:
            application = self._run_effective_apply()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Color Settings",
                f"Project override was cleared, but transform apply failed.\n\n{exc}",
            )
            return
        self._load_ui_for_scope("project")
        self._sync_scope_chrome()
        self._sync_field_enabled(self.backend_combo.currentText())
        self._update_diagnostics_after_apply(application)

    def _warn_ocio_fallback(
        self,
        wanted_ocio: bool,
        application: EffectiveColorApplication,
    ) -> None:
        diagnostics = getattr(application.transform, "diagnostics", None)
        if wanted_ocio and diagnostics is not None and diagnostics.fallback_reason:
            QMessageBox.warning(
                self,
                "Color Settings",
                "OCIO could not be used; falling back to Legacy preview.\n\n"
                f"{diagnostics.fallback_reason}",
            )
