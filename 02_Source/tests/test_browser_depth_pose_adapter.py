import numpy as np
import pytest

from nova_layer.adapters.capabilities.browser_depth_pose import (
    BrowserDepthPoseDetectionCapability,
)
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint


def _artist_skeleton() -> SkeletonGuidance:
    shoulder = SkeletonJoint(x=0.3, y=0.3, label="left_shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.6, label="left_wrist")
    return SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )


def test_browser_bridge_maps_json_to_detection_result() -> None:
    def provider(frame: int, image: object, labels: tuple[str, ...]) -> dict[str, object]:
        del image
        assert labels == ("left_shoulder", "left_wrist")
        return {
            "schema_version": "1.0",
            "frame_number": frame,
            "width": 16,
            "height": 8,
            "pose_model": "mediapipe-pose-full",
            "depth_model": "depth-anything-v2-small",
            "runtime": "webgpu",
            "joints": [
                {
                    "label": "left_shoulder",
                    "x": 0.32,
                    "y": 0.31,
                    "confidence": 0.9,
                    "depth_confidence": 0.8,
                    "depth": 0.42,
                },
                {
                    "label": "left_wrist",
                    "x": 0.62,
                    "y": 0.61,
                    "confidence": 0.85,
                    "depth_confidence": 0.75,
                },
            ],
        }

    adapter = BrowserDepthPoseDetectionCapability(provider)
    result = adapter.detect(
        frame_number=4,
        image=np.zeros((8, 16, 3), dtype=np.uint8),
        artist_skeleton=_artist_skeleton(),
    )

    assert len(result.skeleton.joints) == 2
    assert len(result.skeleton.bones) == 1
    assert result.joint_confidences["left_shoulder"] == 0.9
    assert result.depth_confidences["left_wrist"] == 0.75
    assert result.joint_depths == {"left_shoulder": 0.42}
    assert result.provenance.device == "browser"
    assert "depth-anything-v2-small" in (result.provenance.model_identifier or "")


def test_browser_bridge_rejects_non_finite_depth() -> None:
    def provider(frame: int, image: object, labels: tuple[str, ...]) -> dict[str, object]:
        del image, labels
        return {
            "schema_version": "1.0",
            "frame_number": frame,
            "width": 16,
            "height": 8,
            "pose_model": "pose",
            "depth_model": "depth",
            "runtime": "wasm",
            "joints": [
                {
                    "label": "left_shoulder",
                    "x": 0.32,
                    "y": 0.31,
                    "confidence": 0.9,
                    "depth_confidence": 0.8,
                    "depth": float("nan"),
                }
            ],
        }

    adapter = BrowserDepthPoseDetectionCapability(provider)
    with pytest.raises(ValueError, match="depth must be finite"):
        adapter.detect(
            frame_number=4,
            image=np.zeros((8, 16, 3), dtype=np.uint8),
            artist_skeleton=_artist_skeleton(),
        )


def test_browser_bridge_rejects_wrong_frame_or_dimensions() -> None:
    def provider(frame: int, image: object, labels: tuple[str, ...]) -> dict[str, object]:
        del frame, image, labels
        return {
            "schema_version": "1.0",
            "frame_number": 99,
            "width": 16,
            "height": 8,
            "pose_model": "pose",
            "depth_model": "depth",
            "runtime": "wasm",
            "joints": [],
        }

    adapter = BrowserDepthPoseDetectionCapability(provider)
    with pytest.raises(ValueError, match="frame does not match"):
        adapter.detect(
            frame_number=4,
            image=np.zeros((8, 16, 3), dtype=np.uint8),
            artist_skeleton=_artist_skeleton(),
        )
