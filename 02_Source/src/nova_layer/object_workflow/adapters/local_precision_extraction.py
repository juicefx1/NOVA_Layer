from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
    RgbaImage,
)

PROVIDER_ID = "local.precision_extraction"
PROVIDER_VERSION = "1.1.0"
CancelChecker = Callable[[], bool]

_SAFE_EXPAND = 32
_SAFE_RADIUS = 64.0


class LocalPrecisionExtractionEngine:
    """Deterministic local RGBA extraction with optional alpha edge refinement.

    RGB channels are copied unchanged from the source (unless premultiply is on).
    Alpha is derived from the confirmed BinaryMask after expand/contract,
    morphological cleanup, distance-based feathering, and optional edge blur.
    """

    def __init__(
        self,
        *,
        edge_blur_radius: float = 0.0,
        feather_radius: float = 0.0,
        cleanup_radius: int = 0,
        expand_contract_pixels: int = 0,
        premultiply_alpha: bool = False,
    ) -> None:
        _validate_settings(
            edge_blur_radius=edge_blur_radius,
            feather_radius=feather_radius,
            cleanup_radius=cleanup_radius,
            expand_contract_pixels=expand_contract_pixels,
        )
        self.edge_blur_radius = float(edge_blur_radius)
        self.feather_radius = float(feather_radius)
        self.cleanup_radius = int(cleanup_radius)
        self.expand_contract_pixels = int(expand_contract_pixels)
        self.premultiply_alpha = bool(premultiply_alpha)

    def extract(
        self, request: PrecisionExtractionRequest
    ) -> PrecisionExtractionSuccess | PrecisionExtractionError:
        should_cancel = _cancel_checker(request.provider_options)
        settings = _resolve_settings(self, request.provider_options)
        try:
            if should_cancel():
                return _cancelled(request.request_id)
            validation = _validate_request(request)
            if validation is not None:
                return validation
            if should_cancel():
                return _cancelled(request.request_id)
            image, metadata = build_refined_rgba(
                width=request.source_width,
                height=request.source_height,
                source_rgb=request.source_rgb,
                mask=request.mask,
                cleanup_radius=int(settings["cleanup_radius"]),
                feather_radius=float(settings["feather_radius"]),
                edge_blur_radius=float(settings["edge_blur_radius"]),
                expand_contract_pixels=int(settings["expand_contract_pixels"]),
                premultiply_alpha=bool(settings["premultiply_alpha"]),
                should_cancel=should_cancel,
            )
            if should_cancel():
                return _cancelled(request.request_id)
            return PrecisionExtractionSuccess(
                request_id=request.request_id,
                image=image,
                confidence=0.92,
                provider_id=PROVIDER_ID,
                provider_version=PROVIDER_VERSION,
                diagnostics={
                    **settings,
                    **metadata,
                    "algorithm": "local_precision_extraction_v1",
                    "rgb_policy": (
                        "premultiply_source"
                        if settings["premultiply_alpha"]
                        else "preserve_source"
                    ),
                    "alpha_policy": "processed_confirmed_mask",
                    "crop_mode": "full_source",
                    "remove_small_regions": False,
                },
            )
        except _Cancelled:
            return _cancelled(request.request_id)
        except Exception as exc:  # noqa: BLE001 - engine boundary
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="EXTRACTION_FAILED",
                message=str(exc),
                retryable=False,
            )


class _Cancelled(Exception):
    pass


