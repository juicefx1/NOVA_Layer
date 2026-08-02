from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


class ColorTransformError(RuntimeError):
    """Raised when a color/display transform cannot be constructed or applied."""


@dataclass(frozen=True)
class DisplayTransformDiagnostics:
    backend: Literal["ocio", "legacy"]
    ocio_available: bool
    config_path: str | None
    config_source: str | None
    display: str | None
    view: str | None
    input_color_space: str
    exposure: float
    fallback_reason: str | None = None


@runtime_checkable
class DisplayTransformProtocol(Protocol):
    def apply(
        self,
        image: NDArray[np.floating],
    ) -> NDArray[np.uint8]:
        ...


def linear_to_srgb(linear: NDArray[np.floating[Any]]) -> NDArray[np.float32]:
    """IEC 61966-2-1 Approximate Linear → sRGB transfer (preview).

    Matches the historical ImageSequenceReader EXR preview formula for finite values.
    """
    value = np.asarray(linear, dtype=np.float32)
    # Keep finite linear values bit-compatible. NaN → 0; -Inf clipped to 0; +Inf
    # survives clip then maps to 1.0 in the final uint8 quantize step.
    value = np.where(np.isnan(value), 0.0, value)
    value = np.clip(value, 0.0, None)
    a = 0.055
    return np.where(
        value <= 0.0031308,
        12.92 * value,
        (1.0 + a) * np.power(value, 1.0 / 2.4) - a,
    ).astype(np.float32)


class LegacyDisplayTransform:
    """Scene-linear float RGB(A) → preview uint8 sRGB RGB (non-OCIO fallback)."""

    def __init__(
        self,
        *,
        diagnostics: DisplayTransformDiagnostics | None = None,
    ) -> None:
        if diagnostics is not None:
            self.diagnostics = diagnostics
            return
        try:
            import PyOpenColorIO as _ocio  # noqa: F401
            ocio_available = True
        except ImportError:
            ocio_available = False
        self.diagnostics = DisplayTransformDiagnostics(
            backend="legacy",
            ocio_available=ocio_available,
            config_path=None,
            config_source=None,
            display=None,
            view=None,
            input_color_space="scene_linear",
            exposure=0.0,
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

        rgb = np.asarray(array[:, :, :3], dtype=np.float32)
        srgb = linear_to_srgb(rgb)
        return np.asarray(np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5, dtype=np.uint8)


# Stage-1 / ImageSequenceReader default alias.
DisplayTransform = LegacyDisplayTransform


def create_display_transform(
    *,
    prefer_ocio: bool = True,
    config_path: Path | None = None,
    input_color_space: str = "scene_linear",
    display: str | None = None,
    view: str | None = None,
    exposure: float = 0.0,
) -> DisplayTransformProtocol:
    """Select OCIO or legacy display transform.

    When prefer_ocio is True and OCIO + config succeed, returns OcioDisplayTransform.
    Otherwise returns LegacyDisplayTransform with diagnostics.fallback_reason set.
    """
    from nova_layer.adapters.color.ocio_adapter import (
        OcioDisplayTransform,
        is_ocio_available,
    )

    ocio_available = is_ocio_available()

    def _legacy(reason: str) -> LegacyDisplayTransform:
        return LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=ocio_available,
                config_path=str(config_path) if config_path is not None else None,
                config_source=None,
                display=display,
                view=view,
                input_color_space=input_color_space,
                exposure=exposure,
                fallback_reason=reason,
            )
        )

    if not prefer_ocio:
        return _legacy("prefer_ocio=False")

    if not ocio_available:
        return _legacy("PyOpenColorIO not installed")

    try:
        return OcioDisplayTransform(
            config_path=config_path,
            input_color_space=input_color_space,
            display=display,
            view=view,
            exposure=exposure,
        )
    except ColorTransformError as exc:
        return _legacy(str(exc))
