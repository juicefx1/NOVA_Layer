from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    GuidancePoint,
    SkeletonGuidance,
)


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    mask_reference: str
    mask: NDArray[np.uint8]
    confidence: float
    provenance: CapabilityProvenance


@dataclass(frozen=True, slots=True)
class PropagationResult:
    frame_number: int
    mask_reference: str
    mask: NDArray[np.uint8]
    confidence: float
    provenance: CapabilityProvenance
    is_validation_target: bool = True
    visible: bool = True
    area_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class VideoFrame:
    frame_number: int
    image: NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class SkeletonTrackingResult:
    frame_number: int
    skeleton: SkeletonGuidance
    confidence: float
    provenance: CapabilityProvenance


@dataclass(frozen=True, slots=True)
class SkeletonDetectionResult:
    skeleton: SkeletonGuidance
    joint_confidences: dict[str, float]
    depth_confidences: dict[str, float]
    provenance: CapabilityProvenance
    joint_depths: dict[str, float] = field(default_factory=dict)


class InteractiveSegmentationCapability(Protocol):
    def predict(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        width: int,
        height: int,
        points: Sequence[GuidancePoint],
        bounding_region: BoundingRegion | None,
    ) -> SegmentationResult: ...


class TemporalPropagationCapability(Protocol):
    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: Sequence[int],
        reference_mask: str,
        reference_mask_data: NDArray[np.uint8],
        frames: Sequence[VideoFrame],
    ) -> list[PropagationResult]: ...


class SkeletonTrackingCapability(Protocol):
    @property
    def provenance(self) -> CapabilityProvenance: ...

    def track(
        self,
        *,
        master_frame: int,
        reference_skeleton: SkeletonGuidance,
        frames: Sequence[VideoFrame],
    ) -> list[SkeletonTrackingResult]: ...


class SkeletonDetectionCapability(Protocol):
    @property
    def provenance(self) -> CapabilityProvenance: ...

    def detect(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        artist_skeleton: SkeletonGuidance,
    ) -> SkeletonDetectionResult: ...
