from __future__ import annotations

from collections.abc import Mapping
from math import hypot, isfinite

from nova_layer.domain.models import (
    CapabilityProvenance,
    SkeletonFusionCandidate,
    SkeletonGuidance,
)


def create_fusion_candidate(
    *,
    frame_number: int,
    artist_skeleton: SkeletonGuidance,
    detected_skeleton: SkeletonGuidance,
    joint_confidences: Mapping[str, float],
    depth_confidences: Mapping[str, float] | None,
    joint_depths: Mapping[str, float] | None = None,
    provenance: CapabilityProvenance,
    artist_weight: float = 0.4,
    conflict_distance: float = 0.2,
) -> SkeletonFusionCandidate:
    if artist_weight <= 0:
        raise ValueError("artist_weight must be greater than zero")
    if conflict_distance <= 0:
        raise ValueError("conflict_distance must be greater than zero")
    detected_by_label = detected_skeleton.semantic_joint_map()
    depth_confidences = depth_confidences or {}
    joint_depths = joint_depths or {}
    unknown_depths = set(joint_depths) - set(detected_by_label)
    if unknown_depths:
        raise ValueError(f"sampled depth references unknown labels: {sorted(unknown_depths)}")
    if any(not isfinite(float(value)) for value in joint_depths.values()):
        raise ValueError("sampled depth values must be finite")
    fused_joints = []
    fused_confidences: dict[str, float] = {}
    conflicts: list[str] = []
    for artist_joint in artist_skeleton.joints:
        label = artist_joint.label
        detected_joint = detected_by_label.get(label) if label is not None else None
        if label is None or detected_joint is None:
            fused_joints.append(artist_joint.model_copy(deep=True))
            continue
        model_confidence = _validated_confidence(joint_confidences.get(label, 0.0), label)
        depth_confidence = _validated_confidence(depth_confidences.get(label, 1.0), label)
        effective_model_weight = model_confidence * depth_confidence
        distance = hypot(
            artist_joint.x - detected_joint.x,
            artist_joint.y - detected_joint.y,
        )
        if distance > conflict_distance or effective_model_weight == 0:
            fused_joints.append(artist_joint.model_copy(deep=True))
            if distance > conflict_distance:
                conflicts.append(label)
            fused_confidences[label] = effective_model_weight
            continue
        total_weight = artist_weight + effective_model_weight
        fused_joints.append(
            artist_joint.model_copy(
                update={
                    "x": (
                        artist_joint.x * artist_weight + detected_joint.x * effective_model_weight
                    )
                    / total_weight,
                    "y": (
                        artist_joint.y * artist_weight + detected_joint.y * effective_model_weight
                    )
                    / total_weight,
                }
            )
        )
        fused_confidences[label] = effective_model_weight
    fused = SkeletonGuidance(
        joints=fused_joints,
        bones=[bone.model_copy(deep=True) for bone in artist_skeleton.bones],
    )
    return SkeletonFusionCandidate(
        frame_number=frame_number,
        artist_skeleton=artist_skeleton.model_copy(deep=True),
        detected_skeleton=detected_skeleton.model_copy(deep=True),
        fused_skeleton=fused,
        joint_confidences=fused_confidences,
        depth_confidences=dict(depth_confidences),
        joint_depths=dict(joint_depths),
        conflict_labels=sorted(conflicts),
        provenance=provenance,
    )


def _validated_confidence(value: float, label: str) -> float:
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence for {label} must be between zero and one")
    return confidence
