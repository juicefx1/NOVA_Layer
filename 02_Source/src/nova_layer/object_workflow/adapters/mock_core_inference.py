from __future__ import annotations

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import (
    BoundingBox,
    IntentSignal,
    NegativePoint,
    PositivePoint,
)
from nova_layer.object_workflow.domain.validation import (
    first_bounding_box,
    parse_intent_signals,
)
from nova_layer.object_workflow.ports.core_inference import (
    CandidateResult,
    CoreInferenceError,
    CoreInferenceRequest,
)

PROVIDER_ID = "mock.core_inference"
PROVIDER_VERSION = "1.2.0"


class MockCoreInferenceEngine:
    def generate_hypothesis(
        self, request: CoreInferenceRequest
    ) -> CandidateResult | CoreInferenceError:
        if request.media_type not in {"image/png", "image/jpeg"}:
            return CoreInferenceError(
                request_id=request.request_id,
                error_code="UNSUPPORTED_MEDIA_TYPE",
                message=f"unsupported media type: {request.media_type}",
                retryable=False,
            )
        try:
            signals = parse_intent_signals(request.intent_instruction.payload.signals)
        except Exception as exc:
            code = getattr(exc, "code", "INVALID_REQUEST")
            return CoreInferenceError(
                request_id=request.request_id,
                error_code=str(code),
                message=str(exc),
                retryable=False,
            )

        try:
            masks, confidences = build_deterministic_candidates(
                width=request.source_width,
                height=request.source_height,
                signals=signals,
            )
        except ValueError as exc:
            return CoreInferenceError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message=str(exc),
                retryable=False,
            )

        return CandidateResult(
            request_id=request.request_id,
            masks=masks,
            confidences=confidences,
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            provider_metadata={
                "strategy": "ordered_mixed_prompts",
                "signal_order": "bbox_seed_then_points_in_payload_order",
                "candidate_count": len(masks),
                "candidate_variants": ("primary", "inset", "expanded"),
            },
        )


def build_deterministic_mask(*, width: int, height: int, signals: list[IntentSignal]) -> BinaryMask:
    """Primary deterministic Mock mask (candidate 0)."""
    return build_deterministic_candidates(width=width, height=height, signals=signals)[0][0]


def build_deterministic_candidates(
    *, width: int, height: int, signals: list[IntentSignal]
) -> tuple[tuple[BinaryMask, ...], tuple[float, ...]]:
    """Return three deterministic candidate masks.

    Candidate 0 (primary): bbox seed + points in payload order.
    Candidate 1 (inset): primary eroded by one pixel.
    Candidate 2 (expanded): primary dilated by one pixel.
    """
    primary_pixels = _compose_mask_pixels(width, height, signals)
    inset_pixels = _erode(primary_pixels, width, height)
    expanded_pixels = _dilate(primary_pixels, width, height)
    masks = (
        BinaryMask.from_pixels(width, height, bytes(primary_pixels)),
        BinaryMask.from_pixels(width, height, bytes(inset_pixels)),
        BinaryMask.from_pixels(width, height, bytes(expanded_pixels)),
    )
    has_box = first_bounding_box(signals) is not None
    has_negative = any(isinstance(item, NegativePoint) for item in signals)
    base = 0.75 if has_box else (0.68 if has_negative else 0.70)
    confidences = (base, max(0.0, base - 0.05), max(0.0, base - 0.10))
    return masks, confidences


def _compose_mask_pixels(width: int, height: int, signals: list[IntentSignal]) -> bytearray:
    pixels = bytearray(width * height)
    bbox = first_bounding_box(signals)
    if bbox is not None:
        _fill_region(pixels, width, height, bbox, value=255)

    for signal in signals:
        if isinstance(signal, PositivePoint):
            _fill_point_square(pixels, width, height, signal.x, signal.y, value=255)
        elif isinstance(signal, NegativePoint):
            _fill_point_square(pixels, width, height, signal.x, signal.y, value=0)
        elif isinstance(signal, BoundingBox):
            continue
    return pixels


def _erode(pixels: bytearray, width: int, height: int) -> bytearray:
    out = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            if pixels[y * width + x] == 0:
                continue
            keep = True
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        keep = False
                        break
                    if pixels[ny * width + nx] == 0:
                        keep = False
                        break
                if not keep:
                    break
            if keep:
                out[y * width + x] = 255
    return out


def _dilate(pixels: bytearray, width: int, height: int) -> bytearray:
    out = bytearray(pixels)
    for y in range(height):
        for x in range(width):
            if pixels[y * width + x] == 0:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        out[ny * width + nx] = 255
    return out


def _fill_region(
    pixels: bytearray,
    width: int,
    height: int,
    bbox: BoundingBox,
    *,
    value: int,
) -> None:
    x0 = int(round(bbox.x * width))
    y0 = int(round(bbox.y * height))
    x1 = int(round((bbox.x + bbox.width) * width))
    y1 = int(round((bbox.y + bbox.height) * height))
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    if x1 <= x0:
        x1 = min(width, x0 + 1)
    if y1 <= y0:
        y1 = min(height, y0 + 1)
    for y in range(y0, y1):
        row = y * width
        for x in range(x0, x1):
            pixels[row + x] = value


def _fill_point_square(
    pixels: bytearray,
    width: int,
    height: int,
    x_norm: float,
    y_norm: float,
    *,
    value: int,
) -> None:
    side = max(1, round(min(width, height) * 0.20))
    cx = int(round(x_norm * (width - 1))) if width > 1 else 0
    cy = int(round(y_norm * (height - 1))) if height > 1 else 0
    x0 = cx - side // 2
    y0 = cy - side // 2
    x1 = x0 + side
    y1 = y0 + side
    x0c = max(0, x0)
    y0c = max(0, y0)
    x1c = min(width, x1)
    y1c = min(height, y1)
    for y in range(y0c, y1c):
        row = y * width
        for x in range(x0c, x1c):
            pixels[row + x] = value
