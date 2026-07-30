from __future__ import annotations

from dataclasses import dataclass


class BinaryMaskError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BinaryMask:
    """Engine-neutral binary mask. Do not expose NumPy/OpenCV/PIL/Qt types here."""

    width: int
    height: int
    channels: int
    bit_depth: int
    data: bytes

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise BinaryMaskError("width must be > 0")
        if self.height <= 0:
            raise BinaryMaskError("height must be > 0")
        if self.channels != 1:
            raise BinaryMaskError("channels must be 1")
        if self.bit_depth != 8:
            raise BinaryMaskError("bit_depth must be 8")
        expected = self.width * self.height
        if len(self.data) != expected:
            raise BinaryMaskError(f"data length must be {expected}, got {len(self.data)}")
        # translate removes allowed values; any remainder means invalid pixels.
        # This stays semantic-identical to scanning each byte for {0, 255}.
        if self.data.translate(None, b"\x00\xff"):
            raise BinaryMaskError("every byte must be either 0 or 255")

    @classmethod
    def from_pixels(cls, width: int, height: int, pixels: bytes) -> BinaryMask:
        return cls(width=width, height=height, channels=1, bit_depth=8, data=pixels)
