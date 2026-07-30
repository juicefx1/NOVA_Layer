"""Application-owned video → frame → Background Removal orchestration.

Architecture (vertical slice):

    Video
      ↓
    Application (this service + ProjectController)
      ↓  per-frame RGB + Confirmed Mask
    BackgroundRemovalEngine.extract()   # black box, unchanged
      ↓
    RGBA frame
      ↓
    Application → existing Smart Layer exporter

The plugin never sees video, timeline, decode, or export.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
)

ProgressReporter = Callable[[int, int, str], None]
CancelChecker = Callable[[], bool]

PROVIDER_ID = "nova.background_removal"


@dataclass(frozen=True, slots=True)
class FrameExtractionInput:
    frame_number: int
    rgb: NDArray[np.uint8]
    mask: NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class FrameExtractionOutput:
    frame_number: int
    rgba: NDArray[np.uint8]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class VideoExtractionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_background_removal_engine_path(
    *,
    start: Path | None = None,
) -> Path:
    """Locate plugins/nova_background_removal/engine.py without Plugin SDK changes."""
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "plugins" / "nova_background_removal" / "engine.py"
        if candidate.is_file():
            return candidate
    raise VideoExtractionError(
        "PLUGIN_MISSING",
        "Background Removal plugin engine.py not found under plugins/",
    )


def load_background_removal_engine(
    config: ExtractionRuntimeConfig | None = None,
    *,
    engine_path: Path | None = None,
) -> Any:
    """Load BackgroundRemovalEngine via create_engine (plugin code unchanged)."""
    path = engine_path or resolve_background_removal_engine_path()
    module_name = f"nova_bg_removal_app_{abs(hash(str(path))) & 0xFFFFFFFF:x}"
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise VideoExtractionError(
                "PLUGIN_MISSING",
                f"Could not load Background Removal engine from {path}",
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    create_engine = getattr(module, "create_engine", None)
    if create_engine is None:
        raise VideoExtractionError(
            "PLUGIN_INVALID",
            "Background Removal engine module has no create_engine()",
        )
    runtime = config or ExtractionRuntimeConfig(selected_provider_id=PROVIDER_ID)
    return create_engine(runtime)


def grayscale_mask_to_binary(mask: NDArray[np.uint8]) -> BinaryMask:
    """Convert Smart Layer grayscale mask (0..255) to Confirmed BinaryMask (0/255)."""
    if mask.dtype != np.uint8 or mask.ndim != 2:
        raise VideoExtractionError(
            "INVALID_MASK",
            "confirmed mask must be a 2D uint8 array",
        )
    height, width = mask.shape
    binary = np.where(mask > 127, np.uint8(255), np.uint8(0))
    return BinaryMask.from_pixels(width, height, binary.tobytes())


class VideoExtractionService:
    """Per-frame Background Removal orchestration (Application layer only)."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def extract_frame(
        self,
        item: FrameExtractionInput,
        *,
        should_cancel: CancelChecker | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> FrameExtractionOutput:
        if should_cancel is not None and should_cancel():
            raise VideoExtractionError("CANCELLED", "extraction cancelled")

        rgb = np.ascontiguousarray(item.rgb)
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise VideoExtractionError(
                "INVALID_FRAME",
                "frame must be RGB uint8 with shape (H, W, 3)",
            )
        height, width, _ = rgb.shape
        if item.mask.shape != (height, width):
            raise VideoExtractionError(
                "DIMENSION_MISMATCH",
                f"mask {item.mask.shape} does not match frame {(height, width)}",
            )

        confirmed = grayscale_mask_to_binary(item.mask)
        options = dict(provider_options or {})
        if should_cancel is not None:
            options["should_cancel"] = should_cancel

        request = PrecisionExtractionRequest(
            request_id=str(uuid4()),
            source_width=width,
            source_height=height,
            source_rgb=rgb.tobytes(),
            mask=confirmed,
            provider_options=options,
        )
        result = self._engine.extract(request)
        if isinstance(result, PrecisionExtractionError):
            raise VideoExtractionError(result.error_code, result.message)
        if not isinstance(result, PrecisionExtractionSuccess):
            raise VideoExtractionError(
                "EXTRACTION_FAILED",
                f"unexpected extraction result type: {type(result)!r}",
            )

        rgba = np.frombuffer(result.image.data, dtype=np.uint8).reshape(
            (result.image.height, result.image.width, 4)
        ).copy()
        diagnostics = dict(result.diagnostics or {})
        diagnostics["provider_id"] = result.provider_id
        diagnostics["provider_version"] = result.provider_version
        return FrameExtractionOutput(
            frame_number=item.frame_number,
            rgba=rgba,
            diagnostics=diagnostics,
        )

    def extract_frames(
        self,
        items: Sequence[FrameExtractionInput],
        *,
        report_progress: ProgressReporter | None = None,
        should_cancel: CancelChecker | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> list[FrameExtractionOutput]:
        total = len(items)
        outputs: list[FrameExtractionOutput] = []
        for index, item in enumerate(items, start=1):
            if should_cancel is not None and should_cancel():
                raise VideoExtractionError("CANCELLED", "extraction cancelled")
            if report_progress is not None:
                report_progress(
                    index - 1,
                    total,
                    f"Background Removal frame {item.frame_number}",
                )
            outputs.append(
                self.extract_frame(
                    item,
                    should_cancel=should_cancel,
                    provider_options=provider_options,
                )
            )
            if report_progress is not None:
                report_progress(
                    index,
                    total,
                    f"Background Removal frame {item.frame_number} done",
                )
        return outputs
