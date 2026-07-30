from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ProviderAvailability = Literal["available", "unavailable"]
ProviderKind = Literal["mock", "local_model", "test"]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_positive_point: bool = False
    supports_bounding_box: bool = False
    supports_negative_point: bool = False
    supports_scribble: bool = False
    supports_mask_prompt: bool = False
    supports_cpu: bool = False
    supports_gpu: bool = False
    supports_mps: bool = False
    requires_local_checkpoint: bool = False


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Engine-neutral Core Inference provider metadata. No framework types."""

    provider_id: str
    display_name: str
    provider_version: str
    provider_kind: ProviderKind
    supported_intent_signals: tuple[str, ...]
    supported_devices: tuple[str, ...]
    requires_model_artifact: bool
    availability: ProviderAvailability
    availability_message: str
    capabilities: ProviderCapabilities
    configuration_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfig:
    """Process-local runtime selection. Not persisted in project schema 2.0."""

    selected_provider_id: str = "mock"
    device: str = "auto"
    checkpoint_path: str | None = None
    mask_threshold: float = 0.5
    provider_options: Mapping[str, Any] = field(default_factory=dict)

    def with_provider(self, provider_id: str) -> ProviderRuntimeConfig:
        return ProviderRuntimeConfig(
            selected_provider_id=provider_id,
            device=self.device,
            checkpoint_path=self.checkpoint_path,
            mask_threshold=self.mask_threshold,
            provider_options=dict(self.provider_options),
        )
