import numpy as np
import pytest

from nova_layer.adapters.capabilities.mock import MockSkeletonDetectionCapability
from nova_layer.adapters.capabilities.validated_skeleton_detection import (
    SkeletonDetectionContractError,
    ValidatedSkeletonDetectionCapability,
)
from nova_layer.domain.models import CapabilityProvenance, SkeletonGuidance, SkeletonJoint
from nova_layer.ports.capabilities import SkeletonDetectionResult


def test_validated_detector_accepts_matching_semantic_output() -> None:
    artist = SkeletonGuidance(joints=[SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")])
    detector = ValidatedSkeletonDetectionCapability(MockSkeletonDetectionCapability())

    result = detector.detect(
        frame_number=0,
        image=np.zeros((8, 8, 3), dtype=np.uint8),
        artist_skeleton=artist,
    )

    assert result.joint_confidences["left_shoulder"] == 0.88


def test_validated_detector_rejects_unmatched_labels() -> None:
    artist = SkeletonGuidance(joints=[SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")])

    class BrokenDetector:
        provenance = CapabilityProvenance(
            capability="skeleton_detection",
            adapter="broken",
            adapter_version="1.0",
        )

        def detect(self, **_: object) -> SkeletonDetectionResult:
            return SkeletonDetectionResult(
                skeleton=SkeletonGuidance(joints=[SkeletonJoint(x=0.5, y=0.5, label="nose")]),
                joint_confidences={"nose": 0.9},
                depth_confidences={"nose": 0.8},
                provenance=self.provenance,
            )

    detector = ValidatedSkeletonDetectionCapability(BrokenDetector())

    with pytest.raises(SkeletonDetectionContractError, match="no semantic labels matching"):
        detector.detect(
            frame_number=0,
            image=np.zeros((8, 8, 3), dtype=np.uint8),
            artist_skeleton=artist,
        )


def test_validated_detector_rejects_non_finite_sampled_depth() -> None:
    artist = SkeletonGuidance(joints=[SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")])

    class BrokenDepthDetector:
        provenance = CapabilityProvenance(
            capability="skeleton_detection", adapter="broken-depth", adapter_version="1.0"
        )

        def detect(self, **_: object) -> SkeletonDetectionResult:
            return SkeletonDetectionResult(
                skeleton=artist,
                joint_confidences={"left_shoulder": 0.9},
                depth_confidences={"left_shoulder": 0.8},
                provenance=self.provenance,
                joint_depths={"left_shoulder": float("nan")},
            )

    detector = ValidatedSkeletonDetectionCapability(BrokenDepthDetector())

    with pytest.raises(SkeletonDetectionContractError, match="must be finite"):
        detector.detect(
            frame_number=0,
            image=np.zeros((8, 8, 3), dtype=np.uint8),
            artist_skeleton=artist,
        )
