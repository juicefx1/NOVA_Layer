from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.adapters.neural_matting import (
    BACKEND_ID as NEURAL_BACKEND_ID,
)
from nova_layer.object_workflow.adapters.neural_matting import (
    MattingBackendError,
    MattingCancelled,
    NeuralMattingBackend,
)
from nova_layer.object_workflow.adapters.trimap import (
    TRIMAP_BACKGROUND,
    TRIMAP_FOREGROUND,
    TRIMAP_UNKNOWN,
    Trimap,
    build_trimap_from_binary_mask,
    morphological_dilate,
    morphological_erode,
    trimap_region_counts,
)
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
    RgbaImage,
)

PROVIDER_ID = "local.matting"
PROVIDER_VERSION = "1.1.0"
COLOR_AFFINITY_BACKEND_ID = "color_affinity"
CancelChecker = Callable[[], bool]


class MattingBackend(Protocol):
    """Inference seam for continuous alpha estimation inside the unknown region."""

    def estimate_alpha(
        self,
        *,
        source_rgb: NDArray[np.uint8],
        trimap: Trimap,
        should_cancel: CancelChecker,
    ) -> NDArray[np.float32]:
        """Return float alpha in [0, 1] with source dimensions."""
        ...


class ColorAffinityMattingBackend:
    """CPU classical colour-affinity matting (not neural, not binary blur).

    Unknown pixels receive continuous alpha from RGB distance to nearby
    definite-foreground and definite-background samples.
    """

    backend_id = COLOR_AFFINITY_BACKEND_ID
    algorithm_name = "color_affinity_matting_v1"

    def estimate_alpha(
        self,
        *,
        source_rgb: NDArray[np.uint8],
        trimap: Trimap,
        should_cancel: CancelChecker,
    ) -> NDArray[np.float32]:
        height, width, _channels = source_rgb.shape
        labels = trimap.as_array()
        alpha = np.zeros((height, width), dtype=np.float32)
        alpha[labels == TRIMAP_FOREGROUND] = 1.0
        alpha[labels == TRIMAP_BACKGROUND] = 0.0
        unknown = labels == TRIMAP_UNKNOWN
        if not np.any(unknown):
            return alpha
        if should_cancel():
            raise _Cancelled()

        fg_mask = labels == TRIMAP_FOREGROUND
        bg_mask = labels == TRIMAP_BACKGROUND
        if not np.any(fg_mask) or not np.any(bg_mask):
            # Degenerate trimap: fall back to soft binary inside unknown only.
            alpha[unknown] = 0.5
            return alpha

        sample_radius = max(4, int(trimap.unknown_radius))
        fg_mean = _local_colour_mean(
            source_rgb,
            fg_mask,
            sample_radius,
            should_cancel=should_cancel,
        )
        bg_mean = _local_colour_mean(
            source_rgb,
            bg_mask,
            sample_radius,
            should_cancel=should_cancel,
        )
        if should_cancel():
            raise _Cancelled()

        rgb = source_rgb.astype(np.float32)
        dist_fg = np.linalg.norm(rgb - fg_mean, axis=2)
        dist_bg = np.linalg.norm(rgb - bg_mean, axis=2)
        denom = dist_fg + dist_bg
        soft = np.zeros_like(denom, dtype=np.float32)
        valid = denom > 1e-6
        soft[valid] = (dist_bg[valid] / denom[valid]).astype(np.float32)
        soft[~valid] = 0.5
        alpha[unknown] = np.clip(soft[unknown], 0.0, 1.0)
        return alpha


class _Cancelled(Exception):
    pass