def build_refined_rgba(
    *,
    width: int,
    height: int,
    source_rgb: bytes,
    mask: BinaryMask,
    cleanup_radius: int = 0,
    feather_radius: float = 0.0,
    edge_blur_radius: float = 0.0,
    expand_contract_pixels: int = 0,
    premultiply_alpha: bool = False,
    should_cancel: CancelChecker | None = None,
) -> tuple[RgbaImage, dict[str, Any]]:
    """Preserve source RGB; derive alpha from mask with deterministic refinement."""
    cancel = should_cancel or (lambda: False)
    rgb = np.frombuffer(source_rgb, dtype=np.uint8).reshape((height, width, 3)).copy()
    alpha, normalisation = _normalise_mask_to_float(mask, width=width, height=height)
    if cancel():
        raise _Cancelled()

    binary = alpha >= 0.5
    if expand_contract_pixels > 0:
        binary = _morphological_dilate(binary, expand_contract_pixels)
    elif expand_contract_pixels < 0:
        binary = _morphological_erode(binary, abs(expand_contract_pixels))
    if cancel():
        raise _Cancelled()

    if cleanup_radius > 0:
        binary = _morphological_open(binary, cleanup_radius)
        binary = _morphological_close(binary, cleanup_radius)
    if cancel():
        raise _Cancelled()

    alpha = binary.astype(np.float32)
    feather_algorithm = "none"
    if feather_radius > 0:
        alpha = _distance_feather(binary, float(feather_radius))
        feather_algorithm = "chamfer_distance_soft_edge"
        alpha = np.clip(alpha, 0.0, 1.0)
    if cancel():
        raise _Cancelled()

    if edge_blur_radius > 0:
        alpha = _box_blur(alpha, _radius_to_int(edge_blur_radius))
        alpha = np.clip(alpha, 0.0, 1.0)
    if cancel():
        raise _Cancelled()

    alpha_u8 = np.rint(alpha * 255.0).astype(np.uint8)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    if premultiply_alpha:
        scale = alpha_u8.astype(np.float32) / 255.0
        rgba[:, :, 0] = np.rint(rgb[:, :, 0].astype(np.float32) * scale).astype(np.uint8)
        rgba[:, :, 1] = np.rint(rgb[:, :, 1].astype(np.float32) * scale).astype(np.uint8)
        rgba[:, :, 2] = np.rint(rgb[:, :, 2].astype(np.float32) * scale).astype(np.uint8)
    else:
        rgba[:, :, 0:3] = rgb
    rgba[:, :, 3] = alpha_u8
    metadata = {
        "mask_normalisation": normalisation,
        "feather_algorithm": feather_algorithm,
        "expand_contract_applied": expand_contract_pixels,
        "cleanup_applied": cleanup_radius > 0,
        "edge_blur_applied": edge_blur_radius > 0,
        "premultiplied_alpha": premultiply_alpha,
        "source_dimensions": [width, height],
        "output_dimensions": [width, height],
        "foreground_pixel_count": int(np.count_nonzero(alpha_u8)),
    }
    return RgbaImage(width=width, height=height, data=rgba.tobytes()), metadata


def _normalise_mask_to_float(
    mask: BinaryMask,
    *,
    width: int,
    height: int,
) -> tuple[NDArray[np.float32], str]:
    if mask.width != width or mask.height != height:
        raise ValueError("mask dimensions must match source dimensions")
    if not mask.data:
        raise ValueError("mask data is empty")
    raw = np.frombuffer(mask.data, dtype=np.uint8).reshape((height, width))
    unique = set(int(value) for value in np.unique(raw))
    if unique <= {0, 1}:
        return raw.astype(np.float32), "0_1_binary"
    if unique <= {0, 255}:
        return (raw.astype(np.float32) / 255.0), "0_255_binary"
    # Soft or unexpected values: treat any positive as foreground strength / 255.
    return np.clip(raw.astype(np.float32) / 255.0, 0.0, 1.0), "grayscale_scaled"


def _distance_feather(binary: NDArray[np.bool_], radius: float) -> NDArray[np.float32]:
    """Soft edge via chamfer distance to background, scaled by feather radius.

    Fully interior foreground (distance >= radius) stays opaque.
    Fully exterior background stays transparent.
    Boundary band [0, radius] maps linearly to alpha.
    """
    radius_i = max(1, int(np.ceil(radius)))
    dist = _chamfer_distance_to_background(binary, max_distance=radius_i)
    soft: NDArray[np.float32] = np.clip(dist / float(radius), 0.0, 1.0).astype(
        np.float32
    )
    return soft


def _chamfer_distance_to_background(
    binary: NDArray[np.bool_],
    *,
    max_distance: int,
) -> NDArray[np.float32]:
    height, width = binary.shape
    large = float(max_distance + 1)
    dist = np.where(binary, large, 0.0).astype(np.float32)
    # Forward pass
    for y in range(height):
        for x in range(width):
            if not binary[y, x]:
                continue
            best = dist[y, x]
            if x > 0:
                best = min(best, dist[y, x - 1] + 1.0)
            if y > 0:
                best = min(best, dist[y - 1, x] + 1.0)
            if x > 0 and y > 0:
                best = min(best, dist[y - 1, x - 1] + 1.4142135)
            if x + 1 < width and y > 0:
                best = min(best, dist[y - 1, x + 1] + 1.4142135)
            dist[y, x] = best
    # Backward pass
    for y in range(height - 1, -1, -1):
        for x in range(width - 1, -1, -1):
            if not binary[y, x]:
                continue
            best = dist[y, x]
            if x + 1 < width:
                best = min(best, dist[y, x + 1] + 1.0)
            if y + 1 < height:
                best = min(best, dist[y + 1, x] + 1.0)
            if x + 1 < width and y + 1 < height:
                best = min(best, dist[y + 1, x + 1] + 1.4142135)
            if x > 0 and y + 1 < height:
                best = min(best, dist[y + 1, x - 1] + 1.4142135)
            dist[y, x] = best
    dist = np.where(binary, np.minimum(dist, float(max_distance)), 0.0)
    return dist.astype(np.float32)


