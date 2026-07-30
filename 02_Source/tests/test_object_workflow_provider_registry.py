from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.core_inference_factory import (
    DEFAULT_PROVIDER,
    create_core_inference_engine,
    resolve_provider_name,
)
from nova_layer.object_workflow.adapters.core_inference_registry import (
    CoreInferenceProviderRegistry,
    build_default_core_inference_registry,
)
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import (
    PROVIDER_ID as MOCK_RESULT_PROVIDER_ID,
)
from nova_layer.object_workflow.adapters.mock_core_inference import (
    MockCoreInferenceEngine,
    build_deterministic_mask,
)
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import OperationStatus, WorkflowState
from nova_layer.object_workflow.domain.validation import parse_intent_signals
from nova_layer.object_workflow.ports.core_inference import (
    CoreInferenceEngine,
    CoreInferenceError,
    CoreInferenceRequest,
    CoreInferenceSuccess,
)
from nova_layer.object_workflow.ports.provider_registry import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderRuntimeConfig,
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


def _descriptor(
    provider_id: str,
    *,
    capabilities: ProviderCapabilities,
    availability: str = "available",
    message: str = "ok",
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id,
        provider_version="0.0-test",
        provider_kind="test",
        supported_intent_signals=tuple(
            name
            for name, enabled in (
                ("positive_point", capabilities.supports_positive_point),
                ("bounding_box", capabilities.supports_bounding_box),
            )
            if enabled
        ),
        supported_devices=("cpu",),
        requires_model_artifact=False,
        availability=availability,  # type: ignore[arg-type]
        availability_message=message,
        capabilities=capabilities,
        configuration_keys=(),
    )


class _DeterministicEngine:
    def __init__(self, provider_id: str = "test.deterministic") -> None:
        self.provider_id = provider_id

    def generate_hypothesis(
        self, request: CoreInferenceRequest
    ) -> CoreInferenceSuccess | CoreInferenceError:
        signals = parse_intent_signals(request.intent_instruction.payload.signals)
        mask = build_deterministic_mask(
            width=request.source_width,
            height=request.source_height,
            signals=signals,
        )
        return CoreInferenceSuccess.from_single(
            request_id=request.request_id,
            mask=mask,
            confidence=0.71,
            provider_id=self.provider_id,
            provider_version="0.0-test",
        )


