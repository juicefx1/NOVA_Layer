from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.color.display_transform import (
    ColorTransformError,
    DisplayTransformDiagnostics,
)

try:
    import PyOpenColorIO as OCIO
except ImportError:
    OCIO = None


def is_ocio_available() -> bool:
    return OCIO is not None


def resolve_ocio_config_path(
    config_path: Path | None = None,
) -> tuple[Path, str]:
    """Resolve OCIO config file.

    Order: explicit config_path → $OCIO env var → error.
    """
    if config_path is not None:
        path = config_path.expanduser().resolve()
        if not path.is_file():
            raise ColorTransformError(f"OCIO config file not found: {path}")
        return path, "explicit"

    env_value = os.environ.get("OCIO")
    if env_value:
        path = Path(env_value).expanduser().resolve()
        if not path.is_file():
            raise ColorTransformError(
                f"OCIO environment variable points to missing config: {path}"
            )
        return path, "env"

    raise ColorTransformError(
        "No OCIO config available: pass config_path or set the OCIO environment variable"
    )


@dataclass(frozen=True)
class OcioConfigOptions:
    """Read-only enumeration of choosable OCIO config entries for Color Settings UI."""

    color_spaces: tuple[str, ...]
    displays: tuple[str, ...]
    views_by_display: dict[str, tuple[str, ...]]
    default_display: str | None
    default_view: str | None
    config_path: str
    config_source: str

    def views_for(self, display: str | None) -> tuple[str, ...]:
        if not display:
            return ()
        return self.views_by_display.get(display, ())


def _color_space_names(config: Any) -> tuple[str, ...]:
    names: list[str] = []
    try:
        names.extend(str(item) for item in config.getColorSpaceNames())
    except Exception:  # noqa: BLE001
        count = int(config.getNumColorSpaces())
        for index in range(count):
            names.append(str(config.getColorSpaceNameByIndex(index)))

    role_names: list[str] = []
    try:
        role_names.extend(str(item) for item in config.getRoleNames())
    except Exception:  # noqa: BLE001
        try:
            role_count = int(config.getNumRoles())
            for index in range(role_count):
                role_names.append(str(config.getRoleName(index)))
        except Exception:  # noqa: BLE001
            role_names = []

    for role in role_names:
        if role not in names:
            names.append(role)
    return tuple(names)


def load_ocio_config_options(
    config_path: Path | None = None,
) -> OcioConfigOptions:
    """Load display/view/color-space options from an OCIO config.

    Uses :func:`resolve_ocio_config_path` (explicit path → ``$OCIO``).
    """
    if OCIO is None:
        raise ColorTransformError(
            "PyOpenColorIO is not installed; install nova-layer[color] to use OCIO"
        )

    resolved_path, config_source = resolve_ocio_config_path(config_path)
    try:
        config = OCIO.Config.CreateFromFile(str(resolved_path))
    except Exception as exc:  # noqa: BLE001
        raise ColorTransformError(
            f"Failed to load OCIO config: {resolved_path} ({exc})"
        ) from exc

    displays = tuple(str(item) for item in config.getDisplays())
    views_by_display = {
        display: tuple(str(item) for item in config.getViews(display))
        for display in displays
    }
    default_display = str(config.getDefaultDisplay() or "") or None
    default_view: str | None = None
    if default_display:
        default_view = str(config.getDefaultView(default_display) or "") or None

    color_spaces = _color_space_names(config)
    if not color_spaces:
        raise ColorTransformError(
            f"OCIO config has no color spaces: {resolved_path}"
        )
    if not displays:
        raise ColorTransformError(f"OCIO config has no displays: {resolved_path}")

    return OcioConfigOptions(
        color_spaces=color_spaces,
        displays=displays,
        views_by_display=views_by_display,
        default_display=default_display,
        default_view=default_view,
        config_path=str(resolved_path),
        config_source=config_source,
    )


