from __future__ import annotations

from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.ports.extraction_provider import (
    ExtractionProviderCapabilities,
    ExtractionProviderDescriptor,
)


def register(context) -> None:  # type: ignore[no-untyped-def]
    descriptor = ExtractionProviderDescriptor(
        provider_id="plugin.test.fake_matting",
        display_name="Fake Matting Plugin",
        provider_version="1.0.0",
        provider_kind="test",
        requires_model=False,
        availability="available",
        availability_message="fake matting plugin",
        capabilities=ExtractionProviderCapabilities(
            supports_binary_mask=True,
            supports_alpha_matting=True,
        ),
    )
    context.register_matting(descriptor, lambda _config: MockPrecisionExtractionEngine())
