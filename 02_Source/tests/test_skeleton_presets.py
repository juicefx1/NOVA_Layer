from nova_layer.domain.skeleton_presets import (
    BODY_25_CONNECTIONS,
    BODY_25_LABELS,
    openpose_body_25_preset,
)


def test_openpose_body_25_preset_has_stable_semantic_mapping() -> None:
    skeleton = openpose_body_25_preset()

    assert len(skeleton.joints) == 25
    assert len(skeleton.bones) == 24
    assert tuple(skeleton.semantic_joint_map()) == BODY_25_LABELS
    assert len(BODY_25_CONNECTIONS) == 24
    assert skeleton.semantic_joint_map()["nose"].y < skeleton.semantic_joint_map()["neck"].y
    assert (
        skeleton.semantic_joint_map()["left_ankle"].y > skeleton.semantic_joint_map()["left_knee"].y
    )
