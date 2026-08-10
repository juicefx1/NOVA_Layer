"""Production depth backend factory / diagnostics (Phase D3.5).

Keeps torch / model-path resolution out of ProjectController.
Never downloads weights.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nova_layer.adapters.capabilities.depth_anything_v2 import (
    DAV2_SMALL_CHECKPOINT_NAME,
    DAV2_SMALL_MODEL_ID,
    DAV2_SMALL_PREPROCESSING_VERSION,
    DepthAnythingV2SmallAdapter,
)
from nova_layer.ports.depth import (
    DepthAnalysisCapability,
    DepthBackendUnavailableError,
    DepthModelWeightsMissingError,
)

ENV_DEPTH_MODEL_PATH = "NOVA_DEPTH_MODEL_PATH"
ENV_DEPTH_MODEL_SHA256 = "NOVA_DEPTH_MODEL_SHA256"
ENV_DEPTH_DEVICE = "NOVA_DEPTH_DEVICE"


@dataclass(frozen=True, slots=True)
class DepthBackendDiagnostics:
    backend: str
    model_id: str | None
    model_version: str | None
    preprocessing_version: str | None
    device: str | None
    precision: str | None
    weights_path: str | None
    weights_sha256: str | None
    load_state: str
    last_error: str | None
    available: bool
    torch_available: bool
    opencv_available: bool
    used_cpu_fallback: bool = False


def torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def opencv_available() -> bool:
    return importlib.util.find_spec("cv2") is not None


def depth_runtime_available() -> bool:
    return torch_available() and opencv_available()


def default_depth_model_directories() -> tuple[Path, ...]:
    """Offline lookup roots. Mirrors `.nova_layer/models/…` convention used by matting."""
    home = Path.home()
    return (
        home / ".nova_layer" / "models" / "depth",
        home / "Library" / "Application Support" / "NOVA Layer" / "models" / "depth",
    )


def resolve_depth_model_path(
    *,
    explicit: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    checkpoint_name: str = DAV2_SMALL_CHECKPOINT_NAME,
) -> Path | None:
    """Resolve checkpoint without downloading.

    Order: explicit → ``NOVA_DEPTH_MODEL_PATH`` → known offline directories.
    """
    env = environ if environ is not None else os.environ
    if explicit is not None and str(explicit).strip():
        candidate = Path(str(explicit)).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        return None

    env_path = str(env.get(ENV_DEPTH_MODEL_PATH, "")).strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        if candidate.is_dir():
            nested = candidate / checkpoint_name
            if nested.is_file():
                return nested.resolve()
        return None

    for directory in default_depth_model_directories():
        nested = directory / checkpoint_name
        if nested.is_file():
            return nested.resolve()
    return None


def is_depth_backend_available(
    *,
    model_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if not depth_runtime_available():
        return False
    return resolve_depth_model_path(explicit=model_path, environ=environ) is not None


def create_depth_anything_v2_small_adapter(
    *,
    model_path: str | Path | None = None,
    device: str | None = None,
    environ: Mapping[str, str] | None = None,
    expected_sha256: str | None = None,
) -> DepthAnythingV2SmallAdapter:
    """Create an offline DA-V2 Small adapter or raise a typed availability error."""
    if not torch_available():
        raise DepthBackendUnavailableError(
            "Depth backend requires PyTorch. Install with: pip install 'nova-layer[depth]'"
        )
    if not opencv_available():
        raise DepthBackendUnavailableError(
            "Depth backend requires OpenCV. Install with: pip install 'nova-layer[depth]'"
        )
    env = environ if environ is not None else os.environ
    resolved = resolve_depth_model_path(explicit=model_path, environ=env)
    if resolved is None:
        searched = ", ".join(str(path) for path in default_depth_model_directories())
        raise DepthModelWeightsMissingError(
            "Depth Anything V2 Small weights not found. Set "
            f"{ENV_DEPTH_MODEL_PATH} or place {DAV2_SMALL_CHECKPOINT_NAME} under: {searched}"
        )
    sha = expected_sha256
    if sha is None:
        env_sha = str(env.get(ENV_DEPTH_MODEL_SHA256, "")).strip()
        sha = env_sha or None
    device_choice = device or str(env.get(ENV_DEPTH_DEVICE, "auto")).strip() or "auto"
    return DepthAnythingV2SmallAdapter(
        resolved,
        device=device_choice,
        precision="fp32",
        inference_size=518,
        offline_only=True,
        expected_sha256=sha,
    )


def create_default_depth_capability(
    *,
    model_path: str | Path | None = None,
    device: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> DepthAnalysisCapability | None:
    """Best-effort production depth default. Returns None when unavailable."""
    try:
        return create_depth_anything_v2_small_adapter(
            model_path=model_path,
            device=device,
            environ=environ,
        )
    except (DepthBackendUnavailableError, DepthModelWeightsMissingError):
        return None


def depth_backend_diagnostics(
    capability: DepthAnalysisCapability | None = None,
    *,
    model_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DepthBackendDiagnostics:
    env = environ if environ is not None else os.environ
    torch_ok = torch_available()
    cv_ok = opencv_available()
    resolved = resolve_depth_model_path(explicit=model_path, environ=env)

    if isinstance(capability, DepthAnythingV2SmallAdapter):
        return DepthBackendDiagnostics(
            backend="depth_anything_v2_small",
            model_id=capability.model_id,
            model_version=capability.model_version,
            preprocessing_version=capability.preprocessing_version,
            device=capability.resolved_device,
            precision="fp32",
            weights_path=str(capability.model_path),
            weights_sha256=capability.weights_sha256,
            load_state=capability.load_state,
            last_error=capability.last_error,
            available=True,
            torch_available=torch_ok,
            opencv_available=cv_ok,
            used_cpu_fallback=capability.used_cpu_fallback,
        )

    if capability is not None:
        return DepthBackendDiagnostics(
            backend=type(capability).__name__,
            model_id=getattr(capability, "model_id", None),
            model_version=getattr(capability, "model_version", None),
            preprocessing_version=getattr(capability, "preprocessing_version", None),
            device=None,
            precision=None,
            weights_path=None,
            weights_sha256=None,
            load_state="ready",
            last_error=None,
            available=True,
            torch_available=torch_ok,
            opencv_available=cv_ok,
        )

    error: str | None = None
    if not torch_ok or not cv_ok:
        error = "Depth runtime dependencies missing (need torch + cv2 via nova-layer[depth])."
    elif resolved is None:
        error = (
            f"Weights missing ({DAV2_SMALL_CHECKPOINT_NAME}). "
            f"Set {ENV_DEPTH_MODEL_PATH} or install under ~/.nova_layer/models/depth/."
        )

    return DepthBackendDiagnostics(
        backend=DAV2_SMALL_MODEL_ID,
        model_id=DAV2_SMALL_MODEL_ID,
        model_version=None,
        preprocessing_version=DAV2_SMALL_PREPROCESSING_VERSION,
        device=None,
        precision="fp32",
        weights_path=str(resolved) if resolved is not None else None,
        weights_sha256=None,
        load_state="unavailable",
        last_error=error,
        available=False,
        torch_available=torch_ok,
        opencv_available=cv_ok,
    )
