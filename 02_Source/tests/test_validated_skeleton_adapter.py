from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from nova_layer.adapters.capabilities.mock import MockSkeletonTrackingCapability
from nova_layer.adapters.capabilities.validated_skeleton import (
    SkeletonAdapterContractError,
    ValidatedSkeletonTrackingCapability,
)
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint
from nova_layer.ports.capabilities import SkeletonTrackingResult, VideoFrame


def _skeleton() -> SkeletonGuidance:
    first = SkeletonJoint(x=0.3, y=0.4)
    second = SkeletonJoint(x=0.6, y=0.7)
    return SkeletonGuidance(
        joints=[first, second],
        bones=[SkeletonBone(start_joint_id=first.id, end_joint_id=second.id)],
    )


def _frames() -> list[VideoFrame]:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    return [VideoFrame(frame_number=5, image=image)]


def test_validated_adapter_accepts_preserved_topology() -> None:
    adapter = ValidatedSkeletonTrackingCapability(MockSkeletonTrackingCapability())

    results = adapter.track(master_frame=4, reference_skeleton=_skeleton(), frames=_frames())

    assert [result.frame_number for result in results] == [5]


def test_validated_adapter_rejects_changed_joint_identity() -> None:
    source = MockSkeletonTrackingCapability()
    reference = _skeleton()

    class BrokenAdapter:
        provenance = source.provenance

        def track(self, **_: object) -> list[SkeletonTrackingResult]:
            changed = reference.model_copy(deep=True)
            changed.joints[0].id = uuid4()
            return [
                SkeletonTrackingResult(
                    frame_number=5,
                    skeleton=changed,
                    confidence=0.9,
                    provenance=self.provenance,
                )
            ]

    adapter = ValidatedSkeletonTrackingCapability(BrokenAdapter())

    with pytest.raises(SkeletonAdapterContractError, match="changed reference joint"):
        adapter.track(master_frame=4, reference_skeleton=reference, frames=_frames())


def test_validated_adapter_rejects_unrequested_frame() -> None:
    source = MockSkeletonTrackingCapability()
    reference = _skeleton()

    class BrokenAdapter:
        provenance = source.provenance

        def track(self, **_: object) -> list[SkeletonTrackingResult]:
            return [
                SkeletonTrackingResult(
                    frame_number=99,
                    skeleton=reference,
                    confidence=0.9,
                    provenance=self.provenance,
                )
            ]

    adapter = ValidatedSkeletonTrackingCapability(BrokenAdapter())

    with pytest.raises(SkeletonAdapterContractError, match="outside the requested"):
        adapter.track(master_frame=4, reference_skeleton=reference, frames=_frames())
