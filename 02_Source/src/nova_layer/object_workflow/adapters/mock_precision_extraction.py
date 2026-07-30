from __future__ import annotations

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
    RgbaImage,
)

PROVIDER_ID = "mock.precision_extraction"
PROVIDER_VERSION = "1.0.0"


class MockPrecisionExtractionEngine:
    def extract(
        self, request: PrecisionExtractionRequest
    ) -> PrecisionExtractionSuccess | PrecisionExtractionError:
        mask = request.mask
        if mask.width != request.source_width or mask.height != request.source_height:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message="mask dimensions must match source dimensions",
                retryable=False,
            )
        expected_rgb = request.source_width * request.source_height * 3
        if len(request.source_rgb) != expected_rgb:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message="source_rgb length mismatch",
                retryable=False,
            )
        try:
            image = build_deterministic_rgba(
                width=request.source_width,
                height=request.source_height,
                source_rgb=request.source_rgb,
                mask=mask,
            )
        except ValueError as exc:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message=str(exc),
                retryable=False,
            )
        return PrecisionExtractionSuccess(
            request_id=request.request_id,
            image=image,
            confidence=0.95,
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
        )


def build_deterministic_rgba(
    *,
    width: int,
    height: int,
    source_rgb: bytes,
    mask: BinaryMask,
) -> RgbaImage:
    pixels = bytearray(width * height * 4)
    for index in range(width * height):
        rgb_i = index * 3
        rgba_i = index * 4
        pixels[rgba_i] = source_rgb[rgb_i]
        pixels[rgba_i + 1] = source_rgb[rgb_i + 1]
        pixels[rgba_i + 2] = source_rgb[rgb_i + 2]
        pixels[rgba_i + 3] = mask.data[index]
    return RgbaImage(width=width, height=height, data=bytes(pixels))
