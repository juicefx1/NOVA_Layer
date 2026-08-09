"""Depth analysis service — SOURCE-only inference + cache (Phase D1)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from nova_layer.app.depth_frame_cache import DepthCacheKey, DepthFrameCache
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.ports.depth import (
    DepthAnalysisCancelled,
    DepthAnalysisCapability,
    DepthAnalysisError,
    DepthFrame,
    DepthModelUnavailableError,
    canonicalize_depth_inference,
    validate_source_rgb,
)

DEPTH_INPUT_POLICY = "source_v1"


class DepthAnalysisService:
    """Orchestrate SOURCE decode → depth capability → DepthFrame (+ cache)."""

    def __init__(
        self,
        *,
        frame_decoder: FrameDecodeService,
        capability: DepthAnalysisCapability,
        cache: DepthFrameCache | None = None,
    ) -> None:
        self._frame_decoder = frame_decoder
        self._capability = capability
        self._cache = cache if cache is not None else DepthFrameCache()

    @property
    def cache(self) -> DepthFrameCache:
        return self._cache

    @property
    def capability(self) -> DepthAnalysisCapability:
        return self._capability

    def cache_key(
        self,
        *,
        media_fingerprint: str,
        frame_number: int,
    ) -> DepthCacheKey:
        return DepthCacheKey(
            media_fingerprint=str(media_fingerprint),
            frame_number=int(frame_number),
            model_id=str(self._capability.model_id),
            model_version=str(self._capability.model_version),
            preprocessing_version=str(self._capability.preprocessing_version),
            input_policy=DEPTH_INPUT_POLICY,
        )

    def analyze(
        self,
        *,
        media_path: Path,
        media_fingerprint: str,
        frame_number: int,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DepthFrame:
        capability = self._capability
        if capability is None:  # pragma: no cover - guarded by constructor
            raise DepthModelUnavailableError("Depth analysis capability is not configured.")

        key = self.cache_key(
            media_fingerprint=media_fingerprint,
            frame_number=frame_number,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        self._check_cancel(should_cancel)

        image = self._load_source_frame(media_path, frame_number)
        height, width = validate_source_rgb(image)

        self._check_cancel(should_cancel)

        try:
            inference = capability.infer(frame_number=frame_number, image=image)
        except DepthAnalysisError:
            raise
        except Exception as exc:  # pragma: no cover - adapter bugs
            raise DepthAnalysisError(f"Depth inference failed: {exc}") from exc

        self._check_cancel(should_cancel)

        frame = canonicalize_depth_inference(
            inference,
            frame_number=frame_number,
            media_fingerprint=media_fingerprint,
            source_model=str(capability.model_id),
            model_version=str(capability.model_version),
            preprocessing_version=str(capability.preprocessing_version),
            expected_height=height,
            expected_width=width,
            input_policy="source_v1",
        )

        self._check_cancel(should_cancel)
        self._cache.put(key, frame)
        return frame

    def _load_source_frame(self, media_path: Path, frame_number: int) -> NDArray[np.uint8]:
        # Explicit SOURCE only — never preview/scene/OCIO display.
        frame = self._frame_decoder.get_processing_frame(
            media_path,
            frame_number,
            policy=ProcessingColorPolicy.SOURCE,
        )
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise DepthAnalysisError(
                "SOURCE processing frame must be an uint8 ndarray; "
                f"got {type(frame).__name__} dtype={getattr(frame, 'dtype', None)}"
            )
        return frame

    @staticmethod
    def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel is not None and should_cancel():
            raise DepthAnalysisCancelled("Depth analysis cancelled.")
