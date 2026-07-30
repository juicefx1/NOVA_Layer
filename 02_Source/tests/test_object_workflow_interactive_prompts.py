from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from nova_layer.object_workflow.adapters.core_inference_registry import (
    build_default_core_inference_registry,
)
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import (
    MockCoreInferenceEngine,
    build_deterministic_mask,
)
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.sam2_core_inference import (
    Sam2ProviderError,
    _prompts_from_signals,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import (
    BoundingBox,
    NegativePoint,
    OperationStatus,
    PositivePoint,
    WorkflowState,
)
from nova_layer.object_workflow.domain.validation import (
    count_prompt_signals,
    parse_intent_signals,
)
from nova_layer.object_workflow.ports.provider_registry import ProviderCapabilities


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


class DomainNegativePointTests(TestCase):
    def test_create_positive_negative_and_mixed(self) -> None:
        positive = PositivePoint(x=0.1, y=0.2)
        negative = NegativePoint(x=0.8, y=0.9)
        box = BoundingBox(x=0.2, y=0.2, width=0.3, height=0.3)
        signals = parse_intent_signals(
            [
                positive.model_dump(),
                negative.model_dump(),
                box.model_dump(),
            ]
        )
        self.assertEqual(3, len(signals))
        self.assertIsInstance(signals[0], PositivePoint)
        self.assertIsInstance(signals[1], NegativePoint)
        self.assertIsInstance(signals[2], BoundingBox)
        counts = count_prompt_signals(signals)
        self.assertEqual((1, 1, True), counts)

    def test_deterministic_signal_ordering(self) -> None:
        raw = [
            {"type": "negative_point", "x": 0.9, "y": 0.1},
            {"type": "positive_point", "x": 0.1, "y": 0.9},
            {"type": "bounding_box", "x": 0.2, "y": 0.2, "width": 0.2, "height": 0.2},
        ]
        parsed = parse_intent_signals(raw)
        self.assertEqual(
            ["negative_point", "positive_point", "bounding_box"],
            [item.type for item in parsed],
        )


class ApplicationInteractivePromptTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.service.create_project("interactive")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(64, 48))
        self.service.load_source(source)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_and_edit_prompt_signals(self) -> None:
        first = self.service.create_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.3, "y": 0.3},
                {"type": "negative_point", "x": 0.7, "y": 0.7},
            )
        )
        self.assertEqual(1, first.revision)
        self.assertEqual(2, len(first.instruction.payload.signals))

        moved = self.service.update_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.35, "y": 0.35},
                {"type": "negative_point", "x": 0.7, "y": 0.7},
            )
        )
        self.assertEqual(2, moved.revision)

        cleared_points = self.service.update_artist_intent(
            _intent({"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.4, "height": 0.4})
        )
        self.assertEqual(3, cleared_points.revision)
        self.assertEqual(1, len(cleared_points.instruction.payload.signals))

        replaced_box = self.service.update_artist_intent(
            _intent({"type": "bounding_box", "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3})
        )
        self.assertEqual(4, replaced_box.revision)

        no_box = self.service.update_artist_intent(
            _intent({"type": "positive_point", "x": 0.5, "y": 0.5})
        )
        self.assertEqual(5, no_box.revision)

    def test_noop_apply_creates_no_revision(self) -> None:
        intent = self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.4, "y": 0.4})
        )
        again = self.service.update_artist_intent(
            _intent({"type": "positive_point", "x": 0.4, "y": 0.4})
        )
        self.assertEqual(intent.id, again.id)
        self.assertEqual(1, len(self.service.project.intents))

    def test_editing_invalidates_hypothesis_confirmation_extraction(self) -> None:
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()
        self.service.generate_extraction()
        self.assertEqual(WorkflowState.EXTRACTION_READY, self.service.project.workflow_state)
        self.service.update_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.5, "y": 0.5},
                {"type": "negative_point", "x": 0.2, "y": 0.2},
            )
        )
        project = self.service.project
        self.assertIsNone(project.active_hypothesis_id)
        self.assertIsNone(project.active_candidate_set_id)
        self.assertIsNone(project.active_confirmation_id)
        self.assertIsNone(project.active_confirmed_object_id)
        self.assertIsNone(project.active_extraction_result_id)
        self.assertEqual(WorkflowState.INTENT_PROVIDED, project.workflow_state)
        self.assertEqual(1, len(project.hypotheses))
        self.assertEqual(1, len(project.extraction_results))

    def test_failed_generate_preserves_active_intent(self) -> None:
        class FailingEngine(MockCoreInferenceEngine):
            def generate_hypothesis(self, request):  # type: ignore[no-untyped-def]
                from nova_layer.object_workflow.ports.core_inference import CoreInferenceError

                return CoreInferenceError(
                    request_id=request.request_id,
                    error_code="INFERENCE_FAILED",
                    message="boom",
                    retryable=False,
                )

        failing = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=FailingEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        failing.create_project("fail")
        source = Path(self._tmp.name) / "fail.png"
        source.write_bytes(_png_bytes(32, 32))
        failing.load_source(source)
        intent = failing.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.5, "y": 0.5})
        )
        with self.assertRaises(ApplicationError):
            failing.generate_hypothesis()
        self.assertEqual(intent.id, failing.project.active_intent_id)
        self.assertIsNone(failing.project.active_hypothesis_id)

    def test_stale_result_not_committed_after_newer_edit(self) -> None:
        executor = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=executor,
        )
        service.create_project("stale")
        source = Path(self._tmp.name) / "stale.png"
        source.write_bytes(_png_bytes(40, 40))
        service.load_source(source)
        first = service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.3, "y": 0.3})
        )
        operation_id = service.start_generate_hypothesis()
        service.update_artist_intent(_intent({"type": "positive_point", "x": 0.8, "y": 0.8}))
        # Wait for terminal callback to settle.
        import time

        for _ in range(100):
            if not service.has_running_operation():
                break
            time.sleep(0.02)
        self.assertIsNone(service.project.active_hypothesis_id)
        op = next(item for item in service.project.operations if item.id == operation_id)
        self.assertEqual(OperationStatus.CANCELLED, op.status)
        self.assertEqual(first.revision + 1, service.project.intents[-1].revision)
        executor.shutdown(wait=True)

    def test_successful_generate_binds_revision_at_start(self) -> None:
        intent = self.service.create_artist_intent(
            _intent({"type": "positive_point", "x": 0.4, "y": 0.4})
        )
        hyp = self.service.generate_hypothesis()
        self.assertEqual(intent.id, hyp.intent_id)

    def test_unsupported_negative_rejected_before_operation(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            inference_capabilities=ProviderCapabilities(
                supports_positive_point=True,
                supports_bounding_box=True,
                supports_negative_point=False,
                supports_cpu=True,
            ),
        )
        service.create_project("caps")
        source = Path(self._tmp.name) / "caps.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.4, "y": 0.4},
                {"type": "negative_point", "x": 0.6, "y": 0.6},
            )
        )
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError) as ctx:
            service.start_generate_hypothesis()
        self.assertEqual("UNSUPPORTED_PROVIDER_CAPABILITY", ctx.exception.code)
        self.assertEqual(before, len(service.list_operations()))


