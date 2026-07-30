from pathlib import Path

import numpy as np

from nova_layer.app.project_controller import ProjectController
from nova_layer.benchmark_dataset import review_dataset_case
from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    GuidancePoint,
    LifecycleState,
    MaturityState,
    MediaLinkState,
    SkeletonBone,
    SkeletonGuidance,
    SkeletonJoint,
    ValidationState,
)
from nova_layer.ports.capabilities import PropagationResult, VideoFrame
from nova_layer.ports.media import MediaInfo


class FakeMediaReader:
    def __init__(self, fingerprint: str = "sha256:fake", frame_count: int = 24) -> None:
        self.fingerprint = fingerprint
        self.frame_count = frame_count

    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path.resolve(),
            fingerprint=self.fingerprint,
            frame_count=self.frame_count,
            frame_rate=24.0,
            width=320,
            height=180,
            time_base="1/12288",
            pixel_format="yuv420p",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        return np.full((180, 320, 3), frame_number, dtype=np.uint8)


class FailingSegmentation:
    def predict(self, **kwargs: object) -> object:
        del kwargs
        raise RuntimeError("simulated capability initialization failure")


class LowConfidencePropagation:
    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: list[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: list[VideoFrame],
    ) -> list[PropagationResult]:
        del master_frame, reference_mask, frames
        provenance = CapabilityProvenance(
            capability="temporal_propagation",
            adapter="low_confidence_test",
            adapter_version="1.0",
        )
        return [
            PropagationResult(
                frame_number=frame,
                mask_reference=f"masks/low_{frame:06d}.png",
                mask=reference_mask_data.copy(),
                confidence=0.2,
                provenance=provenance,
            )
            for frame in target_frames
        ]


class IntermediatePropagation:
    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: list[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: list[VideoFrame],
    ) -> list[PropagationResult]:
        del reference_mask
        provenance = CapabilityProvenance(
            capability="temporal_propagation",
            adapter="intermediate_test",
            adapter_version="1.0",
        )
        return [
            PropagationResult(
                frame_number=frame.frame_number,
                mask_reference=f"masks/full_{frame.frame_number:06d}.png",
                mask=reference_mask_data.copy(),
                confidence=0.9,
                provenance=provenance,
                is_validation_target=frame.frame_number in target_frames,
            )
            for frame in frames
            if frame.frame_number != master_frame
        ]


