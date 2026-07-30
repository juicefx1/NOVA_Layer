from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from nova_layer.object_workflow.adapters.local_matting_extraction import (
    PROVIDER_VERSION as MATTING_PROVIDER_VERSION,
)
from nova_layer.object_workflow.adapters.local_matting_extraction import (
    LocalMattingExtractionEngine,
    probe_matting_availability,
)
from nova_layer.object_workflow.adapters.local_precision_extraction import (
    LocalPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    PROVIDER_VERSION as MOCK_PROVIDER_VERSION,
)
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.ports.extraction_provider import (
    ExtractionProviderCapabilities,
    ExtractionProviderDescriptor,
    ExtractionRuntimeConfig,
)
from nova_layer.object_workflow.ports.precision_extraction import PrecisionExtractionEngine

ExtractionFactory = Callable[[ExtractionRuntimeConfig], PrecisionExtractionEngine]
AvailabilityProbe = Callable[[ExtractionRuntimeConfig], tuple[str, str]]

DEFAULT_EXTRACTION_PROVIDER = "mock"
ENV_EXTRACTION_PROVIDER = "NOVA_OBJECT_PRECISION_EXTRACTION"
ENV_EDGE_BLUR = "NOVA_OBJECT_EXTRACTION_EDGE_BLUR"
ENV_FEATHER = "NOVA_OBJECT_EXTRACTION_FEATHER"
ENV_CLEANUP = "NOVA_OBJECT_EXTRACTION_CLEANUP"


