from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from nova_layer.object_workflow.adapters.mock_core_inference import (
    PROVIDER_VERSION as MOCK_PROVIDER_VERSION,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.ports.core_inference import CoreInferenceEngine
from nova_layer.object_workflow.ports.provider_registry import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderRuntimeConfig,
)

ProviderFactory = Callable[[ProviderRuntimeConfig], CoreInferenceEngine]
AvailabilityProbe = Callable[[ProviderRuntimeConfig], tuple[str, str]]

DEFAULT_PROVIDER = "mock"
ENV_PROVIDER = "NOVA_OBJECT_CORE_INFERENCE"
ENV_CHECKPOINT = "NOVA_SAM2_CHECKPOINT"
ENV_DEVICE = "NOVA_OBJECT_CORE_INFERENCE_DEVICE"
DEFAULT_MASK_THRESHOLD = 0.5


class CoreInferenceProviderRegistry:
    """Explicit composition-root registry for Core Inference providers."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._factories: dict[str, ProviderFactory] = {}
        self._descriptors: dict[str, ProviderDescriptor] = {}
        self._probes: dict[str, AvailabilityProbe] = {}

    def register(
        self,
        descriptor: ProviderDescriptor,
        factory: ProviderFactory,
        *,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        provider_id = descriptor.provider_id
        if provider_id in self._factories:
            raise ApplicationError(
                "DUPLICATE_PROVIDER",
                f"provider already registered: {provider_id!r}",
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
                f"unknown core inference provider: {provider_id!r}",
            )
        self._order = [item for item in self._order if item != provider_id]
        self._factories.pop(provider_id, None)
        self._descriptors.pop(provider_id, None)
        self._probes.pop(provider_id, None)

    def contains(self, provider_id: str) -> bool:
        return provider_id in self._factories

    def get(self, provider_id: str) -> ProviderDescriptor:
        if provider_id not in self._descriptors:
            raise ApplicationError(
                "INVALID_PROVIDER_CONFIG",
                f"unknown core inference provider: {provider_id!r}",
            )
        return self._resolved_descriptor(provider_id, ProviderRuntimeConfig())

    def list(self, config: ProviderRuntimeConfig | None = None) -> list[ProviderDescriptor]:
        runtime = config or ProviderRuntimeConfig()
        return [self._resolved_descriptor(provider_id, runtime) for provider_id in self._order]

    def create(
        self,
        provider_id: str,
        config: ProviderRuntimeConfig | None = None,
    ) -> CoreInferenceEngine:
        if provider_id not in self._factories:
            raise ApplicationError(
                "INVALID_PROVIDER_CONFIG",
                f"unknown core inference provider: {provider_id!r}",
            )
        runtime = config or ProviderRuntimeConfig(selected_provider_id=provider_id)
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
                f"failed to create provider {provider_id!r}: {exc}",
            ) from exc

    def _resolved_descriptor(
        self,
        provider_id: str,
        config: ProviderRuntimeConfig,
    ) -> ProviderDescriptor:
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


def runtime_config_from_environ(
    *,
    selected_provider_id: str | None = None,
    device: str | None = None,
    checkpoint_path: str | Path | None = None,
    mask_threshold: float | None = None,
) -> ProviderRuntimeConfig:
    """Single composition-root env reader for provider runtime settings."""
    env_provider = os.environ.get(ENV_PROVIDER, DEFAULT_PROVIDER)
    provider = (
        selected_provider_id if selected_provider_id is not None else env_provider
    ).strip().lower()
    env_device = os.environ.get(ENV_DEVICE, "auto")
    resolved_device: str = device if device is not None else env_device
    checkpoint: str | None
    if checkpoint_path is not None:
        checkpoint = str(Path(checkpoint_path).expanduser())
    else:
        configured = os.environ.get(ENV_CHECKPOINT)
        checkpoint = str(Path(configured).expanduser()) if configured else None
    threshold = DEFAULT_MASK_THRESHOLD if mask_threshold is None else mask_threshold
    return ProviderRuntimeConfig(
        selected_provider_id=provider,
        device=resolved_device,
        checkpoint_path=checkpoint,
        mask_threshold=threshold,
    )


def default_sam2_checkpoint() -> Path:
    configured = os.environ.get(ENV_CHECKPOINT)
    if configured:
        return Path(configured).expanduser()
    repo_root = Path(__file__).resolve().parents[5]
    return repo_root / "03_AI" / "models" / "sam2.1_hiera_tiny.pt"


def build_default_core_inference_registry() -> CoreInferenceProviderRegistry:
    """Explicit Mock + SAM2 registration. No entry-point discovery."""
    registry = CoreInferenceProviderRegistry()
    registry.register(_mock_descriptor(), _create_mock)
    registry.register(
        _sam2_descriptor(),
        _create_sam2,
        availability_probe=_probe_sam2_availability,
    )
    return registry


def _mock_descriptor() -> ProviderDescriptor:
    capabilities = ProviderCapabilities(
        supports_positive_point=True,
        supports_bounding_box=True,
        supports_negative_point=True,
        supports_scribble=False,
        supports_mask_prompt=False,
        supports_cpu=True,
        supports_gpu=False,
        supports_mps=False,
        requires_local_checkpoint=False,
    )
    return ProviderDescriptor(
        provider_id="mock",
        display_name="Mock (deterministic)",
        provider_version=MOCK_PROVIDER_VERSION,
        provider_kind="mock",
        supported_intent_signals=("positive_point", "negative_point", "bounding_box"),
        supported_devices=("cpu",),
        requires_model_artifact=False,
        availability="available",
        availability_message="Deterministic mock provider",
        capabilities=capabilities,
        configuration_keys=(),
    )


def _sam2_descriptor() -> ProviderDescriptor:
    try:
        provider_version = version("SAM-2")
    except PackageNotFoundError:
        provider_version = "not-installed"
    capabilities = ProviderCapabilities(
        supports_positive_point=True,
        supports_bounding_box=True,
        supports_negative_point=True,
        supports_scribble=False,
        supports_mask_prompt=False,
        supports_cpu=True,
        supports_gpu=True,
        supports_mps=True,
        requires_local_checkpoint=True,
    )
    return ProviderDescriptor(
        provider_id="sam2",
        display_name="SAM 2.1 Hiera Tiny",
        provider_version=provider_version,
        provider_kind="local_model",
        supported_intent_signals=("positive_point", "negative_point", "bounding_box"),
        supported_devices=("auto", "cpu", "mps", "cuda"),
        requires_model_artifact=True,
        availability="unavailable",
        availability_message="Availability not probed",
        capabilities=capabilities,
        configuration_keys=("device", "checkpoint_path", "mask_threshold"),
    )


def _create_mock(_config: ProviderRuntimeConfig) -> CoreInferenceEngine:
    return MockCoreInferenceEngine()


def _create_sam2(config: ProviderRuntimeConfig) -> CoreInferenceEngine:
    from nova_layer.object_workflow.adapters.sam2_core_inference import Sam2CoreInferenceEngine

    checkpoint = (
        Path(config.checkpoint_path).expanduser()
        if config.checkpoint_path
        else default_sam2_checkpoint()
    )
    return Sam2CoreInferenceEngine(
        checkpoint=checkpoint,
        device=config.device,
        mask_threshold=config.mask_threshold,
    )


def _probe_sam2_availability(config: ProviderRuntimeConfig) -> tuple[str, str]:
    checkpoint = (
        Path(config.checkpoint_path).expanduser()
        if config.checkpoint_path
        else default_sam2_checkpoint()
    )
    if not checkpoint.is_file():
        return "unavailable", f"MODEL_NOT_AVAILABLE: checkpoint not found: {checkpoint}"
    if importlib.util.find_spec("sam2") is None or importlib.util.find_spec("torch") is None:
        return (
            "unavailable",
            "MODEL_NOT_AVAILABLE: SAM-2 / torch packages are not installed",
        )
    return "available", f"SAM 2.1 checkpoint ready ({checkpoint.name})"
