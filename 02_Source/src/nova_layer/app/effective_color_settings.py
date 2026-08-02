from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova_layer.adapters.color.display_transform import (
    DisplayTransformProtocol,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
    create_display_transform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.settings import (
    ColorSettings,
    ResolvedColorSettings,
    resolve_color_settings,
    to_runtime_color_settings,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager

COLOR_SETTINGS_PREFERENCE_KEY = "smart_layer_color_settings"


@dataclass(frozen=True, slots=True)
class EffectiveColorApplication:
    """Result of resolving project+workspace color settings and applying a transform."""

    resolved: ResolvedColorSettings
    transform: DisplayTransformProtocol


def preference_dict_to_color_settings(raw: Any) -> ColorSettings | None:
    """Map WorkspaceManager ``smart_layer_color_settings`` dict → ColorSettings."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None

    config_path = str(raw.get("config_path") or "").strip()
    backend = raw.get("backend")
    input_cs = raw.get("input_color_space")
    display = raw.get("display")
    view = raw.get("view")
    exposure = raw.get("exposure", None)

    return ColorSettings(
        backend=str(backend) if backend is not None else None,
        config_kind="absolute" if config_path else None,
        config_value=config_path or None,
        input_color_space=str(input_cs) if input_cs is not None else None,
        display=str(display) if display is not None else None,
        view=str(view) if view is not None else None,
        exposure=float(exposure) if exposure is not None else None,
        pin_display_view=False,
    )


def load_workspace_color_settings(workspace: WorkspaceManager) -> ColorSettings | None:
    raw = workspace.get_preference(COLOR_SETTINGS_PREFERENCE_KEY, None)
    return preference_dict_to_color_settings(raw)


def build_transform_from_resolved(
    resolved: ResolvedColorSettings,
) -> DisplayTransformProtocol:
    exposure = ExposureTransform(float(resolved.exposure))
    if resolved.backend != "ocio":
        # Intentional legacy: no fallback_reason (unlike prefer_ocio=False factory path).
        return ViewerDisplayTransform(
            exposure=exposure,
            display_transform=LegacyDisplayTransform(),
        )
    return create_display_transform(
        prefer_ocio=True,
        config_path=resolved.config_path,
        input_color_space=resolved.input_color_space,
        display=resolved.display,
        view=resolved.view,
        exposure=float(resolved.exposure),
    )


def _project_root_for(
    controller: ProjectController,
    project_root: Path | None,
) -> Path | None:
    if project_root is not None:
        return Path(project_root)
    if controller.package_path is not None:
        return Path(controller.package_path)
    return None


def resolve_effective_color_settings(
    controller: ProjectController,
    workspace: WorkspaceManager,
    *,
    project_root: Path | None = None,
) -> ResolvedColorSettings:
    """Resolve project + workspace color settings without applying a transform."""
    project = controller.project
    project_settings = to_runtime_color_settings(
        None if project is None else project.color_settings
    )
    workspace_settings = load_workspace_color_settings(workspace)
    return resolve_color_settings(
        project=project_settings,
        workspace=workspace_settings,
        session=None,
        project_root=_project_root_for(controller, project_root),
    )


def apply_effective_color_settings(
    controller: ProjectController,
    workspace: WorkspaceManager,
    *,
    project_root: Path | None = None,
) -> EffectiveColorApplication:
    """Resolve project + workspace color settings and apply DisplayTransform.

    Does not mutate Project / WorkspaceManager preference schemas. Falls back via
    ``create_display_transform`` when OCIO cannot be constructed.
    """
    resolved = resolve_effective_color_settings(
        controller,
        workspace,
        project_root=project_root,
    )
    transform = build_transform_from_resolved(resolved)
    controller.set_display_transform(transform)
    return EffectiveColorApplication(resolved=resolved, transform=transform)


def to_package_relative_config_value(
    selected: Path,
    project_root: Path,
) -> str:
    """Return a package-relative posix path, or raise ValueError if outside root."""
    resolved = selected.expanduser().resolve()
    root = project_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Config must be inside the project package:\n{root}"
        ) from exc


def format_resolved_provenance(resolved: ResolvedColorSettings) -> str:
    lines = [
        "resolve:",
        f"  backend={resolved.backend} (source={resolved.source_backend})",
        f"  config_path={resolved.config_path or '—'} "
        f"(source={resolved.source_config}, config_source={resolved.config_source or '—'})",
        f"  input_color_space={resolved.input_color_space} "
        f"(source={resolved.source_input_color_space})",
        f"  display={resolved.display or '—'} (source={resolved.source_display})",
        f"  view={resolved.view or '—'} (source={resolved.source_view})",
        f"  exposure={resolved.exposure:g} (source={resolved.source_exposure})",
    ]
    if resolved.warnings:
        lines.append("resolve warnings:")
        lines.extend(f"  - {item}" for item in resolved.warnings)
    return "\n".join(lines)
