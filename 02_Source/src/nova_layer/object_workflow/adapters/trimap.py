from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

TrimapLabel = Literal["background", "unknown", "foreground"]

# Stored as uint8: 0 = definite background, 128 = unknown, 255 = definite foreground
TRIMAP_BACKGROUND = 0
TRIMAP_UNKNOWN = 128
TRIMAP_FOREGROUND = 255


@dataclass(frozen=True, slots=True)
class Trimap:
    width: int
    height: int
    data: bytes  # length == width * height, values in {0, 128, 255}
    algorithm: str
    unknown_radius: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("trimap dimensions must be > 0")
        expected = self.width * self.height
        if len(self.data) != expected:
            raise ValueError(f"trimap data length must be {expected}, got {len(self.data)}")
        if self.unknown_radius < 0:
            raise ValueError("unknown_radius must be >= 0")

    def as_array(self) -> NDArray[np.uint8]:
        return np.frombuffer(self.data, dtype=np.uint8).reshape((self.height, self.width)).copy()


def build_trimap_from_binary_mask(
    *,
    width: int,
    height: int,
    binary_foreground: NDArray[np.bool_],
    unknown_radius: int,
) -> Trimap:
    """Derive a trimap by eroding/dilating the confirmed binary foreground.

    - outside dilated region → definite background
    - inside eroded region → definite foreground
    - remaining band → unknown
    """
    if binary_foreground.shape != (height, width):
        raise ValueError("binary_foreground shape must match width/height")
    if unknown_radius < 0:
        raise ValueError("unknown_radius must be >= 0")
    if unknown_radius > 64:
        raise ValueError("unknown_radius must be <= 64")

    foreground = binary_foreground.astype(bool)
    if unknown_radius == 0:
        labels = np.where(foreground, TRIMAP_FOREGROUND, TRIMAP_BACKGROUND).astype(np.uint8)
        return Trimap(
            width=width,
            height=height,
            data=labels.tobytes(),
            algorithm="erode_dilate_band_v1",
            unknown_radius=0,
        )

    definite_fg = _morphological_erode(foreground, unknown_radius)
    dilated = _morphological_dilate(foreground, unknown_radius)
    labels = np.full((height, width), TRIMAP_BACKGROUND, dtype=np.uint8)
    labels[dilated] = TRIMAP_UNKNOWN
    labels[definite_fg] = TRIMAP_FOREGROUND
    return Trimap(
        width=width,
        height=height,
        data=labels.tobytes(),
        algorithm="erode_dilate_band_v1",
        unknown_radius=unknown_radius,
    )


def trimap_region_counts(trimap: Trimap) -> dict[str, int]:
    arr = np.frombuffer(trimap.data, dtype=np.uint8)
    return {
        "background": int(np.count_nonzero(arr == TRIMAP_BACKGROUND)),
        "unknown": int(np.count_nonzero(arr == TRIMAP_UNKNOWN)),
        "foreground": int(np.count_nonzero(arr == TRIMAP_FOREGROUND)),
    }


def morphological_dilate(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    if radius <= 0:
        return binary
    image = binary.astype(np.uint8)
    padded = np.pad(image, ((0, 0), (radius, radius)), mode="edge")
    height, width = image.shape
    window = 2 * radius + 1
    horizontal = np.empty_like(image)
    for x in range(width):
        horizontal[:, x] = np.max(padded[:, x : x + window], axis=1)
    padded_v = np.pad(horizontal, ((radius, radius), (0, 0)), mode="edge")
    out = np.empty_like(image)
    for y in range(height):
        out[y, :] = np.max(padded_v[y : y + window, :], axis=0)
    return out.astype(bool)


def morphological_erode(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    if radius <= 0:
        return binary
    image = binary.astype(np.uint8)
    padded = np.pad(image, ((0, 0), (radius, radius)), mode="edge")
    height, width = image.shape
    window = 2 * radius + 1
    horizontal = np.empty_like(image)
    for x in range(width):
        horizontal[:, x] = np.min(padded[:, x : x + window], axis=1)
    padded_v = np.pad(horizontal, ((radius, radius), (0, 0)), mode="edge")
    out = np.empty_like(image)
    for y in range(height):
        out[y, :] = np.min(padded_v[y : y + window, :], axis=0)
    return out.astype(bool)


# Keep private aliases used inside this module.
_morphological_dilate = morphological_dilate
_morphological_erode = morphological_erode