def _resolve_settings(
    engine: LocalPrecisionExtractionEngine,
    options: dict[str, Any],
) -> dict[str, Any]:
    raw = options.get("extraction_settings")
    if isinstance(raw, dict):
        feather = float(raw.get("feather_radius", engine.feather_radius))
        blur = float(raw.get("edge_blur_radius", engine.edge_blur_radius))
        cleanup = int(raw.get("cleanup_radius", engine.cleanup_radius))
        expand = int(raw.get("expand_contract_pixels", engine.expand_contract_pixels))
        premultiply = bool(raw.get("premultiply_alpha", engine.premultiply_alpha))
    else:
        feather = engine.feather_radius
        blur = engine.edge_blur_radius
        cleanup = engine.cleanup_radius
        expand = engine.expand_contract_pixels
        premultiply = engine.premultiply_alpha
    _validate_settings(
        edge_blur_radius=blur,
        feather_radius=feather,
        cleanup_radius=cleanup,
        expand_contract_pixels=expand,
    )
    return {
        "feather_radius": feather,
        "edge_blur_radius": blur,
        "cleanup_radius": cleanup,
        "expand_contract_pixels": expand,
        "premultiply_alpha": premultiply,
        "crop_mode": "full_source",
        "crop_padding": 0,
        "remove_small_regions": False,
        "small_region_threshold": 0,
    }


def _validate_settings(
    *,
    edge_blur_radius: float,
    feather_radius: float,
    cleanup_radius: int,
    expand_contract_pixels: int,
) -> None:
    if edge_blur_radius < 0 or feather_radius < 0 or cleanup_radius < 0:
        raise ValueError("refinement radii must be >= 0")
    if feather_radius > _SAFE_RADIUS or edge_blur_radius > _SAFE_RADIUS:
        raise ValueError(f"refinement radii must be <= {_SAFE_RADIUS}")
    if abs(expand_contract_pixels) > _SAFE_EXPAND:
        raise ValueError(f"expand_contract_pixels must be within ±{_SAFE_EXPAND}")


def _validate_request(
    request: PrecisionExtractionRequest,
) -> PrecisionExtractionError | None:
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
    if not mask.data or not any(mask.data):
        return PrecisionExtractionError(
            request_id=request.request_id,
            error_code="EMPTY_MASK",
            message="confirmed mask contains no foreground pixels",
            retryable=False,
        )
    return None


def _cancel_checker(options: dict[str, object]) -> CancelChecker:
    raw = options.get("should_cancel")
    if raw is None:
        return lambda: False
    if callable(raw):

        def _check() -> bool:
            return bool(raw())

        return _check
    raise ValueError("provider_options.should_cancel must be callable")


def _cancelled(request_id: str) -> PrecisionExtractionError:
    return PrecisionExtractionError(
        request_id=request_id,
        error_code="CANCELLED",
        message="CANCELLED: extraction cancelled",
        retryable=False,
    )


def _radius_to_int(radius: float) -> int:
    return max(0, int(round(float(radius))))


def _morphological_erode(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    return _min_filter(binary.astype(np.uint8), radius).astype(bool)


def _morphological_dilate(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    return _max_filter(binary.astype(np.uint8), radius).astype(bool)


def _morphological_open(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    return _morphological_dilate(_morphological_erode(binary, radius), radius)


def _morphological_close(binary: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    return _morphological_erode(_morphological_dilate(binary, radius), radius)


def _max_filter(image: NDArray[np.uint8], radius: int) -> NDArray[np.uint8]:
    if radius <= 0:
        return image
    # Separable max-filter approximation for speed: horizontal then vertical.
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
    return out


def _min_filter(image: NDArray[np.uint8], radius: int) -> NDArray[np.uint8]:
    if radius <= 0:
        return image
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
    return out


def _box_blur(image: NDArray[np.floating], radius: int) -> NDArray[np.float32]:
    if radius <= 0:
        return image.astype(np.float32, copy=False)
    blurred = _uniform_blur_axis(image.astype(np.float64), radius, axis=1)
    blurred = _uniform_blur_axis(blurred, radius, axis=0)
    return blurred.astype(np.float32)


def _uniform_blur_axis(
    image: NDArray[np.floating],
    radius: int,
    *,
    axis: int,
) -> NDArray[np.float64]:
    kernel = 2 * radius + 1
    if axis == 1:
        padded = np.pad(image, ((0, 0), (radius, radius)), mode="edge")
        acc = np.zeros_like(image, dtype=np.float64)
        for offset in range(kernel):
            acc += padded[:, offset : offset + image.shape[1]]
        return acc / kernel
    padded = np.pad(image, ((radius, radius), (0, 0)), mode="edge")
    acc = np.zeros_like(image, dtype=np.float64)
    for offset in range(kernel):
        acc += padded[offset : offset + image.shape[0], :]
    return acc / kernel
