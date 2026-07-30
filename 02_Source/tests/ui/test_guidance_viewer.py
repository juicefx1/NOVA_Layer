from __future__ import annotations

from pytestqt.qtbot import QtBot

from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer


def test_pose_correction_moves_joint_without_changing_topology(qtbot: QtBot) -> None:
    shoulder = SkeletonJoint(x=0.3, y=0.25, label="shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.7, label="wrist")
    skeleton = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.begin_skeleton_correction(skeleton)

    with qtbot.waitSignal(viewer.skeleton_correction_changed):
        viewer._move_correction_joint(shoulder.id, (0.42, 0.38))

    corrected = viewer.correction_skeleton
    assert corrected is not None
    assert corrected.joints[0].id == shoulder.id
    assert corrected.joints[0].x == 0.42
    assert corrected.joints[0].y == 0.38
    assert corrected.bones == skeleton.bones
    viewer.end_skeleton_correction()
    assert viewer.correction_skeleton is None
    assert viewer._mode == GuidanceMode.NAVIGATE


def test_skeleton_joint_label_update_emits_persistable_guidance(qtbot: QtBot) -> None:
    shoulder = SkeletonJoint(x=0.3, y=0.25)
    wrist = SkeletonJoint(x=0.6, y=0.7)
    skeleton = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.set_guidance([], None, skeleton)

    with qtbot.waitSignal(viewer.guidance_changed):
        assert viewer.set_skeleton_joint_label(shoulder.id, "left_shoulder")

    assert viewer.skeleton_guidance.semantic_joint_map()["left_shoulder"].id == shoulder.id
    assert not viewer.set_skeleton_joint_label(wrist.id, "left_shoulder")


def test_fusion_preview_is_isolated_from_authoritative_guidance(qtbot: QtBot) -> None:
    artist = SkeletonGuidance(joints=[SkeletonJoint(x=0.3, y=0.3, label="nose")])
    detected = SkeletonGuidance(joints=[SkeletonJoint(x=0.35, y=0.35, label="nose")])
    fused = SkeletonGuidance(joints=[artist.joints[0].model_copy(update={"x": 0.33, "y": 0.33})])
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.set_guidance([], None, artist)

    viewer.set_fusion_preview(
        detected,
        fused,
        joint_depths={"nose": 0.42},
        depth_confidences={"nose": 0.81},
    )

    assert viewer.skeleton_guidance == artist
    assert viewer._detected_skeleton == detected
    assert viewer._fused_skeleton == fused
    assert viewer._fusion_joint_depths == {"nose": 0.42}
    assert viewer._fusion_depth_confidences == {"nose": 0.81}
    viewer.set_fusion_preview(None, None)
    assert viewer._detected_skeleton is None
    assert viewer._fused_skeleton is None
    assert viewer._fusion_joint_depths == {}
    assert viewer._fusion_depth_confidences == {}