class LocalMattingExtractionEngine:
    """Real local alpha-matting Precision Extraction provider."""

    def __init__(
        self,
        *,
        edge_blur_radius: float = 0.0,
        expand_contract_pixels: int = 0,
        cleanup_radius: int = 0,
        premultiply_alpha: bool = False,
        matting_unknown_radius: int = 8,
        matting_foreground_threshold: float = 0.95,
        matting_background_threshold: float = 0.05,
        matting_refinement_strength: float = 1.0,
        matting_preserve_known_regions: bool = True,
        matting_backend: str = COLOR_AFFINITY_BACKEND_ID,
        matting_onnx_model_path: str | None = None,
        backend: MattingBackend | None = None,
        neural_session_factory: Any | None = None,
    ) -> None:
        if matting_unknown_radius < 0 or matting_unknown_radius > 64:
            raise ValueError("matting_unknown_radius must be in 0..64")
        if not 0.0 <= matting_refinement_strength <= 1.0:
            raise ValueError("matting_refinement_strength must be in 0..1")
        if matting_background_threshold >= matting_foreground_threshold:
            raise ValueError("matting thresholds are unordered")
        if matting_backend not in {COLOR_AFFINITY_BACKEND_ID, NEURAL_BACKEND_ID}:
            raise ValueError(f"unsupported matting_backend: {matting_backend!r}")
        self.edge_blur_radius = float(edge_blur_radius)
        self.expand_contract_pixels = int(expand_contract_pixels)
        self.cleanup_radius = int(cleanup_radius)
        self.premultiply_alpha = bool(premultiply_alpha)
        self.matting_unknown_radius = int(matting_unknown_radius)
        self.matting_foreground_threshold = float(matting_foreground_threshold)
        self.matting_background_threshold = float(matting_background_threshold)
        self.matting_refinement_strength = float(matting_refinement_strength)
        self.matting_preserve_known_regions = bool(matting_preserve_known_regions)
        self.matting_backend_id = str(matting_backend)
        self.matting_onnx_model_path = matting_onnx_model_path
        self._injected_backend = backend
        self._neural_session_factory = neural_session_factory
        self._backend_cache: dict[str, MattingBackend] = {}
        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._resolve_backend(self.matting_backend_id)

    def shutdown(self) -> None:
        """Release cached matting backends (including ONNX sessions)."""
        for backend in list(self._backend_cache.values()):
            closer = getattr(backend, "shutdown", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass
        self._backend_cache.clear()
        closer = getattr(self._backend, "shutdown", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass

    def _resolve_backend(self, backend_id: str) -> MattingBackend:
        if backend_id in self._backend_cache:
            return self._backend_cache[backend_id]
        if backend_id == COLOR_AFFINITY_BACKEND_ID:
            backend: MattingBackend = ColorAffinityMattingBackend()
        elif backend_id == NEURAL_BACKEND_ID:
            backend = NeuralMattingBackend(
                model_path=self.matting_onnx_model_path,
                session_factory=self._neural_session_factory,
            )
        else:
            raise MattingBackendError(
                "BACKEND_UNAVAILABLE",
                f"unsupported matting backend: {backend_id!r}",
            )
        self._backend_cache[backend_id] = backend
        return backend

    def _select_backend(
        self,
        settings: dict[str, Any],
        options: dict[str, Any],
    ) -> MattingBackend:
        injected = options.get("matting_backend_impl")
        if injected is not None:
            return injected  # type: ignore[no-any-return]
        if self._injected_backend is not None:
            return self._injected_backend
        backend_id = str(settings.get("matting_backend", self.matting_backend_id))
        return self._resolve_backend(backend_id)

    def extract(
        self, request: PrecisionExtractionRequest
    ) -> PrecisionExtractionSuccess | PrecisionExtractionError:
        should_cancel = _cancel_checker(request.provider_options)
        settings = _resolve_settings(self, request.provider_options)
        try:
            backend = self._select_backend(settings, request.provider_options)
        except MattingBackendError as exc:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code=exc.code,
                message=exc.message,
                retryable=False,
            )
        try:
            if should_cancel():
                return _cancelled(request.request_id)
            validation = _validate_request(request)
            if validation is not None:
                return validation
            if should_cancel():
                return _cancelled(request.request_id)

            width = request.source_width
            height = request.source_height
            rgb = np.frombuffer(request.source_rgb, dtype=np.uint8).reshape(
                (height, width, 3)
            ).copy()
            binary = _mask_to_binary(request.mask, width=width, height=height)

            if settings["expand_contract_pixels"] > 0:
                binary = morphological_dilate(binary, settings["expand_contract_pixels"])
            elif settings["expand_contract_pixels"] < 0:
                binary = morphological_erode(binary, abs(settings["expand_contract_pixels"]))
            if settings["cleanup_radius"] > 0:
                binary = morphological_dilate(
                    morphological_erode(binary, settings["cleanup_radius"]),
                    settings["cleanup_radius"],
                )
                binary = morphological_erode(
                    morphological_dilate(binary, settings["cleanup_radius"]),
                    settings["cleanup_radius"],
                )
            if should_cancel():
                return _cancelled(request.request_id)

            trimap = build_trimap_from_binary_mask(
                width=width,
                height=height,
                binary_foreground=binary,
                unknown_radius=int(settings["matting_unknown_radius"]),
            )
            counts = trimap_region_counts(trimap)
            if counts["unknown"] == 0 and counts["foreground"] == 0:
                return PrecisionExtractionError(
                    request_id=request.request_id,
                    error_code="EMPTY_MASK",
                    message="confirmed mask produced no foreground or unknown trimap region",
                    retryable=False,
                )
            if should_cancel():
                return _cancelled(request.request_id)

            try:
                model_alpha = backend.estimate_alpha(
                    source_rgb=rgb,
                    trimap=trimap,
                    should_cancel=should_cancel,
                )
            except (_Cancelled, MattingCancelled):
                return _cancelled(request.request_id)
            except MattingBackendError as exc:
                return PrecisionExtractionError(
                    request_id=request.request_id,
                    error_code=exc.code,
                    message=exc.message,
                    retryable=False,
                )
            except Exception as exc:  # noqa: BLE001
                return PrecisionExtractionError(
                    request_id=request.request_id,
                    error_code="INFERENCE_FAILED",
                    message=str(exc),
                    retryable=False,
                )

            alpha = _validate_alpha(model_alpha, width=width, height=height)
            if should_cancel():
                return _cancelled(request.request_id)

            labels = trimap.as_array()
            if settings["matting_preserve_known_regions"]:
                alpha = alpha.copy()
                alpha[labels == TRIMAP_BACKGROUND] = 0.0
                alpha[labels == TRIMAP_FOREGROUND] = 1.0

            strength = float(settings["matting_refinement_strength"])
            if strength < 1.0:
                deterministic = binary.astype(np.float32)
                unknown = labels == TRIMAP_UNKNOWN
                blended = alpha.copy()
                blended[unknown] = (
                    (1.0 - strength) * deterministic[unknown] + strength * alpha[unknown]
                )
                alpha = blended

            if settings["edge_blur_radius"] > 0:
                alpha = _box_blur_2d(
                    alpha,
                    max(0, int(round(settings["edge_blur_radius"]))),
                    should_cancel=should_cancel,
                )
                alpha = np.clip(alpha, 0.0, 1.0)
                if settings["matting_preserve_known_regions"]:
                    alpha[labels == TRIMAP_BACKGROUND] = 0.0
                    alpha[labels == TRIMAP_FOREGROUND] = 1.0

            alpha = np.clip(alpha, 0.0, 1.0)
            # Soft thresholds only for metadata diagnostics; do not hard-binarise.
            alpha_u8 = np.rint(alpha * 255.0).astype(np.uint8)
            rgba = np.empty((height, width, 4), dtype=np.uint8)
            if settings["premultiply_alpha"]:
                scale = alpha_u8.astype(np.float32) / 255.0
                rgba[:, :, 0] = np.rint(rgb[:, :, 0].astype(np.float32) * scale).astype(np.uint8)
                rgba[:, :, 1] = np.rint(rgb[:, :, 1].astype(np.float32) * scale).astype(np.uint8)
                rgba[:, :, 2] = np.rint(rgb[:, :, 2].astype(np.float32) * scale).astype(np.uint8)
            else:
                rgba[:, :, 0:3] = rgb
            rgba[:, :, 3] = alpha_u8

            soft_count = int(np.count_nonzero((alpha_u8 > 0) & (alpha_u8 < 255)))
            image = RgbaImage(width=width, height=height, data=rgba.tobytes())
            algorithm = getattr(backend, "algorithm_name", type(backend).__name__)
            backend_id = getattr(
                backend,
                "backend_id",
                settings.get("matting_backend", COLOR_AFFINITY_BACKEND_ID),
            )
            backend_meta = dict(getattr(backend, "last_run_metadata", {}) or {})
            # Never persist absolute model paths in diagnostics.
            backend_meta.pop("model_path", None)
            return PrecisionExtractionSuccess(
                request_id=request.request_id,
                image=image,
                confidence=0.88,
                provider_id=PROVIDER_ID,
                provider_version=PROVIDER_VERSION,
                diagnostics={
                    **settings,
                    "algorithm": algorithm,
                    "backend_id": backend_id,
                    "provider_id": PROVIDER_ID,
                    "runtime_backend": backend_meta.get("runtime", "cpu"),
                    "device": backend_meta.get("execution_provider", "cpu"),
                    "execution_provider": backend_meta.get("execution_provider", "cpu"),
                    "model_fingerprint": backend_meta.get("model_fingerprint"),
                    "inference_resolution": backend_meta.get(
                        "inference_resolution",
                        [width, height],
                    ),
                    "inference_ms": backend_meta.get("inference_ms"),
                    "trimap_algorithm": trimap.algorithm,
                    "unknown_region_radius": trimap.unknown_radius,
                    "trimap_counts": counts,
                    "unknown_pixel_fraction": counts["unknown"] / float(width * height),
                    "alpha_min": float(alpha.min()),
                    "alpha_max": float(alpha.max()),
                    "soft_alpha_pixel_count": soft_count,
                    "known_region_preservation": bool(
                        settings["matting_preserve_known_regions"]
                    ),
                    "source_dimensions": [width, height],
                    "output_dimensions": [width, height],
                    "model_input_dimensions": backend_meta.get(
                        "inference_resolution",
                        [width, height],
                    ),
                    "resized": bool(backend_meta.get("resized_for_inference", False)),
                    "padded": False,
                    "crop_mode": "full_source",
                    "rgb_policy": (
                        "premultiply_source"
                        if settings["premultiply_alpha"]
                        else "preserve_source"
                    ),
                    "alpha_policy": str(algorithm),
                    "quality_mode": "alpha_matting",
                },
            )
        except (_Cancelled, MattingCancelled):
            return _cancelled(request.request_id)
        except Exception as exc:  # noqa: BLE001
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="EXTRACTION_FAILED",
                message=str(exc),
                retryable=False,
            )