def test_import_creates_single_sequence_and_shot(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    assert controller.create_project("Media Test", tmp_path) is not None

    shot = controller.import_media(tmp_path / "source.mov")

    assert shot is not None
    assert shot.range_start == 0
    assert shot.range_end == 23
    assert shot.master_frame == 11
    assert controller.project is not None
    assert len(controller.project.sequences) == 1
    assert (tmp_path / "Media_Test.nova" / "manifest.json").exists()


def test_shot_selection_is_validated_and_saved(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Range Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")

    assert controller.update_shot_selection(4, 20, 12)
    assert controller.active_shot is not None
    assert controller.active_shot.range_start == 4
    assert controller.active_shot.range_end == 20
    assert controller.active_shot.master_frame == 12
    assert not controller.update_shot_selection(10, 5, 7)


def test_frame_request_emits_rgb_frame(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Frame Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")

    with qtbot.waitSignal(controller.frame_ready) as blocker:  # type: ignore[attr-defined]
        assert controller.request_frame(7)

    frame_number, frame = blocker.args
    assert frame_number == 7
    assert frame.shape == (180, 320, 3)
    assert int(frame[0, 0, 0]) == 7


def test_artist_guidance_creates_smart_layer_and_persists(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Guidance Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    points = [
        GuidancePoint(x=0.4, y=0.5, polarity="positive"),
        GuidancePoint(x=0.8, y=0.2, polarity="negative"),
    ]
    region = BoundingRegion(x=0.2, y=0.1, width=0.6, height=0.7)

    layer = controller.update_artist_guidance(points, region)

    assert layer is not None
    assert layer.object_identity.maturity_state == MaturityState.HYPOTHESIS
    assert layer.artist_intent.points == points
    assert layer.artist_intent.bounding_region == region
    package = tmp_path / "Guidance_Test.nova"
    restored = controller._store.load(package)
    restored_layer = restored.sequences[0].shots[0].smart_layers[0]
    assert restored_layer.object_identity.id == layer.object_identity.id
    assert restored_layer.artist_intent == layer.artist_intent


def test_skeleton_only_guidance_generates_object_hypothesis(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Skeleton Guidance Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    shoulder = SkeletonJoint(x=0.4, y=0.3, label="shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="wrist")
    skeleton = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    layer = controller.update_artist_guidance([], None, skeleton)

    assert layer is not None
    hypothesis = controller.generate_hypothesis()
    assert hypothesis is not None
    assert hypothesis.confidence == 0.7
    assert layer.artist_intent.skeleton_guidance == skeleton
    assert controller.accept_hypothesis()
    assert controller.propagate_confirmed_identity()
    assert len(layer.temporal_skeleton_observations) == 23
    first_observation = layer.temporal_skeleton_observations[0]
    assert first_observation.frame_number == 0
    assert first_observation.provenance.capability == "skeleton_tracking"
    assert first_observation.skeleton.joints[0].x < shoulder.x
    identity_observation = layer.temporal_observations[0]
    assert identity_observation.skeleton_confidence is not None
    assert controller.active_shot is not None
    mask_confidence = max(
        0.55,
        0.95 - abs(identity_observation.frame_number - controller.active_shot.master_frame) * 0.01,
    )
    assert np.isclose(
        identity_observation.confidence,
        0.7 * mask_confidence + 0.3 * identity_observation.skeleton_confidence,
    )
    start_result = next(item for item in layer.frame_results if item.frame_number == 0)
    assert start_result.confidence == identity_observation.confidence
    restored = controller._store.load(tmp_path / "Skeleton_Guidance_Test.nova")
    restored_layer = restored.sequences[0].shots[0].smart_layers[0]
    assert restored_layer.temporal_skeleton_observations == layer.temporal_skeleton_observations


def test_skeleton_fusion_requires_artist_review_before_master_update(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Skeleton Fusion Test", tmp_path)
    shot = controller.import_media(tmp_path / "source.mov")
    assert shot is not None
    shoulder = SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="left_wrist")
    artist = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    layer = controller.update_artist_guidance([], None, artist)
    assert layer is not None
    detected = SkeletonGuidance(
        joints=[
            SkeletonJoint(x=0.45, y=0.34, label="left_shoulder"),
            SkeletonJoint(x=0.64, y=0.68, label="left_wrist"),
        ]
    )

    candidate = controller.propose_skeleton_fusion(
        frame_number=shot.master_frame,
        detected_skeleton=detected,
        joint_confidences={"left_shoulder": 0.9, "left_wrist": 0.85},
        depth_confidences={"left_shoulder": 0.8, "left_wrist": 0.9},
        joint_depths={"left_shoulder": 0.41, "left_wrist": 0.67},
        provenance=CapabilityProvenance(
            capability="skeleton_detection",
            adapter="test_depth_pose",
            adapter_version="1.0",
        ),
    )

    assert candidate is not None
    assert candidate.status == "pending"
    assert layer.artist_intent.skeleton_guidance == artist
    assert controller.review_skeleton_fusion(candidate.id, accept=True)
    assert candidate.status == "accepted"
    assert layer.artist_intent.skeleton_guidance == candidate.fused_skeleton
    assert layer.artist_intent.skeleton_guidance.joints[0].id == shoulder.id
    restored = controller._store.load(tmp_path / "Skeleton_Fusion_Test.nova")
    restored_candidate = (
        restored.sequences[0].shots[0].smart_layers[0].skeleton_fusion_candidates[0]
    )
    assert restored_candidate.status == "accepted"
    assert restored_candidate.depth_confidences == {
        "left_shoulder": 0.8,
        "left_wrist": 0.9,
    }
    assert restored_candidate.joint_depths == {
        "left_shoulder": 0.41,
        "left_wrist": 0.67,
    }


def test_automatic_pose_detection_creates_review_candidate(
    qtbot: object,
    tmp_path: Path,
) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Automatic Fusion Test", tmp_path)
    shot = controller.import_media(tmp_path / "source.mov")
    assert shot is not None
    shoulder = SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="left_wrist")
    artist = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    layer = controller.update_artist_guidance([], None, artist)
    assert layer is not None

    with qtbot.waitSignal(controller.skeleton_fusion_candidate_ready) as ready:  # type: ignore[attr-defined]
        assert controller.start_skeleton_fusion_detection(shot.master_frame)

    candidate = ready.args[0]
    assert candidate.status == "pending"
    assert candidate.provenance.adapter == "deterministic_depth_pose_mock"
    assert candidate.joint_confidences == {
        "left_shoulder": 0.88 * 0.82,
        "left_wrist": 0.88 * 0.82,
    }
    assert layer.artist_intent.skeleton_guidance == artist


def test_artist_skeleton_correction_replaces_tracked_pose_and_persists(
    qtbot: object,
    tmp_path: Path,
) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Skeleton Correction Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    shoulder = SkeletonJoint(x=0.4, y=0.3, label="shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="wrist")
    reference = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    layer = controller.update_artist_guidance([], None, reference)
    assert layer is not None
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()
    assert controller.propagate_confirmed_identity()
    tracked = next(item for item in layer.temporal_skeleton_observations if item.frame_number == 0)
    corrected_joints = [
        joint.model_copy(update={"x": min(1.0, joint.x + 0.05)})
        for joint in tracked.skeleton.joints
    ]
    corrected = tracked.skeleton.model_copy(update={"joints": corrected_joints})
    previous_version = layer.version

    correction = controller.apply_skeleton_correction(0, corrected)

    assert correction is not None
    assert layer.version == previous_version + 1
    assert layer.skeleton_corrections == [correction]
    corrected_observation = next(
        item for item in layer.temporal_skeleton_observations if item.frame_number == 0
    )
    assert corrected_observation.skeleton == corrected
    assert corrected_observation.confidence == 1.0
    identity = next(item for item in layer.temporal_observations if item.frame_number == 0)
    assert identity.mask_confidence is not None
    assert identity.skeleton_confidence == 1.0
    assert np.isclose(identity.confidence, identity.mask_confidence * 0.7 + 0.3)
    assert layer.evidence_history[-1].id == correction.evidence_id
    assert controller.propagate_confirmed_identity()
    corrected_after_propagation = next(
        item for item in layer.temporal_skeleton_observations if item.frame_number == 0
    )
    assert corrected_after_propagation.skeleton == corrected
    assert corrected_after_propagation.provenance.adapter == "artist_skeleton_correction"
    neighbor_after_propagation = next(
        item for item in layer.temporal_skeleton_observations if item.frame_number == 1
    )
    assert np.isclose(
        neighbor_after_propagation.skeleton.joints[0].x,
        corrected.joints[0].x + 0.002,
    )
    assert neighbor_after_propagation.provenance.settings["skeleton_anchor_frame"] == 0
    assert (
        neighbor_after_propagation.provenance.settings["skeleton_anchor_source"]
        == "artist_correction"
    )
    with qtbot.waitSignal(controller.processing_finished) as completed:  # type: ignore[attr-defined]
        assert controller.start_skeleton_retracking()
    assert completed.args == ["skeleton_retracking"]
    neighbor_after_skeleton_only = next(
        item for item in layer.temporal_skeleton_observations if item.frame_number == 1
    )
    assert np.isclose(
        neighbor_after_skeleton_only.skeleton.joints[0].x,
        corrected.joints[0].x + 0.002,
    )
    restored = controller._store.load(tmp_path / "Skeleton_Correction_Test.nova")
    restored_layer = restored.sequences[0].shots[0].smart_layers[0]
    assert restored_layer.skeleton_corrections == [correction]
    assert controller.remove_skeleton_correction(0)
    assert layer.skeleton_corrections == []
    restored_observation = next(
        item for item in layer.temporal_skeleton_observations if item.frame_number == 0
    )
    assert correction.replaced_observation is not None
    assert restored_observation == correction.replaced_observation
    restored_identity = next(item for item in layer.temporal_observations if item.frame_number == 0)
    assert restored_identity.skeleton_confidence == restored_observation.confidence
    removed_project = controller._store.load(tmp_path / "Skeleton_Correction_Test.nova")
    removed_layer = removed_project.sequences[0].shots[0].smart_layers[0]
    assert removed_layer.skeleton_corrections == []


def test_hypothesis_generation_and_confirmation(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Hypothesis Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.5, height=0.5),
    )

    hypothesis = controller.generate_hypothesis()

    assert hypothesis is not None
    assert hypothesis.validation_state == ValidationState.PENDING
    assert (tmp_path / "Hypothesis_Test.nova" / hypothesis.mask_reference).exists()
    assert controller.accept_hypothesis()
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    assert layer.object_identity.maturity_state == MaturityState.CONFIRMED
    assert layer.object_identity.lifecycle_state == LifecycleState.CONFIRMED
    assert layer.frame_results[-1].validation_state == ValidationState.ACCEPTED
    assert layer.reasoning_history[-1].decision == "artist_accepted_object_hypothesis"

    propagated = controller.propagate_confirmed_identity()

    assert {result.frame_number for result in propagated} == {0, 23}
    assert {result.direction for result in propagated} == {"backward", "forward"}
    assert layer.object_identity.lifecycle_state == LifecycleState.TRACKED
    assert len(layer.temporal_observations) == 23
    assert len(controller.smart_layer_frame_sources()) == 24
    diagnostics = controller.last_propagation_diagnostics
    assert diagnostics is not None
    assert diagnostics.complete
    assert diagnostics.mode == "mock"
    assert len(diagnostics.requested_frames) == 23
    assert diagnostics.missing_frames == ()
    assert all(
        item.lifecycle_state == LifecycleState.TRACKED for item in layer.temporal_observations
    )
    for result in propagated:
        assert (tmp_path / "Hypothesis_Test.nova" / result.mask_reference).exists()

    assert controller.set_validation_state(0, ValidationState.CORRECTION_REQUIRED)
    assert layer.object_identity.maturity_state == MaturityState.CONFIRMED
    corrected = controller.apply_frame_correction(
        0,
        [GuidancePoint(x=0.45, y=0.55, polarity="positive")],
        BoundingRegion(x=0.15, y=0.15, width=0.55, height=0.6),
    )
    assert corrected is not None
    assert corrected.validation_state == ValidationState.PENDING
    assert corrected.mask_reference == "masks/correction_000000.png"
    assert layer.version == 2
    assert layer.reasoning_history[-1].decision == "artist_correction_recomputed_backward_region"
    assert controller.set_validation_state(0, ValidationState.ACCEPTED)
    assert controller.set_validation_state(23, ValidationState.ACCEPTED)
    assert layer.object_identity.maturity_state == MaturityState.VALIDATED
    assert len(layer.extraction_previews) == 3
    assert all(
        (tmp_path / "Hypothesis_Test.nova" / preview.image_reference).exists()
        for preview in layer.extraction_previews
    )
    assert all(
        result.validation_state == ValidationState.ACCEPTED for result in layer.frame_results
    )

    previews = controller.validation_previews()
    assert [result.frame_number for result, _, _ in previews] == [0, 11, 23]


def test_hypothesis_can_run_as_background_job(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Async Hypothesis Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.5, height=0.5),
    )

    with qtbot.waitSignal(controller.processing_finished) as completed:  # type: ignore[attr-defined]
        assert controller.start_hypothesis()

    assert completed.args == ["interactive_hypothesis"]
    assert controller.active_shot is not None
    result = controller.active_shot.smart_layers[0].frame_results[-1]
    assert result.direction == "master"
    assert (tmp_path / "Async_Hypothesis_Test.nova" / result.mask_reference).exists()


def test_missing_media_requires_relink(qtbot: object, tmp_path: Path) -> None:
    source = tmp_path / "source.mov"
    source.touch()
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Relink Test", tmp_path)
    controller.import_media(source)
    package = tmp_path / "Relink_Test.nova"
    source.unlink()

    reopened = ProjectController(media_reader=FakeMediaReader())
    with qtbot.waitSignal(reopened.media_link_state_changed) as blocker:  # type: ignore[attr-defined]
        reopened.open_project(package)

    assert blocker.args[0] == MediaLinkState.MISSING.value
    replacement = tmp_path / "replacement.mov"
    replacement.touch()
    assert reopened.relink_media(replacement)
    assert reopened.active_shot is not None
    assert reopened.active_shot.media.link_state == MediaLinkState.LINKED


def test_changed_media_requires_explicit_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "source.mov"
    replacement = tmp_path / "replacement.mov"
    source.touch()
    replacement.touch()
    controller = ProjectController(media_reader=FakeMediaReader("sha256:original"))
    controller.create_project("Changed Test", tmp_path)
    controller.import_media(source)

    controller._media_reader = FakeMediaReader("sha256:replacement")
    assert not controller.relink_media(replacement)
    assert controller.active_shot is not None
    assert controller.active_shot.media.link_state == MediaLinkState.CHANGED
    assert controller.relink_media(replacement, accept_changed=True)
    assert controller.active_shot.media.fingerprint == "sha256:replacement"


def test_short_replacement_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.mov"
    replacement = tmp_path / "short.mov"
    source.touch()
    replacement.touch()
    controller = ProjectController(media_reader=FakeMediaReader(frame_count=24))
    controller.create_project("Short Test", tmp_path)
    controller.import_media(source)

    controller._media_reader = FakeMediaReader("sha256:short", frame_count=8)
    assert not controller.relink_media(replacement, accept_changed=True)
    assert controller.active_shot is not None
    assert controller.active_shot.media.source_path == str(source.resolve())


def test_controller_restores_recovery_journal(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    project = controller.create_project("Recovery Test", tmp_path)
    assert project is not None
    package = tmp_path / "Recovery_Test.nova"
    recovered = project.model_copy(update={"name": "Recovered Name"})
    controller._store.recovery_path(package).write_text(
        recovered.model_dump_json(indent=2),
        encoding="utf-8",
    )

    reopened = ProjectController(media_reader=FakeMediaReader())
    with qtbot.waitSignal(reopened.recovery_available):  # type: ignore[attr-defined]
        reopened.open_project(package)
    assert reopened.restore_recovery()
    assert reopened.project is not None
    assert reopened.project.name == "Recovered Name"
    assert not reopened._store.has_recovery(package)


def test_capability_failure_preserves_project_state(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController(
        media_reader=FakeMediaReader(),
        segmentation=FailingSegmentation(),  # type: ignore[arg-type]
    )
    controller.create_project("Failure Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    layer = controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        None,
    )
    assert layer is not None
    identity_id = layer.object_identity.id

    with qtbot.waitSignal(controller.error_occurred) as error:  # type: ignore[attr-defined]
        result = controller.generate_hypothesis()

    assert result is None
    assert "simulated capability" in error.args[0]
    assert controller.active_shot is not None
    preserved = controller.active_shot.smart_layers[0]
    assert preserved.object_identity.id == identity_id
    assert preserved.frame_results == []


def test_low_confidence_propagation_requires_artist_review(tmp_path: Path) -> None:
    controller = ProjectController(
        media_reader=FakeMediaReader(),
        propagation=LowConfidencePropagation(),
    )
    controller.create_project("Ambiguity Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        None,
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()

    results = controller.propagate_confirmed_identity()

    assert len(results) == 2
    assert all(result.confidence == 0.2 for result in results)
    assert all(result.validation_state == ValidationState.CORRECTION_REQUIRED for result in results)
    assert controller.active_shot is not None
    identity = controller.active_shot.smart_layers[0].object_identity
    assert identity.maturity_state == MaturityState.CONFIRMED


def test_temporal_observations_record_loss_and_recovery(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("Lifecycle Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    assert controller.update_shot_selection(0, 20, 10)
    shot = controller.active_shot
    assert shot is not None
    provenance = CapabilityProvenance(
        capability="temporal_propagation",
        adapter="lifecycle_test",
        adapter_version="1.0",
    )
    mask = np.ones((180, 320), dtype=np.uint8)
    results = [
        PropagationResult(11, "11.png", mask, 0.9, provenance, False, True, 1.0),
        PropagationResult(12, "12.png", mask, 0.4, provenance, False, False, 0.0),
        PropagationResult(13, "13.png", mask, 0.8, provenance, False, True, 0.9),
    ]

    observations = controller._build_temporal_observations(shot, results)

    assert [item.lifecycle_state for item in observations] == [
        LifecycleState.TRACKED,
        LifecycleState.TEMPORARILY_LOST,
        LifecycleState.RECOVERED,
    ]


def test_low_confidence_visible_mask_is_not_treated_as_recovery(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=FakeMediaReader())
    controller.create_project("False Recovery Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    shot = controller.active_shot
    assert shot is not None
    provenance = CapabilityProvenance(
        capability="temporal_propagation",
        adapter="lifecycle_test",
        adapter_version="1.0",
    )
    mask = np.ones((180, 320), dtype=np.uint8)
    results = [
        PropagationResult(12, "12.png", mask, 0.4, provenance, False, False, 0.0),
        PropagationResult(13, "13.png", mask, 0.48, provenance, False, True, 0.1),
    ]

    observations = controller._build_temporal_observations(shot, results)

    assert [item.lifecycle_state for item in observations] == [
        LifecycleState.TEMPORARILY_LOST,
        LifecycleState.TEMPORARILY_LOST,
    ]


def test_full_shot_masks_are_persisted_without_extra_validation_cards(
    qtbot: object, tmp_path: Path
) -> None:
    (tmp_path / "source.mov").write_bytes(b"licensed-test-placeholder")
    controller = ProjectController(
        media_reader=FakeMediaReader(frame_count=5),
        propagation=IntermediatePropagation(),
    )
    controller.create_project("Full Mask Test", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    controller.update_artist_guidance([GuidancePoint(x=0.5, y=0.5, polarity="positive")], None)
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()

    validation_results = controller.propagate_confirmed_identity()

    assert len(validation_results) == 2
    assert controller.active_shot is not None
    layer = controller.active_shot.smart_layers[0]
    assert len(layer.temporal_observations) == 4
    assert len(layer.frame_results) == 3
    assert len(controller.smart_layer_frame_sources()) == 5
    package = tmp_path / "Full_Mask_Test.nova"
    assert all(
        (package / observation.mask_reference).exists()
        for observation in layer.temporal_observations
    )

    assert controller.set_validation_state(0, ValidationState.ACCEPTED)
    assert controller.set_validation_state(4, ValidationState.ACCEPTED)
    dataset_export = controller.export_benchmark_case(
        tmp_path / "benchmark_dataset", "hero person closeup"
    )
    assert dataset_export is not None
    assert dataset_export.case_id == "hero-person-closeup"
    assert dataset_export.mask_path.is_file()
    dataset_manifest = dataset_export.manifest_path.read_text(encoding="utf-8")
    assert '"annotation_source": "artist_validated_smart_layer"' in dataset_manifest
    assert '"annotation_status": "candidate"' in dataset_manifest
    review_dataset_case(
        dataset_export.manifest_path,
        dataset_export.case_id,
        status="approved",
        reviewer="Test Artist",
        notes="Edges checked at 200%.",
    )
    reviewed_manifest = dataset_export.manifest_path.read_text(encoding="utf-8")
    assert '"annotation_status": "approved"' in reviewed_manifest
    assert '"reviewer": "Test Artist"' in reviewed_manifest
    with qtbot.waitSignal(controller.smart_layer_render_ready) as ready:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_render()

    render = ready.args[0]
    assert render.version == 1
    assert len(render.frames) == 5
    assert len(render.checksums) == 5
    assert len(layer.renders) == 1
    assert all((package / item.image_reference).exists() for item in render.frames)
    assert controller.verify_smart_layer_render(1).valid

    with qtbot.waitSignal(controller.smart_layer_render_ready) as second_ready:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_render()
    second_render = second_ready.args[0]
    assert second_render.version == 2
    comparison = controller.compare_render_versions(1, 2)
    assert comparison is not None
    assert comparison.identical
    assert comparison.shared_frames == 5
    assert controller.set_render_protected(1, True)
    assert layer.renders[0].protected
    assert not controller.delete_smart_layer_render(1)
    second_render_path = package / Path(second_render.frames[0].image_reference).parent
    assert second_render_path.is_dir()
    assert controller.delete_smart_layer_render(2)
    assert not second_render_path.exists()
    assert [item.version for item in layer.renders] == [1]

    with qtbot.waitSignal(controller.smart_layer_render_ready) as third_ready:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_render()
    assert third_ready.args[0].version == 3
    assert layer.render_version_counter == 3
    audit = controller.inspect_smart_layer_render(1)
    assert audit is not None
    assert audit.source_layer_version == render.source_layer_version
    assert audit.frame_count == 5
    assert audit.storage_bytes > 0
    assert audit.protected
    assert audit.integrity_valid

    export_root = tmp_path / "exports"
    export_root.mkdir()
    exported = controller.export_smart_layer_render(export_root, version=1)
    assert exported is not None
    assert (exported / "manifest.json").exists()
    assert len(list(exported.glob("frame_*.png"))) == 5
    assert controller.export_smart_layer_render(export_root, version=1) is None

    first_frame = package / render.frames[0].image_reference
    first_frame.write_bytes(b"tampered")
    integrity = controller.verify_smart_layer_render(1)
    assert not integrity.valid
    assert "Checksum mismatch" in integrity.issues[0]
