from pathlib import Path

import numpy as np

from nova_layer.depth_pose_benchmark import DepthPoseBenchmarkCase
from nova_layer.depth_pose_review_assets import generate_review_assets, skeleton_overlay
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint
from nova_layer.ports.media import MediaInfo


class ReviewMediaReader:
    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path,
            fingerprint="review-media",
            frame_count=1,
            frame_rate=24.0,
            width=32,
            height=24,
            time_base="1/24",
            pixel_format="rgb24",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path, frame_number
        return np.zeros((24, 32, 3), dtype=np.uint8)


def pose() -> SkeletonGuidance:
    shoulder = SkeletonJoint(x=0.3, y=0.3, label="left_shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.7, label="left_wrist")
    return SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )


def test_skeleton_overlay_draws_colored_pixels() -> None:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    overlay = skeleton_overlay(frame, ((pose(), (255, 214, 64)),))

    assert overlay.shape == (24, 32, 4)
    assert np.count_nonzero(overlay[:, :, :3]) > 0
    assert np.all(overlay[:, :, 3] == 255)


def test_review_assets_include_images_labels_and_status(tmp_path: Path) -> None:
    case = DepthPoseBenchmarkCase(
        case_id="person/front",
        media_path=tmp_path / "person.mov",
        frame_number=0,
        artist_skeleton=pose(),
        ground_truth_skeleton=pose(),
        annotation_status="candidate",
        source_media_fingerprint="review-media",
    )

    index = generate_review_assets((case,), tmp_path / "review", media_reader=ReviewMediaReader())
    content = index.read_text(encoding="utf-8")

    assert "person/front" in content
    assert "left_shoulder" in content
    assert "candidate" in content
    assert (index.parent / "person-front_compare.png").is_file()