def probe_matting_availability() -> tuple[str, str]:
    try:
        import numpy as _np  # noqa: F401
    except ImportError:
        return (
            "unavailable",
            "MATTING_DEPENDENCY_MISSING: numpy is required for Local Alpha Matting",
        )
    return "available", "CPU colour-affinity alpha matting"


def _local_colour_mean(
    rgb: NDArray[np.uint8],
    region: NDArray[np.bool_],
    radius: int,
    *,
    should_cancel: CancelChecker | None = None,
) -> NDArray[np.float32]:
    """Propagate region colour means into a dense map via box averaging of masked colours."""
    height, width, _ = rgb.shape
    weights = region.astype(np.float64)
    colour = rgb.astype(np.float64) * weights[:, :, None]
    # Separable box sum for colour and weights.
    sum_c = np.zeros_like(colour)
    sum_w = np.zeros_like(weights)
    for channel in range(3):
        if should_cancel is not None and should_cancel():
            raise _Cancelled()
        blurred_c = _box_blur_2d(
            colour[:, :, channel],
            radius,
            should_cancel=should_cancel,
        )
        sum_c[:, :, channel] = blurred_c
    sum_w = _box_blur_2d(weights, radius, should_cancel=should_cancel).astype(np.float64)
    mean = np.zeros_like(colour, dtype=np.float32)
    valid = sum_w > 1e-6
    for channel in range(3):
        channel_mean = np.zeros((height, width), dtype=np.float32)
        channel_mean[valid] = (sum_c[:, :, channel][valid] / sum_w[valid]).astype(np.float32)
        mean[:, :, channel] = channel_mean
    # Global fallback for pixels with empty neighbourhood.
    if np.any(region):
        global_mean = rgb[region].astype(np.float32).mean(axis=0)
        for channel in range(3):
            mean[:, :, channel][~valid] = global_mean[channel]
    return mean


