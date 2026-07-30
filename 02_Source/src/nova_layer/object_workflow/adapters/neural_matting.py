from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.adapters.trimap import (
    TRIMAP_BACKGROUND,
    TRIMAP_FOREGROUND,
    TRIMAP_UNKNOWN,
    Trimap,
)

BACKEND_ID = "neural_onnx"
ALGORITHM_NAME = "neural_onnx_matting_v1"
ENV_MATTING_ONNX_MODEL = "NOVA_MATTING_ONNX_MODEL"
CancelChecker = Callable[[], bool]


class MattingBackendError(RuntimeError):
    """Stable adapter-level error for neural matting."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MattingCancelled(Exception):
    """Raised when should_cancel() returns True during matting inference."""


class OnnxInferenceSession(Protocol):
    """Injectable ONNX Runtime session boundary (tests use FakeOnnxSession)."""

    def get_inputs(self) -> Sequence[Any]: ...

    def get_outputs(self) -> Sequence[Any]: ...

    def run(
        self,
        output_names: Sequence[str] | None,
        input_feed: Mapping[str, NDArray[np.floating[Any]]],
    ) -> Sequence[NDArray[np.floating[Any]]]: ...


class FakeOnnxSession:
    """Deterministic CI stand-in: soft alpha from trimap channel, no onnxruntime."""

    def __init__(self, *, height: int = 0, width: int = 0) -> None:
        self._height = height
        self._width = width
        self.run_count = 0
        self.last_input_feed: Mapping[str, NDArray[np.floating[Any]]] | None = None

    def get_inputs(self) -> list[Any]:
        return [_FakeIO("rgb_trimap", [1, 4, None, None])]

    def get_outputs(self) -> list[Any]:
        return [_FakeIO("alpha", [1, 1, None, None])]

    def run(
        self,
        output_names: Sequence[str] | None,
        input_feed: Mapping[str, NDArray[np.floating[Any]]],
    ) -> list[NDArray[np.float32]]:
        self.run_count += 1
        self.last_input_feed = input_feed
        tensor = next(iter(input_feed.values()))
        if tensor.ndim != 4 or tensor.shape[1] < 4:
            raise MattingBackendError(
                "MODEL_INVALID",
                "FakeOnnxSession expects NCHW input with 4 channels (RGB+trimap)",
            )
        # Channel 3 is trimap encoded as 0 / 0.5 / 1.
        trimap_ch = tensor[0, 3]
        alpha = np.zeros_like(trimap_ch, dtype=np.float32)
        alpha[trimap_ch >= 0.75] = 1.0
        alpha[(trimap_ch > 0.25) & (trimap_ch < 0.75)] = 0.55
        return [alpha[np.newaxis, np.newaxis, :, :]]


class _FakeIO:
    def __init__(self, name: str, shape: list[Any]) -> None:
        self.name = name
        self.shape = shape


def onnx_runtime_available() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


def resolve_matting_onnx_model(
    *,
    explicit: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve model path without downloading.

    Order: explicit runtime config → env → bundled package dir → app model dir.
    """
    env = environ if environ is not None else os.environ
    if explicit is not None and str(explicit).strip():
        candidate = Path(str(explicit)).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        # Explicit runtime config must not silently fall through to another model.
        return None
    candidates: list[Path] = []
    env_path = env.get(ENV_MATTING_ONNX_MODEL, "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(_bundled_model_candidates())
    candidates.extend(_application_model_candidates())
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def model_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()[:16]


def probe_neural_matting_availability(
    *,
    model_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    require_onnx: bool = True,
) -> tuple[str, str]:
    if require_onnx and not onnx_runtime_available():
        return (
            "unavailable",
            "DEPENDENCY_MISSING: onnxruntime is not installed",
        )
    resolved = resolve_matting_onnx_model(explicit=model_path, environ=environ)
    if resolved is None:
        return (
            "unavailable",
            "MODEL_MISSING: no ONNX matting model configured "
            f"(set {ENV_MATTING_ONNX_MODEL} or place a .onnx under models/matting)",
        )
    if resolved.suffix.lower() != ".onnx":
        return "unavailable", f"MODEL_INVALID: expected .onnx file, got {resolved.suffix!r}"
    if resolved.stat().st_size < 16:
        return "unavailable", "MODEL_INVALID: model file is empty or too small"
    return "available", f"Neural ONNX matting ready ({resolved.name})"


def create_onnx_session(model_path: Path) -> OnnxInferenceSession:
    """Create a real onnxruntime session. Raises MattingBackendError on failure."""
    if not onnx_runtime_available():
        raise MattingBackendError(
            "DEPENDENCY_MISSING",
            "onnxruntime is not installed",
        )
    try:
        ort = importlib.import_module("onnxruntime")
    except Exception as exc:  # noqa: BLE001
        raise MattingBackendError("DEPENDENCY_MISSING", str(exc)) from exc
    providers = ["CPUExecutionProvider"]
    if "CUDAExecutionProvider" in ort.get_available_providers():
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    try:
        session = ort.InferenceSession(str(model_path), providers=providers)
    except Exception as exc:  # noqa: BLE001
        raise MattingBackendError("MODEL_INVALID", str(exc)) from exc
    return session


def _bundled_model_candidates() -> list[Path]:
    package_root = Path(__file__).resolve().parents[1]  # object_workflow/
    return [
        package_root / "models" / "matting" / "neural_matting.onnx",
        package_root / "models" / "matting" / "model.onnx",
    ]


def _application_model_candidates() -> list[Path]:
    home = Path.home() / ".nova_layer" / "models" / "matting"
    return [
        home / "neural_matting.onnx",
        home / "model.onnx",
    ]


class NeuralMattingBackend:
    """Optional ONNX neural alpha-matting backend implementing MattingBackend."""

    backend_id = BACKEND_ID
    algorithm_name = ALGORITHM_NAME

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        session_factory: Callable[[Path], OnnxInferenceSession] | None = None,
        inference_max_side: int = 1024,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._configured_model = (
            Path(str(model_path)).expanduser() if model_path is not None else None
        )
        self._session_factory = session_factory or create_onnx_session
        self._inference_max_side = max(64, int(inference_max_side))
        self._environ = environ
        self._lock = RLock()
        self._session: OnnxInferenceSession | None = None
        self._resolved_model: Path | None = None
        self._fingerprint: str | None = None
        self._execution_provider = "CPUExecutionProvider"
        self.last_run_metadata: dict[str, Any] = {}

    def ensure_session(self) -> OnnxInferenceSession:
        with self._lock:
            if self._session is not None:
                return self._session
            resolved = resolve_matting_onnx_model(
                explicit=self._configured_model,
                environ=self._environ,
            )
            if resolved is None:
                raise MattingBackendError(
                    "MODEL_MISSING",
                    "no ONNX matting model available",
                )
            if not resolved.is_file():
                raise MattingBackendError(
                    "MODEL_MISSING",
                    f"model file not found: {resolved.name}",
                )
            if resolved.suffix.lower() != ".onnx":
                raise MattingBackendError(
                    "MODEL_INVALID",
                    f"expected .onnx model, got {resolved.suffix!r}",
                )
            try:
                fingerprint = model_fingerprint(resolved)
            except OSError as exc:
                raise MattingBackendError("MODEL_INVALID", str(exc)) from exc
            try:
                session = self._session_factory(resolved)
            except MattingBackendError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise MattingBackendError("BACKEND_UNAVAILABLE", str(exc)) from exc
            self._session = session
            self._resolved_model = resolved
            self._fingerprint = fingerprint
            self._execution_provider = _session_provider_name(session)
            return session

    def shutdown(self) -> None:
        """Drop the ONNX session so GPU/CPU runtime resources can be released."""
        with self._lock:
            self._session = None

    def estimate_alpha(
        self,
        *,
        source_rgb: NDArray[np.uint8],
        trimap: Trimap,
        should_cancel: CancelChecker,
    ) -> NDArray[np.float32]:
        height, width, channels = source_rgb.shape
        if channels != 3:
            raise MattingBackendError("MODEL_INVALID", "source_rgb must be HxWx3")
        if should_cancel():
            raise MattingCancelled()
        started = time.perf_counter()
        session = self.ensure_session()
        if should_cancel():
            raise MattingCancelled()

        labels = trimap.as_array()
        work_rgb, work_labels, scale = _downscale_for_inference(
            source_rgb,
            labels,
            max_side=self._inference_max_side,
        )
        tensor, input_name = _build_rgb_trimap_tensor(work_rgb, work_labels, session)
        if should_cancel():
            raise MattingCancelled()
        try:
            outputs = session.run(None, {input_name: tensor})
        except MattingCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MattingBackendError("INFERENCE_FAILED", str(exc)) from exc
        if should_cancel():
            raise MattingCancelled()
        if not outputs:
            raise MattingBackendError("INFERENCE_FAILED", "ONNX session returned no outputs")
        alpha_small = _extract_alpha_map(outputs[0], work_rgb.shape[0], work_rgb.shape[1])
        if scale != 1.0:
            alpha = _resize_alpha(alpha_small, height=height, width=width)
        else:
            alpha = alpha_small
        # Preserve known regions at source resolution.
        alpha = alpha.copy()
        alpha[labels == TRIMAP_FOREGROUND] = 1.0
        alpha[labels == TRIMAP_BACKGROUND] = 0.0
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self.last_run_metadata = {
            "backend_id": self.backend_id,
            "runtime": "onnxruntime" if not isinstance(session, FakeOnnxSession) else "fake",
            "execution_provider": self._execution_provider,
            "model_fingerprint": self._fingerprint,
            "model_name": None if self._resolved_model is None else self._resolved_model.name,
            "inference_resolution": [int(work_rgb.shape[1]), int(work_rgb.shape[0])],
            "source_resolution": [width, height],
            "inference_ms": round(elapsed_ms, 3),
            "resized_for_inference": scale != 1.0,
        }
        return np.clip(alpha.astype(np.float32), 0.0, 1.0)


def _session_provider_name(session: OnnxInferenceSession) -> str:
    get_providers = getattr(session, "get_providers", None)
    if callable(get_providers):
        try:
            providers = list(get_providers())
            if providers:
                return str(providers[0])
        except Exception:  # noqa: BLE001
            return "unknown"
    if isinstance(session, FakeOnnxSession):
        return "fake"
    return "CPUExecutionProvider"


def _downscale_for_inference(
    rgb: NDArray[np.uint8],
    labels: NDArray[np.uint8],
    *,
    max_side: int,
) -> tuple[NDArray[np.uint8], NDArray[np.uint8], float]:
    height, width = labels.shape
    longest = max(height, width)
    if longest <= max_side:
        return rgb, labels, 1.0
    scale = max_side / float(longest)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    # Nearest for labels; simple box average via slicing for RGB.
    ys = (np.linspace(0, height - 1, new_h)).astype(np.int32)
    xs = (np.linspace(0, width - 1, new_w)).astype(np.int32)
    resized_rgb = rgb[ys][:, xs]
    resized_labels = labels[ys][:, xs]
    return resized_rgb, resized_labels, scale


def _build_rgb_trimap_tensor(
    rgb: NDArray[np.uint8],
    labels: NDArray[np.uint8],
    session: OnnxInferenceSession,
) -> tuple[NDArray[np.float32], str]:
    inputs = list(session.get_inputs())
    if not inputs:
        raise MattingBackendError("MODEL_INVALID", "ONNX model has no inputs")
    input_meta = inputs[0]
    input_name = str(input_meta.name)
    shape = list(getattr(input_meta, "shape", [1, 4, None, None]))
    channels = 4
    if len(shape) >= 2 and isinstance(shape[1], int):
        channels = int(shape[1])
    height, width, _ = rgb.shape
    rgb_f = rgb.astype(np.float32) / 255.0
    trimap = np.zeros((height, width), dtype=np.float32)
    trimap[labels == TRIMAP_FOREGROUND] = 1.0
    trimap[labels == TRIMAP_UNKNOWN] = 0.5
    trimap[labels == TRIMAP_BACKGROUND] = 0.0
    if channels >= 4:
        stacked = np.stack(
            [rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2], trimap],
            axis=0,
        )
    else:
        stacked = np.stack([rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2]], axis=0)
    return stacked[np.newaxis, ...].astype(np.float32), input_name


def _extract_alpha_map(
    raw: NDArray[np.floating[Any]],
    height: int,
    width: int,
) -> NDArray[np.float32]:
    array = np.asarray(raw, dtype=np.float32)
    while array.ndim > 2 and array.shape[0] == 1:
        array = array[0]
    while array.ndim > 2 and array.shape[-1] == 1:
        array = array[..., 0]
    if array.ndim == 3 and array.shape[0] in {1, 3, 4}:
        array = array[0]
    if array.shape != (height, width):
        array = _resize_alpha(array, height=height, width=width)
    if float(array.max()) > 1.5:
        array = array / 255.0
    return np.clip(array, 0.0, 1.0)


def _resize_alpha(
    alpha: NDArray[np.floating[Any]],
    *,
    height: int,
    width: int,
) -> NDArray[np.float32]:
    src_h, src_w = alpha.shape[-2], alpha.shape[-1]
    flat = np.asarray(alpha, dtype=np.float32).reshape(src_h, src_w)
    ys = (np.linspace(0, src_h - 1, height)).astype(np.int32)
    xs = (np.linspace(0, src_w - 1, width)).astype(np.int32)
    return flat[ys][:, xs].astype(np.float32)
