from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import IntentInstruction


@dataclass(frozen=True, slots=True)
class CoreInferenceRequest:
    request_id: str
    source_image_path: str
    source_width: int
    source_height: int
    media_type: str
    content_fingerprint: str
    intent_instruction: IntentInstruction
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """Multi-candidate Core Inference result. Application owns selection."""

    request_id: str
    masks: tuple[BinaryMask, ...]
    confidences: tuple[float, ...]
    provider_id: str
    provider_version: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.masks:
            raise ValueError("CandidateResult requires at least one mask")
        if len(self.masks) != len(self.confidences):
            raise ValueError("CandidateResult masks and confidences length mismatch")

    @classmethod
    def from_single(
        cls,
        *,
        request_id: str,
        mask: BinaryMask,
        confidence: float,
        provider_id: str,
        provider_version: str,
        provider_metadata: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> CandidateResult:
        metadata = provider_metadata if provider_metadata is not None else (diagnostics or {})
        return cls(
            request_id=request_id,
            masks=(mask,),
            confidences=(float(confidence),),
            provider_id=provider_id,
            provider_version=provider_version,
            provider_metadata=dict(metadata),
        )

    @property
    def mask(self) -> BinaryMask:
        """First mask — convenience for single-candidate callers."""
        return self.masks[0]

    @property
    def confidence(self) -> float:
        return self.confidences[0]

    @property
    def diagnostics(self) -> dict[str, Any]:
        return self.provider_metadata


# Backward-compatible alias used by older call sites and tests.
CoreInferenceSuccess = CandidateResult


@dataclass(frozen=True, slots=True)
class CoreInferenceError:
    request_id: str
    error_code: str
    message: str
    retryable: bool


class CoreInferenceEngine(Protocol):
    def generate_hypothesis(
        self, request: CoreInferenceRequest
    ) -> CandidateResult | CoreInferenceError: ...
