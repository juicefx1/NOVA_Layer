from __future__ import annotations

from nova_layer.object_workflow.adapters.core_inference_factory import (
    create_core_inference_engine,
    default_sam2_checkpoint,
)
from nova_layer.object_workflow.adapters.core_inference_registry import (
    CoreInferenceProviderRegistry,
    build_default_core_inference_registry,
)
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.local_matting_extraction import (
    LocalMattingExtractionEngine,
)
from nova_layer.object_workflow.adapters.local_precision_extraction import (
    LocalPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    PrecisionExtractionProviderRegistry,
    build_default_precision_extraction_registry,
    create_precision_extraction_engine,
)
from nova_layer.object_workflow.adapters.sam2_core_inference import Sam2CoreInferenceEngine
from nova_layer.object_workflow.adapters.source_probe import probe_source_bytes

__all__ = [
    "CoreInferenceProviderRegistry",
    "JsonProjectStore",
    "LocalMattingExtractionEngine",
    "LocalPrecisionExtractionEngine",
    "MockCoreInferenceEngine",
    "MockOperationExecutor",
    "MockPrecisionExtractionEngine",
    "PrecisionExtractionProviderRegistry",
    "Sam2CoreInferenceEngine",
    "build_default_core_inference_registry",
    "build_default_precision_extraction_registry",
    "create_core_inference_engine",
    "create_precision_extraction_engine",
    "default_sam2_checkpoint",
    "probe_source_bytes",
]