class MockMixedPromptTests(TestCase):
    def test_positive_negative_and_box_behaviour(self) -> None:
        width, height = 100, 100
        positive_only = build_deterministic_mask(
            width=width,
            height=height,
            signals=[PositivePoint(x=0.5, y=0.5)],
        )
        mixed = build_deterministic_mask(
            width=width,
            height=height,
            signals=[
                BoundingBox(x=0.1, y=0.1, width=0.8, height=0.8),
                PositivePoint(x=0.5, y=0.5),
                NegativePoint(x=0.5, y=0.5),
            ],
        )
        self.assertIn(255, positive_only.data)
        # Negative clears the square around the same centre after box seed.
        cx = round(0.5 * (width - 1))
        cy = round(0.5 * (height - 1))
        self.assertEqual(0, mixed.data[cy * width + cx])
        a = build_deterministic_mask(
            width=64,
            height=48,
            signals=[
                PositivePoint(x=0.2, y=0.2),
                NegativePoint(x=0.8, y=0.8),
                BoundingBox(x=0.3, y=0.3, width=0.2, height=0.2),
            ],
        )
        b = build_deterministic_mask(
            width=64,
            height=48,
            signals=[
                PositivePoint(x=0.2, y=0.2),
                NegativePoint(x=0.8, y=0.8),
                BoundingBox(x=0.3, y=0.3, width=0.2, height=0.2),
            ],
        )
        self.assertEqual(a.data, b.data)


