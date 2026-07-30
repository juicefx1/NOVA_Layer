from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def compose_rgba(frame: NDArray[np.uint8], mask: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Preview extraction requires an RGB uint8 frame.")
    if mask.dtype != np.uint8 or mask.shape != frame.shape[:2]:
        raise ValueError("Preview mask must be uint8 and match the frame dimensions.")
    rgba = np.empty((*frame.shape[:2], 4), dtype=np.uint8)
    rgba[:, :, :3] = frame
    rgba[:, :, 3] = mask
    return rgba
