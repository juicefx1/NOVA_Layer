from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray


class ExposureTransform:
    """Apply photographic exposure stops as a linear gain: ``image * 2**stops``.

    Returns a new float32 RGB array; never mutates the input.
    """

    def __init__(self, stops: float = 0.0) -> None:
        self._stops = float(stops)

    @property
    def stops(self) -> float:
        return self._stops

    def apply(
        self,
        image: NDArray[np.floating],
    ) -> NDArray[np.float32]:
        array = np.asarray(image)
        if array.ndim != 3:
            raise ValueError(f"Exposure transform expects HxWxC, got shape {array.shape}")
        if array.shape[2] < 3:
            raise ValueError(
                f"Exposure transform requires at least 3 channels, got {array.shape[2]}"
            )
        if not np.issubdtype(array.dtype, np.floating):
            raise TypeError(f"Exposure transform expects floating image, got {array.dtype}")

        rgb = np.array(array[:, :, :3], dtype=np.float32, copy=True)
        rgb = np.where(np.isnan(rgb), np.float32(0.0), rgb)
        rgb = np.where(rgb == -np.inf, np.float32(0.0), rgb)
        # Leave +Inf as +Inf so Legacy transfer still quantizes to 255.
        if self._stops != 0.0:
            rgb = rgb * np.float32(2.0**self._stops)
        return rgb
