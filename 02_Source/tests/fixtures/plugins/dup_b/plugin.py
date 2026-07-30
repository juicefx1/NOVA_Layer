from __future__ import annotations

from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.ports.provider_registry import (
    ProviderCapabilities,
    ProviderDescriptor,
)


def register(context) -> None:  # type: ignore[no-untyped-def]
    descriptor = ProviderDescriptor(
        provider_id="plugin.test.duplicate_b",
        display_name="Duplicate B",
        provider_version="1.0.0",
        provider_kind="test",
        supported_intent_signals=("positive_point",),
        supported_devices=("cpu",),
        requires_model_artifact=False,
        availability="available",
        availability_message="dup b",
        capabilities=ProviderCapabilities(supports_positive_point=True, supports_cpu=True),
    )
    context.register_inference(descriptor, lambda _config: MockCoreInferenceEngine())
