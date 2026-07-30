import json
from pathlib import Path
from uuid import uuid4

import pytest

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.depth_pose_dataset import export_case
from nova_layer.domain.models import (
    ArtistIntent,
    CapabilityProvenance,
    MediaReference,
    Project,
    Sequence,
    Shot,
    SkeletonCorrection,
    SkeletonFusionCandidate,
    SkeletonGuidance,
    SkeletonJoint,
    SmartLayer,
)
from nova_layer.ui.workspace import WorkspaceWindow


def project_with_correction(media_path: Path, *, include_correction: bool = True) -> Project:
    rough = SkeletonGuidance(joints=[SkeletonJoint(x=0.3, y=0.4, label="left_shoulder")])
    corrected = SkeletonGuidance(joints=[SkeletonJoint(x=0.34, y=0.38, label="left_shoulder")])
    layer = SmartLayer(
        artist_intent=ArtistIntent(master_frame=2, skeleton_guidance=rough),
        skeleton_corrections=(
            [SkeletonCorrection(frame_number=2, skeleton=corrected, evidence_id=uuid4())]
            if include_correction
            else []
        ),
    )
    shot = Shot(
        media=MediaReference(
            relative_path="media/person.mov",
            source_path=str(media_path),
            fingerprint="pose-source",
            frame_count=5,
            frame_rate=24.0,
            width=64,
            height=64,
        ),
        range_start=0,
        range_end=4,
        master_frame=2,
        smart_layers=[layer],
    )
    return Project(name="Pose Project", sequences=[Sequence(shots=[shot])])


def test_export_uses_master_frame_artist_correction(tmp_path: Path) -> None:
    media = tmp_path / "person.mov"
    media.write_bytes(b"test-media")
    package = tmp_path / "pose.nova"
    JsonProjectStore().save(project_with_correction(media), package)

    exported = export_case(package, tmp_path / "dataset", "person/front")
    payload = json.loads(exported.manifest_path.read_text(encoding="utf-8"))
    case = payload["cases"][0]

    assert exported.case_id == "person-front"
    assert exported.ground_truth_source == "artist_master_frame_correction"
    assert case["frame"] == 2
    assert case["annotation_status"] == "candidate"
    assert case["ground_truth_skeleton"]["joints"][0]["x"] == 0.34
    assert case["source_media_fingerprint"] == "pose-source"
    assert case["minimum_sampled_depth_coverage"] == 0.8
    assert payload["gates"]["maximum_mean_temporal_relative_depth_delta"] is None
    assert payload["gates"]["minimum_temporal_transition_coverage"] is None


def test_export_rejects_unreviewed_automatic_pose(tmp_path: Path) -> None:
    media = tmp_path / "person.mov"
    media.write_bytes(b"test-media")
    package = tmp_path / "pose.nova"
    JsonProjectStore().save(project_with_correction(media, include_correction=False), package)

    with pytest.raises(ValueError, match="artist correction or accepted fusion"):
        export_case(package, tmp_path / "dataset", "person")


def test_workspace_pose_export_visibility_requires_reviewed_master_pose(
    tmp_path: Path,
) -> None:
    media = tmp_path / "person.mov"
    media.write_bytes(b"test-media")

    reviewed_shot = project_with_correction(media).sequences[0].shots[0]
    automatic_only_shot = (
        project_with_correction(media, include_correction=False).sequences[0].shots[0]
    )

    assert WorkspaceWindow._pose_export_available(reviewed_shot)
    assert not WorkspaceWindow._pose_export_available(automatic_only_shot)


def test_export_preserves_original_artist_pose_from_accepted_fusion(tmp_path: Path) -> None:
    media = tmp_path / "person.mov"
    media.write_bytes(b"test-media")
    project = project_with_correction(media, include_correction=False)
    layer = project.sequences[0].shots[0].smart_layers[0]
    original_artist = layer.artist_intent.skeleton_guidance.model_copy(deep=True)
    fused = SkeletonGuidance(joints=[SkeletonJoint(x=0.34, y=0.38, label="left_shoulder")])
    candidate = SkeletonFusionCandidate(
        frame_number=2,
        artist_skeleton=original_artist,
        detected_skeleton=fused,
        fused_skeleton=fused,
        joint_confidences={"left_shoulder": 0.8},
        provenance=CapabilityProvenance(
            capability="skeleton_detection", adapter="test", adapter_version="1.0"
        ),
        status="accepted",
    )
    layer.skeleton_fusion_candidates.append(candidate)
    layer.artist_intent.skeleton_guidance = fused
    package = tmp_path / "accepted-fusion.nova"
    JsonProjectStore().save(project, package)

    exported = export_case(package, tmp_path / "dataset", "fusion-person")
    payload = json.loads(exported.manifest_path.read_text(encoding="utf-8"))
    case = payload["cases"][0]

    assert exported.ground_truth_source == "artist_accepted_fusion"
    assert case["artist_skeleton"]["joints"][0]["x"] == 0.3
    assert case["ground_truth_skeleton"]["joints"][0]["x"] == 0.34
