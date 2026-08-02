from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonNegativeFrame = Annotated[int, Field(ge=0)]
NormalizedCoordinate = Annotated[float, Field(ge=0.0, le=1.0)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LifecycleState(StrEnum):
    NOT_DETECTED = "not_detected"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    TRACKED = "tracked"
    TEMPORARILY_LOST = "temporarily_lost"
    RECOVERED = "recovered"
    COMPLETED = "completed"


class MaturityState(StrEnum):
    HYPOTHESIS = "hypothesis"
    CONFIRMED = "confirmed"
    VALIDATED = "validated"
    PRODUCTION_READY = "production_ready"
    PERSISTENT = "persistent"


class ValidationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTION_REQUIRED = "correction_required"
    REJECTED = "rejected"


class MediaLinkState(StrEnum):
    LINKED = "linked"
    MISSING = "missing"
    CHANGED = "changed"


class GuidancePoint(DomainModel):
    x: NormalizedCoordinate
    y: NormalizedCoordinate
    polarity: Literal["positive", "negative"]


class SkeletonJoint(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    x: NormalizedCoordinate
    y: NormalizedCoordinate
    label: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")] | None = None


class SkeletonBone(DomainModel):
    start_joint_id: UUID
    end_joint_id: UUID

    @model_validator(mode="after")
    def connects_distinct_joints(self) -> SkeletonBone:
        if self.start_joint_id == self.end_joint_id:
            raise ValueError("a skeleton bone must connect two distinct joints")
        return self


class SkeletonGuidance(DomainModel):
    joints: list[SkeletonJoint] = Field(default_factory=list)
    bones: list[SkeletonBone] = Field(default_factory=list)

    @model_validator(mode="after")
    def bones_reference_existing_unique_joints(self) -> SkeletonGuidance:
        joint_ids = [joint.id for joint in self.joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("skeleton joint identifiers must be unique")
        labels = [joint.label for joint in self.joints if joint.label is not None]
        if len(labels) != len(set(labels)):
            raise ValueError("labeled skeleton joints must have unique semantic labels")
        known = set(joint_ids)
        connections: set[frozenset[UUID]] = set()
        for bone in self.bones:
            if bone.start_joint_id not in known or bone.end_joint_id not in known:
                raise ValueError("skeleton bones must reference existing joints")
            connection = frozenset((bone.start_joint_id, bone.end_joint_id))
            if connection in connections:
                raise ValueError("duplicate skeleton bones are not allowed")
            connections.add(connection)
        return self

    def semantic_joint_map(self) -> dict[str, SkeletonJoint]:
        return {joint.label: joint for joint in self.joints if joint.label is not None}

    def positive_points(self) -> list[GuidancePoint]:
        return [GuidancePoint(x=joint.x, y=joint.y, polarity="positive") for joint in self.joints]


class BoundingRegion(DomainModel):
    x: NormalizedCoordinate
    y: NormalizedCoordinate
    width: NormalizedCoordinate
    height: NormalizedCoordinate

    @model_validator(mode="after")
    def remains_inside_frame(self) -> BoundingRegion:
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("bounding region must remain inside the normalized frame")
        return self


class ArtistIntent(DomainModel):
    master_frame: NonNegativeFrame
    points: list[GuidancePoint] = Field(default_factory=list)
    bounding_region: BoundingRegion | None = None
    skeleton_guidance: SkeletonGuidance = Field(default_factory=SkeletonGuidance)
    correction_ids: list[UUID] = Field(default_factory=list)


class CapabilityProvenance(DomainModel):
    capability: str
    adapter: str
    adapter_version: str
    model_identifier: str | None = None
    device: str = "mock"
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)


class EvidenceRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    source_type: Literal["artist", "appearance", "boundary", "temporal", "capability"]
    frame_number: NonNegativeFrame
    payload_reference: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    provenance: CapabilityProvenance | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ReasoningRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    evidence_ids: list[UUID]
    decision: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    previous_maturity: MaturityState
    resulting_maturity: MaturityState
    artist_confirmation_required: bool
    created_at: datetime = Field(default_factory=utc_now)


class FrameResult(DomainModel):
    frame_number: NonNegativeFrame
    direction: Literal["master", "backward", "forward"]
    mask_reference: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    validation_state: ValidationState = ValidationState.PENDING
    evidence_ids: list[UUID] = Field(default_factory=list)
    provenance: CapabilityProvenance


class TemporalIdentityObservation(DomainModel):
    frame_number: NonNegativeFrame
    lifecycle_state: LifecycleState
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    mask_confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    skeleton_confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    skeleton_provenance: CapabilityProvenance | None = None
    visible: bool
    area_ratio: Annotated[float, Field(ge=0.0)]
    mask_reference: str | None = None
    provenance: CapabilityProvenance


class TemporalSkeletonObservation(DomainModel):
    frame_number: NonNegativeFrame
    skeleton: SkeletonGuidance
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    provenance: CapabilityProvenance


class SkeletonCorrection(DomainModel):
    frame_number: NonNegativeFrame
    skeleton: SkeletonGuidance
    evidence_id: UUID
    replaced_observation: TemporalSkeletonObservation | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SkeletonFusionCandidate(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    frame_number: NonNegativeFrame
    artist_skeleton: SkeletonGuidance
    detected_skeleton: SkeletonGuidance
    fused_skeleton: SkeletonGuidance
    joint_confidences: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]]
    depth_confidences: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(
        default_factory=dict
    )
    joint_depths: dict[str, float] = Field(default_factory=dict)
    conflict_labels: list[str] = Field(default_factory=list)
    provenance: CapabilityProvenance
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=utc_now)


