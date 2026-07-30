from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from nova_layer.object_workflow.domain.binary_mask import BinaryMask


@dataclass(frozen=True, slots=True)
class RgbaImage:
    """Engine-neutral RGBA8 image. Do not expose NumPy/OpenCV/PIL/Qt types here."""

    width: int
    height: int
    data: bytes  # length == width * height * 4, RGBA order

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be > 0")
        expected = self.width * self.height * 4
        if len(self.data) != expected:
            raise ValueError(f"RGBA data length must be {expected}, got {len(self.data)}")


@dataclass(frozen=True, slots=True)
class PrecisionExtractionRequest:
    request_id: str
    source_width: int
    source_height: int
    source_rgb: bytes  # length == width * height * 3
    mask: BinaryMask
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PrecisionExtractionSuccess:
    request_id: str
    image: RgbaImage
    confidence: float
    provider_id: str
    provider_version: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PrecisionExtractionError:
    request_id: str
    error_code: str
    message: str
    retryable: bool


class PrecisionExtractionEngine(Protocol):
    def extract(
        self, request: PrecisionExtractionRequest
    ) -> PrecisionExtractionSuccess | PrecisionExtractionError: ...
