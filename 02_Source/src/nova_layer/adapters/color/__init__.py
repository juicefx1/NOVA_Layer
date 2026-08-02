"""Color / display transform adapters (preview pipeline)."""

from nova_layer.adapters.color.display_transform import (
    ColorTransformError,
    DisplayTransform,
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
    create_display_transform,
    linear_to_srgb,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.ocio_adapter import (
    OcioConfigOptions,
    OcioDisplayTransform,
    is_ocio_available,
    load_ocio_config_options,
    resolve_ocio_config_path,
)
from nova_layer.adapters.color.ocio_color_space_converter import OcioColorSpaceConverter
from nova_layer.adapters.color.settings import (
    ColorSettings,
    ResolvedColorSettings,
    resolve_color_settings,
    to_runtime_color_settings,
)
from nova_layer.adapters.color.source_frame_encoder import (
    WorkingSourceEncoder,
    quantize_float_rgb_to_uint8,
    resolve_source_output_color_space,
)

__all__ = [
    "ColorSettings",
    "ColorTransformError",
    "DisplayTransform",
    "DisplayTransformDiagnostics",
    "DisplayTransformProtocol",
    "ExposureTransform",
    "LegacyDisplayTransform",
    "OcioConfigOptions",
    "OcioColorSpaceConverter",
    "OcioDisplayTransform",
    "ResolvedColorSettings",
    "ViewerDisplayTransform",
    "WorkingSourceEncoder",
    "create_display_transform",
    "is_ocio_available",
    "linear_to_srgb",
    "load_ocio_config_options",
    "quantize_float_rgb_to_uint8",
    "resolve_color_settings",
    "resolve_ocio_config_path",
    "resolve_source_output_color_space",
    "to_runtime_color_settings",
]
