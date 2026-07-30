from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.generation import (
    latest_generation_record,
    ordered_generations,
)


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


class GenerationHistoryTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.service.create_project("generations")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(48, 36))
        self.service.load_source(source)
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_successful_generate_appends_generation_record(self) -> None:
        before_ops = len(self.service.project.operations)
        cset = self.service.generate_candidates()
        project = self.service.project
        self.assertEqual(1, len(ordered_generations(project)))
        record = latest_generation_record(project, cset.generation_id)
        assert record is not None
        self.assertEqual("available", record.status)
        self.assertEqual(1, record.sequence_number)
        self.assertEqual(cset.generation_id, project.active_generation_id)
        self.assertEqual(cset.id, record.candidate_set_id)
        self.assertEqual(before_ops + 1, len(project.operations))

    def test_second_generate_appends_history(self) -> None:
        first = self.service.generate_candidates()
        second = self.service.generate_candidates()
        history = self.service.get_generation_history()
        self.assertEqual(2, len(history))
        self.assertEqual([1, 2], [item.sequence_number for item in history])
        self.assertEqual(second.generation_id, self.service.project.active_generation_id)
        self.assertNotEqual(first.generation_id, second.generation_id)

    def test_reject_active_generation(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        ops_before = len(self.service.project.operations)
        self.service.reject_generation()
        record = latest_generation_record(self.service.project, cset.generation_id)
        assert record is not None
        self.assertEqual("rejected", record.status)
        self.assertIsNone(self.service.project.active_hypothesis_id)
        self.assertEqual(ops_before, len(self.service.project.operations))
        self.assertFalse(self.service.can_confirm_generation())

    def test_rejected_generation_can_be_restored_but_not_confirmed(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.reject_generation()
        self.service.restore_generation(cset.generation_id)
        self.assertEqual(cset.generation_id, self.service.project.active_generation_id)
        self.assertFalse(self.service.can_confirm_generation())

    def test_reactivate_enables_confirm_after_selection(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.reject_generation()
        self.service.reactivate_generation(cset.generation_id)
        self.service.select_candidate(cset.candidates[0].id)
        self.assertTrue(self.service.can_confirm_generation())

    def test_restore_preserves_selected_candidate(self) -> None:
        first = self.service.generate_candidates()
        self.service.select_candidate(first.candidates[1].id)
        second = self.service.generate_candidates()
        self.assertNotEqual(first.generation_id, second.generation_id)
        self.service.restore_generation(first.generation_id)
        restored = self.service.get_active_candidate_set()
        assert restored is not None
        self.assertEqual(first.candidates[1].id, restored.active_candidate_id)

    def test_confirm_marks_generation_confirmed(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()
        record = latest_generation_record(self.service.project, cset.generation_id)
        assert record is not None
        self.assertEqual("confirmed", record.status)

    def test_load_source_clears_generation_history(self) -> None:
        self.service.generate_candidates()
        source = Path(self._tmp.name) / "b.png"
        source.write_bytes(_png_bytes(32, 32))
        self.service.load_source(source)
        self.assertEqual([], self.service.project.generation_records)
        self.assertIsNone(self.service.project.active_generation_id)

    def test_invalid_generation_id_does_not_mutate(self) -> None:
        self.service.generate_candidates()
        before = self.service.project.model_dump(mode="json")
        with self.assertRaises(ApplicationError):
            self.service.restore_generation(uuid4())
        self.assertEqual(before, self.service.project.model_dump(mode="json"))

    def test_navigation_clamps(self) -> None:
        cset = self.service.generate_candidates()
        self.assertEqual(cset.generation_id, self.service.get_previous_generation_id())
        self.assertEqual(cset.generation_id, self.service.get_next_generation_id())
        self.service.generate_candidates()
        active = self.service.get_active_generation()
        assert active is not None
        self.assertEqual(active.generation_id, self.service.get_next_generation_id())

    def test_persistence_round_trip(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        package = Path(self._tmp.name) / "proj.nova"
        self.service.save_project(package)
        other = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        other.load_project(package)
        self.assertEqual(1, len(other.get_generation_history()))
        self.assertIsNotNone(other.project.active_generation_id)

    def test_migration_from_legacy_project_without_generation_records(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        project = self.service.project
        project.generation_records = []
        project.active_generation_id = None
        for candidate_set in project.candidate_sets:
            candidate_set.generation_id = None
        package = Path(self._tmp.name) / "legacy.nova"
        self.service.save_project(package)
        loaded, _assets = JsonProjectStore().load(package)
        self.assertEqual(1, len(ordered_generations(loaded)))
        self.assertIsNotNone(loaded.active_generation_id)

    def test_generation_record_status_via_append_only(self) -> None:
        project = self.service.project
        cset = self.service.generate_candidates()
        assert cset.generation_id is not None
        before = len(project.generation_records)
        self.service.reject_generation(cset.generation_id)
        self.assertEqual(before + 1, len(project.generation_records))
