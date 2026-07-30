from __future__ import annotations

from collections.abc import Sequence

from nova_layer.domain.models import CapabilityProvenance, SkeletonGuidance
from nova_layer.ports.capabilities import (
    SkeletonTrackingCapability,
    SkeletonTrackingResult,
    VideoFrame,
)


class SkeletonAdapterContractError(RuntimeError):
    """Raised when an external tracker violates NOVA's capability contract."""


class ValidatedSkeletonTrackingCapability:
    """Protect NOVA state from malformed results returned by optional pose adapters."""

    def __init__(self, capability: SkeletonTrackingCapability) -> None:
        self._capability = capability

    @property
    def provenance(self) -> CapabilityProvenance:
        return self._capability.provenance

    def track(
        self,
        *,
        master_frame: int,
        reference_skeleton: SkeletonGuidance,
        frames: Sequence[VideoFrame],
    ) -> list[SkeletonTrackingResult]:
        results = self._capability.track(
            master_frame=master_frame,
            reference_skeleton=reference_skeleton,
            frames=frames,
        )
        expected_frames = {frame.frame_number for frame in frames}
        result_frames = [result.frame_number for result in results]
        if len(result_frames) != len(set(result_frames)):
            raise SkeletonAdapterContractError("adapter returned duplicate frame results")
        unexpected = set(result_frames) - expected_frames
        if unexpected:
            raise SkeletonAdapterContractError(
                f"adapter returned results outside the requested frames: {sorted(unexpected)}"
            )
        reference_joint_ids = {joint.id for joint in reference_skeleton.joints}
        reference_bones = {
            frozenset((bone.start_joint_id, bone.end_joint_id)) for bone in reference_skeleton.bones
        }
        for result in results:
            if result.provenance.capability != "skeleton_tracking":
                raise SkeletonAdapterContractError(
                    "result provenance must declare skeleton_tracking"
                )
            tracked_joint_ids = {joint.id for joint in result.skeleton.joints}
            if tracked_joint_ids != reference_joint_ids:
                raise SkeletonAdapterContractError(
                    f"frame {result.frame_number} changed reference joint identities"
                )
            tracked_bones = {
                frozenset((bone.start_joint_id, bone.end_joint_id))
                for bone in result.skeleton.bones
            }
            if tracked_bones != reference_bones:
                raise SkeletonAdapterContractError(
                    f"frame {result.frame_number} changed reference bone topology"
                )
        return results
