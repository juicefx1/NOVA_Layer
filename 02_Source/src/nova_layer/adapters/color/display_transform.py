from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.color.exposure_transform import ExposureTransform


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
    """Exposed float RGB(A) → preview uint8 sRGB RGB (non-OCIO fallback).

    Expects exposure (if any) to already be applied. Does not apply stops gain.
    """

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


class ViewerDisplayTransform:
    """Compose exposure then display: float → ExposureTransform → Display → uint8."""

    def __init__(
        self,
        *,
        exposure: ExposureTransform,
        display_transform: DisplayTransformProtocol,
    ) -> None:
        self._exposure = exposure
        self._display_transform = display_transform

    @property
    def exposure(self) -> ExposureTransform:
        return self._exposure

    @property
    def display_transform(self) -> DisplayTransformProtocol:
        return self._display_transform

    @property
    def diagnostics(self) -> DisplayTransformDiagnostics:
        inner = getattr(self._display_transform, "diagnostics", None)
        if isinstance(inner, DisplayTransformDiagnostics):
            return replace(inner, exposure=float(self._exposure.stops))
        return DisplayTransformDiagnostics(
            backend="legacy",
            ocio_available=False,
            config_path=None,
            config_source=None,
            display=None,
            view=None,
            input_color_space="scene_linear",
            exposure=float(self._exposure.stops),
            fallback_reason=None,
        )

    def apply(self, image: NDArray[np.floating[Any]]) -> NDArray[np.uint8]:
        exposed = self._exposure.apply(image)
        return self._display_transform.apply(exposed)


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
    """Select OCIO or legacy display transform, wrapped with ExposureTransform.

    Returns a :class:`ViewerDisplayTransform` that applies exposure stops then the
    chosen display transform. Callers that only need ``apply`` / ``diagnostics`` are
    unchanged. When prefer_ocio is True and OCIO + config succeed, the inner
    transform is OcioDisplayTransform; otherwise LegacyDisplayTransform with
    ``diagnostics.fallback_reason`` set.
    """
    from nova_layer.adapters.color.ocio_adapter import (
        OcioDisplayTransform,
        is_ocio_available,
    )

    ocio_available = is_ocio_available()
    stops = float(exposure)

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
                exposure=0.0,
                fallback_reason=reason,
            )
        )

    def _wrap(inner: DisplayTransformProtocol) -> ViewerDisplayTransform:
        return ViewerDisplayTransform(
            exposure=ExposureTransform(stops),
            display_transform=inner,
        )

    if not prefer_ocio:
        return _wrap(_legacy("prefer_ocio=False"))

    if not ocio_available:
        return _wrap(_legacy("PyOpenColorIO not installed"))

    try:
        # Exposure is applied by ViewerDisplayTransform; inner keep stops=0.
        inner = OcioDisplayTransform(
            config_path=config_path,
            input_color_space=input_color_space,
            display=display,
            view=view,
            exposure=0.0,
        )
        return _wrap(inner)
    except ColorTransformError as exc:
        return _wrap(_legacy(str(exc)))