class Sam2PromptMappingTests(TestCase):
    def test_label_mapping_and_ordering(self) -> None:
        signals = parse_intent_signals(
            [
                {"type": "positive_point", "x": 0.1, "y": 0.2},
                {"type": "negative_point", "x": 0.8, "y": 0.9},
                {"type": "positive_point", "x": 0.4, "y": 0.4},
                {"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
            ]
        )
        coords, labels, box = _prompts_from_signals(signals, width=100, height=200)
        assert coords is not None and labels is not None and box is not None
        self.assertEqual((3, 2), coords.shape)
        np.testing.assert_array_equal(labels, np.asarray([1, 0, 1], dtype=np.int32))
        self.assertEqual([10.0, 20.0, 60.0, 120.0], box.tolist())

    def test_out_of_bounds_rejection(self) -> None:
        from nova_layer.object_workflow.adapters.sam2_core_inference import _to_pixel

        with self.assertRaises(Sam2ProviderError):
            _to_pixel(1.5, 0.2, width=10, height=10)
        with self.assertRaises(Sam2ProviderError):
            _to_pixel(-0.1, 0.2, width=10, height=10)


class ProviderCapabilityReportingTests(TestCase):
    def test_mock_and_sam2_report_negative_point(self) -> None:
        registry = build_default_core_inference_registry()
        mock = registry.get("mock")
        sam2 = registry.get("sam2")
        self.assertTrue(mock.capabilities.supports_negative_point)
        self.assertTrue(sam2.capabilities.supports_negative_point)
        self.assertIn("negative_point", mock.supported_intent_signals)
        self.assertIn("negative_point", sam2.supported_intent_signals)


class PersistenceNegativePointTests(TestCase):
    def test_negative_and_mixed_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            service = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
                extraction=MockPrecisionExtractionEngine(),
            )
            service.create_project("persist-neg")
            source = Path(tmp) / "a.png"
            source.write_bytes(_png_bytes(32, 24))
            service.load_source(source)
            signals = [
                {"type": "positive_point", "x": 0.2, "y": 0.3},
                {"type": "negative_point", "x": 0.8, "y": 0.7},
                {"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.4, "height": 0.5},
            ]
            service.create_artist_intent(_intent(*signals))
            package = Path(tmp) / "proj.nova"
            service.save_project(package)

            loaded = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
            )
            project = loaded.load_project(package)
            self.assertEqual("2.0", project.schema_version)
            intent = next(item for item in project.intents if item.id == project.active_intent_id)
            self.assertEqual(signals, intent.instruction.payload.signals)

    def test_existing_schema_without_negative_loads(self) -> None:
        with TemporaryDirectory() as tmp:
            service = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
            )
            service.create_project("legacy")
            source = Path(tmp) / "a.png"
            source.write_bytes(_png_bytes(32, 24))
            service.load_source(source)
            service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
            package = Path(tmp) / "legacy.nova"
            service.save_project(package)
            loaded = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
            )
            project = loaded.load_project(package)
            intent = next(item for item in project.intents if item.id == project.active_intent_id)
            self.assertEqual(
                [{"type": "positive_point", "x": 0.5, "y": 0.5}],
                intent.instruction.payload.signals,
            )