def _box_blur_2d(
    image: NDArray[np.floating],
    radius: int,
    *,
    should_cancel: CancelChecker | None = None,
) -> NDArray[np.float32]:
    if radius <= 0:
        return image.astype(np.float32, copy=False)
    kernel = 2 * radius + 1
    padded = np.pad(image.astype(np.float64), ((0, 0), (radius, radius)), mode="edge")
    acc = np.zeros_like(image, dtype=np.float64)
    for offset in range(kernel):
        if should_cancel is not None and offset % 8 == 0 and should_cancel():
            raise _Cancelled()
        acc += padded[:, offset : offset + image.shape[1]]
    horizontal = acc / kernel
    padded_v = np.pad(horizontal, ((radius, radius), (0, 0)), mode="edge")
    acc_v = np.zeros_like(image, dtype=np.float64)
    for offset in range(kernel):
        if should_cancel is not None and offset % 8 == 0 and should_cancel():
            raise _Cancelled()
        acc_v += padded_v[offset : offset + image.shape[0], :]
    return (acc_v / kernel).astype(np.float32)


def _mask_to_binary(mask: BinaryMask, *, width: int, height: int) -> NDArray[np.bool_]:
    if mask.width != width or mask.height != height:
        raise ValueError("mask dimensions must match source dimensions")
    raw = np.frombuffer(mask.data, dtype=np.uint8).reshape((height, width))
    return raw > 0


