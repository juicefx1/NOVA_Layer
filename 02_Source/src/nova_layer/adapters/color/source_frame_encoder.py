"""SOURCE v2 encoder: WorkingScene float → encoded sRGB texture uint8.

Phase 10C-3A contract:
- Float RGB WorkingSceneFrame pixels in.
- OCIO ColorSpaceTransform(working → output) only — no Display/View/Exposure.
- After transform: clip [0,1], then *255 + 0.5 → uint8.
- Input arrays are never mutated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.color.display_transform import ColorTransformError
from nova_layer.adapters.color.ocio_color_space_converter import OcioColorSpaceConverter

try:
    import PyOpenColorIO as OCIO
except ImportError:
    OCIO = None

# Known encoded-sRGB texture candidates (checked against config color spaces).
TEXTURE_SRGB_CANDIDATES: tuple[str, ...] = (
    "sRGB",
    "Utility - sRGB - Texture",
    "sRGB - Texture",
)

TEXTURE_ROLE_NAMES: tuple[str, ...] = (
    "texture_paint",
    "texture",
)


def quantize_float_rgb_to_uint8(
    image: NDArray[np.floating[Any]],
) -> NDArray[np.uint8]:
    """Clip [0,1] then round via ``*255 + 0.5`` → uint8.

    Does not mutate ``image``. Negatives and values > 1 are clipped after the
    (caller-provided) float transform.
    """
    rgb = np.asarray(image)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ColorTransformError(
            f"quantize_float_rgb_to_uint8 expects HxWx3+ RGB, got shape {rgb.shape}"
        )
    clipped = np.clip(rgb[..., :3].astype(np.float64, copy=False), 0.0, 1.0)
    return (clipped * 255.0 + 0.5).astype(np.uint8)


def resolve_source_output_color_space(
    *,
    config_path: Path | None,
    explicit: str | None = None,
) -> tuple[str, str]:
    """Resolve encoded sRGB texture output color space.

    Priority:
    1. Explicit ``output_color_space`` (must exist in config)
    2. Config role ``texture_paint`` / ``texture``
    3. Known candidate names present in the config
    4. Hard error

    Returns ``(color_space_name, resolution_reason)``.
    """
    from nova_layer.adapters.color.ocio_adapter import resolve_ocio_config_path

    if OCIO is None:
        raise ColorTransformError(
            "PyOpenColorIO is not installed; install nova-layer[color] to resolve "
            "SOURCE v2 output color space"
        )

    explicit_text = str(explicit or "").strip() or None
    resolved_path, _config_source = resolve_ocio_config_path(config_path)
    try:
        config = OCIO.Config.CreateFromFile(str(resolved_path))
    except Exception as exc:  # noqa: BLE001
        raise ColorTransformError(
            f"Failed to load OCIO config for SOURCE output resolve: "
            f"{resolved_path} ({exc})"
        ) from exc

    def _has_cs(name: str) -> bool:
        try:
            return config.getColorSpace(name) is not None
        except Exception:  # noqa: BLE001
            return False

    if explicit_text is not None:
        if not _has_cs(explicit_text):
            raise ColorTransformError(
                f"SOURCE v2 output color space not found in OCIO config: "
                f"{explicit_text!r}"
            )
        return explicit_text, "explicit"

    # Roles first (texture_paint preferred). Config.getRole(name) → CS name.
    for role_name in TEXTURE_ROLE_NAMES:
        cs_name: str | None = None
        try:
            cs_name = str(config.getRole(role_name) or "").strip() or None
        except Exception:  # noqa: BLE001
            cs_name = None
        if cs_name and _has_cs(cs_name):
            return cs_name, f"role:{role_name}"

    for candidate in TEXTURE_SRGB_CANDIDATES:
        if _has_cs(candidate):
            return candidate, f"candidate:{candidate}"

    raise ColorTransformError(
        "SOURCE v2 could not resolve an encoded sRGB texture output color space "
        "(no explicit name, texture role, or known candidate found in OCIO config)"
    )


class WorkingSourceEncoder:
    """Encode WorkingScene float RGB to SOURCE uint8 via ColorSpaceTransform.

    Uses :class:`OcioColorSpaceConverter` for the float transform, then
    :func:`quantize_float_rgb_to_uint8`. Never applies DisplayView or Exposure.
    """

    def __init__(
        self,
        *,
        config_path: Path | None,
        working_color_space: str,
        output_color_space: str,
        color_space_converter_cls: type[OcioColorSpaceConverter] | None = None,
    ) -> None:
        working = str(working_color_space or "").strip()
        output = str(output_color_space or "").strip()
        if not working or not output:
            raise ColorTransformError(
                "WorkingSourceEncoder requires non-empty working and output "
                "color spaces"
            )

        converter_cls = color_space_converter_cls or OcioColorSpaceConverter
        # Converter maps source→working; for SOURCE v2 we map working→output.
        self._converter = converter_cls(
            config_path=config_path,
            source_color_space=working,
            working_color_space=output,
        )
        self._working = working
        self._output = output
        self._config_path = self._converter.config_path
        self._config_source = self._converter.config_source

    @property
    def working_color_space(self) -> str:
        return self._working

    @property
    def output_color_space(self) -> str:
        return self._output

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def config_source(self) -> str:
        return self._config_source

    def apply(
        self,
        image: NDArray[np.floating[Any]],
    ) -> NDArray[np.uint8]:
        """Transform working float → output float, then clip/quantize to uint8."""
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ColorTransformError(
                f"WorkingSourceEncoder expects HxWx3+ RGB, got shape {arr.shape}"
            )
        # Defensive copy guard: converter must not mutate; we verify via identity
        # of input buffer after apply in tests. Pass through converter as float.
        float_out = self._converter.apply(arr)
        return quantize_float_rgb_to_uint8(float_out)