def _sanitize_rgb(rgb: NDArray[np.float32]) -> NDArray[np.float32]:
    value = np.asarray(rgb, dtype=np.float32)
    value = np.where(np.isnan(value), 0.0, value)
    value = np.clip(value, 0.0, None)
    # OpenColorIO rejects non-finite input; map leftover +Inf before the processor.
    return np.where(np.isfinite(value), value, 0.0).astype(np.float32, copy=False)


class OcioDisplayTransform:
    """Scene-linear float RGB(A) → preview uint8 via OpenColorIO Display/View."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        input_color_space: str = "scene_linear",
        display: str | None = None,
        view: str | None = None,
        exposure: float = 0.0,
    ) -> None:
        if OCIO is None:
            raise ColorTransformError(
                "PyOpenColorIO is not installed; install nova-layer[color] to use OCIO"
            )

        resolved_path, config_source = resolve_ocio_config_path(config_path)
        try:
            config = OCIO.Config.CreateFromFile(str(resolved_path))
        except Exception as exc:  # noqa: BLE001 - OCIO raises various types
            raise ColorTransformError(
                f"Failed to load OCIO config: {resolved_path} ({exc})"
            ) from exc

        if config.getColorSpace(input_color_space) is None:
            raise ColorTransformError(
                f"OCIO input color space not found in config: {input_color_space!r}"
            )

        resolved_display = display if display is not None else config.getDefaultDisplay()
        if not resolved_display:
            raise ColorTransformError("OCIO config has no default display")

        displays = list(config.getDisplays())
        if resolved_display not in displays:
            raise ColorTransformError(
                f"OCIO display not found in config: {resolved_display!r}"
            )

        resolved_view = (
            view if view is not None else config.getDefaultView(resolved_display)
        )
        if not resolved_view:
            raise ColorTransformError(
                f"OCIO config has no default view for display {resolved_display!r}"
            )

        views = list(config.getViews(resolved_display))
        if resolved_view not in views:
            raise ColorTransformError(
                f"OCIO view {resolved_view!r} not found for display {resolved_display!r}"
            )

        transform = OCIO.DisplayViewTransform()
        transform.setSrc(input_color_space)
        transform.setDisplay(resolved_display)
        transform.setView(resolved_view)

        try:
            processor = config.getProcessor(transform)
            cpu_processor = processor.getDefaultCPUProcessor()
        except Exception as exc:  # noqa: BLE001
            raise ColorTransformError(
                f"Failed to build OCIO display processor "
                f"({input_color_space!r} → {resolved_display}/{resolved_view}): {exc}"
            ) from exc

        self._cpu_processor = cpu_processor
        self._exposure = float(exposure)
        self.diagnostics = DisplayTransformDiagnostics(
            backend="ocio",
            ocio_available=True,
            config_path=str(resolved_path),
            config_source=config_source,
            display=resolved_display,
            view=resolved_view,
            input_color_space=input_color_space,
            exposure=self._exposure,
            fallback_reason=None,
        )

    def apply(self, image: NDArray[np.floating[Any]]) -> NDArray[np.uint8]:
        array = np.asarray(image)
        if array.ndim != 3:
            raise ValueError(f"Display transform expects HxWxC, got shape {array.shape}")
        if array.shape[2] < 3:
            raise ValueError(
                f"Display transform requires at least 3 channels, got {array.shape[2]}"
            )
        if not np.issubdtype(array.dtype, np.floating):
            raise TypeError(f"Display transform expects floating image, got {array.dtype}")

        rgb = _sanitize_rgb(np.asarray(array[:, :, :3], dtype=np.float32))
        if self._exposure != 0.0:
            rgb = rgb * np.float32(2.0**self._exposure)

        working = np.ascontiguousarray(rgb, dtype=np.float32)
        try:
            self._cpu_processor.applyRGB(working)
        except Exception as exc:  # noqa: BLE001
            raise ColorTransformError(f"OCIO display transform failed: {exc}") from exc

        return np.asarray(np.clip(working, 0.0, 1.0) * 255.0 + 0.5, dtype=np.uint8)
