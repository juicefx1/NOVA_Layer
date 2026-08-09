"""Phase D1 depth contract / canonicalization tests."""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from nova_layer.ports.depth import (
    DepthInferenceResult,
    DepthNormalization,
    InvalidDepthFrameError,
    canonicalize_depth_inference,
    copy_depth_frame,
)


def _base_result(depth: np.ndarray, valid_mask: np.ndarray | None = None) -> DepthInferenceResult:
    return DepthInferenceResult(
        depth=depth,
        valid_mask=valid_mask,
        quantity="relative_disparity",
        near_is="high",
        normalization=DepthNormalization(kind="model_native"),
        metadata={"k": "v"},
    )


def _canonicalize(
    depth: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    height: int | None = None,
    width: int | None = None,
    **kwargs: object,
):
    h = height if height is not None else int(depth.shape[0])
    w = width if width is not None else int(depth.shape[1])
    return canonicalize_depth_inference(
        _base_result(depth, valid_mask),
        frame_number=3,
        media_fingerprint="fp",
        source_model="fake_depth_v1",
        model_version="1.0.0",
        preprocessing_version="prep",
        expected_height=h,
        expected_width=w,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_floating_dtypes_become_float32(dtype: np.dtype) -> None:
    depth = np.linspace(0.0, 1.0, 12, dtype=dtype).reshape(3, 4)
    frame = _canonicalize(depth)
    assert frame.depth.dtype == np.float32
    assert frame.depth.shape == (3, 4)


def test_reject_channel_shapes() -> None:
    with pytest.raises(InvalidDepthFrameError, match="HxW"):
        _canonicalize(np.ones((4, 4, 1), dtype=np.float32), height=4, width=4)
    with pytest.raises(InvalidDepthFrameError, match="HxW"):
        _canonicalize(np.ones((4, 4, 3), dtype=np.float32), height=4, width=4)


def test_valid_mask_mismatch_and_bool() -> None:
    depth = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
    with pytest.raises(InvalidDepthFrameError, match="valid_mask"):
        _canonicalize(depth, valid_mask=np.ones((2, 2), dtype=bool))
    frame = _canonicalize(depth, valid_mask=np.ones((4, 4), dtype=np.uint8))
    assert frame.valid_mask is not None
    assert frame.valid_mask.dtype == bool


def test_partial_nan_and_inf_marked_invalid() -> None:
    depth = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
    depth[0, 0] = np.nan
    depth[1, 1] = np.inf
    frame = _canonicalize(depth)
    assert frame.valid_mask is not None
    assert not frame.valid_mask[0, 0]
    assert not frame.valid_mask[1, 1]
    assert bool(frame.valid_mask[2, 2])


def test_all_nan_rejected() -> None:
    depth = np.full((3, 3), np.nan, dtype=np.float32)
    with pytest.raises(InvalidDepthFrameError, match="no finite"):
        _canonicalize(depth)


def test_flat_map_rejected() -> None:
    depth = np.full((5, 5), 0.5, dtype=np.float32)
    with pytest.raises(InvalidDepthFrameError, match="flat"):
        _canonicalize(depth)


def test_input_arrays_unchanged_and_output_write_protected() -> None:
    depth = np.linspace(0.0, 1.0, 9, dtype=np.float32).reshape(3, 3)
    original = depth.copy()
    mask = np.ones((3, 3), dtype=bool)
    frame = _canonicalize(depth, valid_mask=mask)
    depth[0, 0] = 99.0
    mask[0, 0] = False
    assert np.array_equal(original, np.linspace(0.0, 1.0, 9, dtype=np.float32).reshape(3, 3))
    assert not frame.depth.flags.writeable
    assert frame.valid_mask is not None
    assert not frame.valid_mask.flags.writeable
    with pytest.raises(ValueError):
        frame.depth[0, 0] = 1.0


def test_metadata_mutation_protection() -> None:
    depth = np.linspace(0.0, 1.0, 9, dtype=np.float32).reshape(3, 3)
    meta = {"a": "1"}
    result = _base_result(depth)
    # Rebuild with mutable mapping
    result = DepthInferenceResult(
        depth=depth,
        valid_mask=None,
        quantity="relative_disparity",
        near_is="high",
        normalization=DepthNormalization(kind="model_native"),
        metadata=meta,
    )
    frame = canonicalize_depth_inference(
        result,
        frame_number=0,
        media_fingerprint="fp",
        source_model="m",
        model_version="1",
        preprocessing_version="p",
        expected_height=3,
        expected_width=3,
    )
    meta["a"] = "mutated"
    assert frame.metadata["a"] == "1"
    assert isinstance(frame.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        frame.metadata["b"] = "x"  # type: ignore[index]


def test_quantity_near_is_validation() -> None:
    depth = np.linspace(0.0, 1.0, 4, dtype=np.float32).reshape(2, 2)
    bad_quantity = DepthInferenceResult(
        depth=depth,
        valid_mask=None,
        quantity="relative_disparity",
        near_is="high",
        normalization=DepthNormalization(kind="model_native"),
        metadata={},
    )
    object.__setattr__(bad_quantity, "quantity", "not_a_quantity")  # type: ignore[misc]
    with pytest.raises(InvalidDepthFrameError, match="quantity"):
        canonicalize_depth_inference(
            bad_quantity,
            frame_number=0,
            media_fingerprint="fp",
            source_model="m",
            model_version="1",
            preprocessing_version="p",
            expected_height=2,
            expected_width=2,
        )

    bad_near = _base_result(depth)
    object.__setattr__(bad_near, "near_is", "sideways")  # type: ignore[misc]
    with pytest.raises(InvalidDepthFrameError, match="near_is"):
        canonicalize_depth_inference(
            bad_near,
            frame_number=0,
            media_fingerprint="fp",
            source_model="m",
            model_version="1",
            preprocessing_version="p",
            expected_height=2,
            expected_width=2,
        )


def test_copy_depth_frame_isolates_caller() -> None:
    depth = np.linspace(0.0, 1.0, 9, dtype=np.float32).reshape(3, 3)
    frame = _canonicalize(depth)
    copied = copy_depth_frame(frame)
    assert np.allclose(copied.depth, frame.depth)
    assert copied.depth is not frame.depth
