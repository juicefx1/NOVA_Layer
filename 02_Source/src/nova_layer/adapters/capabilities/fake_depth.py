"""Deterministic fake depth capability for Phase D1 (no network / no real model)."""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

from nova_layer.ports.depth import (
    DepthInferenceResult,
    DepthNormalization,
    InvalidDepthFrameError,
    validate_source_rgb,
)

FAKE_DEPTH_MODEL_ID = "fake_depth_v1"
FAKE_DEPTH_MODEL_VERSION = "1.0.0"
FAKE_DEPTH_PREPROCESSING_VERSION = "source_uint8_rgb_v1"


class FakeDepthAnalysisCapability:
    """SOURCE uint8 → deterministic float32 HxW relative depth (luma + x gradient)."""

    def __init__(
        self,
        *,
        near_is: Literal["high", "low"] = "high",
        quantity: Literal[
            "relative_disparity",
            "relative_metric",
            "absolute_metric",
        ] = "relative_disparity",
    ) -> None:
        self._near_is = near_is
        self._quantity = quantity
        self.call_count = 0
        self.last_image_id: int | None = None

    @property
    def model_id(self) -> str:
        return FAKE_DEPTH_MODEL_ID

    @property
    def model_version(self) -> str:
        return FAKE_DEPTH_MODEL_VERSION

    @property
    def preprocessing_version(self) -> str:
        return FAKE_DEPTH_PREPROCESSING_VERSION

    def infer(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
    ) -> DepthInferenceResult:
        del frame_number
        validate_source_rgb(image)
        self.call_count += 1
        self.last_image_id = int(id(image))

        height, width = image.shape[:2]
        luma = image.astype(np.float32).mean(axis=2) / np.float32(255.0)
        xx = np.linspace(0.0, 1.0, num=width, dtype=np.float32)
        gradient = np.broadcast_to(xx, (height, width))
        depth = luma + gradient
        if self._near_is == "low":
            depth = -depth

        if float(np.max(depth) - np.min(depth)) == 0.0:  # pragma: no cover
            raise InvalidDepthFrameError("fake depth produced a flat map")

        return DepthInferenceResult(
            depth=depth,
            valid_mask=None,
            quantity=self._quantity,
            near_is=self._near_is,
            normalization=DepthNormalization(kind="model_native"),
            metadata={
                "adapter": "fake_depth",
                "formula": "luma_norm + x_gradient",
            },
        )
