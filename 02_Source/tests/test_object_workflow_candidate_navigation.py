from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
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


class CandidateNavigationApplicationTests(TestCase):
    """Boundary policy Option A: clamp at first/last (no wrap)."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.service.create_project("nav")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(40, 32))
        self.service.load_source(source)
        self.service.create_artist_intent(_intent({"type": "positive_point", "x": 0.4, "y": 0.4}))
        self.cset = self.service.generate_candidates()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_next_previous_clamp_option_a(self) -> None:
        first = self.cset.candidates[0].id
        last = self.cset.candidates[-1].id
        self.assertEqual(first, self.service.get_previous_candidate_id(first))
        self.assertEqual(last, self.service.get_next_candidate_id(last))
        self.assertEqual(
            self.cset.candidates[1].id,
            self.service.get_next_candidate_id(first),
        )
        self.assertEqual(
            self.cset.candidates[-2].id,
            self.service.get_previous_candidate_id(last),
        )

    def test_select_active_is_noop(self) -> None:
        hyp = self.service.select_candidate(self.cset.candidates[1].id)
        before_sets = len(self.service.project.candidate_sets)
        before_hyps = len(self.service.project.hypotheses)
        again = self.service.select_candidate(self.cset.candidates[1].id)
        self.assertEqual(hyp.id, again.id)
        self.assertEqual(before_sets, len(self.service.project.candidate_sets))
        self.assertEqual(before_hyps, len(self.service.project.hypotheses))

    def test_invalid_candidate_does_not_mutate(self) -> None:
        before = self.service.project.model_dump(mode="json")
        with self.assertRaises(ApplicationError) as ctx:
            self.service.select_candidate(uuid4())
        self.assertEqual("CANDIDATE_NOT_FOUND", ctx.exception.code)
        self.assertEqual(before, self.service.project.model_dump(mode="json"))

    def test_select_creates_no_operation_and_skips_provider(self) -> None:
        class CountingEngine(MockCoreInferenceEngine):
            def __init__(self) -> None:
                self.calls = 0

            def generate_hypothesis(self, request):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().generate_hypothesis(request)

        engine = CountingEngine()
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=engine,
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        service.create_project("count")
        source = Path(self._tmp.name) / "b.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
        cset = service.generate_candidates()
        self.assertEqual(1, engine.calls)
        ops_before = len(service.list_operations())
        service.select_candidate(cset.candidates[0].id)
        self.assertEqual(1, engine.calls)
        self.assertEqual(ops_before, len(service.list_operations()))

    def test_confirm_uses_committed_not_query_helpers(self) -> None:
        first = self.service.select_candidate(self.cset.candidates[0].id)
        second = self.service.select_candidate(self.cset.candidates[2].id)
        confirmed = self.service.confirm_hypothesis()
        self.assertEqual(second.id, confirmed.hypothesis_id)
        self.assertNotEqual(first.id, confirmed.hypothesis_id)
        self.assertEqual(
            self.cset.candidates[2].mask_relative_path,
            confirmed.mask_relative_path,
        )

    def test_query_helpers(self) -> None:
        self.assertIsNone(self.service.get_active_candidate())
        self.service.select_candidate(self.cset.candidates[1].id)
        active = self.service.get_active_candidate()
        assert active is not None
        self.assertEqual(self.cset.candidates[1].id, active.id)
        self.assertEqual(1, self.service.get_candidate_index(active.id))
        fetched = self.service.get_candidate(active.id)
        self.assertEqual(active.id, fetched.id)


class CandidateNavigationControllerTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.controller = ObjectWorkflowController(service)
        self.controller.create_project("ctrl")
        source = Path(self._tmp.name) / "c.png"
        source.write_bytes(_png_bytes(36, 36))
        self.controller.load_source(source)
        self.controller.apply_artist_intent(positive_points=[(0.5, 0.5)], bounding_box=None)
        self.controller.generate_hypothesis()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_preview_and_clear(self) -> None:
        candidates = self.controller.list_candidates()
        self.assertEqual(3, len(candidates))
        self.controller.preview_candidate(candidates[2].id)
        self.assertEqual(candidates[2].id, self.controller.preview_candidate_id)
        self.assertIsNotNone(self.controller.mask_overlay)
        committed_before_clear = self.controller.committed_mask_overlay
        self.controller.clear_candidate_preview()
        self.assertIsNone(self.controller.preview_candidate_id)
        # No committed selection yet → display mask is cleared.
        self.assertIsNone(self.controller.mask_overlay)
        self.assertEqual(
            None if committed_before_clear is None else committed_before_clear.tobytes(),
            None
            if self.controller.committed_mask_overlay is None
            else self.controller.committed_mask_overlay.tobytes(),
        )

    def test_focus_next_previous_then_commit(self) -> None:
        candidates = self.controller.list_candidates()
        self.controller.preview_candidate(candidates[0].id)
        self.controller.focus_next_candidate()
        self.assertEqual(candidates[1].id, self.controller.focused_candidate_id)
        self.controller.focus_previous_candidate()
        self.assertEqual(candidates[0].id, self.controller.focused_candidate_id)
        # Clamp at first.
        self.controller.focus_previous_candidate()
        self.assertEqual(candidates[0].id, self.controller.focused_candidate_id)
        self.controller.commit_focused_or_previewed_candidate()
        self.assertEqual(
            WorkflowState.HYPOTHESIS_READY.value,
            self.controller.view_state().workflow_state,
        )
        self.assertIsNone(self.controller.preview_candidate_id)
        self.assertTrue(self.controller.view_state().can_confirm)

    def test_select_next_previous_commit(self) -> None:
        candidates = self.controller.list_candidates()
        self.controller.select_candidate(candidates[0].id)
        self.controller.select_next_candidate()
        items = self.controller.list_candidates()
        self.assertTrue(items[1].is_active)
        self.controller.select_previous_candidate()
        items = self.controller.list_candidates()
        self.assertTrue(items[0].is_active)

    def test_no_candidate_set_errors(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
        )
        controller = ObjectWorkflowController(service)
        controller.create_project("empty")
        errors: list[str] = []
        controller.error_occurred.connect(errors.append)
        controller.select_next_candidate()
        controller.preview_candidate(uuid4())
        self.assertTrue(any("NO_ACTIVE_CANDIDATE_SET" in item for item in errors))

    def test_toggle_comparison(self) -> None:
        candidates = self.controller.list_candidates()
        self.controller.select_candidate(candidates[0].id)
        self.controller._focused_candidate_id = candidates[2].id
        self.controller.toggle_candidate_comparison()
        self.assertTrue(self.controller.comparison_mode)
        self.assertEqual(candidates[2].id, self.controller.preview_candidate_id)
        self.controller.toggle_candidate_comparison()
        self.assertFalse(self.controller.comparison_mode)
        self.assertIsNone(self.controller.preview_candidate_id)
