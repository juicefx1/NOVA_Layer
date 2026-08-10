"""Depth Anything V2 Small (vits) production depth capability (Phase D3.5).

Preprocessing mirrors upstream DepthAnything/Depth-Anything-V2 ``infer_image`` /
``image2tensor`` (Apache-2.0), adapted for NOVA SOURCE RGB uint8 (no BGR convert).

Architecture code is vendored under ``_vendor/depth_anything_v2`` with LICENSE copy.
Weights are never downloaded — an offline checkpoint path is required.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from nova_layer.ports.depth import (
    DepthInferenceError,
    DepthInferenceResult,
    DepthModelLoadError,
    DepthModelWeightsMissingError,
    DepthNormalization,
    InvalidDepthFrameError,
    validate_source_rgb,
)

DAV2_SMALL_MODEL_ID = "depth_anything_v2_small"
DAV2_SMALL_ENCODER = "vits"
DAV2_SMALL_CHECKPOINT_NAME = "depth_anything_v2_vits.pth"
DAV2_DEFAULT_INFERENCE_SIZE = 518
# Official pipeline: lower_bound aspect, multiple-of-14, cubic resize,
# ImageNet normalize, bilinear restore to source HxW. RGB SOURCE (not BGR).
DAV2_SMALL_PREPROCESSING_VERSION = (
    "dav2_vits:518:lower_bound_aspect:mult14:cubic:imagenet:rgb_u8:bilinear_restore:v1"
)
DAV2_SMALL_FEATURES = 64
DAV2_SMALL_OUT_CHANNELS = [48, 96, 192, 384]
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class DepthTorchModule(Protocol):
    """Minimal torch.nn.Module surface used by the adapter."""

    def eval(self) -> Any: ...

    def to(self, device: Any) -> Any: ...

    def load_state_dict(self, state_dict: Any, strict: bool = True) -> Any: ...

    def forward(self, x: Any) -> Any: ...


ModelFactory = Callable[[], DepthTorchModule]


def constrain_to_multiple_of(
    value: float,
    *,
    multiple_of: int = 14,
    min_val: int = 0,
    max_val: int | None = None,
) -> int:
    """Match upstream ``Resize.constrain_to_multiple_of``."""
    y = int(np.round(value / multiple_of) * multiple_of)
    if max_val is not None and y > max_val:
        y = int(np.floor(value / multiple_of) * multiple_of)
    if y < min_val:
        y = int(np.ceil(value / multiple_of) * multiple_of)
    return int(y)


def compute_dav2_network_size(
    width: int,
    height: int,
    *,
    input_size: int = DAV2_DEFAULT_INFERENCE_SIZE,
    multiple_of: int = 14,
) -> tuple[int, int]:
    """Official lower_bound + keep_aspect + multiple-of sizing → (out_w, out_h)."""
    scale_height = input_size / float(height)
    scale_width = input_size / float(width)
    if scale_width > scale_height:
        scale_height = scale_width
    else:
        scale_width = scale_height
    new_height = constrain_to_multiple_of(
        scale_height * height, multiple_of=multiple_of, min_val=input_size
    )
    new_width = constrain_to_multiple_of(
        scale_width * width, multiple_of=multiple_of, min_val=input_size
    )
    return int(new_width), int(new_height)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def select_torch_device(requested: str = "auto") -> str:
    """Resolve ``auto|cuda|mps|cpu`` using the same preference as upstream DA-V2."""
    import torch

    choice = (requested or "auto").strip().lower()
    if choice == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if choice in {"cuda", "mps", "cpu"}:
        if choice == "cuda" and not torch.cuda.is_available():
            raise DepthModelLoadError("CUDA was requested but is not available.")
        if choice == "mps" and not (
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        ):
            raise DepthModelLoadError("MPS was requested but is not available.")
        return choice
    raise DepthModelLoadError(f"Unsupported depth device: {requested!r}")


def preprocess_source_rgb_for_dav2(
    image: NDArray[np.uint8],
    *,
    input_size: int = DAV2_DEFAULT_INFERENCE_SIZE,
) -> tuple[Any, tuple[int, int]]:
    """SOURCE RGB uint8 → NCHW float32 tensor + original (h, w).

    Matches upstream ``image2tensor`` after BGR→RGB (NOVA already provides RGB).
    """
    import cv2
    import torch

    height, width = validate_source_rgb(image)
    rgb = image.astype(np.float32) / np.float32(255.0)
    out_w, out_h = compute_dav2_network_size(width, height, input_size=input_size)
    resized = cv2.resize(rgb, (out_w, out_h), interpolation=cv2.INTER_CUBIC)
    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32).reshape(1, 1, 3)
    std = np.asarray(IMAGENET_STD, dtype=np.float32).reshape(1, 1, 3)
    normalized = (resized - mean) / std
    chw = np.ascontiguousarray(np.transpose(normalized, (2, 0, 1))).astype(np.float32)
    batch = torch.from_numpy(chw).unsqueeze(0)
    return batch, (height, width)


def restore_depth_to_source_size(
    depth: Any,
    *,
    source_height: int,
    source_width: int,
) -> NDArray[np.float32]:
    """Bilinear upsample (align_corners=True) back to SOURCE HxW — official path."""
    import torch
    import torch.nn.functional as F

    if not isinstance(depth, torch.Tensor):
        depth = torch.as_tensor(depth)
    if depth.ndim == 2:
        depth = depth.unsqueeze(0).unsqueeze(0)
    elif depth.ndim == 3:
        depth = depth.unsqueeze(1)
    elif depth.ndim != 4:
        raise DepthInferenceError(f"Unexpected depth tensor ndim={depth.ndim}")
    restored = F.interpolate(
        depth.float(),
        (int(source_height), int(source_width)),
        mode="bilinear",
        align_corners=True,
    )[0, 0]
    return np.ascontiguousarray(restored.detach().cpu().numpy().astype(np.float32))


def build_dav2_small_model() -> DepthTorchModule:
    """Construct uninitialized DA-V2 Small (vits) from vendored Apache-2.0 sources."""
    from nova_layer.adapters.capabilities._vendor.depth_anything_v2.dpt import (
        DepthAnythingV2,
    )

    model = DepthAnythingV2(
        encoder=DAV2_SMALL_ENCODER,
        features=DAV2_SMALL_FEATURES,
        out_channels=list(DAV2_SMALL_OUT_CHANNELS),
    )
    return model


class DepthAnythingV2SmallAdapter:
    """Production DepthAnalysisCapability for Depth Anything V2 Small (offline)."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        device: str = "auto",
        precision: str = "fp32",
        inference_size: int = DAV2_DEFAULT_INFERENCE_SIZE,
        offline_only: bool = True,
        expected_sha256: str | None = None,
        model_factory: ModelFactory | None = None,
        model: DepthTorchModule | None = None,
    ) -> None:
        del offline_only  # documented intent: this adapter never downloads.
        path = Path(model_path).expanduser()
        self._model_path = path
        self._device_request = device
        self._precision = (precision or "fp32").strip().lower()
        if self._precision != "fp32":
            raise DepthModelLoadError(
                f"D3.5 Depth Anything V2 Small supports fp32 only; got {precision!r}"
            )
        self._inference_size = int(inference_size)
        if self._inference_size < 14:
            raise DepthModelLoadError("inference_size must be >= 14")
        self._expected_sha256 = (
            expected_sha256.strip().lower() if expected_sha256 else None
        )
        self._model_factory = model_factory or build_dav2_small_model
        self._injected_model = model
        self._model: DepthTorchModule | None = model
        self._resolved_device: str | None = None
        self._weights_sha256: str | None = None
        self._load_state = "injected" if model is not None else "unloaded"
        self._last_error: str | None = None
        self._used_cpu_fallback = False
        self._lock = RLock()
        self._infer_count = 0

    @property
    def model_id(self) -> str:
        return DAV2_SMALL_MODEL_ID

    @property
    def model_version(self) -> str:
        # Prefer content identity once known; filename pin before first load.
        if self._weights_sha256:
            return f"vits-pth-sha256:{self._weights_sha256[:16]}"
        return f"vits-pth:{DAV2_SMALL_CHECKPOINT_NAME}"

    @property
    def preprocessing_version(self) -> str:
        return DAV2_SMALL_PREPROCESSING_VERSION

    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def resolved_device(self) -> str | None:
        return self._resolved_device

    @property
    def load_state(self) -> str:
        return self._load_state

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def weights_sha256(self) -> str | None:
        return self._weights_sha256

    @property
    def used_cpu_fallback(self) -> bool:
        return bool(self._used_cpu_fallback)

    @property
    def infer_count(self) -> int:
        return int(self._infer_count)

    def ensure_loaded(self) -> None:
        with self._lock:
            self._ensure_loaded_locked()

    def _ensure_loaded_locked(self) -> None:
        if self._model is not None and self._resolved_device is not None:
            return
        try:
            import torch

            device = select_torch_device(self._device_request)
            if self._injected_model is not None:
                model = self._injected_model.to(device).eval()
                self._model = model
                self._resolved_device = device
                self._load_state = "ready"
                self._last_error = None
                return

            if not self._model_path.is_file():
                raise DepthModelWeightsMissingError(
                    f"Depth model weights not found: {self._model_path}"
                )
            self._weights_sha256 = sha256_file(self._model_path)
            if self._expected_sha256 and self._weights_sha256 != self._expected_sha256:
                raise DepthModelLoadError(
                    "Depth model SHA-256 mismatch for "
                    f"{self._model_path.name}: expected {self._expected_sha256}, "
                    f"got {self._weights_sha256}"
                )
            self._load_state = "loading"
            model = self._model_factory()
            state = torch.load(
                str(self._model_path),
                map_location="cpu",
                weights_only=True,
            )
            if not isinstance(state, dict):
                raise DepthModelLoadError(
                    f"Unexpected checkpoint type: {type(state)!r}"
                )
            model.load_state_dict(state, strict=True)
            model = model.to(device).eval()
            self._model = model
            self._resolved_device = device
            self._load_state = "ready"
            self._last_error = None
        except (DepthModelWeightsMissingError, DepthModelLoadError) as exc:
            self._load_state = "error"
            self._last_error = str(exc)
            raise
        except Exception as exc:  # pragma: no cover - torch/cv2 edge failures
            self._load_state = "error"
            message = f"Failed to load Depth Anything V2 Small: {exc}"
            self._last_error = message
            raise DepthModelLoadError(message) from exc

    def infer(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
    ) -> DepthInferenceResult:
        del frame_number
        validate_source_rgb(image)
        with self._lock:
            self._ensure_loaded_locked()
            assert self._model is not None
            assert self._resolved_device is not None
            try:
                return self._infer_locked(image, allow_cpu_fallback=True)
            except DepthInferenceError:
                raise
            except Exception as exc:
                message = f"Depth Anything V2 inference failed: {exc}"
                self._last_error = message
                raise DepthInferenceError(message) from exc

    def _infer_locked(
        self,
        image: NDArray[np.uint8],
        *,
        allow_cpu_fallback: bool,
    ) -> DepthInferenceResult:
        import torch

        assert self._model is not None
        batch, (height, width) = preprocess_source_rgb_for_dav2(
            image, input_size=self._inference_size
        )
        device = self._resolved_device or "cpu"
        batch = batch.to(device)
        try:
            with torch.inference_mode():
                depth = self._model.forward(batch)
            depth_np = restore_depth_to_source_size(
                depth, source_height=height, source_width=width
            )
        except Exception as exc:
            if (
                allow_cpu_fallback
                and device != "cpu"
                and self._is_device_runtime_failure(exc)
            ):
                self._used_cpu_fallback = True
                self._last_error = f"Depth device fallback {device}→cpu: {exc}"
                self._model = self._model.to("cpu").eval()
                self._resolved_device = "cpu"
                return self._infer_locked(image, allow_cpu_fallback=False)
            raise

        if depth_np.shape != (height, width):
            raise InvalidDepthFrameError(
                f"Restored depth shape {depth_np.shape} != SOURCE {(height, width)}"
            )
        if not np.issubdtype(depth_np.dtype, np.floating):
            raise InvalidDepthFrameError(f"depth dtype must be floating; got {depth_np.dtype}")
        # Preserve model-native values — never min-max normalize here.
        self._infer_count += 1
        return DepthInferenceResult(
            depth=depth_np,
            valid_mask=None,
            quantity="relative_disparity",
            near_is="high",
            normalization=DepthNormalization(kind="model_native"),
            metadata={
                "adapter": "depth_anything_v2_small",
                "encoder": DAV2_SMALL_ENCODER,
                "device": str(self._resolved_device),
                "inference_size": str(self._inference_size),
                "precision": self._precision,
                "cpu_fallback": "1" if self._used_cpu_fallback else "0",
            },
        )

    @staticmethod
    def _is_device_runtime_failure(exc: BaseException) -> bool:
        text = str(exc).casefold()
        markers = (
            "mps",
            "metal",
            "cuda",
            "not implemented",
            "backend",
            "out of memory",
            "oom",
        )
        return any(marker in text for marker in markers)
