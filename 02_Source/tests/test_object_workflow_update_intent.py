from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import WorkflowState


def _png_bytes(width: int, height: int, fill: int = 128) -> bytes:
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend([fill] * width)
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _intent(*signals: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {"signals": list(signals)},
    }


class UpdateArtistIntentTests(TestCase):
    def setUp(self) -> None:
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
        )
        self.service.create_project("rev")
        self._tmp = TemporaryDirectory()
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(80, 60))
        self.service.load_source(source)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_revision_history_and_active_switching(self) -> None:
        first = self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.3, "y": 0.3})
        )
        self.assertEqual(1, first.revision)
        second = self.service.update_artist_intent(
            _intent({"type": "positive_point", "x": 0.6, "y": 0.6})
        )
        project = self.service.project
        assert project is not None
        self.assertEqual(2, len(project.intents))
        self.assertEqual(1, project.intents[0].revision)
        self.assertEqual(2, project.intents[1].revision)
        self.assertEqual(first.id, project.intents[0].id)
        self.assertEqual(second.id, project.active_intent_id)
        self.assertEqual(
            project.intents[0].instruction.payload.signals[0]["x"],
            0.3,
        )

    def test_previous_revision_not_mutated(self) -> None:
        first = self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.2, "y": 0.2})
        )
        original_signals = list(first.instruction.payload.signals)
        self.service.update_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.8, "y": 0.8},
                {"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            )
        )
        project = self.service.project
        assert project is not None
        preserved = next(item for item in project.intents if item.id == first.id)
        self.assertEqual(original_signals, preserved.instruction.payload.signals)

    def test_hypothesis_and_confirmed_invalidation(self) -> None:
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.4, "y": 0.5}))
        cset = self.service.generate_hypothesis()
        hypothesis = self.service.select_candidate(cset.candidates[0].id)
        confirmed = self.service.confirm_hypothesis()
        project = self.service.project
        assert project is not None
        self.assertEqual(WorkflowState.OBJECT_CONFIRMED, project.workflow_state)
        self.assertEqual(hypothesis.id, project.active_hypothesis_id)
        self.assertEqual(confirmed.id, project.active_confirmed_object_id)

        updated = self.service.update_artist_intent(
            _intent({"type": "positive_point", "x": 0.7, "y": 0.2})
        )
        self.assertEqual(WorkflowState.INTENT_PROVIDED, project.workflow_state)
        self.assertEqual(updated.id, project.active_intent_id)
        self.assertIsNone(project.active_hypothesis_id)
        self.assertIsNone(project.active_candidate_set_id)
        self.assertIsNone(project.active_confirmation_id)
        self.assertIsNone(project.active_confirmed_object_id)
        self.assertEqual(1, len(project.hypotheses))
        self.assertEqual(1, len(project.confirmed_objects))
        self.assertEqual(hypothesis.id, project.hypotheses[0].id)
        self.assertEqual(confirmed.id, project.confirmed_objects[0].id)

    def test_multiple_sequential_edits_and_regenerate(self) -> None:
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
        first_set = self.service.generate_hypothesis()
        first_hyp = self.service.select_candidate(first_set.candidates[0].id)
        self.service.update_artist_intent(
            _intent({"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4})
        )
        second_set = self.service.generate_hypothesis()
        second_hyp = self.service.select_candidate(second_set.candidates[0].id)
        self.service.update_artist_intent(_intent({"type": "positive_point", "x": 0.2, "y": 0.8}))
        third_set = self.service.generate_hypothesis()
        third_hyp = self.service.select_candidate(third_set.candidates[0].id)
        project = self.service.project
        assert project is not None
        self.assertEqual(3, len(project.intents))
        self.assertEqual(3, len(project.hypotheses))
        self.assertEqual(third_hyp.id, project.active_hypothesis_id)
        self.assertNotEqual(first_hyp.mask_relative_path, second_hyp.mask_relative_path)

    def test_save_load_preserves_revision_history(self) -> None:
        first = self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.3, "y": 0.4})
        )
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        second = self.service.update_artist_intent(
            _intent({"type": "positive_point", "x": 0.55, "y": 0.55})
        )
        package = Path(self._tmp.name) / "hist.nova"
        self.service.save_project(package)

        restored_service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
        )
        restored = restored_service.load_project(package)
        self.assertEqual(2, len(restored.intents))
        self.assertEqual(first.id, restored.intents[0].id)
        self.assertEqual(second.id, restored.active_intent_id)
        self.assertEqual(2, restored.intents[1].revision)
        self.assertIsNone(restored.active_hypothesis_id)
        self.assertIsNone(restored.active_candidate_set_id)
        self.assertEqual(1, len(restored.hypotheses))
        self.assertEqual(WorkflowState.INTENT_PROVIDED, restored.workflow_state)