class ExtractionPreview(DomainModel):
    frame_number: NonNegativeFrame
    image_reference: str
    mask_reference: str
    created_at: datetime = Field(default_factory=utc_now)


class SmartLayerRender(DomainModel):
    version: int = Field(ge=1)
    source_layer_version: int = Field(default=1, ge=1)
    frame_start: NonNegativeFrame
    frame_end: NonNegativeFrame
    frames: list[ExtractionPreview]
    checksums: dict[str, str] = Field(default_factory=dict)
    protected: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class ObjectIdentity(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    maturity_state: MaturityState = MaturityState.HYPOTHESIS
    lifecycle_state: LifecycleState = LifecycleState.CANDIDATE
    confirmed_subject_reference: str | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


class SmartLayer(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = "Smart Layer 1"
    object_identity: ObjectIdentity = Field(default_factory=ObjectIdentity)
    artist_intent: ArtistIntent
    evidence_history: list[EvidenceRecord] = Field(default_factory=list)
    reasoning_history: list[ReasoningRecord] = Field(default_factory=list)
    frame_results: list[FrameResult] = Field(default_factory=list)
    temporal_observations: list[TemporalIdentityObservation] = Field(default_factory=list)
    temporal_skeleton_observations: list[TemporalSkeletonObservation] = Field(default_factory=list)
    skeleton_corrections: list[SkeletonCorrection] = Field(default_factory=list)
    skeleton_fusion_candidates: list[SkeletonFusionCandidate] = Field(default_factory=list)
    extraction_previews: list[ExtractionPreview] = Field(default_factory=list)
    renders: list[SmartLayerRender] = Field(default_factory=list)
    render_version_counter: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)


class MediaReference(DomainModel):
    relative_path: str
    source_path: str | None = None
    fingerprint: str
    frame_count: Annotated[int, Field(gt=0)]
    frame_rate: Annotated[float, Field(gt=0.0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    time_base: str = "1/1"
    pixel_format: str | None = None
    link_state: MediaLinkState = MediaLinkState.LINKED


class Shot(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = "Shot 1"
    media: MediaReference
    range_start: NonNegativeFrame
    range_end: NonNegativeFrame
    master_frame: NonNegativeFrame
    smart_layers: list[SmartLayer] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_frame_range(self) -> Shot:
        if self.range_start > self.range_end:
            raise ValueError("range_start must not exceed range_end")
        if not self.range_start <= self.master_frame <= self.range_end:
            raise ValueError("master_frame must be inside the shot range")
        if self.range_end >= self.media.frame_count:
            raise ValueError("shot range must be inside the source media")
        return self


class Sequence(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = "Sequence 1"
    shots: list[Shot] = Field(default_factory=list)


class ProjectColorSettings(DomainModel):
    """Optional Smart Layer project color / display-transform preferences.

    Path resolution and OCIO availability are not validated here — runtime
    ``resolve_color_settings`` owns that. Distinct from Object Workflow Schema 2.0.
    """

    backend: Literal["legacy", "ocio"] | None = None
    config_kind: Literal["env", "package_relative", "absolute", "named"] | None = None
    config_value: str | None = None
    input_color_space: str | None = None
    display: str | None = None
    view: str | None = None
    exposure: float | None = None
    pin_display_view: bool = False


class Project(DomainModel):
    schema_version: Literal["1.1"] = "1.1"
    id: UUID = Field(default_factory=uuid4)
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    sequences: list[Sequence] = Field(default_factory=list)
    color_settings: ProjectColorSettings | None = None

    def touch(self) -> None:
        self.updated_at = utc_now()

    @property
    def package_name(self) -> str:
        safe_name = "_".join(self.name.strip().split()) or "Untitled"
        return f"{safe_name}.nova"


def ensure_relative_asset_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("asset paths must be relative to the project package")
    return path.as_posix()