class PrecisionExtractionProviderRegistry:
    """Explicit composition-root registry for Precision Extraction providers."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._factories: dict[str, ExtractionFactory] = {}
        self._descriptors: dict[str, ExtractionProviderDescriptor] = {}
        self._probes: dict[str, AvailabilityProbe] = {}

    def register(
        self,
        descriptor: ExtractionProviderDescriptor,
        factory: ExtractionFactory,
        *,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        provider_id = descriptor.provider_id
        if provider_id in self._factories:
            raise ApplicationError(
                "DUPLICATE_PROVIDER",
                f"extraction provider already registered: {provider_id!r}",
            )
        self._order.append(provider_id)
        self._factories[provider_id] = factory
        self._descriptors[provider_id] = descriptor
        if availability_probe is not None:
            self._probes[provider_id] = availability_probe

    def unregister(self, provider_id: str) -> None:
        if provider_id not in self._factories:
            raise ApplicationError(
                "INVALID_PROVIDER_CONFIG",
                f"unknown extraction provider: {provider_id!r}",
            )
        self._order = [item for item in self._order if item != provider_id]
        self._factories.pop(provider_id, None)
        self._descriptors.pop(provider_id, None)
        self._probes.pop(provider_id, None)

    def contains(self, provider_id: str) -> bool:
        return provider_id in self._factories

    def get(self, provider_id: str) -> ExtractionProviderDescriptor:
        if provider_id not in self._descriptors:
            raise ApplicationError(
                "INVALID_PROVIDER_CONFIG",
                f"unknown extraction provider: {provider_id!r}",
            )
        return self._resolved_descriptor(provider_id, ExtractionRuntimeConfig())

    def list(
        self, config: ExtractionRuntimeConfig | None = None
    ) -> list[ExtractionProviderDescriptor]:
        runtime = config or ExtractionRuntimeConfig()
        return [self._resolved_descriptor(provider_id, runtime) for provider_id in self._order]

    def create(
        self,
        provider_id: str,
        config: ExtractionRuntimeConfig | None = None,
    ) -> PrecisionExtractionEngine:
        if provider_id not in self._factories:
            raise ApplicationError(
                "INVALID_PROVIDER_CONFIG",
                f"unknown extraction provider: {provider_id!r}",
            )
        runtime = config or ExtractionRuntimeConfig(selected_provider_id=provider_id)
        descriptor = self._resolved_descriptor(provider_id, runtime)
        if descriptor.availability != "available":
            raise ApplicationError(
                "PROVIDER_UNAVAILABLE",
                descriptor.availability_message or f"provider unavailable: {provider_id}",
            )
        try:
            return self._factories[provider_id](runtime)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                "PROVIDER_CREATE_FAILED",
                f"failed to create extraction provider {provider_id!r}: {exc}",
            ) from exc

    def _resolved_descriptor(
        self,
        provider_id: str,
        config: ExtractionRuntimeConfig,
    ) -> ExtractionProviderDescriptor:
        base = self._descriptors[provider_id]
        probe = self._probes.get(provider_id)
        if probe is None:
            return base
        availability, message = probe(config)
        return replace(
            base,
            availability="available" if availability == "available" else "unavailable",
            availability_message=message,
        )


def extraction_runtime_config_from_environ(
    *,
    selected_provider_id: str | None = None,
    edge_blur_radius: float | None = None,
    feather_radius: float | None = None,
    cleanup_radius: int | None = None,
    expand_contract_pixels: int | None = None,
    premultiply_alpha: bool | None = None,
) -> ExtractionRuntimeConfig:
    env_provider = os.environ.get(ENV_EXTRACTION_PROVIDER, DEFAULT_EXTRACTION_PROVIDER)
    provider = (
        selected_provider_id if selected_provider_id is not None else env_provider
    ).strip().lower()

    def _float_env(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        return float(raw)

    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        return int(raw)

    def _bool_env(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    return ExtractionRuntimeConfig(
        selected_provider_id=provider,
        edge_blur_radius=(
            edge_blur_radius
            if edge_blur_radius is not None
            else _float_env(ENV_EDGE_BLUR, 0.0)
        ),
        feather_radius=(
            feather_radius if feather_radius is not None else _float_env(ENV_FEATHER, 0.0)
        ),
        cleanup_radius=(
            cleanup_radius if cleanup_radius is not None else _int_env(ENV_CLEANUP, 0)
        ),
        expand_contract_pixels=(
            expand_contract_pixels
            if expand_contract_pixels is not None
            else _int_env("NOVA_OBJECT_EXTRACTION_EXPAND", 0)
        ),
        premultiply_alpha=(
            premultiply_alpha
            if premultiply_alpha is not None
            else _bool_env("NOVA_OBJECT_EXTRACTION_PREMULTIPLY", False)
        ),
    )


def build_default_precision_extraction_registry() -> PrecisionExtractionProviderRegistry:
    registry = PrecisionExtractionProviderRegistry()
    registry.register(_mock_descriptor(), _create_mock)
    registry.register(_real_descriptor(), _create_real)
    registry.register(
        _matting_descriptor(),
        _create_matting,
        availability_probe=lambda _config: probe_matting_availability(),
    )
    return registry


def create_precision_extraction_engine(
    provider: str | None = None,
    *,
    edge_blur_radius: float | None = None,
    feather_radius: float | None = None,
    cleanup_radius: int | None = None,
    registry: PrecisionExtractionProviderRegistry | None = None,
    config: ExtractionRuntimeConfig | None = None,
) -> PrecisionExtractionEngine:
    """Thin compatibility wrapper over PrecisionExtractionProviderRegistry.create."""
    active = registry or build_default_precision_extraction_registry()
    runtime = config or extraction_runtime_config_from_environ(
        selected_provider_id=provider,
        edge_blur_radius=edge_blur_radius,
        feather_radius=feather_radius,
        cleanup_radius=cleanup_radius,
    )
    if provider is not None:
        runtime = runtime.with_provider(str(provider).strip().lower())
    return active.create(runtime.selected_provider_id, runtime)


def _mock_descriptor() -> ExtractionProviderDescriptor:
    return ExtractionProviderDescriptor(
        provider_id="mock",
        display_name="Mock Extraction",
        provider_version=MOCK_PROVIDER_VERSION,
        provider_kind="mock",
        requires_model=False,
        availability="available",
        availability_message="Deterministic mock extraction",
        capabilities=ExtractionProviderCapabilities(
            supports_binary_mask=True,
            supports_edge_feather=False,
            supports_morphological_cleanup=False,
            supports_edge_blur=False,
            requires_model=False,
        ),
        configuration_keys=(),
    )


def _real_descriptor() -> ExtractionProviderDescriptor:
    return ExtractionProviderDescriptor(
        provider_id="real",
        display_name="Local Edge-Refined Extraction",
        provider_version="1.0.0",
        provider_kind="local",
        requires_model=False,
        availability="available",
        availability_message="Local deterministic RGBA extraction",
        capabilities=ExtractionProviderCapabilities(
            supports_binary_mask=True,
            supports_edge_feather=True,
            supports_morphological_cleanup=True,
            supports_edge_blur=True,
            supports_expand_contract=True,
            supports_premultiply_alpha=True,
            requires_model=False,
        ),
        configuration_keys=(
            "edge_blur_radius",
            "feather_radius",
            "cleanup_radius",
            "expand_contract_pixels",
            "premultiply_alpha",
        ),
    )


def _matting_descriptor() -> ExtractionProviderDescriptor:
    return ExtractionProviderDescriptor(
        provider_id="matting",
        display_name="Local Alpha Matting",
        provider_version=MATTING_PROVIDER_VERSION,
        provider_kind="local",
        requires_model=False,
        availability="available",
        availability_message="CPU colour-affinity alpha matting",
        capabilities=ExtractionProviderCapabilities(
            supports_binary_mask=True,
            supports_edge_feather=False,
            supports_morphological_cleanup=True,
            supports_edge_blur=True,
            supports_alpha_matting=True,
            supports_expand_contract=True,
            supports_premultiply_alpha=True,
            requires_model=False,
        ),
        configuration_keys=(
            "matting_unknown_radius",
            "matting_refinement_strength",
            "matting_preserve_known_regions",
            "matting_backend",
            "expand_contract_pixels",
            "edge_blur_radius",
            "cleanup_radius",
            "premultiply_alpha",
        ),
    )


def _create_mock(_config: ExtractionRuntimeConfig) -> PrecisionExtractionEngine:
    return MockPrecisionExtractionEngine()


def _create_real(config: ExtractionRuntimeConfig) -> PrecisionExtractionEngine:
    return LocalPrecisionExtractionEngine(
        edge_blur_radius=config.edge_blur_radius,
        feather_radius=config.feather_radius,
        cleanup_radius=config.cleanup_radius,
        expand_contract_pixels=config.expand_contract_pixels,
        premultiply_alpha=config.premultiply_alpha,
    )


def _create_matting(config: ExtractionRuntimeConfig) -> PrecisionExtractionEngine:
    return LocalMattingExtractionEngine(
        edge_blur_radius=config.edge_blur_radius,
        expand_contract_pixels=config.expand_contract_pixels,
        cleanup_radius=config.cleanup_radius,
        premultiply_alpha=config.premultiply_alpha,
        matting_unknown_radius=config.matting_unknown_radius,
        matting_foreground_threshold=config.matting_foreground_threshold,
        matting_background_threshold=config.matting_background_threshold,
        matting_refinement_strength=config.matting_refinement_strength,
        matting_preserve_known_regions=config.matting_preserve_known_regions,
        matting_backend=config.matting_backend,
        matting_onnx_model_path=config.matting_onnx_model_path,
    )
