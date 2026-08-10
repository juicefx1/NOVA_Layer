"""Depth analysis port contracts (Phase D1).

Depth is a coarse spatial prior only — never a final matte.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray


class DepthAnalysisError(RuntimeError):
    """Base error for depth analysis failures."""


class DepthModelUnavailableError(DepthAnalysisError):
    """Depth capability or model cannot be used."""


class DepthBackendUnavailableError(DepthModelUnavailableError):
    """Optional depth backend dependency or configuration is unavailable."""


class DepthModelWeightsMissingError(DepthModelUnavailableError):
    """Configured depth model weights are missing or inaccessible."""


class DepthModelLoadError(DepthAnalysisError):
    """Depth model architecture/weights failed to load."""


class DepthInferenceError(DepthAnalysisError):
    """Depth model inference failed after a successful load."""


class InvalidDepthFrameError(DepthAnalysisError):
    """Inference result failed DepthFrame canonicalization/validation."""


class DepthAnalysisCancelled(Exception):
    """Soft cancel; mapped to job cancelled (not failed)."""


@dataclass(frozen=True, slots=True)
class DepthNormalization:
    kind: Literal["model_native", "affine"]
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True, slots=True)
class DepthInferenceResult:
    depth: NDArray[np.floating]
    valid_mask: NDArray[np.bool_] | None
    quantity: Literal[
        "relative_disparity",
        "relative_metric",
        "absolute_metric",
    ]
    near_is: Literal["high", "low"]
    normalization: DepthNormalization
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DepthFrame:
    frame_number: int
    media_fingerprint: str
    depth: NDArray[np.float32]
    valid_mask: NDArray[np.bool_] | None
    quantity: Literal[
        "relative_disparity",
        "relative_metric",
        "absolute_metric",
    ]
    near_is: Literal["high", "low"]
    normalization: DepthNormalization
    source_model: str
    model_version: str
    preprocessing_version: str
    input_policy: Literal["source_v1"]
    metadata: Mapping[str, str]


class DepthAnalysisCapability(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def preprocessing_version(self) -> str: ...

    def infer(
        self,
        *,
        frame_number: int,
        image: NDArray[np.uint8],
    ) -> DepthInferenceResult:
        """Infer relative/absolute depth from a SOURCE uint8 RGB frame (HxWx3)."""
        ...


_QUANTITIES = frozenset({"relative_disparity", "relative_metric", "absolute_metric"})
_NEAR_IS = frozenset({"high", "low"})


def freeze_mapping(metadata: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({str(key): str(value) for key, value in metadata.items()})


def freeze_depth_array(array: NDArray[np.float32]) -> NDArray[np.float32]:
    frozen = np.array(array, dtype=np.float32, copy=True)
    frozen.setflags(write=False)
    return frozen


def freeze_valid_mask(mask: NDArray[np.bool_] | None) -> NDArray[np.bool_] | None:
    if mask is None:
        return None
    frozen = np.asarray(mask, dtype=bool).copy()
    frozen.setflags(write=False)
    return frozen


def copy_depth_frame(frame: DepthFrame) -> DepthFrame:
    """Return a caller-safe copy with write-protected arrays."""
    return DepthFrame(
        frame_number=int(frame.frame_number),
        media_fingerprint=str(frame.media_fingerprint),
        depth=freeze_depth_array(frame.depth),
        valid_mask=freeze_valid_mask(frame.valid_mask),
        quantity=frame.quantity,
        near_is=frame.near_is,
        normalization=frame.normalization,
        source_model=str(frame.source_model),
        model_version=str(frame.model_version),
        preprocessing_version=str(frame.preprocessing_version),
        input_policy="source_v1",
        metadata=freeze_mapping(frame.metadata),
    )


def canonicalize_depth_inference(
    result: DepthInferenceResult,
    *,
    frame_number: int,
    media_fingerprint: str,
    source_model: str,
    model_version: str,
    preprocessing_version: str,
    expected_height: int,
    expected_width: int,
    input_policy: Literal["source_v1"] = "source_v1",
) -> DepthFrame:
    """Validate and freeze a capability inference result into a DepthFrame."""
    if input_policy != "source_v1":
        raise InvalidDepthFrameError(f"Unsupported depth input policy: {input_policy}")
    if result.quantity not in _QUANTITIES:
        raise InvalidDepthFrameError(f"Unsupported depth quantity: {result.quantity!r}")
    if result.near_is not in _NEAR_IS:
        raise InvalidDepthFrameError(f"Unsupported near_is: {result.near_is!r}")
    if not isinstance(result.normalization, DepthNormalization):
        raise InvalidDepthFrameError("normalization must be DepthNormalization")

    depth_in = result.depth
    if not isinstance(depth_in, np.ndarray):
        raise InvalidDepthFrameError("depth must be a numpy ndarray")
    if depth_in.ndim != 2:
        raise InvalidDepthFrameError(
            f"depth must be HxW; got ndim={depth_in.ndim} shape={depth_in.shape}"
        )
    if depth_in.shape != (expected_height, expected_width):
        raise InvalidDepthFrameError(
            "depth shape must match SOURCE frame "
            f"({expected_height}, {expected_width}); got {depth_in.shape}"
        )
    if not np.issubdtype(depth_in.dtype, np.floating):
        raise InvalidDepthFrameError(f"depth dtype must be floating; got {depth_in.dtype}")

    depth = np.array(depth_in, dtype=np.float32, copy=True)

    valid: NDArray[np.bool_]
    if result.valid_mask is None:
        valid = np.isfinite(depth)
    else:
        mask_in = result.valid_mask
        if not isinstance(mask_in, np.ndarray):
            raise InvalidDepthFrameError("valid_mask must be a numpy ndarray or None")
        if mask_in.shape != depth.shape:
            raise InvalidDepthFrameError(
                f"valid_mask shape {mask_in.shape} must match depth {depth.shape}"
            )
        valid = np.asarray(mask_in, dtype=bool).copy()
        # Non-finite depth is always invalid regardless of provided mask.
        valid &= np.isfinite(depth)

    if not bool(np.any(valid)):
        raise InvalidDepthFrameError("depth map has no finite valid pixels")

    values = depth[valid]
    if values.size == 0 or float(np.nanmax(values) - np.nanmin(values)) == 0.0:
        raise InvalidDepthFrameError("flat depth map is not allowed in D1")

    # Mark non-finite as NaN for clarity while keeping invalid bits in mask.
    depth = np.where(valid, depth, np.float32(np.nan))

    return DepthFrame(
        frame_number=int(frame_number),
        media_fingerprint=str(media_fingerprint),
        depth=freeze_depth_array(depth),
        valid_mask=freeze_valid_mask(valid),
        quantity=result.quantity,
        near_is=result.near_is,
        normalization=DepthNormalization(
            kind=result.normalization.kind,
            scale=float(result.normalization.scale),
            offset=float(result.normalization.offset),
        ),
        source_model=str(source_model),
        model_version=str(model_version),
        preprocessing_version=str(preprocessing_version),
        input_policy="source_v1",
        metadata=freeze_mapping(result.metadata),
    )


def validate_source_rgb(image: NDArray[np.uint8]) -> tuple[int, int]:
    """Validate SOURCE uint8 RGB input; returns (height, width)."""
    if not isinstance(image, np.ndarray):
        raise InvalidDepthFrameError("SOURCE image must be a numpy ndarray")
    if image.dtype != np.uint8:
        raise InvalidDepthFrameError(f"SOURCE image must be uint8; got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise InvalidDepthFrameError(
            f"SOURCE image must be HxWx3 uint8; got shape {getattr(image, 'shape', None)}"
        )
    height, width = int(image.shape[0]), int(image.shape[1])
    if height < 1 or width < 1:
        raise InvalidDepthFrameError("SOURCE image dimensions must be positive")
    return height, width
