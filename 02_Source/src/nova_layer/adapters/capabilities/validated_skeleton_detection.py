from __future__ import annotations

from math import isfinite

import numpy as np
from numpy.typing import NDArray

from nova_layer.domain.models import CapabilityProvenance, SkeletonGuidance
from nova_layer.ports.capabilities import (
    SkeletonDetectionCapability,
    SkeletonDetectionResult,
)


class SkeletonDetectionContractError(RuntimeError):
    """Raised when an automatic pose detector violates NOVA's result contract."""


class ValidatedSkeletonDetectionCapability:
    def __init__(self, capability: SkeletonDetectionCapability) -> None:
        self._capability = capability

    @property
    def provenance(self) -> CapabilityProvenance:
        return self._capability.provenance

    def detect(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        artist_skeleton: SkeletonGuidance,
    ) -> SkeletonDetectionResult:
        result = self._capability.detect(
            frame_number=frame_number,
            image=image,
            artist_skeleton=artist_skeleton,
        )
        if result.provenance.capability != "skeleton_detection":
            raise SkeletonDetectionContractError(
                "result provenance must declare skeleton_detection"
            )
        detected_labels = set(result.skeleton.semantic_joint_map())
        artist_labels = set(artist_skeleton.semantic_joint_map())
        if not detected_labels & artist_labels:
            raise SkeletonDetectionContractError(
                "detected skeleton has no semantic labels matching the artist prompt"
            )
        for source_name, confidences in (
            ("joint", result.joint_confidences),
            ("depth", result.depth_confidences),
        ):
            unknown = set(confidences) - detected_labels
            if unknown:
                raise SkeletonDetectionContractError(
                    f"{source_name} confidence references unknown labels: {sorted(unknown)}"
                )
            invalid = {
                label: value
                for label, value in confidences.items()
                if not isfinite(float(value)) or not 0.0 <= float(value) <= 1.0
            }
            if invalid:
                raise SkeletonDetectionContractError(
                    f"{source_name} confidence must be finite and between zero and one"
                )
        unknown_depths = set(result.joint_depths) - detected_labels
        if unknown_depths:
            raise SkeletonDetectionContractError(
                f"sampled depth references unknown labels: {sorted(unknown_depths)}"
            )
        if any(not isfinite(float(value)) for value in result.joint_depths.values()):
            raise SkeletonDetectionContractError("sampled depth values must be finite")
        return result
