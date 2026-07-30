from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ExtractionAvailability = Literal["available", "unavailable"]
ExtractionProviderKind = Literal["mock", "local", "test"]
MattingBackendId = Literal["color_affinity", "neural_onnx"]


@dataclass(frozen=True, slots=True)
class ExtractionProviderCapabilities:
    supports_binary_mask: bool = True
    supports_edge_feather: bool = False
    supports_morphological_cleanup: bool = False
    supports_edge_blur: bool = False
    supports_alpha_matting: bool = False
    supports_expand_contract: bool = False
    supports_premultiply_alpha: bool = False
    requires_model: bool = False


@dataclass(frozen=True, slots=True)
class ExtractionProviderDescriptor:
    """Engine-neutral Precision Extraction provider metadata."""

    provider_id: str
    display_name: str
    provider_version: str
    provider_kind: ExtractionProviderKind
    requires_model: bool
    availability: ExtractionAvailability
    availability_message: str
    capabilities: ExtractionProviderCapabilities
    configuration_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionRuntimeConfig:
    """Process-local extraction selection. Not persisted in schema 2.0."""

    selected_provider_id: str = "mock"
    edge_blur_radius: float = 0.0
    feather_radius: float = 0.0
    cleanup_radius: int = 0
    expand_contract_pixels: int = 0
    premultiply_alpha: bool = False
    matting_unknown_radius: int = 8
    matting_foreground_threshold: float = 0.95
    matting_background_threshold: float = 0.05
    matting_refinement_strength: float = 1.0
    matting_preserve_known_regions: bool = True
    matting_backend: MattingBackendId = "color_affinity"
    matting_onnx_model_path: str | None = None
    provider_options: Mapping[str, Any] = field(default_factory=dict)

    def with_provider(self, provider_id: str) -> ExtractionRuntimeConfig:
        return ExtractionRuntimeConfig(
            selected_provider_id=provider_id,
            edge_blur_radius=self.edge_blur_radius,
            feather_radius=self.feather_radius,
            cleanup_radius=self.cleanup_radius,
            expand_contract_pixels=self.expand_contract_pixels,
            premultiply_alpha=self.premultiply_alpha,
            matting_unknown_radius=self.matting_unknown_radius,
            matting_foreground_threshold=self.matting_foreground_threshold,
            matting_background_threshold=self.matting_background_threshold,
            matting_refinement_strength=self.matting_refinement_strength,
            matting_preserve_known_regions=self.matting_preserve_known_regions,
            matting_backend=self.matting_backend,
            matting_onnx_model_path=self.matting_onnx_model_path,
            provider_options=dict(self.provider_options),
        )

    def with_refinement(
        self,
        *,
        edge_blur_radius: float | None = None,
        feather_radius: float | None = None,
        cleanup_radius: int | None = None,
        expand_contract_pixels: int | None = None,
        premultiply_alpha: bool | None = None,
        matting_unknown_radius: int | None = None,
        matting_foreground_threshold: float | None = None,
        matting_background_threshold: float | None = None,
        matting_refinement_strength: float | None = None,
        matting_preserve_known_regions: bool | None = None,
        matting_backend: MattingBackendId | None = None,
        matting_onnx_model_path: str | None = None,
    ) -> ExtractionRuntimeConfig:
        return ExtractionRuntimeConfig(
            selected_provider_id=self.selected_provider_id,
            edge_blur_radius=(
                self.edge_blur_radius if edge_blur_radius is None else edge_blur_radius
            ),
            feather_radius=self.feather_radius if feather_radius is None else feather_radius,
            cleanup_radius=self.cleanup_radius if cleanup_radius is None else cleanup_radius,
            expand_contract_pixels=(
                self.expand_contract_pixels
                if expand_contract_pixels is None
                else expand_contract_pixels
            ),
            premultiply_alpha=(
                self.premultiply_alpha if premultiply_alpha is None else premultiply_alpha
            ),
            matting_unknown_radius=(
                self.matting_unknown_radius
                if matting_unknown_radius is None
                else matting_unknown_radius
            ),
            matting_foreground_threshold=(
                self.matting_foreground_threshold
                if matting_foreground_threshold is None
                else matting_foreground_threshold
            ),
            matting_background_threshold=(
                self.matting_background_threshold
                if matting_background_threshold is None
                else matting_background_threshold
            ),
            matting_refinement_strength=(
                self.matting_refinement_strength
                if matting_refinement_strength is None
                else matting_refinement_strength
            ),
            matting_preserve_known_regions=(
                self.matting_preserve_known_regions
                if matting_preserve_known_regions is None
                else matting_preserve_known_regions
            ),
            matting_backend=self.matting_backend if matting_backend is None else matting_backend,
            matting_onnx_model_path=(
                self.matting_onnx_model_path
                if matting_onnx_model_path is None
                else matting_onnx_model_path
            ),
            provider_options=dict(self.provider_options),
        )

    def settings_snapshot(self) -> dict[str, Any]:
        return {
            "feather_radius": float(self.feather_radius),
            "edge_blur_radius": float(self.edge_blur_radius),
            "expand_contract_pixels": int(self.expand_contract_pixels),
            "cleanup_radius": int(self.cleanup_radius),
            "remove_small_regions": False,
            "small_region_threshold": 0,
            "premultiply_alpha": bool(self.premultiply_alpha),
            "crop_mode": "full_source",
            "crop_padding": 0,
            "matting_unknown_radius": int(self.matting_unknown_radius),
            "matting_foreground_threshold": float(self.matting_foreground_threshold),
            "matting_background_threshold": float(self.matting_background_threshold),
            "matting_refinement_strength": float(self.matting_refinement_strength),
            "matting_preserve_known_regions": bool(self.matting_preserve_known_regions),
            "matting_backend": str(self.matting_backend),
        }
