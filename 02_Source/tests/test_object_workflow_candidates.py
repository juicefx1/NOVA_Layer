from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.sam2_core_inference import (
    Sam2CoreInferenceEngine,
    convert_all_sam_masks_to_binary_masks,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import OperationStatus, WorkflowState
from nova_layer.object_workflow.ports.core_inference import CandidateResult


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


class CandidateWorkflowTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.service.create_project("candidates")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(48, 36))
        self.service.load_source(source)
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_produces_multiple_candidates_without_selection(self) -> None:
        cset = self.service.generate_candidates()
        self.assertEqual(3, len(cset.candidates))
        self.assertIsNone(cset.active_candidate_id)
        self.assertEqual(WorkflowState.CANDIDATE_SET_READY, self.service.project.workflow_state)
        self.assertIsNone(self.service.project.active_hypothesis_id)
        with self.assertRaises(ApplicationError) as ctx:
            self.service.confirm_hypothesis()
        self.assertEqual("GENERATION_NOT_CONFIRMABLE", ctx.exception.code)

    def test_select_candidate_activates_hypothesis_without_operation(self) -> None:
        cset = self.service.generate_candidates()
        before_ops = len(self.service.list_operations())
        hypothesis = self.service.select_candidate(cset.candidates[1].id)
        self.assertEqual(before_ops, len(self.service.list_operations()))
        self.assertEqual(WorkflowState.HYPOTHESIS_READY, self.service.project.workflow_state)
        self.assertEqual(cset.candidates[1].id, hypothesis.candidate_id)
        active_set = next(
            item
            for item in self.service.project.candidate_sets
            if item.id == self.service.project.active_candidate_set_id
        )
        self.assertEqual(cset.candidates[1].id, active_set.active_candidate_id)
        self.assertNotEqual(cset.id, active_set.id)

    def test_generate_replaces_active_candidate_set(self) -> None:
        first = self.service.generate_candidates()
        second = self.service.generate_candidates()
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.id, self.service.project.active_candidate_set_id)
        self.assertIsNone(self.service.project.active_hypothesis_id)

    def test_editing_intent_clears_candidate_set(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.update_artist_intent(_intent({"type": "positive_point", "x": 0.2, "y": 0.2}))
        self.assertIsNone(self.service.project.active_candidate_set_id)
        self.assertIsNone(self.service.project.active_hypothesis_id)
        self.assertEqual(WorkflowState.INTENT_PROVIDED, self.service.project.workflow_state)

    def test_confirm_uses_active_candidate_mask(self) -> None:
        cset = self.service.generate_candidates()
        chosen = cset.candidates[2]
        hypothesis = self.service.select_candidate(chosen.id)
        confirmed = self.service.confirm_hypothesis()
        self.assertEqual(hypothesis.id, confirmed.hypothesis_id)
        self.assertEqual(chosen.mask_relative_path, confirmed.mask_relative_path)

    def test_selection_persists_round_trip(self) -> None:
        cset = self.service.generate_candidates()
        hypothesis = self.service.select_candidate(cset.candidates[0].id)
        package = Path(self._tmp.name) / "cand.nova"
        self.service.save_project(package)
        loaded = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
        )
        project = loaded.load_project(package)
        self.assertEqual("2.0", project.schema_version)
        self.assertGreaterEqual(len(project.candidate_sets), 1)
        active = next(
            item for item in project.candidate_sets if item.id == project.active_candidate_set_id
        )
        self.assertEqual(hypothesis.candidate_id, active.active_candidate_id)
        self.assertEqual(3, len(active.candidates))

    def test_stale_async_generation_discarded(self) -> None:
        executor = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            executor=executor,
        )
        service.create_project("stale")
        source = Path(self._tmp.name) / "stale.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.3, "y": 0.3}))
        op_id = service.start_generate_candidates()
        service.update_artist_intent(_intent({"type": "positive_point", "x": 0.9, "y": 0.9}))
        import time

        for _ in range(100):
            if not service.has_running_operation():
                break
            time.sleep(0.02)
        self.assertIsNone(service.project.active_candidate_set_id)
        op = next(item for item in service.project.operations if item.id == op_id)
        self.assertEqual(OperationStatus.CANCELLED, op.status)
        executor.shutdown(wait=True)

    def test_clear_candidate_set(self) -> None:
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.clear_candidate_set()
        self.assertIsNone(self.service.project.active_candidate_set_id)
        self.assertIsNone(self.service.project.active_hypothesis_id)
        self.assertEqual(WorkflowState.INTENT_PROVIDED, self.service.project.workflow_state)


class MockAndSam2CandidateTests(TestCase):
    def test_mock_returns_three_deterministic_masks(self) -> None:
        engine = MockCoreInferenceEngine()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(40, 40))
            from nova_layer.object_workflow.domain.models import IntentInstruction, IntentPayload
            from nova_layer.object_workflow.ports.core_inference import CoreInferenceRequest

            result = engine.generate_hypothesis(
                CoreInferenceRequest(
                    request_id="r1",
                    source_image_path=str(path),
                    source_width=40,
                    source_height=40,
                    media_type="image/png",
                    content_fingerprint="x",
                    intent_instruction=IntentInstruction(
                        schema_name="nova.intent.guidance.v1",
                        payload=IntentPayload(
                            signals=[{"type": "positive_point", "x": 0.5, "y": 0.5}]
                        ),
                    ),
                )
            )
        assert isinstance(result, CandidateResult)
        self.assertEqual(3, len(result.masks))
        self.assertEqual(3, len(result.confidences))
        self.assertNotEqual(result.masks[0].data, result.masks[1].data)

    def test_sam2_imports_all_runtime_candidates(self) -> None:
        masks = np.zeros((2, 8, 10), dtype=np.float32)
        masks[0, 1:4, 1:4] = 0.9
        masks[1, 2:6, 2:7] = 0.8
        scores = np.asarray([0.55, 0.77], dtype=np.float32)
        binary, confidences = convert_all_sam_masks_to_binary_masks(
            masks=masks,
            scores=scores,
            source_width=10,
            source_height=8,
            mask_threshold=0.5,
        )
        self.assertEqual(2, len(binary))
        self.assertAlmostEqual(0.55, confidences[0], places=5)
        self.assertAlmostEqual(0.77, confidences[1], places=5)
        # Single-candidate runtime stays size 1.
        one_mask = masks[:1]
        one_score = scores[:1]
        binary_one, conf_one = convert_all_sam_masks_to_binary_masks(
            masks=one_mask,
            scores=one_score,
            source_width=10,
            source_height=8,
            mask_threshold=0.5,
        )
        self.assertEqual(1, len(binary_one))
        self.assertEqual(1, len(conf_one))
        _ = Sam2CoreInferenceEngine  # imported for coverage of module wiring
