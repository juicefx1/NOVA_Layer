import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from pydantic import ValidationError

from nova_layer.adapters.capabilities.mock import (
    MockPropagationCapability,
    MockSegmentationCapability,
)
from nova_layer.adapters.persistence.json_store import JsonProjectStore, ProjectStoreError
from nova_layer.domain.models import (
    ArtistIntent,
    BoundingRegion,
    GuidancePoint,
    MediaReference,
    Project,
    Sequence,
    Shot,
    SkeletonBone,
    SkeletonGuidance,
    SkeletonJoint,
    SmartLayer,
)


def make_project() -> Project:
    media = MediaReference(
        relative_path="media/source.mov",
        fingerprint="sha256:test",
        frame_count=100,
        frame_rate=24.0,
        width=1920,
        height=1080,
    )
    intent = ArtistIntent(
        master_frame=50,
        points=[GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        bounding_region=BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.5),
    )
    layer = SmartLayer(artist_intent=intent)
    shot = Shot(
        media=media,
        range_start=10,
        range_end=90,
        master_frame=50,
        smart_layers=[layer],
    )
    return Project(name="NOVA Test", sequences=[Sequence(shots=[shot])])


class DomainTests(TestCase):
    def test_artist_skeleton_guidance_preserves_connected_normalized_joints(self) -> None:
        shoulder = SkeletonJoint(x=0.4, y=0.3, label="shoulder")
        elbow = SkeletonJoint(x=0.55, y=0.5, label="elbow")
        bone = SkeletonBone(start_joint_id=shoulder.id, end_joint_id=elbow.id)
        skeleton = SkeletonGuidance(joints=[shoulder, elbow], bones=[bone])
        intent = ArtistIntent(master_frame=0, skeleton_guidance=skeleton)

        restored = ArtistIntent.model_validate_json(intent.model_dump_json())
        self.assertEqual(2, len(restored.skeleton_guidance.joints))
        self.assertEqual(1, len(restored.skeleton_guidance.bones))
        self.assertEqual(2, len(restored.skeleton_guidance.positive_points()))

        with self.assertRaises(ValidationError):
            SkeletonGuidance(joints=[shoulder], bones=[bone])

    def test_skeleton_semantic_labels_are_unique_and_queryable(self) -> None:
        shoulder = SkeletonJoint(x=0.4, y=0.3, label="left_shoulder")
        wrist = SkeletonJoint(x=0.55, y=0.5, label="left_wrist")
        skeleton = SkeletonGuidance(joints=[shoulder, wrist])

        self.assertEqual(
            {"left_shoulder": shoulder, "left_wrist": wrist},
            skeleton.semantic_joint_map(),
        )
        with self.assertRaises(ValidationError):
            SkeletonGuidance(joints=[shoulder, wrist.model_copy(update={"label": "left_shoulder"})])
        with self.assertRaises(ValidationError):
            SkeletonJoint(x=0.2, y=0.3, label="Left Shoulder")

    def test_master_frame_must_be_inside_range(self) -> None:
        media = MediaReference(
            relative_path="source.mov",
            fingerprint="test",
            frame_count=10,
            frame_rate=24,
            width=100,
            height=100,
        )
        with self.assertRaises(ValidationError):
            Shot(media=media, range_start=2, range_end=8, master_frame=9)

    def test_mock_capabilities_are_deterministic(self) -> None:
        project = make_project()
        shot = project.sequences[0].shots[0]
        intent = shot.smart_layers[0].artist_intent
        segmentation = MockSegmentationCapability().predict(
            frame_number=shot.master_frame,
            image=np.zeros((shot.media.height, shot.media.width, 3), dtype=np.uint8),
            width=shot.media.width,
            height=shot.media.height,
            points=intent.points,
            bounding_region=intent.bounding_region,
        )
        propagated = MockPropagationCapability().propagate(
            master_frame=shot.master_frame,
            target_frames=[shot.range_start, shot.range_end],
            reference_mask=segmentation.mask_reference,
            reference_mask_data=segmentation.mask,
            frames=[],
        )
        self.assertEqual([10, 90], [item.frame_number for item in propagated])
        self.assertEqual(segmentation.confidence, 0.8)

    def test_project_round_trip_preserves_identity(self) -> None:
        project = make_project()
        identity_id = project.sequences[0].shots[0].smart_layers[0].object_identity.id
        with TemporaryDirectory() as directory:
            package = Path(directory) / project.package_name
            store = JsonProjectStore()
            store.save(project, package)
            restored = store.load(package)

        restored_id = restored.sequences[0].shots[0].smart_layers[0].object_identity.id
        self.assertEqual(identity_id, restored_id)
        self.assertEqual(project, restored)

    def test_successful_save_clears_recovery_journal(self) -> None:
        project = make_project()
        with TemporaryDirectory() as directory:
            package = Path(directory) / project.package_name
            store = JsonProjectStore()
            store.save(project, package)
            self.assertFalse(store.has_recovery(package))

    def test_recovery_journal_can_be_loaded_and_discarded(self) -> None:
        project = make_project()
        with TemporaryDirectory() as directory:
            package = Path(directory) / project.package_name
            store = JsonProjectStore()
            store.save(project, package)
            recovered = project.model_copy(update={"name": "Recovered Project"})
            store.recovery_path(package).write_text(
                recovered.model_dump_json(indent=2),
                encoding="utf-8",
            )

            self.assertTrue(store.has_recovery(package))
            self.assertEqual(store.load_recovery(package).name, "Recovered Project")
            store.discard_recovery(package)
            self.assertFalse(store.has_recovery(package))

    def test_legacy_schema_migrates_without_modifying_source_manifest(self) -> None:
        project = make_project()
        manifest = project.model_dump(mode="json")
        legacy = dict(manifest)
        legacy["schema_version"] = "0.9"
        legacy["shots"] = legacy.pop("sequences")[0]["shots"]
        with TemporaryDirectory() as directory:
            package = Path(directory) / "Legacy.nova"
            package.mkdir()
            manifest_path = package / "manifest.json"
            manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
            store = JsonProjectStore()

            restored = store.load(package)

            self.assertEqual(restored.schema_version, "1.0")
            self.assertEqual(len(restored.sequences[0].shots), 1)
            self.assertEqual(store.last_migration_steps, ("0.9 → 1.0",))
            source_after_load = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(source_after_load["schema_version"], "0.9")

    def test_future_schema_is_rejected_without_overwrite(self) -> None:
        project = make_project()
        manifest = project.model_dump(mode="json")
        manifest["schema_version"] = "9.0"
        with TemporaryDirectory() as directory:
            package = Path(directory) / "Future.nova"
            package.mkdir()
            manifest_path = package / "manifest.json"
            original = json.dumps(manifest)
            manifest_path.write_text(original, encoding="utf-8")

            with self.assertRaises(ProjectStoreError):
                JsonProjectStore().load(package)

            self.assertEqual(manifest_path.read_text(encoding="utf-8"), original)
