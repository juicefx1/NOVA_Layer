"""Float→float OCIO color-space conversion (Phase 10C-2).

Separate from :class:`~nova_layer.adapters.color.ocio_adapter.OcioDisplayTransform`,
which clips to 0–1 and quantizes to uint8 for PREVIEW.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.color.display_transform import ColorTransformError

try:
    import PyOpenColorIO as OCIO
except ImportError:
    OCIO = None


def _sanitize_scene_rgb(rgb: NDArray[np.floating[Any]]) -> NDArray[np.float32]:
    """Match SceneFrame sanitize: NaN/-Inf→0, +Inf→f32 max; preserve negatives."""
    value = np.array(rgb, dtype=np.float32, copy=True)
    value = np.where(np.isnan(value), np.float32(0.0), value)
    value = np.where(value == -np.inf, np.float32(0.0), value)
    finite_max = np.finfo(np.float32).max
    value = np.where(value == np.inf, np.float32(finite_max), value)
    return value


class OcioColorSpaceConverter:
    """Convert float RGB(A) from ``source_color_space`` → ``working_color_space``.

    Contract:
    - Output float32 RGB (HxWx3); no uint8 path; no 0–1 clip.
    - Negatives and values > 1 are preserved (after NaN/Inf sanitize).
    - Input arrays are not mutated.
    - ``source == working`` → contiguous float32 copy (no OCIO round-trip required).
    """

    def __init__(
        self,
        *,
        config_path: Path | None,
        source_color_space: str,
        working_color_space: str,
    ) -> None:
        from nova_layer.adapters.color.ocio_adapter import resolve_ocio_config_path

        if OCIO is None:
            raise ColorTransformError(
                "PyOpenColorIO is not installed; install nova-layer[color] to use "
                "working-space conversion"
            )

        source = str(source_color_space or "").strip()
        working = str(working_color_space or "").strip()
        if not source or not working:
            raise ColorTransformError(
                "OcioColorSpaceConverter requires non-empty source and working "
                "color spaces"
            )

        resolved_path, config_source = resolve_ocio_config_path(config_path)
        try:
            config = OCIO.Config.CreateFromFile(str(resolved_path))
        except Exception as exc:  # noqa: BLE001
            raise ColorTransformError(
                f"Failed to load OCIO config: {resolved_path} ({exc})"
            ) from exc

        if config.getColorSpace(source) is None:
            raise ColorTransformError(
                f"OCIO source color space not found in config: {source!r}"
            )
        if config.getColorSpace(working) is None:
            raise ColorTransformError(
                f"OCIO working color space not found in config: {working!r}"
            )

        self._source = source
        self._working = working
        self._config_path = str(resolved_path)
        self._config_source = config_source
        self._cpu_processor: Any | None = None

        if source != working:
            transform = OCIO.ColorSpaceTransform()
            transform.setSrc(source)
            transform.setDst(working)
            try:
                processor = config.getProcessor(transform)
                self._cpu_processor = processor.getDefaultCPUProcessor()
            except Exception as exc:  # noqa: BLE001
                raise ColorTransformError(
                    f"Failed to build OCIO color-space processor "
                    f"({source!r} → {working!r}): {exc}"
                ) from exc

    @property
    def source_color_space(self) -> str:
        return self._source

    @property
    def working_color_space(self) -> str:
        return self._working

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def config_source(self) -> str:
        return self._config_source

    def apply(
        self,
        image: NDArray[np.floating[Any]],
    ) -> NDArray[np.float32]:
        array = np.asarray(image)
        if array.ndim != 3:
            raise ValueError(
                f"Color-space converter expects HxWxC, got shape {array.shape}"
            )
        if array.shape[2] < 3:
            raise ValueError(
                f"Color-space converter requires at least 3 channels, "
                f"got {array.shape[2]}"
            )
        if not np.issubdtype(array.dtype, np.floating):
            raise TypeError(
                f"Color-space converter expects floating image, got {array.dtype}"
            )

        rgb = _sanitize_scene_rgb(np.asarray(array[:, :, :3]))
        if self._cpu_processor is None:
            return np.ascontiguousarray(rgb, dtype=np.float32)

        working = np.ascontiguousarray(rgb, dtype=np.float32)
        try:
            self._cpu_processor.applyRGB(working)
        except Exception as exc:  # noqa: BLE001
            raise ColorTransformError(
                f"OCIO color-space conversion failed "
                f"({self._source!r} → {self._working!r}): {exc}"
            ) from exc
        return working
