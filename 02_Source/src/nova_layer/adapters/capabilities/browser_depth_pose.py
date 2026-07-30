from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Annotated, Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nova_layer.domain.models import (
    CapabilityProvenance,
    SkeletonBone,
    SkeletonGuidance,
    SkeletonJoint,
)
from nova_layer.ports.capabilities import SkeletonDetectionResult


class BridgeJoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    x: Annotated[float, Field(ge=0.0, le=1.0)]
    y: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    depth_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    depth: float | None = None

    @field_validator("x", "y", "confidence", "depth_confidence", mode="after")
    @classmethod
    def finite_normalized_fields(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("bridge joint coordinates and confidences must be finite")
        return value

    @field_validator("depth", mode="after")
    @classmethod
    def finite_depth(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("bridge joint depth must be finite when present")
        return value


class DepthPoseBridgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[str, Field(pattern=r"^1\.0$")] = "1.0"
    frame_number: Annotated[int, Field(ge=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    pose_model: str
    depth_model: str
    runtime: str
    joints: list[BridgeJoint]

    @model_validator(mode="after")
    def unique_joint_labels(self) -> DepthPoseBridgePayload:
        labels = [joint.label for joint in self.joints]
        if len(labels) != len(set(labels)):
            raise ValueError("bridge joint labels must be unique")
        return self


BridgeProvider = Callable[
    [int, NDArray[np.uint8], tuple[str, ...]],
    dict[str, Any],
]


class BrowserDepthPoseDetectionCapability:
    """Convert a licensed local browser bridge response into NOVA detection evidence."""

    def __init__(self, provider: BridgeProvider) -> None:
        self._provider = provider

    @property
    def provenance(self) -> CapabilityProvenance:
        return CapabilityProvenance(
            capability="skeleton_detection",
            adapter="local_depth_pose_json_bridge",
            adapter_version="1.0",
            device="browser",
        )

    def detect(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
        artist_skeleton: SkeletonGuidance,
    ) -> SkeletonDetectionResult:
        labels = tuple(artist_skeleton.semantic_joint_map())
        payload = DepthPoseBridgePayload.model_validate(self._provider(frame_number, image, labels))
        if payload.frame_number != frame_number:
            raise ValueError("bridge response frame does not match the requested frame")
        height, width = image.shape[:2]
        if payload.width != width or payload.height != height:
            raise ValueError("bridge response dimensions do not match the source frame")
        detected_by_label = {
            item.label: SkeletonJoint(x=item.x, y=item.y, label=item.label)
            for item in payload.joints
        }
        artist_by_id = {joint.id: joint for joint in artist_skeleton.joints}
        bones: list[SkeletonBone] = []
        for artist_bone in artist_skeleton.bones:
            start_label = artist_by_id[artist_bone.start_joint_id].label
            end_label = artist_by_id[artist_bone.end_joint_id].label
            if start_label in detected_by_label and end_label in detected_by_label:
                bones.append(
                    SkeletonBone(
                        start_joint_id=detected_by_label[start_label].id,
                        end_joint_id=detected_by_label[end_label].id,
                    )
                )
        skeleton = SkeletonGuidance(
            joints=list(detected_by_label.values()),
            bones=bones,
        )
        provenance = self.provenance.model_copy(
            update={
                "model_identifier": f"pose={payload.pose_model};depth={payload.depth_model}",
                "settings": {
                    "runtime": payload.runtime,
                    "bridge_schema": payload.schema_version,
                },
            }
        )
        return SkeletonDetectionResult(
            skeleton=skeleton,
            joint_confidences={item.label: item.confidence for item in payload.joints},
            depth_confidences={item.label: item.depth_confidence for item in payload.joints},
            provenance=provenance,
            joint_depths={
                item.label: item.depth for item in payload.joints if item.depth is not None
            },
        )
