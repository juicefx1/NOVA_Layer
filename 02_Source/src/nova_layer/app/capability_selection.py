from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nova_layer.adapters.capabilities.browser_depth_pose import (
    BrowserDepthPoseDetectionCapability,
)
from nova_layer.adapters.capabilities.browser_depth_pose_http import (
    LocalDepthPoseHttpProvider,
)
from nova_layer.adapters.capabilities.mock import (
    MockPropagationCapability,
    MockSegmentationCapability,
    MockSkeletonDetectionCapability,
    MockSkeletonTrackingCapability,
)
from nova_layer.adapters.capabilities.sam2_image import Sam2ImageSegmentationCapability
from nova_layer.adapters.capabilities.sam2_video import Sam2VideoPropagationCapability
from nova_layer.adapters.capabilities.validated_skeleton import (
    ValidatedSkeletonTrackingCapability,
)
from nova_layer.adapters.capabilities.validated_skeleton_detection import (
    ValidatedSkeletonDetectionCapability,
)
from nova_layer.ports.capabilities import (
    InteractiveSegmentationCapability,
    SkeletonDetectionCapability,
    SkeletonTrackingCapability,
    TemporalPropagationCapability,
)


@dataclass(frozen=True, slots=True)
class SegmentationSelection:
    capability: InteractiveSegmentationCapability
    mode: str
    message: str
    checkpoint: Path | None = None


@dataclass(frozen=True, slots=True)
class PropagationSelection:
    capability: TemporalPropagationCapability
    mode: str
    message: str
    checkpoint: Path | None = None


@dataclass(frozen=True, slots=True)
class SkeletonTrackingSelection:
    capability: SkeletonTrackingCapability
    mode: str
    message: str
    adapter_spec: str | None = None


@dataclass(frozen=True, slots=True)
class SkeletonDetectionSelection:
    capability: SkeletonDetectionCapability
    mode: str
    message: str
    adapter_spec: str | None = None


def load_skeleton_adapter(spec: str) -> SkeletonTrackingCapability:
    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("expected 'python.module:factory'")
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    capability = factory()
    if not callable(getattr(capability, "track", None)):
        raise TypeError("factory result does not implement track()")
    provenance = getattr(capability, "provenance", None)
    if provenance is None or provenance.capability != "skeleton_tracking":
        raise TypeError("adapter provenance must declare skeleton_tracking")
    return ValidatedSkeletonTrackingCapability(cast(SkeletonTrackingCapability, capability))


def load_skeleton_detection_adapter(spec: str) -> SkeletonDetectionCapability:
    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("expected 'python.module:factory'")
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    capability = factory()
    if not callable(getattr(capability, "detect", None)):
        raise TypeError("factory result does not implement detect()")
    provenance = getattr(capability, "provenance", None)
    if provenance is None or provenance.capability != "skeleton_detection":
        raise TypeError("adapter provenance must declare skeleton_detection")
    return ValidatedSkeletonDetectionCapability(cast(SkeletonDetectionCapability, capability))


def select_skeleton_detection() -> SkeletonDetectionSelection:
    requested_mode = os.environ.get("NOVA_AI_MODE", "auto").lower()
    adapter_spec = os.environ.get("NOVA_SKELETON_DETECTOR", "").strip()
    bridge_url = os.environ.get("NOVA_DEPTH_POSE_BRIDGE_URL", "").strip()
    if requested_mode == "mock":
        return SkeletonDetectionSelection(
            capability=MockSkeletonDetectionCapability(),
            mode="mock",
            message="Mock pose detection explicitly selected by NOVA_AI_MODE.",
        )
    if adapter_spec:
        try:
            capability = load_skeleton_detection_adapter(adapter_spec)
        except Exception as exc:
            if requested_mode == "skeleton":
                raise RuntimeError(
                    f"Skeleton detector '{adapter_spec}' could not be loaded: {exc}"
                ) from exc
            return SkeletonDetectionSelection(
                capability=MockSkeletonDetectionCapability(),
                mode="mock",
                message=f"Mock pose detection active; detector unavailable: {exc}.",
                adapter_spec=adapter_spec,
            )
        return SkeletonDetectionSelection(
            capability=capability,
            mode="external",
            message=f"External skeleton detector ready: {adapter_spec}.",
            adapter_spec=adapter_spec,
        )
    if bridge_url:
        try:
            capability = ValidatedSkeletonDetectionCapability(
                BrowserDepthPoseDetectionCapability(LocalDepthPoseHttpProvider(bridge_url))
            )
        except Exception as exc:
            if requested_mode == "skeleton":
                raise RuntimeError(
                    f"Depth/pose bridge '{bridge_url}' could not be configured: {exc}"
                ) from exc
            return SkeletonDetectionSelection(
                capability=MockSkeletonDetectionCapability(),
                mode="mock",
                message=f"Mock pose detection active; depth/pose bridge unavailable: {exc}.",
                adapter_spec=bridge_url,
            )
        return SkeletonDetectionSelection(
            capability=capability,
            mode="browser_bridge",
            message=f"Local depth/pose browser bridge ready: {bridge_url}.",
            adapter_spec=bridge_url,
        )
    return SkeletonDetectionSelection(
        capability=MockSkeletonDetectionCapability(),
        mode="mock",
        message="Mock pose detection active; no external detector configured.",
    )


