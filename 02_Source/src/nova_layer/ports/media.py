from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    fingerprint: str
    frame_count: int
    frame_rate: float
    width: int
    height: int
    time_base: str
    pixel_format: str | None


class MediaReader(Protocol):
    def inspect(self, path: Path) -> MediaInfo: ...

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]: ...
