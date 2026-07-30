from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.local_precision_extraction import (
    PROVIDER_ID as LOCAL_PROVIDER_ID,
)
from nova_layer.object_workflow.adapters.local_precision_extraction import (
    LocalPrecisionExtractionEngine,
    build_refined_rgba,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    PROVIDER_ID as MOCK_PROVIDER_ID,
)
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
    build_deterministic_rgba,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    DEFAULT_EXTRACTION_PROVIDER,
    PrecisionExtractionProviderRegistry,
    build_default_precision_extraction_registry,
    create_precision_extraction_engine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import WorkflowState
from nova_layer.object_workflow.ports.extraction_provider import (
    ExtractionProviderCapabilities,
    ExtractionProviderDescriptor,
    ExtractionRuntimeConfig,
)
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionError,
    PrecisionExtractionRequest,
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


def _rgb(width: int, height: int, value: int = 90) -> bytes:
    return bytes([value, value // 2, value // 3]) * (width * height)


def _mask(width: int, height: int) -> BinaryMask:
    data = bytearray(width * height)
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            data[y * width + x] = 255
    return BinaryMask.from_pixels(width, height, bytes(data))


class ExtractionRegistryTests(TestCase):
    def test_default_order_and_mock(self) -> None:
        registry = build_default_precision_extraction_registry()
        ids = [item.provider_id for item in registry.list()]
        self.assertEqual(["mock", "real", "matting"], ids)
        self.assertEqual(DEFAULT_EXTRACTION_PROVIDER, "mock")
        self.assertIsInstance(registry.create("mock"), MockPrecisionExtractionEngine)
        self.assertIsInstance(
            create_precision_extraction_engine("mock"),
            MockPrecisionExtractionEngine,
        )

    def test_descriptor_and_duplicate_unknown(self) -> None:
        registry = build_default_precision_extraction_registry()
        real = registry.get("real")
        self.assertEqual("Local Edge-Refined Extraction", real.display_name)
        self.assertTrue(real.capabilities.supports_edge_feather)
        self.assertFalse(real.requires_model)
        for descriptor in registry.list():
            self.assertIsInstance(descriptor.provider_id, str)
            self.assertIsInstance(descriptor.capabilities, ExtractionProviderCapabilities)

        with self.assertRaises(ApplicationError) as dup:
            registry.register(real, lambda _c: MockPrecisionExtractionEngine())
        self.assertEqual("DUPLICATE_PROVIDER", dup.exception.code)
        with self.assertRaises(ApplicationError) as missing:
            registry.create("nope")
        self.assertEqual("INVALID_PROVIDER_CONFIG", missing.exception.code)

    def test_unavailable_provider(self) -> None:
        registry = PrecisionExtractionProviderRegistry()
        registry.register(
            ExtractionProviderDescriptor(
                provider_id="down",
                display_name="Down",
                provider_version="0",
                provider_kind="test",
                requires_model=False,
                availability="unavailable",
                availability_message="offline",
                capabilities=ExtractionProviderCapabilities(),
            ),
            lambda _c: MockPrecisionExtractionEngine(),
        )
        with self.assertRaises(ApplicationError) as ctx:
            registry.create("down")
        self.assertEqual("PROVIDER_UNAVAILABLE", ctx.exception.code)


class LocalExtractionAdapterTests(TestCase):
    def test_deterministic_rgba_preserves_rgb_and_alpha(self) -> None:
        width, height = 8, 6
        rgb = _rgb(width, height, value=100)
        mask = _mask(width, height)
        first, _meta = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            cleanup_radius=0,
            feather_radius=0.0,
            edge_blur_radius=0.0,
        )
        second, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
        )
        self.assertEqual(first.data, second.data)
        baseline = build_deterministic_rgba(
            width=width, height=height, source_rgb=rgb, mask=mask
        )
        self.assertEqual(first.data, baseline.data)
        for index in range(width * height):
            rgba_i = index * 4
            rgb_i = index * 3
            self.assertEqual(first.data[rgba_i], rgb[rgb_i])
            self.assertEqual(first.data[rgba_i + 1], rgb[rgb_i + 1])
            self.assertEqual(first.data[rgba_i + 2], rgb[rgb_i + 2])
            self.assertEqual(first.data[rgba_i + 3], mask.data[index])

    def test_edge_refinement_changes_alpha_deterministically(self) -> None:
        width, height = 16, 12
        rgb = _rgb(width, height)
        mask = _mask(width, height)
        plain, _ = build_refined_rgba(
            width=width, height=height, source_rgb=rgb, mask=mask
        )
        refined, meta = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            cleanup_radius=1,
            feather_radius=1.0,
            edge_blur_radius=1.0,
        )
        self.assertNotEqual(plain.data, refined.data)
        again, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            cleanup_radius=1,
            feather_radius=1.0,
            edge_blur_radius=1.0,
        )
        self.assertEqual(refined.data, again.data)
        for index in range(width * height):
            rgba_i = index * 4
            rgb_i = index * 3
            self.assertEqual(refined.data[rgba_i], rgb[rgb_i])
            self.assertEqual(refined.data[rgba_i + 1], rgb[rgb_i + 1])
            self.assertEqual(refined.data[rgba_i + 2], rgb[rgb_i + 2])

    def test_cancel_before_work(self) -> None:
        engine = LocalPrecisionExtractionEngine()
        request = PrecisionExtractionRequest(
            request_id=str(uuid4()),
            source_width=4,
            source_height=4,
            source_rgb=_rgb(4, 4),
            mask=_mask(4, 4),
            provider_options={"should_cancel": lambda: True},
        )
        result = engine.extract(request)
        self.assertIsInstance(result, PrecisionExtractionError)
        self.assertEqual("CANCELLED", result.error_code)  # type: ignore[union-attr]


class ExtractionWorkflowTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.registry = build_default_precision_extraction_registry()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=self.registry.create(
                "real",
                ExtractionRuntimeConfig(
                    selected_provider_id="real",
                    feather_radius=1.0,
                    cleanup_radius=1,
                ),
            ),
        )
        self.service.create_project("extract-real")
        source = Path(self._tmp.name) / "plate.png"
        source.write_bytes(_png_bytes(40, 30, fill=90))
        self.service.load_source(source)
        self.service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {
                    "signals": [
                        {"type": "positive_point", "x": 0.5, "y": 0.5},
                        {
                            "type": "bounding_box",
                            "x": 0.2,
                            "y": 0.2,
                            "width": 0.4,
                            "height": 0.4,
                        },
                    ]
                },
            }
        )
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_real_extraction_and_provider_switch(self) -> None:
        result = self.service.generate_extraction()
        self.assertEqual(LOCAL_PROVIDER_ID, result.provider_id)
        self.assertEqual(WorkflowState.EXTRACTION_READY, self.service.project.workflow_state)
        history = list(self.service.project.extraction_results)  # type: ignore[union-attr]
        self.service.set_extraction_engine(self.registry.create("mock"))
        self.assertEqual(history, self.service.project.extraction_results)  # type: ignore[union-attr]
        again = self.service.generate_extraction()
        self.assertEqual(MOCK_PROVIDER_ID, again.provider_id)

    def test_switch_blocked_during_extraction(self) -> None:
        executor = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=executor,
        )
        service.create_project("busy")
        source = Path(self._tmp.name) / "busy.png"
        source.write_bytes(_png_bytes(32, 24))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.4, "y": 0.4}]},
            }
        )
        cset = service.generate_hypothesis()
        service.select_candidate(cset.candidates[0].id)
        service.confirm_hypothesis()
        op_id = service.start_generate_extraction()
        with self.assertRaises(ApplicationError) as ctx:
            service.set_extraction_engine(LocalPrecisionExtractionEngine())
        self.assertEqual("OPERATION_IN_PROGRESS", ctx.exception.code)
        service.wait_operation(op_id)
        executor.shutdown(wait=True)

    def test_duplicate_protection_and_persistence(self) -> None:
        executor = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=self.registry.create("real"),
            executor=executor,
        )
        service.create_project("dup")
        source = Path(self._tmp.name) / "dup.png"
        source.write_bytes(_png_bytes(32, 24))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
            }
        )
        cset = service.generate_hypothesis()
        service.select_candidate(cset.candidates[0].id)
        service.confirm_hypothesis()
        first = service.start_generate_extraction()
        with self.assertRaises(ApplicationError) as ctx:
            service.start_generate_extraction()
        self.assertEqual("OPERATION_IN_PROGRESS", ctx.exception.code)
        service.wait_operation(first)
        package = Path(self._tmp.name) / "proj.nova"
        service.save_project(package)
        loaded = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        project = loaded.load_project(package)
        self.assertEqual(WorkflowState.EXTRACTION_READY, project.workflow_state)
        extraction = next(
            item
            for item in project.extraction_results
            if item.id == project.active_extraction_result_id
        )
        self.assertEqual(LOCAL_PROVIDER_ID, extraction.provider_id)
        executor.shutdown(wait=True)


class ExtractionControllerTests(TestCase):
    def test_ui_provider_controls(self) -> None:
        controller = ObjectWorkflowController()
        ids = [item.provider_id for item in controller.list_precision_extraction_providers()]
        # Built-in providers remain present; installed/discovered plugins may add more.
        for expected in ("mock", "real", "matting"):
            self.assertIn(expected, ids)
        self.assertEqual(["mock", "real", "matting"], ids[:3])
        state = controller.view_state()
        self.assertEqual("mock", state.precision_extraction_provider)
        controller.set_precision_extraction_provider("real")
        self.assertEqual("real", controller.view_state().precision_extraction_provider)
        controller.set_extraction_refinement(feather_radius=2.0, cleanup_radius=1)
        state = controller.view_state()
        self.assertEqual(2.0, state.precision_extraction_feather_radius)
        self.assertEqual(1, state.precision_extraction_cleanup_radius)
