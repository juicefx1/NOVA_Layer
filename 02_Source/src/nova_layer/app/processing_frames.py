"""Processing frame color policies (viewer look vs stable model input).

SOURCE is a stable uint8 RGB processing raster — not scene-linear float itself.
SCENE is EXR-only float32. MODEL normalization stays inside capability adapters.
"""

from __future__ import annotations

from enum import Enum


class ProcessingColorPolicy(str, Enum):
    """How pixels are prepared for viewer vs capability / processing paths.

    PREVIEW:
        Viewer-identical uint8 RGB. Applies the active session Exposure /
        Display / View (OCIO or Legacy composition). Uses preview + raw caches.

    SOURCE:
        Viewer-look-independent stable uint8 RGB for SAM / skeleton / similar.
        - PNG / JPEG / TIFF / BMP / video: source raster uint8 RGB (no viewer
          transform).
        - EXR: scene float → fixed Legacy linear→sRGB (exposure 0); never uses
          workspace/project Display, View, or Exposure. Result is **not**
          scene-linear — it is a reproducible uint8 processing raster.

    SCENE:
        EXR raw float32 :class:`~nova_layer.ports.scene_frames.SceneFrame` via
        the raw cache. Non-EXR raises MediaReadError. Not passed directly into
        uint8-only capabilities in Phase 8C-2.
    """

    PREVIEW = "preview"
    SOURCE = "source"
    SCENE = "scene"


# Fixed source-bake identity (source cache key component).
SOURCE_TRANSFORM_VERSION = "source_legacy_srgb_v1"
