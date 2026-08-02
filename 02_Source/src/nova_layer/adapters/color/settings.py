from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

BackendName = Literal["legacy", "ocio"]
ConfigKind = Literal["env", "package_relative", "absolute", "named"]
Provenance = Literal[
    "project",
    "workspace",
    "session",
    "environment",
    "default",
    "none",
]


@dataclass(frozen=True, slots=True)
class ColorSettings:
    backend: str | None = None
    config_kind: str | None = None
    config_value: str | None = None
    input_color_space: str | None = None
    display: str | None = None
    view: str | None = None
    exposure: float | None = None
    pin_display_view: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedColorSettings:
    backend: str
    config_path: Path | None
    config_source: str | None
    input_color_space: str
    display: str | None
    view: str | None
    exposure: float

    source_backend: str
    source_config: str
    source_input_color_space: str
    source_display: str
    source_view: str
    source_exposure: str

    warnings: tuple[str, ...]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text else None


def _normalize_settings(settings: ColorSettings | None) -> ColorSettings | None:
    if settings is None:
        return None
    return replace(
        settings,
        backend=_blank_to_none(settings.backend),
        config_kind=_blank_to_none(settings.config_kind),
        config_value=_blank_to_none(settings.config_value),
        input_color_space=_blank_to_none(settings.input_color_space),
        display=_blank_to_none(settings.display),
        view=_blank_to_none(settings.view),
    )


def _parse_backend(raw: str | None) -> BackendName | None:
    if raw is None:
        return None
    text = raw.strip().casefold()
    if text in {"legacy", "ocio"}:
        return text  # type: ignore[return-value]
    return None


def _is_finite_exposure(value: float | None) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _is_within_project_root(path: Path, project_root: Path) -> bool:
    try:
        path.resolve().relative_to(project_root.resolve())
        return True
    except ValueError:
        return False


def _resolve_config_candidate(
    *,
    settings: ColorSettings,
    layer: Literal["project", "workspace"],
    project_root: Path | None,
    environ: Mapping[str, str],
    warnings: list[str],
) -> tuple[Path | None, str | None, Provenance | None]:
    """Resolve one layer's config. Returns (path, config_source, provenance) or Nones."""
    kind_raw = settings.config_kind
    if kind_raw is None and settings.config_value is None:
        return None, None, None

    kind = (kind_raw or "absolute").strip().casefold()
    value = settings.config_value

    if kind == "env":
        env_name = value or "OCIO"
        env_value = _blank_to_none(environ.get(env_name))
        if env_value is None:
            warnings.append(
                f"{layer} config kind=env: environment variable {env_name!r} is not set"
            )
            return None, None, None
        path = Path(env_value).expanduser().resolve()
        if not path.is_file():
            warnings.append(
                f"{layer} config kind=env: {env_name}={path} is not an existing file"
            )
            return None, None, None
        return path, f"env:{env_name}", "environment"

    if kind == "package_relative":
        if project_root is None:
            warnings.append(
                f"{layer} config kind=package_relative requires project_root"
            )
            return None, None, None
        if value is None:
            warnings.append(f"{layer} config kind=package_relative missing config_value")
            return None, None, None
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            warnings.append(
                f"{layer} config kind=package_relative rejects unsafe path {value!r}"
            )
            return None, None, None
        root = project_root.expanduser().resolve()
        path = (root / relative).resolve()
        if not _is_within_project_root(path, root):
            warnings.append(
                f"{layer} config kind=package_relative escaped project_root: {value!r}"
            )
            return None, None, None
        if not path.is_file():
            warnings.append(
                f"{layer} config kind=package_relative file not found: {path}"
            )
            return None, None, None
        return path, "package_relative", layer

    if kind == "absolute":
        if value is None:
            warnings.append(f"{layer} config kind=absolute missing config_value")
            return None, None, None
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            warnings.append(f"{layer} config kind=absolute file not found: {path}")
            return None, None, None
        return path, "absolute", layer

    if kind == "named":
        warnings.append(
            f"{layer} config kind=named is not supported yet "
            f"(value={value!r}); leaving config unresolved"
        )
        return None, None, None

    warnings.append(f"{layer} config kind={kind_raw!r} is unrecognized")
    return None, None, None