class RegistryTests(TestCase):
    def test_default_registry_order_and_mock(self) -> None:
        registry = build_default_core_inference_registry()
        ids = [item.provider_id for item in registry.list()]
        self.assertEqual(["mock", "sam2"], ids)
        self.assertTrue(registry.contains("mock"))
        self.assertIsInstance(registry.create("mock"), MockCoreInferenceEngine)
        self.assertEqual(DEFAULT_PROVIDER, "mock")
        self.assertEqual("mock", resolve_provider_name(None))

    def test_duplicate_and_unknown_rejection(self) -> None:
        registry = CoreInferenceProviderRegistry()
        caps = ProviderCapabilities(supports_positive_point=True, supports_cpu=True)
        registry.register(
            _descriptor("alpha", capabilities=caps),
            lambda _c: MockCoreInferenceEngine(),
        )
        with self.assertRaises(ApplicationError) as dup:
            registry.register(
                _descriptor("alpha", capabilities=caps),
                lambda _c: MockCoreInferenceEngine(),
            )
        self.assertEqual("DUPLICATE_PROVIDER", dup.exception.code)
        with self.assertRaises(ApplicationError) as missing:
            registry.create("missing")
        self.assertEqual("INVALID_PROVIDER_CONFIG", missing.exception.code)
        with self.assertRaises(ApplicationError) as unknown:
            resolve_provider_name("cloud-magic")
        self.assertEqual("INVALID_PROVIDER_CONFIG", unknown.exception.code)

    def test_unavailable_provider_reporting_and_create(self) -> None:
        registry = CoreInferenceProviderRegistry()
        caps = ProviderCapabilities(supports_positive_point=True, supports_cpu=True)
        registry.register(
            _descriptor("gone", capabilities=caps, availability="unavailable", message="not here"),
            lambda _c: MockCoreInferenceEngine(),
        )
        descriptor = registry.get("gone")
        self.assertEqual("unavailable", descriptor.availability)
        self.assertEqual("not here", descriptor.availability_message)
        with self.assertRaises(ApplicationError) as ctx:
            registry.create("gone")
        self.assertEqual("PROVIDER_UNAVAILABLE", ctx.exception.code)

    def test_create_failure_mapping(self) -> None:
        registry = CoreInferenceProviderRegistry()
        caps = ProviderCapabilities(supports_cpu=True)

        def boom(_config: ProviderRuntimeConfig) -> CoreInferenceEngine:
            raise RuntimeError("boom")

        registry.register(_descriptor("boom", capabilities=caps), boom)
        with self.assertRaises(ApplicationError) as ctx:
            registry.create("boom")
        self.assertEqual("PROVIDER_CREATE_FAILED", ctx.exception.code)

    def test_descriptor_has_no_framework_types(self) -> None:
        for descriptor in build_default_core_inference_registry().list():
            for value in (
                descriptor.provider_id,
                descriptor.display_name,
                descriptor.provider_version,
                descriptor.provider_kind,
                descriptor.availability,
                descriptor.availability_message,
            ):
                self.assertIsInstance(value, str)
            self.assertIsInstance(descriptor.supported_intent_signals, tuple)
            self.assertIsInstance(descriptor.supported_devices, tuple)
            self.assertIsInstance(descriptor.requires_model_artifact, bool)
            self.assertIsInstance(descriptor.capabilities, ProviderCapabilities)

    def test_sam2_descriptor_registered(self) -> None:
        registry = build_default_core_inference_registry()
        descriptor = registry.get("sam2")
        self.assertEqual("SAM 2.1 Hiera Tiny", descriptor.display_name)
        self.assertTrue(descriptor.requires_model_artifact)
        self.assertTrue(descriptor.capabilities.requires_local_checkpoint)
        self.assertTrue(descriptor.capabilities.supports_positive_point)
        self.assertTrue(descriptor.capabilities.supports_bounding_box)
        self.assertTrue(descriptor.capabilities.supports_negative_point)

    def test_factory_wrapper_uses_registry(self) -> None:
        engine = create_core_inference_engine("mock")
        self.assertIsInstance(engine, MockCoreInferenceEngine)


class CapabilityValidationTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _service(self, capabilities: ProviderCapabilities) -> ObjectWorkflowService:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=_DeterministicEngine(),  # type: ignore[arg-type]
            extraction=MockPrecisionExtractionEngine(),
            inference_capabilities=capabilities,
        )
        service.create_project("caps")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(32, 24))
        service.load_source(source)
        return service

    def test_point_only_rejects_box_before_operation(self) -> None:
        caps = ProviderCapabilities(supports_positive_point=True, supports_cpu=True)
        service = self._service(caps)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {
                    "signals": [
                        {"type": "positive_point", "x": 0.4, "y": 0.4},
                        {"type": "bounding_box", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                    ]
                },
            }
        )
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError) as ctx:
            service.start_generate_hypothesis()
        self.assertEqual("UNSUPPORTED_PROVIDER_CAPABILITY", ctx.exception.code)
        self.assertEqual(before, len(service.list_operations()))

    def test_box_only_rejects_point_before_operation(self) -> None:
        caps = ProviderCapabilities(supports_bounding_box=True, supports_cpu=True)
        service = self._service(caps)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
            }
        )
        before = len(service.list_operations())
        with self.assertRaises(ApplicationError) as ctx:
            service.generate_hypothesis()
        self.assertEqual("UNSUPPORTED_PROVIDER_CAPABILITY", ctx.exception.code)
        self.assertEqual(before, len(service.list_operations()))

    def test_switch_provider_preserves_history(self) -> None:
        registry = build_default_core_inference_registry()
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=registry.create("mock"),
            extraction=MockPrecisionExtractionEngine(),
            inference_capabilities=registry.get("mock").capabilities,
        )
        service.create_project("hist")
        source = Path(self._tmp.name) / "b.png"
        source.write_bytes(_png_bytes(40, 30))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
            }
        )
        hyp = service.generate_hypothesis()
        self.assertEqual(MOCK_RESULT_PROVIDER_ID, hyp.provider_id)
        ops_before = list(service.list_operations())
        hyps_before = list(service.project.hypotheses)  # type: ignore[union-attr]
        point_only = ProviderCapabilities(supports_positive_point=True, supports_cpu=True)
        service.set_inference_engine(
            _DeterministicEngine("switched"),  # type: ignore[arg-type]
            capabilities=point_only,
        )
        self.assertEqual(ops_before, service.list_operations())
        self.assertEqual(hyps_before, service.project.hypotheses)  # type: ignore[union-attr]
        self.assertEqual(WorkflowState.CANDIDATE_SET_READY, service.project.workflow_state)

    def test_switch_blocked_during_generate(self) -> None:
        executor = MockOperationExecutor(step_delay_seconds=0.05)
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=executor,
        )
        service.create_project("busy")
        source = Path(self._tmp.name) / "c.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.3, "y": 0.3}]},
            }
        )
        op_id = service.start_generate_hypothesis()
        with self.assertRaises(ApplicationError) as ctx:
            service.set_inference_engine(MockCoreInferenceEngine())
        self.assertEqual("OPERATION_IN_PROGRESS", ctx.exception.code)
        service.wait_operation(op_id)
        executor.shutdown(wait=True)

    def test_hypothesis_records_provider_from_engine_at_start(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=_DeterministicEngine("bound.first"),  # type: ignore[arg-type]
            extraction=MockPrecisionExtractionEngine(),
            inference_capabilities=ProviderCapabilities(
                supports_positive_point=True,
                supports_bounding_box=True,
                supports_cpu=True,
            ),
        )
        service.create_project("bind")
        source = Path(self._tmp.name) / "d.png"
        source.write_bytes(_png_bytes(32, 32))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
            }
        )
        hyp = service.generate_hypothesis()
        self.assertEqual("bound.first", hyp.provider_id)
        self.assertEqual("0.0-test", hyp.provider_version)


