from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import (
    BoundingBox,
    IntentSignal,
    NegativePoint,
    PositivePoint,
)
from nova_layer.object_workflow.domain.validation import (
    IntentValidationError,
    parse_intent_signals,
)
from nova_layer.object_workflow.ports.core_inference import (
    CandidateResult,
    CoreInferenceError,
    CoreInferenceRequest,
)

PROVIDER_ID = "sam2.1_hiera_tiny"
CancelChecker = Callable[[], bool]


class Sam2ProviderError(RuntimeError):
    """Adapter-internal error carrying a provider-specific code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class Sam2ImageRuntime(Protocol):
    """Injectable runtime boundary for unit tests (no torch/sam2 required)."""

    @property
    def device(self) -> str: ...

    def ensure_loaded(self) -> None: ...

    def predict(
        self,
        *,
        image_rgb: NDArray[np.uint8],
        point_coords: NDArray[np.float32] | None,
        point_labels: NDArray[np.int32] | None,
        box: NDArray[np.float32] | None,
        image_fingerprint: str | None = None,
    ) -> tuple[NDArray[np.floating[Any]], NDArray[np.floating[Any]]]:
        """Return (masks[N,H,W], scores[N]). Masks may be bool or float."""
        ...


class TorchSam2ImageRuntime:
    """Local SAM 2.1 image predictor. Loads lazily; reuses one model instance."""

    def __init__(
        self,
        checkpoint: Path,
        *,
        device: str,
        model_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml",
    ) -> None:
        self.checkpoint = checkpoint
        self.requested_device = device
        self.model_config = model_config
        self._device = device
        self._predictor: Any | None = None
        self._last_image_fingerprint: str | None = None
        self._lock = RLock()

    @property
    def device(self) -> str:
        return self._device

    def shutdown(self) -> None:
        with self._lock:
            self._predictor = None
            self._last_image_fingerprint = None
            # Best-effort GPU memory release when torch is available.
            try:
                import torch

                if self._device.startswith("cuda") and torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass

    def ensure_loaded(self) -> None:
        with self._lock:
            self._load_locked()

    def predict(
        self,
        *,
        image_rgb: NDArray[np.uint8],
        point_coords: NDArray[np.float32] | None,
        point_labels: NDArray[np.int32] | None,
        box: NDArray[np.float32] | None,
        image_fingerprint: str | None = None,
    ) -> tuple[NDArray[np.floating[Any]], NDArray[np.floating[Any]]]:
        with self._lock:
            predictor = self._load_locked()
            try:
                # Skip costly set_image when the same source fingerprint is reused.
                if (
                    image_fingerprint is None
                    or image_fingerprint != self._last_image_fingerprint
                ):
                    predictor.set_image(image_rgb)
                    self._last_image_fingerprint = image_fingerprint
                masks, scores, _ = predictor.predict(
                    point_coords=point_coords,
                    point_labels=point_labels,
                    box=box,
                    multimask_output=True,
                )
            except RuntimeError as exc:
                text = str(exc).lower()
                if "out of memory" in text or "oom" in text:
                    raise Sam2ProviderError("OUT_OF_MEMORY", str(exc), retryable=True) from exc
                raise Sam2ProviderError("INFERENCE_FAILED", str(exc)) from exc
            return (
                np.asarray(masks, dtype=np.float32),
                np.asarray(scores, dtype=np.float32),
            )

    def _load_locked(self) -> Any:
        if self._predictor is not None:
            return self._predictor
        if not self.checkpoint.is_file():
            raise Sam2ProviderError(
                "MODEL_NOT_AVAILABLE",
                f"SAM 2 checkpoint not found: {self.checkpoint}",
            )
        if importlib.util.find_spec("sam2") is None or importlib.util.find_spec("torch") is None:
            raise Sam2ProviderError(
                "MODEL_NOT_AVAILABLE",
                "SAM-2 / torch packages are not installed (optional extra 'ai')",
            )
        try:
            torch = importlib.import_module("torch")
            device = self._resolve_device(torch, self.requested_device)
            self._device = device
            build_module = importlib.import_module("sam2.build_sam")
            predictor_module = importlib.import_module("sam2.sam2_image_predictor")
            model = build_module.build_sam2(
                self.model_config,
                str(self.checkpoint),
                device=device,
                apply_postprocessing=False,
            )
            self._predictor = predictor_module.SAM2ImagePredictor(model)
        except Sam2ProviderError:
            raise
        except Exception as exc:
            raise Sam2ProviderError(
                "MODEL_LOAD_FAILED",
                f"Could not initialize SAM 2 on {self.requested_device}: {exc}",
            ) from exc
        return self._predictor

    @staticmethod
    def _resolve_device(torch: Any, requested: str) -> str:
        name = requested.strip().lower()
        if name == "auto":
            if bool(torch.backends.mps.is_available()):
                return "mps"
            return "cpu"
        if name == "mps":
            if not bool(torch.backends.mps.is_available()):
                raise Sam2ProviderError(
                    "UNSUPPORTED_DEVICE",
                    "MPS was requested but is not available",
                )
            return "mps"
        if name == "cpu":
            return "cpu"
        if name == "cuda":
            if not bool(torch.cuda.is_available()):
                raise Sam2ProviderError(
                    "UNSUPPORTED_DEVICE",
                    "CUDA was requested but is not available",
                )
            return "cuda"
        raise Sam2ProviderError("UNSUPPORTED_DEVICE", f"unsupported device: {requested!r}")


class Sam2CoreInferenceEngine:
    """Real local Core Inference provider behind the engine-neutral port."""

    def __init__(
        self,
        *,
        checkpoint: Path,
        device: str = "auto",
        mask_threshold: float = 0.5,
        runtime: Sam2ImageRuntime | None = None,
    ) -> None:
        if not 0.0 <= mask_threshold <= 1.0:
            raise ValueError("mask_threshold must be in [0, 1]")
        self.checkpoint = Path(checkpoint)
        self.mask_threshold = mask_threshold
        self._runtime = runtime or TorchSam2ImageRuntime(self.checkpoint, device=device)
        self._lock = RLock()

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    @property
    def provider_version(self) -> str:
        try:
            return version("SAM-2")
        except PackageNotFoundError:
            return "not-installed"

    @property
    def device(self) -> str:
        return self._runtime.device

    def shutdown(self) -> None:
        """Release SAM2 predictor / GPU resources."""
        self._runtime.shutdown()

    def generate_hypothesis(
        self, request: CoreInferenceRequest
    ) -> CandidateResult | CoreInferenceError:
        should_cancel = _cancel_checker(request.provider_options)
        try:
            if should_cancel():
                return _cancelled(request.request_id)
            if request.media_type not in {"image/png", "image/jpeg"}:
                return _public_error(
                    request.request_id,
                    "UNSUPPORTED_MEDIA_TYPE",
                    f"unsupported media type: {request.media_type}",
                )
            if should_cancel():
                return _cancelled(request.request_id)

            signals = _parse_signals(request)
            image_rgb = _load_rgb_image(Path(request.source_image_path))
            height, width = image_rgb.shape[0], image_rgb.shape[1]
            if width != request.source_width or height != request.source_height:
                raise Sam2ProviderError(
                    "INVALID_REQUEST",
                    "decoded source dimensions do not match CoreInferenceRequest",
                )
            point_coords, point_labels, box = _prompts_from_signals(
                signals,
                width=request.source_width,
                height=request.source_height,
            )
            if point_coords is None and box is None:
                raise Sam2ProviderError(
                    "INVALID_REQUEST",
                    "SAM 2 requires at least one point or bounding_box",
                )

            if should_cancel():
                return _cancelled(request.request_id)

            with self._lock:
                self._runtime.ensure_loaded()
                if should_cancel():
                    return _cancelled(request.request_id)
                masks, scores = self._runtime.predict(
                    image_rgb=image_rgb,
                    point_coords=point_coords,
                    point_labels=point_labels,
                    box=box,
                    image_fingerprint=request.content_fingerprint,
                )

            if should_cancel():
                return _cancelled(request.request_id)

            binary_masks, confidences = convert_all_sam_masks_to_binary_masks(
                masks=masks,
                scores=scores,
                source_width=request.source_width,
                source_height=request.source_height,
                mask_threshold=self.mask_threshold,
            )
            if should_cancel():
                return _cancelled(request.request_id)

            return CandidateResult(
                request_id=request.request_id,
                masks=binary_masks,
                confidences=confidences,
                provider_id=self.provider_id,
                provider_version=self.provider_version,
                provider_metadata={
                    "device": self.device,
                    "checkpoint": str(self.checkpoint),
                    "mask_threshold": self.mask_threshold,
                    "candidate_count": len(binary_masks),
                    "colour_space": "RGB8",
                    "resize": "nearest_to_source_if_needed",
                    "ordering": "runtime_mask_order",
                },
            )
        except IntentValidationError as exc:
            return _public_error(
                request.request_id,
                _public_code(exc.code),
                exc.message,
                provider_code=exc.code,
            )
        except Sam2ProviderError as exc:
            return _map_provider_error(request.request_id, exc)
        except Exception as exc:  # noqa: BLE001 - engine boundary
            return _public_error(
                request.request_id,
                "INFERENCE_FAILED",
                str(exc),
                provider_code="INFERENCE_FAILED",
                retryable=False,
            )


def convert_all_sam_masks_to_binary_masks(
    *,
    masks: NDArray[np.floating[Any]],
    scores: NDArray[np.floating[Any]],
    source_width: int,
    source_height: int,
    mask_threshold: float,
) -> tuple[tuple[BinaryMask, ...], tuple[float, ...]]:
    """Convert every SAM runtime candidate; preserve runtime order."""
    if masks.ndim != 3 or scores.ndim != 1 or masks.shape[0] == 0 or scores.shape[0] == 0:
        raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "SAM masks/scores have invalid shape")
    if masks.shape[0] != scores.shape[0]:
        raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "SAM mask/score count mismatch")

    binary_masks: list[BinaryMask] = []
    confidences: list[float] = []
    for index in range(masks.shape[0]):
        selected = np.asarray(masks[index], dtype=np.float32)
        if selected.ndim != 2:
            raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "SAM mask must be 2D")
        if selected.shape != (source_height, source_width):
            selected = _resize_nearest(selected, source_width, source_height)
        binary = (selected >= float(mask_threshold)).astype(np.uint8) * 255
        unique = set(np.unique(binary).tolist())
        if not unique.issubset({0, 255}):
            raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "mask values must be 0 or 255")
        binary_masks.append(
            BinaryMask.from_pixels(source_width, source_height, binary.tobytes())
        )
        confidences.append(float(np.clip(float(scores[index]), 0.0, 1.0)))
    return tuple(binary_masks), tuple(confidences)


def convert_sam_masks_to_binary_mask(
    *,
    masks: NDArray[np.floating[Any]],
    scores: NDArray[np.floating[Any]],
    source_width: int,
    source_height: int,
    mask_threshold: float,
) -> tuple[BinaryMask, float, int]:
    """Legacy helper: argmax score selection among SAM candidates."""
    binary_masks, confidences = convert_all_sam_masks_to_binary_masks(
        masks=masks,
        scores=scores,
        source_width=source_width,
        source_height=source_height,
        mask_threshold=mask_threshold,
    )
    selected_index = int(np.argmax(np.asarray(confidences, dtype=np.float32)))
    return binary_masks[selected_index], confidences[selected_index], selected_index


def _resize_nearest(
    mask: NDArray[np.floating[Any]], width: int, height: int
) -> NDArray[np.floating[Any]]:
    src_h, src_w = mask.shape
    if src_h <= 0 or src_w <= 0:
        raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "empty SAM mask")
    ys = (np.arange(height) * (src_h / height)).astype(np.int64)
    xs = (np.arange(width) * (src_w / width)).astype(np.int64)
    ys = np.clip(ys, 0, src_h - 1)
    xs = np.clip(xs, 0, src_w - 1)
    resized = np.asarray(mask[ys][:, xs], dtype=np.float32)
    return resized


def _load_rgb_image(path: Path) -> NDArray[np.uint8]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise Sam2ProviderError(
            "MODEL_NOT_AVAILABLE",
            "Pillow is required to decode source images for SAM 2",
        ) from exc
    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.uint8)
    except Exception as exc:
        raise Sam2ProviderError(
            "INFERENCE_FAILED",
            f"failed to decode source image: {exc}",
        ) from exc
    if array.ndim != 3 or array.shape[2] != 3:
        raise Sam2ProviderError("INVALID_PROVIDER_OUTPUT", "decoded image must be HxWx3 RGB")
    return np.ascontiguousarray(array.copy())


def _parse_signals(request: CoreInferenceRequest) -> list[IntentSignal]:
    schema = request.intent_instruction.schema_name
    if schema != "nova.intent.guidance.v1":
        raise IntentValidationError(
            "UNSUPPORTED_INTENT_SCHEMA",
            f"unsupported intent schema: {schema!r}",
        )
    return parse_intent_signals(request.intent_instruction.payload.signals)


def _prompts_from_signals(
    signals: Sequence[IntentSignal],
    *,
    width: int,
    height: int,
) -> tuple[NDArray[np.float32] | None, NDArray[np.int32] | None, NDArray[np.float32] | None]:
    """Map ArtistIntent signals to SAM2 prompts.

    Point ordering: preserve ArtistIntent payload order.
    Labels: PositivePoint → 1 (foreground), NegativePoint → 0 (background).
    BoundingBox: first box only (XYXY pixels); later boxes ignored deterministically.
    """
    points: list[tuple[float, float]] = []
    labels: list[int] = []
    box: NDArray[np.float32] | None = None
    for signal in signals:
        if isinstance(signal, PositivePoint):
            px, py = _to_pixel(signal.x, signal.y, width=width, height=height)
            points.append((px, py))
            labels.append(1)
        elif isinstance(signal, NegativePoint):
            px, py = _to_pixel(signal.x, signal.y, width=width, height=height)
            points.append((px, py))
            labels.append(0)
        elif isinstance(signal, BoundingBox):
            if box is None:
                x0, y0 = _to_pixel(signal.x, signal.y, width=width, height=height)
                x1, y1 = _to_pixel(
                    signal.x + signal.width,
                    signal.y + signal.height,
                    width=width,
                    height=height,
                    allow_edge=True,
                )
                if x1 <= x0 or y1 <= y0:
                    raise Sam2ProviderError(
                        "INVALID_REQUEST",
                        "bounding box collapses to empty pixel region",
                    )
                box = np.asarray([x0, y0, x1, y1], dtype=np.float32)
        else:
            raise IntentValidationError(
                "UNSUPPORTED_INTENT_SIGNAL",
                f"unsupported intent signal type: {type(signal)!r}",
            )
    point_coords = None
    point_labels = None
    if points:
        point_coords = np.asarray(points, dtype=np.float32)
        point_labels = np.asarray(labels, dtype=np.int32)
    return point_coords, point_labels, box


def _to_pixel(
    x_norm: float,
    y_norm: float,
    *,
    width: int,
    height: int,
    allow_edge: bool = False,
) -> tuple[float, float]:
    if x_norm < 0.0 or y_norm < 0.0 or x_norm > 1.0 or y_norm > 1.0:
        raise Sam2ProviderError(
            "INVALID_REQUEST",
            f"prompt coordinate out of bounds: ({x_norm}, {y_norm})",
        )
    px = x_norm * width
    py = y_norm * height
    if allow_edge:
        px = min(max(px, 0.0), float(width))
        py = min(max(py, 0.0), float(height))
    else:
        # Interior points map into [0, width) / [0, height).
        if width <= 0 or height <= 0:
            raise Sam2ProviderError("INVALID_REQUEST", "invalid source dimensions")
        px = min(max(px, 0.0), float(width - 1) if width > 1 else 0.0)
        py = min(max(py, 0.0), float(height - 1) if height > 1 else 0.0)
    return px, py


def _cancel_checker(options: dict[str, Any]) -> CancelChecker:
    raw = options.get("should_cancel")
    if raw is None:
        return lambda: False
    if callable(raw):
        return cast(CancelChecker, raw)
    raise Sam2ProviderError("INVALID_REQUEST", "provider_options.should_cancel must be callable")


def _cancelled(request_id: str) -> CoreInferenceError:
    return CoreInferenceError(
        request_id=request_id,
        error_code="CANCELLED",
        message="CANCELLED: inference cancelled",
        retryable=False,
    )


def _map_provider_error(request_id: str, exc: Sam2ProviderError) -> CoreInferenceError:
    return _public_error(
        request_id,
        _public_code(exc.code),
        exc.message,
        provider_code=exc.code,
        retryable=exc.retryable,
    )


def _public_code(provider_code: str) -> str:
    """Map adapter codes onto the published Core Inference public set."""
    if provider_code in {
        "INVALID_REQUEST",
        "UNSUPPORTED_MEDIA_TYPE",
        "UNSUPPORTED_INTENT_SCHEMA",
        "UNSUPPORTED_INTENT_SIGNAL",
        "CANCELLED",
    }:
        return provider_code
    # MODEL_NOT_AVAILABLE, MODEL_LOAD_FAILED, UNSUPPORTED_DEVICE,
    # OUT_OF_MEMORY, INVALID_PROVIDER_OUTPUT, INFERENCE_FAILED → INFERENCE_FAILED
    return "INFERENCE_FAILED"


def _public_error(
    request_id: str,
    public_code: str,
    message: str,
    *,
    provider_code: str | None = None,
    retryable: bool = False,
) -> CoreInferenceError:
    prefix = provider_code or public_code
    text = message if message.startswith(f"{prefix}:") else f"{prefix}: {message}"
    return CoreInferenceError(
        request_id=request_id,
        error_code=public_code,
        message=text,
        retryable=retryable,
    )
