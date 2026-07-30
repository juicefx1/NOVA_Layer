"""Background Removal plugin entry — registers matting provider only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from nova_layer.object_workflow.ports.extraction_provider import (
    ExtractionProviderCapabilities,
    ExtractionProviderDescriptor,
    ExtractionRuntimeConfig,
)


def _load_engine_module() -> Any:
    engine_path = Path(__file__).resolve().parent / "engine.py"
    module_name = "nova_background_removal_engine"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None) == str(engine_path):
        return existing
    spec = importlib.util.spec_from_file_location(module_name, engine_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load engine module from {engine_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def register(context) -> None:  # type: ignore[no-untyped-def]
    engine_mod = _load_engine_module()
    provider_id = engine_mod.PROVIDER_ID
    descriptor = ExtractionProviderDescriptor(
        provider_id=provider_id,
        display_name="Background Removal",
        provider_version=engine_mod.PROVIDER_VERSION,
        provider_kind="local",
        requires_model=False,
        availability="available",
        availability_message="deterministic ConfirmedMaskRefine backend",
        capabilities=ExtractionProviderCapabilities(
            supports_binary_mask=True,
            supports_alpha_matting=True,
            supports_premultiply_alpha=False,
            requires_model=False,
        ),
        configuration_keys=("matting_onnx_model_path",),
    )

    def factory(config: ExtractionRuntimeConfig):
        return engine_mod.create_engine(config)

    context.register_matting(
        descriptor,
        factory,
        availability_probe=engine_mod.probe_availability,
    )