class ControllerRegistryTests(TestCase):
    def test_registry_driven_provider_list_and_generate_gate(self) -> None:
        registry = CoreInferenceProviderRegistry()
        point_only = ProviderCapabilities(supports_positive_point=True, supports_cpu=True)
        registry.register(
            _descriptor("pointy", capabilities=point_only),
            lambda _c: _DeterministicEngine("pointy"),  # type: ignore[arg-type, return-value]
        )
        registry.register(
            _descriptor(
                "down",
                capabilities=point_only,
                availability="unavailable",
                message="offline",
            ),
            lambda _c: MockCoreInferenceEngine(),
        )
        controller = ObjectWorkflowController(
            registry=registry,
            runtime_config=ProviderRuntimeConfig(selected_provider_id="pointy"),
        )
        ids = [item.provider_id for item in controller.list_core_inference_providers()]
        self.assertEqual(["pointy", "down"], ids)
        with TemporaryDirectory() as tmp:
            controller.create_project("ui")
            source = Path(tmp) / "e.png"
            source.write_bytes(_png_bytes(40, 30))
            controller.load_source(source)
            controller.apply_artist_intent(
                positive_points=[(0.5, 0.5)],
                bounding_box=(0.1, 0.1, 0.2, 0.2),
            )
            state = controller.view_state()
            self.assertFalse(state.can_generate)
            self.assertEqual("pointy", state.core_inference_provider)
            errors: list[str] = []
            controller.error_occurred.connect(errors.append)
            controller.set_core_inference_provider("down")
            self.assertTrue(any("PROVIDER_UNAVAILABLE" in item for item in errors))
            self.assertEqual("pointy", controller.view_state().core_inference_provider)

    def test_load_without_real_provider_still_works(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        with TemporaryDirectory() as tmp:
            service.create_project("load")
            source = Path(tmp) / "f.png"
            source.write_bytes(_png_bytes(40, 30))
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
            package = Path(tmp) / "p.nova"
            service.save_project(package)
            empty_registry = CoreInferenceProviderRegistry()
            empty_registry.register(
                _descriptor(
                    "mock",
                    capabilities=ProviderCapabilities(
                        supports_positive_point=True,
                        supports_bounding_box=True,
                        supports_cpu=True,
                    ),
                ),
                lambda _c: MockCoreInferenceEngine(),
            )
            loaded = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
                extraction=MockPrecisionExtractionEngine(),
            )
            project = loaded.load_project(package)
            self.assertEqual(WorkflowState.OBJECT_CONFIRMED, project.workflow_state)
            self.assertEqual(OperationStatus.SUCCEEDED, project.operations[-1].status)