def select_skeleton_tracking() -> SkeletonTrackingSelection:
    requested_mode = os.environ.get("NOVA_AI_MODE", "auto").lower()
    adapter_spec = os.environ.get("NOVA_SKELETON_ADAPTER", "").strip()
    if requested_mode == "mock":
        return SkeletonTrackingSelection(
            capability=MockSkeletonTrackingCapability(),
            mode="mock",
            message="Mock skeleton tracking explicitly selected by NOVA_AI_MODE.",
        )
    if adapter_spec:
        try:
            capability = load_skeleton_adapter(adapter_spec)
        except Exception as exc:
            if requested_mode == "skeleton":
                raise RuntimeError(
                    f"Skeleton adapter '{adapter_spec}' could not be loaded: {exc}"
                ) from exc
            return SkeletonTrackingSelection(
                capability=MockSkeletonTrackingCapability(),
                mode="mock",
                message=f"Mock skeleton tracking active; adapter unavailable: {exc}.",
                adapter_spec=adapter_spec,
            )
        return SkeletonTrackingSelection(
            capability=capability,
            mode="external",
            message=f"External skeleton adapter ready: {adapter_spec}.",
            adapter_spec=adapter_spec,
        )
    if requested_mode == "skeleton":
        raise RuntimeError(
            "Skeleton tracking was explicitly requested but NOVA_SKELETON_ADAPTER is not set."
        )
    return SkeletonTrackingSelection(
        capability=MockSkeletonTrackingCapability(),
        mode="mock",
        message="Mock skeleton tracking active; no external adapter configured.",
    )


def default_checkpoint() -> Path:
    project_root = Path(__file__).resolve().parents[4]
    configured = os.environ.get("NOVA_SAM2_CHECKPOINT")
    return (
        Path(configured).expanduser()
        if configured
        else project_root / "03_AI" / "models" / "sam2.1_hiera_tiny.pt"
    )


def select_interactive_segmentation() -> SegmentationSelection:
    requested_mode = os.environ.get("NOVA_AI_MODE", "auto").lower()
    if requested_mode == "mock":
        return SegmentationSelection(
            capability=MockSegmentationCapability(),
            mode="mock",
            message="Mock Mode explicitly selected by NOVA_AI_MODE.",
        )

    checkpoint = default_checkpoint()
    try:
        torch = importlib.import_module("torch")
        mps_available = bool(torch.backends.mps.is_available())
        sam2_available = importlib.util.find_spec("sam2") is not None
    except Exception:
        mps_available = False
        sam2_available = False

    if checkpoint.is_file() and sam2_available and mps_available:
        return SegmentationSelection(
            capability=Sam2ImageSegmentationCapability(checkpoint, device="mps"),
            mode="sam2_mps",
            message="SAM 2.1 Hiera Tiny ready on Apple MPS.",
            checkpoint=checkpoint,
        )

    missing = []
    if not checkpoint.is_file():
        missing.append("checkpoint")
    if not sam2_available:
        missing.append("SAM-2 package")
    if not mps_available:
        missing.append("MPS access")
    reason = ", ".join(missing) or "runtime compatibility"
    if requested_mode == "sam2":
        raise RuntimeError(f"SAM 2 was explicitly requested but is not ready: {reason}.")
    return SegmentationSelection(
        capability=MockSegmentationCapability(),
        mode="mock",
        message=f"Mock Mode active; unavailable: {reason}.",
        checkpoint=checkpoint,
    )


def select_temporal_propagation() -> PropagationSelection:
    requested_mode = os.environ.get("NOVA_AI_MODE", "auto").lower()
    if requested_mode == "mock":
        return PropagationSelection(
            capability=MockPropagationCapability(),
            mode="mock",
            message="Mock Mode explicitly selected by NOVA_AI_MODE.",
        )

    checkpoint = default_checkpoint()
    try:
        torch = importlib.import_module("torch")
        mps_available = bool(torch.backends.mps.is_available())
        sam2_available = importlib.util.find_spec("sam2") is not None
    except Exception:
        mps_available = False
        sam2_available = False

    if checkpoint.is_file() and sam2_available and mps_available:
        return PropagationSelection(
            capability=Sam2VideoPropagationCapability(checkpoint, device="mps"),
            mode="sam2_video_mps",
            message="SAM 2.1 bidirectional video propagation ready on Apple MPS.",
            checkpoint=checkpoint,
        )
    if requested_mode == "sam2":
        raise RuntimeError("SAM 2 video propagation was explicitly requested but is not ready.")
    return PropagationSelection(
        capability=MockPropagationCapability(),
        mode="mock",
        message="Mock propagation active because the SAM 2 MPS runtime is unavailable.",
        checkpoint=checkpoint,
    )
