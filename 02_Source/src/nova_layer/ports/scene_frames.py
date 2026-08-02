from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class SceneFrame:
    """Scene-linear float RGB frame (EXR OIIO decode product)."""

    path: Path
    frame_number: int
    pixels: NDArray[np.float32]
    width: int
    height: int
    channels: int = 3
    pixel_format: str = "float32_rgb"


class SceneFrameSource(Protocol):
    """Additive source for scene-linear frames. Does not replace MediaReader."""

    def read_scene_frame(
        self,
        path: Path,
        frame_number: int,
    ) -> SceneFrame: ...
