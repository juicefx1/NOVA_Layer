import numpy as np

from nova_layer.app.skeleton_fusion import create_fusion_candidate
from nova_layer.domain.models import CapabilityProvenance, SkeletonGuidance, SkeletonJoint


def test_artist_guided_fusion_matches_labels_and_preserves_artist_identity() -> None:
    artist_shoulder = SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")
    artist_wrist = SkeletonJoint(x=0.55, y=0.6, label="left_wrist")
    artist = SkeletonGuidance(joints=[artist_shoulder, artist_wrist])
    detected = SkeletonGuidance(
        joints=[
            SkeletonJoint(x=0.45, y=0.35, label="left_shoulder"),
            SkeletonJoint(x=0.58, y=0.63, label="left_wrist"),
        ]
    )
    candidate = create_fusion_candidate(
        frame_number=10,
        artist_skeleton=artist,
        detected_skeleton=detected,
        joint_confidences={"left_shoulder": 0.9, "left_wrist": 0.8},
        depth_confidences={"left_shoulder": 0.5, "left_wrist": 1.0},
        joint_depths={"left_shoulder": 0.42, "left_wrist": 0.68},
        provenance=CapabilityProvenance(
            capability="skeleton_detection",
            adapter="test_depth_pose",
            adapter_version="1.0",
        ),
    )

    fused = candidate.fused_skeleton.semantic_joint_map()
    assert fused["left_shoulder"].id == artist_shoulder.id
    assert artist_shoulder.x < fused["left_shoulder"].x < 0.45
    assert np.isclose(fused["left_wrist"].x, (0.55 * 0.4 + 0.58 * 0.8) / 1.2)
    assert candidate.conflict_labels == []
    assert candidate.depth_confidences == {"left_shoulder": 0.5, "left_wrist": 1.0}
    assert candidate.joint_depths == {"left_shoulder": 0.42, "left_wrist": 0.68}


def test_large_detection_disagreement_keeps_artist_joint_for_review() -> None:
    artist_joint = SkeletonJoint(x=0.1, y=0.1, label="nose")
    detected_joint = SkeletonJoint(x=0.9, y=0.9, label="nose")

    candidate = create_fusion_candidate(
        frame_number=0,
        artist_skeleton=SkeletonGuidance(joints=[artist_joint]),
        detected_skeleton=SkeletonGuidance(joints=[detected_joint]),
        joint_confidences={"nose": 0.99},
        depth_confidences={"nose": 1.0},
        provenance=CapabilityProvenance(
            capability="skeleton_detection",
            adapter="test_depth_pose",
            adapter_version="1.0",
        ),
    )

    assert candidate.fused_skeleton.joints[0] == artist_joint
    assert candidate.conflict_labels == ["nose"]