def _validate_alpha(
    alpha: NDArray[np.floating],
    *,
    width: int,
    height: int,
) -> NDArray[np.float32]:
    if alpha.ndim != 2 or alpha.shape != (height, width):
        raise ValueError(
            f"MATTING_OUTPUT_SHAPE_MISMATCH: expected {(height, width)}, got {alpha.shape}"
        )
    if not np.isfinite(alpha).all():
        raise ValueError("NON_FINITE_ALPHA_OUTPUT: alpha contains NaN or Inf")
    return np.clip(alpha.astype(np.float32), 0.0, 1.0)


def _resolve_settings(
    engine: LocalMattingExtractionEngine,
    options: dict[str, Any],
) -> dict[str, Any]:
    raw = options.get("extraction_settings")
    if isinstance(raw, dict):
        return {
            "edge_blur_radius": float(raw.get("edge_blur_radius", engine.edge_blur_radius)),
            "expand_contract_pixels": int(
                raw.get("expand_contract_pixels", engine.expand_contract_pixels)
            ),
            "cleanup_radius": int(raw.get("cleanup_radius", engine.cleanup_radius)),
            "premultiply_alpha": bool(raw.get("premultiply_alpha", engine.premultiply_alpha)),
            "matting_unknown_radius": int(
                raw.get("matting_unknown_radius", engine.matting_unknown_radius)
            ),
            "matting_foreground_threshold": float(
                raw.get("matting_foreground_threshold", engine.matting_foreground_threshold)
            ),
            "matting_background_threshold": float(
                raw.get("matting_background_threshold", engine.matting_background_threshold)
            ),
            "matting_refinement_strength": float(
                raw.get("matting_refinement_strength", engine.matting_refinement_strength)
            ),
            "matting_preserve_known_regions": bool(
                raw.get(
                    "matting_preserve_known_regions",
                    engine.matting_preserve_known_regions,
                )
            ),
            "matting_backend": str(
                raw.get("matting_backend", engine.matting_backend_id)
            ),
            "feather_radius": float(raw.get("feather_radius", 0.0)),
            "remove_small_regions": False,
            "small_region_threshold": 0,
            "crop_mode": "full_source",
            "crop_padding": 0,
        }
    return {
        "edge_blur_radius": engine.edge_blur_radius,
        "expand_contract_pixels": engine.expand_contract_pixels,
        "cleanup_radius": engine.cleanup_radius,
        "premultiply_alpha": engine.premultiply_alpha,
        "matting_unknown_radius": engine.matting_unknown_radius,
        "matting_foreground_threshold": engine.matting_foreground_threshold,
        "matting_background_threshold": engine.matting_background_threshold,
        "matting_refinement_strength": engine.matting_refinement_strength,
        "matting_preserve_known_regions": engine.matting_preserve_known_regions,
        "matting_backend": engine.matting_backend_id,
        "feather_radius": 0.0,
        "remove_small_regions": False,
        "small_region_threshold": 0,
        "crop_mode": "full_source",
        "crop_padding": 0,
    }


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
