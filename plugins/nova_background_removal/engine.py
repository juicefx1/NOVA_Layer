"""Background Removal engine — ConfirmedMaskRefine + ONNX/deterministic backends.

Phase B: ONNX replaces the deterministic alpha estimator when a model is available.
Mask policy (MP-1..MP-6), identifiers, and public success/error behaviour stay frozen.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
    RgbaImage,
)

PLUGIN_ID = "nova.background_removal"
PROVIDER_ID = "nova.background_removal"
PROVIDER_VERSION = "1.0.0"
MASK_POLICY_ID = "ConfirmedMaskRefine"
DEFAULT_MASK_DILATION_RADIUS = 2
ENV_BG_REMOVAL_ONNX_MODEL = "NOVA_BACKGROUND_REMOVAL_ONNX_MODEL"


class _OnnxSession(Protocol):
    def get_inputs(self) -> Sequence[Any]: ...

    def get_outputs(self) -> Sequence[Any]: ...

    def run(
        self,
        output_names: Sequence[str] | None,
        input_feed: Mapping[str, Any],
    ) -> Sequence[Any]: ...


def create_engine(config: ExtractionRuntimeConfig | None = None) -> BackgroundRemovalEngine:
    return BackgroundRemovalEngine(config)


class BackgroundRemovalEngine:
    """PrecisionExtractionEngine implementing ConfirmedMaskRefine."""

    def __init__(self, config: ExtractionRuntimeConfig | None = None) -> None:
        self._config = config or ExtractionRuntimeConfig(selected_provider_id=PROVIDER_ID)
        self._session: _OnnxSession | None = None
        self._session_model: Path | None = None

    def extract(
        self, request: PrecisionExtractionRequest
    ) -> PrecisionExtractionSuccess | PrecisionExtractionError:
        if request.mask is None:  # type: ignore[redundant-expr]
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message="confirmed mask is mandatory",
                retryable=False,
            )

        mask = request.mask
        width = request.source_width
        height = request.source_height

        if mask.width != width or mask.height != height:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="DIMENSION_MISMATCH",
                message=(
                    f"mask size {mask.width}x{mask.height} does not match "
                    f"source {width}x{height}"
                ),
                retryable=False,
            )

        expected_rgb = width * height * 3
        if len(request.source_rgb) != expected_rgb:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="INVALID_REQUEST",
                message=f"source_rgb length must be {expected_rgb}",
                retryable=False,
            )

        if not any(mask.data):
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="EMPTY_MASK",
                message="confirmed mask has no foreground pixels",
                retryable=False,
            )

        options = dict(request.provider_options or {})
        should_cancel = options.get("should_cancel")
        if callable(should_cancel) and should_cancel():
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code="CANCELLED",
                message="extraction cancelled",
                retryable=True,
            )

        dilation = DEFAULT_MASK_DILATION_RADIUS
        preserve_interior = bool(options.get("mask_policy_preserve_interior", True))

        try:
            alpha, backend_id, backend_meta = self._estimate_alpha(
                request.source_rgb,
                mask,
                width=width,
                height=height,
                options=options,
                should_cancel=should_cancel if callable(should_cancel) else None,
            )
        except _BackendError as exc:
            return PrecisionExtractionError(
                request_id=request.request_id,
                error_code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )

        # --- ConfirmedMaskRefine (unchanged public policy) ---
        allowed = _dilate_binary(mask, dilation)

        clamp_applied = False
        for i, flag in enumerate(allowed):
            if flag == 0 and alpha[i] != 0:
                alpha[i] = 0
                clamp_applied = True

        if preserve_interior:
            interior = _erode_binary(mask, dilation)
            for i, flag in enumerate(interior):
                if flag == 255:
                    alpha[i] = 255

        rgba = bytearray(width * height * 4)
        src = request.source_rgb
        for i in range(width * height):
            o = i * 4
            s = i * 3
            rgba[o] = src[s]
            rgba[o + 1] = src[s + 1]
            rgba[o + 2] = src[s + 2]
            rgba[o + 3] = alpha[i]

        diagnostics: dict[str, Any] = {
            "mask_policy_id": MASK_POLICY_ID,
            "mask_dilation_radius": dilation,
            "mask_clamp_outside_applied": clamp_applied,
            "backend": backend_id,
        }
        diagnostics.update(backend_meta)

        return PrecisionExtractionSuccess(
            request_id=request.request_id,
            image=RgbaImage(width=width, height=height, data=bytes(rgba)),
            confidence=1.0 if backend_id == "deterministic_mask" else 0.95,
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            diagnostics=diagnostics,
        )

    def _estimate_alpha(
        self,
        source_rgb: bytes,
        mask: BinaryMask,
        *,
        width: int,
        height: int,
        options: dict[str, Any],
        should_cancel: Callable[[], bool] | None,
    ) -> tuple[bytearray, str, dict[str, Any]]:
        """Return raw alpha (0..255) before ConfirmedMaskRefine clamp/preserve."""
        force_deterministic = bool(options.get("background_removal_force_deterministic"))
        injected = options.get("onnx_session")
        explicit = _explicit_model_config(self._config, options)

        def _deterministic() -> tuple[bytearray, str, dict[str, Any]]:
            alpha = bytearray(mask.data)
            allowed = _dilate_binary(mask, DEFAULT_MASK_DILATION_RADIUS)
            for i, flag in enumerate(allowed):
                if flag == 255 and alpha[i] == 0:
                    alpha[i] = 255
            return alpha, "deterministic_mask", {}

        # Test/support override: deterministic only when no model is configured.
        if force_deterministic and explicit is None:
            return _deterministic()

        if should_cancel is not None and should_cancel():
            raise _BackendError("CANCELLED", "extraction cancelled", retryable=True)

        # Injected session selects the ONNX estimator path (validation harness).
        if injected is not None:
            alpha = _run_onnx_alpha(
                source_rgb,
                mask,
                width=width,
                height=height,
                model_path=None,
                session=injected,
                engine=self,
            )
            return alpha, "onnx", {"onnx_model": "injected_session"}

        # Explicit model configuration must not silently fall back.
        if explicit is not None:
            model = _require_usable_onnx_model(explicit)
            alpha = _run_onnx_alpha(
                source_rgb,
                mask,
                width=width,
                height=height,
                model_path=model,
                session=None,
                engine=self,
            )
            return alpha, "onnx", {"onnx_model": str(model)}

        # Optional bundled model — only if present and runtime available.
        bundled = Path(__file__).resolve().parent / "models" / "background_removal.onnx"
        if bundled.is_file() and _onnx_runtime_available():
            alpha = _run_onnx_alpha(
                source_rgb,
                mask,
                width=width,
                height=height,
                model_path=bundled,
                session=None,
                engine=self,
            )
            return alpha, "onnx", {"onnx_model": str(bundled)}

        # No model configured → deterministic fallback (frozen public behaviour).
        return _deterministic()

def probe_availability(config: ExtractionRuntimeConfig) -> tuple[str, str]:
    """Availability probe using existing config / provider_options only."""
    options = dict(config.provider_options or {})
    if options.get("background_removal_force_unavailable"):
        return "unavailable", "background removal forced unavailable (probe)"
    if options.get("background_removal_force_available"):
        return "available", "background removal forced available (deterministic)"

    model_path = config.matting_onnx_model_path
    if model_path:
        path = Path(str(model_path)).expanduser()
        if not path.is_file():
            return (
                "unavailable",
                f"matting model path not found: {path}",
            )
        if path.suffix.lower() != ".onnx":
            return "unavailable", f"expected .onnx model, got {path.suffix!r}"
        if not _onnx_runtime_available():
            return "unavailable", "onnxruntime is not installed"
        return "available", f"ONNX background removal ready ({path.name})"

    # No explicit model: deterministic fallback remains available (frozen public behaviour).
    return "available", "deterministic ConfirmedMaskRefine backend ready"


class _BackendError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _onnx_runtime_available() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


def _explicit_model_config(
    config: ExtractionRuntimeConfig,
    options: Mapping[str, Any],
) -> str | None:
    """Return a configured model path string, or None if no model was requested."""
    for candidate in (
        options.get("onnx_model_path"),
        config.matting_onnx_model_path,
        os.environ.get(ENV_BG_REMOVAL_ONNX_MODEL, ""),
    ):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return None


def _require_usable_onnx_model(configured: str) -> Path:
    """Validate an explicitly configured model path or raise _BackendError."""
    path = Path(configured).expanduser()
    if not path.is_file():
        raise _BackendError(
            "MODEL_MISSING",
            f"matting model path not found: {path}",
            retryable=False,
        )
    if path.suffix.lower() != ".onnx":
        raise _BackendError(
            "MODEL_INVALID",
            f"expected .onnx model, got {path.suffix!r}",
            retryable=False,
        )
    if not _onnx_runtime_available():
        raise _BackendError(
            "DEPENDENCY_MISSING",
            "onnxruntime is not installed",
            retryable=False,
        )
    return path

def _create_onnx_session(model_path: Path) -> _OnnxSession:
    if not _onnx_runtime_available():
        raise _BackendError(
            "DEPENDENCY_MISSING",
            "onnxruntime is not installed",
            retryable=False,
        )
    try:
        ort = importlib.import_module("onnxruntime")
    except Exception as exc:  # noqa: BLE001
        raise _BackendError("DEPENDENCY_MISSING", str(exc), retryable=False) from exc
    providers = ["CPUExecutionProvider"]
    try:
        available = list(ort.get_available_providers())
        if "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:  # noqa: BLE001
        pass
    try:
        return ort.InferenceSession(str(model_path), providers=providers)
    except Exception as exc:  # noqa: BLE001
        raise _BackendError("MODEL_INVALID", str(exc), retryable=False) from exc


def _run_onnx_alpha(
    source_rgb: bytes,
    mask: BinaryMask,
    *,
    width: int,
    height: int,
    model_path: Path | None,
    session: Any | None,
    engine: BackgroundRemovalEngine,
) -> bytearray:
    try:
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise _BackendError("DEPENDENCY_MISSING", f"numpy required for ONNX: {exc}") from exc

    if session is not None:
        sess: _OnnxSession = session
    else:
        if model_path is None:
            raise _BackendError("MODEL_MISSING", "no ONNX model path available")
        if engine._session is None or engine._session_model != model_path:
            engine._session = _create_onnx_session(model_path)
            engine._session_model = model_path
        sess = engine._session

    try:
        inputs = list(sess.get_inputs())
        outputs = list(sess.get_outputs())
        if not inputs or not outputs:
            raise _BackendError("MODEL_INVALID", "ONNX model has no inputs/outputs")

        input_meta = inputs[0]
        input_name = str(input_meta.name)
        shape = list(getattr(input_meta, "shape", []) or [])
        channels = _static_dim(shape, 1, default=3)
        in_h = _static_dim(shape, 2, default=height)
        in_w = _static_dim(shape, 3, default=width)

        rgb = np.frombuffer(source_rgb, dtype=np.uint8).reshape((height, width, 3))
        rgb_f = rgb.astype(np.float32) / 255.0
        if (in_h, in_w) != (height, width):
            rgb_f = _resize_hwc(rgb_f, in_h, in_w)

        if channels >= 4:
            mask_2d = np.frombuffer(mask.data, dtype=np.uint8).reshape((height, width))
            mask_f = (mask_2d.astype(np.float32) / 255.0)[..., None]
            if (in_h, in_w) != (height, width):
                mask_f = _resize_hwc(mask_f, in_h, in_w)
            hwc = np.concatenate([rgb_f, mask_f], axis=2)
            if channels > 4:
                pad = np.zeros((in_h, in_w, channels - 4), dtype=np.float32)
                hwc = np.concatenate([hwc, pad], axis=2)
        else:
            hwc = rgb_f if channels == 3 else rgb_f[..., :channels]

        nchw = np.transpose(hwc, (2, 0, 1))[None, ...]
        out_tensors = sess.run(None, {input_name: nchw})
        if not out_tensors:
            raise _BackendError("INFERENCE_FAILED", "ONNX session returned no outputs")
        alpha_f = np.asarray(out_tensors[0], dtype=np.float32)
        alpha_f = np.squeeze(alpha_f)
        if alpha_f.ndim != 2:
            # Take first channel if NCHW-like residual dims remain.
            while alpha_f.ndim > 2:
                alpha_f = alpha_f[0]
        if alpha_f.shape != (height, width):
            alpha_f = _resize_hwc(alpha_f[..., None], height, width)[..., 0]
        return _sanitize_alpha_to_u8(alpha_f)
    except _BackendError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _BackendError("INFERENCE_FAILED", str(exc), retryable=False) from exc


def _sanitize_alpha_to_u8(alpha_f: Any) -> bytearray:
    """Sanitise ONNX alpha to 0..255 bytes.

    - Non-finite values (NaN/Inf) → 0
    - Detect 0..255-scale tensors *before* unit clipping (max > 1.5)
    - Clamp to [0, 1] then scale to uint8
    """
    import numpy as np

    arr = np.asarray(alpha_f, dtype=np.float32)
    if arr.size == 0:
        return bytearray()
    finite = np.isfinite(arr)
    if not bool(finite.all()):
        arr = np.where(finite, arr, 0.0).astype(np.float32)

    # Detect 0..255 encoding *before* unit clipping.
    # Require a clear 0..255 signature so a few out-of-range unit values
    # (e.g. 2.5) are clamped, not mis-scaled.
    peak = float(np.max(arr)) if arr.size else 0.0
    if peak > 1.5:
        frac_hi = float(np.mean(arr > 1.5)) if arr.size else 0.0
        if peak >= 10.0 or frac_hi > 0.1:
            arr = arr / 255.0

    arr = np.clip(arr, 0.0, 1.0)
    return bytearray((arr * 255.0 + 0.5).astype(np.uint8).reshape(-1).tolist())

def _static_dim(shape: Sequence[Any], index: int, *, default: int) -> int:
    if index >= len(shape):
        return default
    value = shape[index]
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return ivalue if ivalue > 0 else default


def _resize_hwc(image: Any, out_h: int, out_w: int) -> Any:
    """Nearest-neighbor resize for HWC float arrays (no OpenCV dependency)."""
    import numpy as np

    in_h, in_w = int(image.shape[0]), int(image.shape[1])
    if (in_h, in_w) == (out_h, out_w):
        return image
    y_idx = (np.linspace(0, in_h - 1, out_h)).astype(np.int32)
    x_idx = (np.linspace(0, in_w - 1, out_w)).astype(np.int32)
    return image[y_idx][:, x_idx]


def _dilate_binary(mask: BinaryMask, radius: int) -> bytes:
    if radius <= 0:
        return mask.data
    w, h = mask.width, mask.height
    src = mask.data
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if src[y * w + x] == 0:
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        out[ny * w + nx] = 255
    return bytes(out)


def _erode_binary(mask: BinaryMask, radius: int) -> bytes:
    if radius <= 0:
        return mask.data
    w, h = mask.width, mask.height
    src = mask.data
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            ok = True
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h) or src[ny * w + nx] == 0:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                out[y * w + x] = 255
    return bytes(out)
