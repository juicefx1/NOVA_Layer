from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NormalizedCoordinate = Annotated[float, Field(ge=0.0, le=1.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> UUID:
    return uuid4()


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class WorkflowState(StrEnum):
    NO_SOURCE = "no_source"
    SOURCE_READY = "source_ready"
    INTENT_PROVIDED = "intent_provided"
    CANDIDATE_SET_READY = "candidate_set_ready"
    HYPOTHESIS_READY = "hypothesis_ready"
    OBJECT_CONFIRMED = "object_confirmed"
    EXTRACTION_READY = "extraction_ready"


class OperationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PositivePoint(DomainModel):
    type: Literal["positive_point"] = "positive_point"
    x: NormalizedCoordinate
    y: NormalizedCoordinate


class NegativePoint(DomainModel):
    type: Literal["negative_point"] = "negative_point"
    x: NormalizedCoordinate
    y: NormalizedCoordinate


class BoundingBox(DomainModel):
    type: Literal["bounding_box"] = "bounding_box"
    x: NormalizedCoordinate
    y: NormalizedCoordinate
    width: NormalizedCoordinate
    height: NormalizedCoordinate

    @model_validator(mode="after")
    def geometry_inside_bounds(self) -> BoundingBox:
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("bounding box width and height must be positive")
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise ValueError("bounding box must be inside source-image bounds")
        return self


IntentSignal = PositivePoint | NegativePoint | BoundingBox


class IntentPayload(DomainModel):
    signals: list[dict[str, Any]]

    @field_validator("signals")
    @classmethod
    def non_empty(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not value:
            raise ValueError("signals must contain at least one intent signal")
        return value


class IntentInstruction(DomainModel):
    schema_name: str = Field(alias="schema", serialization_alias="schema")
    payload: IntentPayload

    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)


class SourceImage(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    original_filename: str
    relative_asset_path: str
    media_type: Literal["image/png", "image/jpeg"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(ge=0)
    content_fingerprint: str


class ArtistIntent(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(ge=1)
    source_image_id: UUID
    instruction: IntentInstruction


class HypothesisCandidate(DomainModel):
    """One immutable segmentation candidate from Core Inference."""

    id: UUID = Field(default_factory=new_id)
    confidence: Confidence
    mask_relative_path: str
    preview_relative_path: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


GenerationStatus = Literal["available", "rejected", "confirmed"]


class GenerationRecord(DomainModel):
    """Immutable lifecycle record for one segmentation generation."""

    id: UUID = Field(default_factory=new_id)
    generation_id: UUID = Field(default_factory=new_id)
    sequence_number: int = Field(ge=1)
    artist_intent_id: UUID
    artist_intent_revision: int = Field(ge=1)
    provider_id: str
    provider_version: str
    candidate_set_id: UUID
    operation_id: UUID
    status: GenerationStatus = "available"
    created_at: datetime = Field(default_factory=utc_now)
    rejected_at: datetime | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class HypothesisCandidateSet(DomainModel):
    """Immutable candidate set for one Generate operation / selection revision."""

    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    generation_id: UUID | None = None
    artist_intent_revision: int = Field(ge=1)
    intent_id: UUID
    source_image_id: UUID
    provider_id: str
    provider_version: str
    candidates: list[HypothesisCandidate] = Field(min_length=1)
    active_candidate_id: UUID | None = None
    operation_id: UUID

    @model_validator(mode="after")
    def active_candidate_belongs(self) -> HypothesisCandidateSet:
        if self.active_candidate_id is None:
            return self
        ids = {item.id for item in self.candidates}
        if self.active_candidate_id not in ids:
            raise ValueError("active_candidate_id must reference a candidate in this set")
        return self


class ObjectHypothesis(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(ge=1)
    source_image_id: UUID
    intent_id: UUID
    status: Literal["ready", "rejected"]
    mask_relative_path: str
    confidence: Confidence
    provider_id: str
    provider_version: str
    operation_id: UUID
    candidate_set_id: UUID | None = None
    candidate_id: UUID | None = None
    generation_id: UUID | None = None


class ConfirmationRecord(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    hypothesis_id: UUID
    confirmed_by: Literal["artist"] = "artist"
    note: str | None = None


class ConfirmedObject(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(ge=1)
    source_image_id: UUID
    intent_id: UUID
    hypothesis_id: UUID
    confirmation_id: UUID
    mask_relative_path: str
    confidence: Confidence


class ExtractionSettings(DomainModel):
    """Immutable snapshot of Precision Extraction parameters used for one result."""

    feather_radius: float = Field(default=0.0, ge=0.0, le=64.0)
    edge_blur_radius: float = Field(default=0.0, ge=0.0, le=64.0)
    expand_contract_pixels: int = Field(default=0, ge=-32, le=32)
    cleanup_radius: int = Field(default=0, ge=0, le=16)
    remove_small_regions: bool = False
    small_region_threshold: int = Field(default=0, ge=0)
    premultiply_alpha: bool = False
    crop_mode: Literal["full_source"] = "full_source"
    crop_padding: int = Field(default=0, ge=0)
    matting_unknown_radius: int = Field(default=8, ge=0, le=64)
    matting_foreground_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    matting_background_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    matting_refinement_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    matting_preserve_known_regions: bool = True
    matting_backend: Literal["color_affinity", "neural_onnx"] = "color_affinity"

    @model_validator(mode="after")
    def thresholds_ordered(self) -> ExtractionSettings:
        if self.matting_background_threshold >= self.matting_foreground_threshold:
            raise ValueError(
                "matting_background_threshold must be < matting_foreground_threshold"
            )
        return self


class ExtractionResult(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(ge=1)
    confirmed_object_id: UUID
    source_image_id: UUID
    relative_asset_path: str
    confidence: Confidence
    provider_id: str
    provider_version: str
    operation_id: UUID
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    confirmed_generation_id: UUID | None = None
    confirmed_candidate_set_id: UUID | None = None
    confirmed_candidate_id: UUID | None = None
    confirmed_hypothesis_id: UUID | None = None
    artist_intent_revision: int | None = Field(default=None, ge=1)
    mask_provider_id: str | None = None
    mask_provider_version: str | None = None
    settings: ExtractionSettings | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class OperationRecord(DomainModel):
    id: UUID = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)
    operation_type: str
    status: OperationStatus
    request_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class Project(DomainModel):
    id: UUID = Field(default_factory=new_id)
    schema_version: Literal["2.0"] = "2.0"
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    workflow_state: WorkflowState = WorkflowState.NO_SOURCE
    source_images: list[SourceImage] = Field(default_factory=list)
    intents: list[ArtistIntent] = Field(default_factory=list)
    candidate_sets: list[HypothesisCandidateSet] = Field(default_factory=list)
    generation_records: list[GenerationRecord] = Field(default_factory=list)
    hypotheses: list[ObjectHypothesis] = Field(default_factory=list)
    confirmations: list[ConfirmationRecord] = Field(default_factory=list)
    confirmed_objects: list[ConfirmedObject] = Field(default_factory=list)
    extraction_results: list[ExtractionResult] = Field(default_factory=list)
    operations: list[OperationRecord] = Field(default_factory=list)
    active_source_image_id: UUID | None = None
    active_intent_id: UUID | None = None
    active_candidate_set_id: UUID | None = None
    active_generation_id: UUID | None = None
    active_hypothesis_id: UUID | None = None
    active_confirmation_id: UUID | None = None
    active_confirmed_object_id: UUID | None = None
    active_extraction_result_id: UUID | None = None

    def touch(self) -> None:
        self.updated_at = utc_now()
