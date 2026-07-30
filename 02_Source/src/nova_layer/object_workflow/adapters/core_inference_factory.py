from __future__ import annotations

from pathlib import Path

from nova_layer.object_workflow.adapters.core_inference_registry import (
    DEFAULT_MASK_THRESHOLD,
    DEFAULT_PROVIDER,
    ENV_CHECKPOINT,
    ENV_DEVICE,
    ENV_PROVIDER,
    build_default_core_inference_registry,
    default_sam2_checkpoint,
    runtime_config_from_environ,
)
from nova_layer.object_workflow.ports.core_inference import CoreInferenceEngine
from nova_layer.object_workflow.ports.provider_registry import ProviderRuntimeConfig

# Deprecated alias: prefer build_default_core_inference_registry().contains / list.
SUPPORTED_PROVIDERS = frozenset({"mock", "sam2"})


def resolve_provider_name(provider: str | None = None) -> str:
    """Thin compatibility wrapper over the default registry."""
    config = runtime_config_from_environ(selected_provider_id=provider)
    registry = build_default_core_inference_registry()
    provider_id = config.selected_provider_id
    if not registry.contains(provider_id):
        from nova_layer.object_workflow.application.errors import ApplicationError

        raise ApplicationError(
            "INVALID_PROVIDER_CONFIG",
            "unknown core inference provider: "
            f"{provider_id!r}; expected one of {[item.provider_id for item in registry.list()]}",
        )
    return provider_id


def create_core_inference_engine(
    provider: str | None = None,
    *,
    checkpoint: Path | None = None,
    device: str | None = None,
    mask_threshold: float = DEFAULT_MASK_THRESHOLD,
    registry: object | None = None,
    config: ProviderRuntimeConfig | None = None,
) -> CoreInferenceEngine:
    """Deprecated entrypoint: thin wrapper over CoreInferenceProviderRegistry.create.

    Prefer composition-root use of build_default_core_inference_registry().
    """
    from nova_layer.object_workflow.adapters.core_inference_registry import (
        CoreInferenceProviderRegistry,
    )

    active_registry = registry if isinstance(registry, CoreInferenceProviderRegistry) else (
        build_default_core_inference_registry()
    )
    runtime = config or runtime_config_from_environ(
        selected_provider_id=provider,
        device=device,
        checkpoint_path=checkpoint,
        mask_threshold=mask_threshold,
    )
    if provider is not None:
        runtime = runtime.with_provider(str(provider).strip().lower())
    return active_registry.create(runtime.selected_provider_id, runtime)


__all__ = [
    "DEFAULT_MASK_THRESHOLD",
    "DEFAULT_PROVIDER",
    "ENV_CHECKPOINT",
    "ENV_DEVICE",
    "ENV_PROVIDER",
    "SUPPORTED_PROVIDERS",
    "build_default_core_inference_registry",
    "create_core_inference_engine",
    "default_sam2_checkpoint",
    "resolve_provider_name",
    "runtime_config_from_environ",
]
