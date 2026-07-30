from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    GuidancePoint,
    SkeletonGuidance,
)
from nova_layer.ports.capabilities import (
    PropagationResult,
    SegmentationResult,
    SkeletonDetectionResult,
    SkeletonTrackingResult,
    VideoFrame,
)


class MockSegmentationCapability:
    provenance = CapabilityProvenance(
        capability="interactive_segmentation",
        adapter="deterministic_mock",
        adapter_version="1.0",
        settings={
            "mode": "mock",
            "quality": "Mock/Test Quality",
        },
    )

    def predict(
        self,
        *,
        frame_number: int,
        image: np.ndarray,
        width: int,
        height: int,
        points: Sequence[GuidancePoint],
        bounding_region: BoundingRegion | None,
    ) -> SegmentationResult:
        del image
        confidence = min(0.5 + len(points) * 0.1 + (0.2 if bounding_region else 0.0), 0.99)
        mask = np.zeros((height, width), dtype=np.uint8)
        if bounding_region is not None:
            x1 = round(bounding_region.x * width)
            y1 = round(bounding_region.y * height)
            x2 = round((bounding_region.x + bounding_region.width) * width)
            y2 = round((bounding_region.y + bounding_region.height) * height)
            mask[y1:y2, x1:x2] = 255

        yy, xx = np.ogrid[:height, :width]
        radius = max(6, round(min(width, height) * 0.08))
        for point in points:
            center_x = round(point.x * width)
            center_y = round(point.y * height)
            circle = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
            mask[circle] = 255 if point.polarity == "positive" else 0
        return SegmentationResult(
            mask_reference=f"masks/hypothesis_{frame_number:06d}.png",
            mask=mask,
            confidence=confidence,
            provenance=self.provenance,
        )


class MockPropagationCapability:
    provenance = CapabilityProvenance(
        capability="temporal_propagation",
        adapter="deterministic_mock",
        adapter_version="1.0",
        settings={
            "mode": "mock",
            "quality": "Mock/Test Quality",
        },
    )

    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: Sequence[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: Sequence[VideoFrame] = (),
    ) -> list[PropagationResult]:
        del reference_mask, frames
        results: list[PropagationResult] = []
        # Cover every requested target (full shot-range support for workflow QA).
        for frame in sorted(set(int(item) for item in target_frames)):
            if frame == master_frame:
                continue
            distance = abs(frame - master_frame)
            confidence = max(0.55, 0.95 - distance * 0.01)
            horizontal_shift = max(-12, min(12, frame - master_frame))
            mask = np.roll(reference_mask_data, horizontal_shift, axis=1)
            results.append(
                PropagationResult(
                    frame_number=frame,
                    mask_reference=f"masks/frame_{frame:06d}.png",
                    mask=mask,
                    confidence=confidence,
                    provenance=self.provenance,
                    is_validation_target=False,
                )
            )
        return results


class MockSkeletonTrackingCapability:
    provenance = CapabilityProvenance(
        capability="skeleton_tracking",
        adapter="deterministic_skeleton_mock",
        adapter_version="1.0",
    )

    def track(
        self,
        *,
        master_frame: int,
        reference_skeleton: SkeletonGuidance,
        frames: Sequence[VideoFrame],
    ) -> list[SkeletonTrackingResult]:
        results: list[SkeletonTrackingResult] = []
        for frame in frames:
            if frame.frame_number == master_frame:
                continue
            shift = max(-0.08, min(0.08, (frame.frame_number - master_frame) * 0.002))
            joints = [
                joint.model_copy(update={"x": min(1.0, max(0.0, joint.x + shift))})
                for joint in reference_skeleton.joints
            ]
            results.append(
                SkeletonTrackingResult(
                    frame_number=frame.frame_number,
                    skeleton=reference_skeleton.model_copy(update={"joints": joints}),
                    confidence=max(0.6, 0.98 - abs(frame.frame_number - master_frame) * 0.01),
                    provenance=self.provenance,
                )
            )
        return results


class MockSkeletonDetectionCapability:
    provenance = CapabilityProvenance(
        capability="skeleton_detection",
        adapter="deterministic_depth_pose_mock",
        adapter_version="1.0",
        device="mock",
    )

    def detect(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        artist_skeleton: SkeletonGuidance,
    ) -> SkeletonDetectionResult:
        del image
        joints = [
            joint.model_copy(
                update={
                    "x": min(1.0, max(0.0, joint.x + 0.012)),
                    "y": min(1.0, max(0.0, joint.y + 0.008)),
                }
            )
            for joint in artist_skeleton.joints
        ]
        skeleton = artist_skeleton.model_copy(update={"joints": joints})
        labeled = [joint.label for joint in joints if joint.label is not None]
        return SkeletonDetectionResult(
            skeleton=skeleton,
            joint_confidences={label: 0.88 for label in labeled},
            depth_confidences={label: 0.82 for label in labeled},
            joint_depths={
                joint.label: min(1.0, max(0.0, joint.y * 0.7 + joint.x * 0.3))
                for joint in joints
                if joint.label is not None
            },
            provenance=self.provenance.model_copy(
                update={"settings": {"source_frame": frame_number}}
            ),
        )
