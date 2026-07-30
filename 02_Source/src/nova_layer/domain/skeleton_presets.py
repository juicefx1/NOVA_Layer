from __future__ import annotations

from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint

# Interoperability labels follow OpenPose's documented BODY_25 output ordering.
# This is NOVA-authored neutral-pose geometry and does not include OpenPose code or weights.
BODY_25_LABELS = (
    "nose",
    "neck",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "mid_hip",
    "right_hip",
    "right_knee",
    "right_ankle",
    "left_hip",
    "left_knee",
    "left_ankle",
    "right_eye",
    "left_eye",
    "right_ear",
    "left_ear",
    "left_big_toe",
    "left_small_toe",
    "left_heel",
    "right_big_toe",
    "right_small_toe",
    "right_heel",
)

BODY_25_CONNECTIONS = (
    (1, 8),
    (1, 2),
    (1, 5),
    (2, 3),
    (3, 4),
    (5, 6),
    (6, 7),
    (8, 9),
    (9, 10),
    (10, 11),
    (8, 12),
    (12, 13),
    (13, 14),
    (1, 0),
    (0, 15),
    (15, 17),
    (0, 16),
    (16, 18),
    (14, 19),
    (19, 20),
    (14, 21),
    (11, 22),
    (22, 23),
    (11, 24),
)

_NEUTRAL_COORDINATES = (
    (0.50, 0.12),
    (0.50, 0.22),
    (0.42, 0.24),
    (0.35, 0.39),
    (0.30, 0.54),
    (0.58, 0.24),
    (0.65, 0.39),
    (0.70, 0.54),
    (0.50, 0.50),
    (0.45, 0.52),
    (0.43, 0.70),
    (0.42, 0.88),
    (0.55, 0.52),
    (0.57, 0.70),
    (0.58, 0.88),
    (0.47, 0.10),
    (0.53, 0.10),
    (0.44, 0.11),
    (0.56, 0.11),
    (0.60, 0.94),
    (0.63, 0.94),
    (0.55, 0.93),
    (0.40, 0.94),
    (0.37, 0.94),
    (0.45, 0.93),
)


def openpose_body_25_preset() -> SkeletonGuidance:
    joints = [
        SkeletonJoint(x=x, y=y, label=label)
        for label, (x, y) in zip(BODY_25_LABELS, _NEUTRAL_COORDINATES, strict=True)
    ]
    bones = [
        SkeletonBone(
            start_joint_id=joints[start].id,
            end_joint_id=joints[end].id,
        )
        for start, end in BODY_25_CONNECTIONS
    ]
    return SkeletonGuidance(joints=joints, bones=bones)
