from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase
from uuid import uuid4

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mask_io import read_binary_mask_png
from nova_layer.object_workflow.adapters.mock_core_inference import (
    MockCoreInferenceEngine,
    build_deterministic_mask,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.binary_mask import BinaryMask, BinaryMaskError
from nova_layer.object_workflow.domain.models import (
    BoundingBox,
    OperationStatus,
    PositivePoint,
    Project,
    WorkflowState,
)
from nova_layer.object_workflow.ports.core_inference import (
    CoreInferenceError,
    CoreInferenceRequest,
    CoreInferenceSuccess,
)
from nova_layer.object_workflow.ports.project_store import ProjectStoreError


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


# Minimal valid 1x1 JPEG (SOF0).
_MIN_JPEG = bytes(
    [
        0xFF,
        0xD8,
        0xFF,
        0xE0,
        0x00,
        0x10,
        0x4A,
        0x46,
        0x49,
        0x46,
        0x00,
        0x01,
        0x01,
        0x00,
        0x00,
        0x01,
        0x00,
        0x01,
        0x00,
        0x00,
        0xFF,
        0xDB,
        0x00,
        0x43,
        0x00,
        *([0x08] * 64),
        0xFF,
        0xC0,
        0x00,
        0x0B,
        0x08,
        0x00,
        0x01,
        0x00,
        0x01,
        0x01,
        0x01,
        0x11,
        0x00,
        0xFF,
        0xC4,
        0x00,
        0x14,
        0x00,
        0x01,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x03,
        0xFF,
        0xDA,
        0x00,
        0x08,
        0x01,
        0x01,
        0x00,
        0x00,
        0x3F,
        0x00,
        0x7F,
        0xFF,
        0xD9,
    ]
)


def _service() -> ObjectWorkflowService:
    return ObjectWorkflowService(store=JsonProjectStore(), inference=MockCoreInferenceEngine())


def _intent(
    *signals: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {"signals": list(signals)},
    }


class FailingSaveStore(JsonProjectStore):
    def save(self, project: Project, package_path: Path, assets: dict[str, bytes]) -> None:
        raise ProjectStoreError("SAVE_FAILED", "forced save failure")


class FailingInference:
    def generate_hypothesis(
        self, request: CoreInferenceRequest
    ) -> CoreInferenceSuccess | CoreInferenceError:
        return CoreInferenceError(
            request_id=request.request_id,
            error_code="INFERENCE_FAILED",
            message="forced inference failure",
            retryable=False,
        )


class BinaryMaskTests(TestCase):
    def test_binary_mask_validation(self) -> None:
        mask = BinaryMask.from_pixels(2, 2, bytes([0, 255, 0, 255]))
        self.assertEqual(1, mask.channels)
        self.assertEqual(8, mask.bit_depth)
        with self.assertRaises(BinaryMaskError):
            BinaryMask.from_pixels(2, 2, bytes([0, 1, 0, 255]))
        with self.assertRaises(BinaryMaskError):
            BinaryMask(width=2, height=2, channels=3, bit_depth=8, data=bytes(12))


class MockGeometryTests(TestCase):
    def test_bounding_box_mask_geometry(self) -> None:
        signals = [BoundingBox(type="bounding_box", x=0.1, y=0.2, width=0.25, height=0.3)]
        mask = build_deterministic_mask(width=100, height=80, signals=signals)
        x0, y0 = round(0.1 * 100), round(0.2 * 80)
        x1, y1 = round(0.35 * 100), round(0.5 * 80)
        for y in range(80):
            for x in range(100):
                expected = 255 if y0 <= y < y1 and x0 <= x < x1 else 0
                self.assertEqual(expected, mask.data[y * 100 + x])

    def test_positive_point_fallback_square(self) -> None:
        signals = [PositivePoint(type="positive_point", x=0.5, y=0.5)]
        mask = build_deterministic_mask(width=100, height=100, signals=signals)
        side = max(1, round(min(100, 100) * 0.20))
        self.assertEqual(20, side)
        self.assertIn(255, mask.data)
        self.assertIn(0, mask.data)

    def test_deterministic_identical_inputs(self) -> None:
        signals = [
            PositivePoint(type="positive_point", x=0.25, y=0.75),
            BoundingBox(type="bounding_box", x=0.1, y=0.1, width=0.2, height=0.2),
        ]
        a = build_deterministic_mask(width=64, height=48, signals=signals)
        b = build_deterministic_mask(width=64, height=48, signals=signals)
        self.assertEqual(a.data, b.data)


class ObjectWorkflowUnitTests(TestCase):
    def test_create_project_nosource(self) -> None:
        service = _service()
        project = service.create_project("demo")
        self.assertEqual("2.0", project.schema_version)
        self.assertEqual(WorkflowState.NO_SOURCE, project.workflow_state)
        self.assertIsNone(project.active_source_image_id)
        self.assertEqual([], project.operations)

    def test_unsupported_extension_creates_no_operation(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.bmp"
            path.write_bytes(b"BM")
            with self.assertRaises(ApplicationError) as ctx:
                service.load_source(path)
            self.assertEqual("UNSUPPORTED_MEDIA_TYPE", ctx.exception.code)
        self.assertEqual([], service.list_operations())

    def test_misleading_extension_rejected(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.png"
            path.write_bytes(b"not-a-png")
            with self.assertRaises(ApplicationError) as ctx:
                service.load_source(path)
            self.assertEqual("UNSUPPORTED_MEDIA_TYPE", ctx.exception.code)
        ops = service.list_operations()
        self.assertEqual(1, len(ops))
        self.assertEqual(OperationStatus.FAILED, ops[0].status)

    def test_empty_intent_creates_no_operation(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(32, 24))
            service.load_source(path)
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError):
            service.create_artist_intent(_intent())
        self.assertEqual(before, len(service.list_operations()))
        self.assertEqual(WorkflowState.SOURCE_READY, service.project.workflow_state)

    def test_invalid_geometry_and_unsupported_signal(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(32, 24))
            service.load_source(path)
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError) as bad_point:
            service.create_artist_intent(_intent({"type": "positive_point", "x": 1.5, "y": 0.2}))
        self.assertEqual("INVALID_INTENT_GEOMETRY", bad_point.exception.code)
        with self.assertRaises(ApplicationError) as unsupported:
            service.create_artist_intent(_intent({"type": "scribble", "points": []}))
        self.assertEqual("UNSUPPORTED_INTENT_SIGNAL", unsupported.exception.code)
        self.assertEqual(before, len(service.list_operations()))
        self.assertIsNone(service.project.active_intent_id)

    def test_artist_intent_already_exists(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(32, 24))
            service.load_source(path)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.4, "y": 0.6}))
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError) as ctx:
            service.create_artist_intent(_intent({"type": "positive_point", "x": 0.1, "y": 0.1}))
        self.assertEqual("ARTIST_INTENT_ALREADY_EXISTS", ctx.exception.code)
        self.assertIn("UpdateArtistIntent", ctx.exception.message)
        self.assertEqual(before, len(service.list_operations()))

    def test_inference_failure_preserves_intent_provided(self) -> None:
        service = ObjectWorkflowService(store=JsonProjectStore(), inference=FailingInference())
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(40, 40))
            service.load_source(path)
        service.create_artist_intent(_intent({"type": "positive_point", "x": 0.5, "y": 0.5}))
        with self.assertRaises(ApplicationError) as ctx:
            service.generate_hypothesis()
        self.assertEqual("INFERENCE_FAILED", ctx.exception.code)
        self.assertEqual(WorkflowState.INTENT_PROVIDED, service.project.workflow_state)
        failed = [
            op for op in service.list_operations() if op.operation_type == "generate_hypothesis"
        ]
        self.assertEqual(1, len(failed))
        self.assertEqual(OperationStatus.FAILED, failed[0].status)
        self.assertIsNone(service.project.active_hypothesis_id)


