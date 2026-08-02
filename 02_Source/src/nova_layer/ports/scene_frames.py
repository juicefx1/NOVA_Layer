"""Scene-linear / file-native float frame contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class SceneFrame:
    """File-native floating RGB frame with no display/view/exposure transform.

    ``pixels`` are the EXR (OIIO) float channel values after numeric sanitize
    only. This does **not** guarantee an OCIO ``scene_linear`` role, specific
    RGB primaries, or a project ``input_color_space`` conversion.

    ``color_space`` is an interpretation *tag* (file metadata or user), not a
    conversion product. Missing tags use ``color_space=None`` with
    ``color_space_source="unspecified"``.
    """

    path: Path
    frame_number: int
    pixels: NDArray[np.float32]
    width: int
    height: int
    channels: int = 3
    pixel_format: str = "float32_rgb"
    color_space: str | None = None
    color_space_source: str = "unspecified"


@dataclass(frozen=True, slots=True)
class WorkingSceneFrame:
    """Canonical working-space floating RGB (Phase 10C+).

    ``pixels`` are float32 RGB in ``working_color_space`` after a source→working
    conversion. Display / view / exposure are **not** applied.

    Phase 10C-1 defines the type only — no production construction path yet.
    Callers must not mutate ``pixels`` in place after construction; caches
    copy-on-put / copy-on-get.
    """

    path: Path
    frame_number: int
    pixels: NDArray[np.float32]
    width: int
    height: int
    source_color_space: str
    working_color_space: str
    ocio_config_identity: str
    converter_version: str
    channels: int = 3
    pixel_format: str = "float32_rgb"


class SceneFrameSource(Protocol):
    """Additive source for file-native scene frames. Does not replace MediaReader."""

    def read_scene_frame(
        self,
        path: Path,
        frame_number: int,
    ) -> SceneFrame: ...