def resolve_color_settings(
    *,
    project: ColorSettings | None,
    workspace: ColorSettings | None,
    session: ColorSettings | None = None,
    project_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedColorSettings:
    """Compose project / workspace / session color settings into one resolved view.

    Pure function: no OCIO import, no Qt, no filesystem writes. File existence is
    checked only for path-based config candidates.
    """
    warnings: list[str] = []
    env = environ if environ is not None else os.environ

    project_n = _normalize_settings(project)
    workspace_n = _normalize_settings(workspace)
    session_n = _normalize_settings(session)

    # --- backend: project → workspace → legacy ---
    backend: str = "legacy"
    source_backend: Provenance = "default"
    for layer_name, layer in (("project", project_n), ("workspace", workspace_n)):
        if layer is None or layer.backend is None:
            continue
        parsed = _parse_backend(layer.backend)
        if parsed is None:
            warnings.append(
                f"{layer_name} backend {layer.backend!r} is invalid; ignoring"
            )
            continue
        backend = parsed
        source_backend = layer_name  # type: ignore[assignment]
        break

    # --- config: project → workspace → $OCIO → None ---
    config_path: Path | None = None
    config_source: str | None = None
    source_config: Provenance = "none"
    for layer_name, layer in (("project", project_n), ("workspace", workspace_n)):
        if layer is None:
            continue
        if layer.config_kind is None and layer.config_value is None:
            continue
        path, source, provenance = _resolve_config_candidate(
            settings=layer,
            layer=layer_name,  # type: ignore[arg-type]
            project_root=project_root,
            environ=env,
            warnings=warnings,
        )
        if path is not None and provenance is not None:
            config_path = path
            config_source = source
            source_config = provenance
            break
        # named returns path=None without falling through to next kind on same layer;
        # continue to next layer / $OCIO.

    if config_path is None:
        ocio_env = _blank_to_none(env.get("OCIO"))
        if ocio_env is not None:
            path = Path(ocio_env).expanduser().resolve()
            if path.is_file():
                config_path = path
                config_source = "env:OCIO"
                source_config = "environment"
            else:
                warnings.append(
                    f"environment OCIO={path} is not an existing file"
                )
        # else remains none

    # --- input_color_space: project → workspace → scene_linear ---
    input_color_space = "scene_linear"
    source_input: Provenance = "default"
    for layer_name, layer in (("project", project_n), ("workspace", workspace_n)):
        if layer is None or layer.input_color_space is None:
            continue
        input_color_space = layer.input_color_space
        source_input = layer_name  # type: ignore[assignment]
        break

    # --- display / view ---
    pin = bool(project_n.pin_display_view) if project_n is not None else False
    if pin:
        display_order: tuple[tuple[str, ColorSettings | None], ...] = (
            ("project", project_n),
            ("workspace", workspace_n),
        )
    else:
        display_order = (
            ("workspace", workspace_n),
            ("project", project_n),
        )

    display: str | None = None
    source_display: Provenance = "none"
    for layer_name, layer in display_order:
        if layer is None or layer.display is None:
            continue
        display = layer.display
        source_display = layer_name  # type: ignore[assignment]
        break

    view: str | None = None
    source_view: Provenance = "none"
    for layer_name, layer in display_order:
        if layer is None or layer.view is None:
            continue
        view = layer.view
        source_view = layer_name  # type: ignore[assignment]
        break

    # --- exposure: session → workspace → project → 0.0 ---
    exposure = 0.0
    source_exposure: Provenance = "default"
    for layer_name, layer in (
        ("session", session_n),
        ("workspace", workspace_n),
        ("project", project_n),
    ):
        if layer is None or layer.exposure is None:
            continue
        if not _is_finite_exposure(layer.exposure):
            warnings.append(
                f"{layer_name} exposure {layer.exposure!r} is not finite; ignoring"
            )
            continue
        exposure = float(layer.exposure)
        source_exposure = layer_name  # type: ignore[assignment]
        break

    return ResolvedColorSettings(
        backend=backend,
        config_path=config_path,
        config_source=config_source,
        input_color_space=input_color_space,
        display=display,
        view=view,
        exposure=exposure,
        source_backend=source_backend,
        source_config=source_config,
        source_input_color_space=source_input,
        source_display=source_display,
        source_view=source_view,
        source_exposure=source_exposure,
        warnings=tuple(warnings),
    )


def to_runtime_color_settings(value: object | None) -> ColorSettings | None:
    """Convert ProjectColorSettings (or compatible object) to runtime ColorSettings.

    Pure mapping — does not resolve paths or touch persistence/UI.
    """
    if value is None:
        return None
    backend = getattr(value, "backend", None)
    config_kind = getattr(value, "config_kind", None)
    config_value = getattr(value, "config_value", None)
    input_color_space = getattr(value, "input_color_space", None)
    display = getattr(value, "display", None)
    view = getattr(value, "view", None)
    exposure = getattr(value, "exposure", None)
    pin_display_view = bool(getattr(value, "pin_display_view", False))
    return ColorSettings(
        backend=backend,
        config_kind=config_kind,
        config_value=config_value,
        input_color_space=input_color_space,
        display=display,
        view=view,
        exposure=exposure,
        pin_display_view=pin_display_view,
    )