class PersistenceTests(TestCase):
    def test_schema_1_0_and_unknown_rejected(self) -> None:
        store = JsonProjectStore()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for version, folder in (("1.0", "old.nova"), ("9.9", "future.nova")):
                package = root / folder
                package.mkdir()
                (package / "manifest.json").write_text(
                    json.dumps({"schema_version": version, "name": "x"}),
                    encoding="utf-8",
                )
                with self.assertRaises(ProjectStoreError) as ctx:
                    store.load(package)
                self.assertEqual("UNSUPPORTED_SCHEMA", ctx.exception.code)

    def test_relative_path_traversal_rejected(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(_png_bytes(16, 16))
            service.load_source(path)
            service.project.source_images[0].relative_asset_path = "assets/../secret.png"
            package = Path(tmp) / "proj.nova"
            with self.assertRaises(ApplicationError) as ctx:
                service.save_project(package)
            self.assertEqual("INVALID_ASSET_PATH", ctx.exception.code)

    def test_save_failure_preserves_previous_package(self) -> None:
        good = ObjectWorkflowService(store=JsonProjectStore(), inference=MockCoreInferenceEngine())
        good.create_project("demo")
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.png"
            src.write_bytes(_png_bytes(20, 20))
            good.load_source(src)
            package = Path(tmp) / "proj.nova"
            good.save_project(package)
            manifest_before = (package / "manifest.json").read_text(encoding="utf-8")

            bad = ObjectWorkflowService(
                store=FailingSaveStore(),
                inference=MockCoreInferenceEngine(),
            )
            bad.create_project("other")
            bad.load_source(src)
            with self.assertRaises(ApplicationError):
                bad.save_project(package)
            self.assertEqual(
                manifest_before,
                (package / "manifest.json").read_text(encoding="utf-8"),
            )

    def test_load_failure_preserves_in_memory_project(self) -> None:
        service = _service()
        service.create_project("keep-me")
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.nova"
            with self.assertRaises(ApplicationError):
                service.load_project(missing)
            self.assertEqual("keep-me", service.project.name)
            self.assertEqual(WorkflowState.NO_SOURCE, service.project.workflow_state)

    def test_round_trip_confirmation_lineage(self) -> None:
        service = _service()
        service.create_project("demo")
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "frame.jpg"
            src.write_bytes(_MIN_JPEG)
            # Misleading would fail; this is real jpeg with .jpg
            source = service.load_source(src)
            intent = service.create_artist_intent(
                _intent(
                    {"type": "positive_point", "x": 0.5, "y": 0.5},
                    {"type": "bounding_box", "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3},
                )
            )
            candidate_set = service.generate_hypothesis()
            hypothesis = service.select_candidate(candidate_set.candidates[0].id)
            confirmed = service.confirm_hypothesis()
            package = Path(tmp) / "proj.nova"
            service.save_project(package)

            restored = _service()
            restored.load_project(package)
            summary = restored.get_project_summary()
            self.assertEqual(WorkflowState.OBJECT_CONFIRMED.value, summary["workflow_state"])
            self.assertEqual(str(source.id), summary["active_source_image_id"])
            self.assertEqual(str(intent.id), summary["active_intent_id"])
            self.assertEqual(str(hypothesis.id), summary["active_hypothesis_id"])
            active = restored.get_active_confirmed_object()
            assert active is not None
            self.assertEqual(confirmed.id, active.id)
            self.assertEqual(hypothesis.id, active.hypothesis_id)
            confirmation_ids = {item.id for item in restored.project.confirmations}
            self.assertIn(active.confirmation_id, confirmation_ids)
            self.assertEqual(
                source.content_fingerprint,
                restored.project.source_images[0].content_fingerprint,
            )
            width, height, data = read_binary_mask_png(
                package / Path(hypothesis.mask_relative_path)
            )
            self.assertEqual(source.width, width)
            self.assertEqual(source.height, height)
            BinaryMask.from_pixels(width, height, data)


class FirstSliceEndToEndTests(TestCase):
    def test_complete_first_slice_workflow(self) -> None:
        service = _service()
        project = service.create_project("slice-one")
        self.assertEqual(WorkflowState.NO_SOURCE, project.workflow_state)

        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "plate.png"
            src.write_bytes(_png_bytes(80, 60, fill=90))
            service.load_source(src)
            self.assertEqual(WorkflowState.SOURCE_READY, service.project.workflow_state)

            service.create_artist_intent(_intent({"type": "positive_point", "x": 0.4, "y": 0.55}))
            self.assertEqual(WorkflowState.INTENT_PROVIDED, service.project.workflow_state)

            candidate_set = service.generate_hypothesis()
            self.assertEqual(WorkflowState.CANDIDATE_SET_READY, service.project.workflow_state)
            self.assertEqual(3, len(candidate_set.candidates))
            first = service.select_candidate(candidate_set.candidates[0].id)
            second = MockCoreInferenceEngine().generate_hypothesis(
                CoreInferenceRequest(
                    request_id=str(uuid4()),
                    source_image_path=str(src),
                    source_width=80,
                    source_height=60,
                    media_type="image/png",
                    content_fingerprint=service.project.source_images[0].content_fingerprint,
                    intent_instruction=service.project.intents[0].instruction,
                )
            )
            assert isinstance(second, CoreInferenceSuccess)
            self.assertEqual(3, len(second.masks))
            self.assertEqual(
                service.get_asset_bytes(first.mask_relative_path)[:0],  # touch asset map
                b"",
            )
            # Compare mask pixels via deterministic rebuild
            rebuilt = build_deterministic_mask(
                width=80,
                height=60,
                signals=[PositivePoint(type="positive_point", x=0.4, y=0.55)],
            )
            _, _, saved = read_binary_mask_png(
                # decode from in-memory png bytes
                _write_temp_mask(tmp, service.get_asset_bytes(first.mask_relative_path))
            )
            self.assertEqual(rebuilt.data, saved)
            self.assertEqual(WorkflowState.HYPOTHESIS_READY, service.project.workflow_state)

            service.confirm_hypothesis()
            self.assertEqual(WorkflowState.OBJECT_CONFIRMED, service.project.workflow_state)

            package = Path(tmp) / "slice.nova"
            service.save_project(package)
            other = _service()
            other.load_project(package)
            self.assertEqual(
                WorkflowState.OBJECT_CONFIRMED,
                other.project.workflow_state,
            )
            self.assertIsNotNone(other.get_active_confirmed_object())
            for op in other.list_operations():
                self.assertNotEqual(OperationStatus.RUNNING, op.status)


def _write_temp_mask(tmp: str, blob: bytes) -> Path:
    path = Path(tmp) / f"{uuid4().hex}.png"
    path.write_bytes(blob)
    return path
