from __future__ import annotations

import struct
import threading
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import OperationStatus, WorkflowState
from nova_layer.object_workflow.ports.core_inference import (
    CoreInferenceError,
    CoreInferenceRequest,
)
from nova_layer.object_workflow.ports.operation_executor import OperationProgress, OperationSnapshot


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


class FailingInference:
    def generate_hypothesis(self, request: CoreInferenceRequest) -> CoreInferenceError:
        return CoreInferenceError(
            request_id=request.request_id,
            error_code="INFERENCE_FAILED",
            message="mock failure",
            retryable=False,
        )


class OperationRuntimeTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.executor = MockOperationExecutor(step_delay_seconds=0.0)
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=self.executor,
        )
        self.service.create_project("ops")
        source = Path(self._tmp.name) / "plate.png"
        source.write_bytes(_png_bytes(40, 30, fill=90))
        self.service.load_source(source)
        self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.5, "y": 0.5})
        )

    def tearDown(self) -> None:
        self.executor.shutdown(wait=True)
        self._tmp.cleanup()

    def test_operation_created_before_execution_and_runs(self) -> None:
        slow = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=slow,
        )
        service.create_project("running")
        source = Path(self._tmp.name) / "run.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.4, "y": 0.4}))

        operation_id = service.start_generate_hypothesis()
        record = next(item for item in service.list_operations() if item.id == operation_id)
        self.assertEqual(OperationStatus.RUNNING, record.status)
        self.assertTrue(service.has_running_operation())
        snapshot = service.query_operation(operation_id)
        assert snapshot is not None
        self.assertEqual("running", snapshot.status)

        finished = service.wait_operation(operation_id)
        self.assertEqual("succeeded", finished.status)
        self.assertEqual(WorkflowState.CANDIDATE_SET_READY, service.project.workflow_state)
        slow.shutdown(wait=True)

    def test_successful_completion_activates_candidate_set(self) -> None:
        operation_id = self.service.start_generate_hypothesis()
        snapshot = self.service.wait_operation(operation_id)
        self.assertEqual("succeeded", snapshot.status)
        project = self.service.project
        assert project is not None
        self.assertIsNotNone(project.active_candidate_set_id)
        self.assertIsNone(project.active_hypothesis_id)
        self.assertEqual(WorkflowState.CANDIDATE_SET_READY, project.workflow_state)
        record = next(item for item in project.operations if item.id == operation_id)
        self.assertEqual(OperationStatus.SUCCEEDED, record.status)
        candidate_set = next(
            item for item in project.candidate_sets if item.id == project.active_candidate_set_id
        )
        self.assertEqual(3, len(candidate_set.candidates))
        hypothesis = self.service.select_candidate(candidate_set.candidates[0].id)
        self.assertEqual(WorkflowState.HYPOTHESIS_READY, project.workflow_state)
        self.assertEqual(hypothesis.id, project.active_hypothesis_id)

    def test_cancellation(self) -> None:
        slow = MockOperationExecutor(step_delay_seconds=0.08)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=slow,
        )
        service.create_project("cancel")
        source = Path(self._tmp.name) / "cancel.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.3, "y": 0.3}))
        before = service.project.workflow_state

        operation_id = service.start_generate_hypothesis()
        self.assertTrue(service.cancel_operation(operation_id))
        snapshot = service.wait_operation(operation_id)
        self.assertEqual("cancelled", snapshot.status)
        project = service.project
        assert project is not None
        self.assertIsNone(project.active_hypothesis_id)
        self.assertEqual(before, project.workflow_state)
        record = next(item for item in project.operations if item.id == operation_id)
        self.assertEqual(OperationStatus.CANCELLED, record.status)
        slow.shutdown(wait=True)

    def test_failed_operation_preserves_workflow(self) -> None:
        failing = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=FailingInference(),  # type: ignore[arg-type]
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        failing.create_project("fail")
        source = Path(self._tmp.name) / "fail.png"
        source.write_bytes(_png_bytes(32, 32))
        failing.load_source(source)
        failing.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
        before = failing.project.workflow_state

        with self.assertRaises(ApplicationError) as ctx:
            failing.generate_hypothesis()
        self.assertEqual("INFERENCE_FAILED", ctx.exception.code)
        project = failing.project
        assert project is not None
        self.assertEqual(before, project.workflow_state)
        self.assertIsNone(project.active_hypothesis_id)
        self.assertEqual(OperationStatus.FAILED, project.operations[-1].status)

    def test_duplicate_request_rejected(self) -> None:
        slow = MockOperationExecutor(step_delay_seconds=0.08)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=slow,
        )
        service.create_project("dup")
        source = Path(self._tmp.name) / "dup.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))

        first = service.start_generate_hypothesis()
        with self.assertRaises(ApplicationError) as ctx:
            service.start_generate_hypothesis()
        self.assertEqual("OPERATION_IN_PROGRESS", ctx.exception.code)
        service.wait_operation(first)
        slow.shutdown(wait=True)

    def test_progress_notification(self) -> None:
        events: list[object] = []
        barrier = threading.Event()

        def handler(event: object) -> None:
            events.append(event)
            if isinstance(event, OperationProgress) and event.current >= 1:
                barrier.set()

        slow = MockOperationExecutor(step_delay_seconds=0.02)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=slow,
        )
        service.add_operation_event_handler(handler)
        service.create_project("progress")
        source = Path(self._tmp.name) / "progress.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))

        operation_id = service.start_generate_hypothesis()
        self.assertTrue(barrier.wait(timeout=5.0))
        service.wait_operation(operation_id)
        progress_events = [item for item in events if isinstance(item, OperationProgress)]
        terminal = [item for item in events if isinstance(item, OperationSnapshot)]
        self.assertGreaterEqual(len(progress_events), 1)
        self.assertEqual(1, len(terminal))
        self.assertEqual("succeeded", terminal[0].status)
        messages = [item.message for item in progress_events]
        self.assertEqual(messages, sorted(messages, key=messages.index))
        slow.shutdown(wait=True)

    def test_workflow_updated_after_extraction_completion(self) -> None:
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()
        self.assertEqual(WorkflowState.OBJECT_CONFIRMED, self.service.project.workflow_state)
        operation_id = self.service.start_generate_extraction()
        snapshot = self.service.wait_operation(operation_id)
        self.assertEqual("succeeded", snapshot.status)
        self.assertEqual(WorkflowState.EXTRACTION_READY, self.service.project.workflow_state)
        self.assertIsNotNone(self.service.project.active_extraction_result_id)
