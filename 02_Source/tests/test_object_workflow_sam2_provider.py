from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.adapters.core_inference_factory import (
    DEFAULT_PROVIDER,
    create_core_inference_engine,
    resolve_provider_name,
)
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.sam2_core_inference import (
    Sam2CoreInferenceEngine,
    Sam2ProviderError,
    convert_sam_masks_to_binary_mask,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.models import (
    IntentInstruction,
    IntentPayload,
    OperationStatus,
    WorkflowState,
)
from nova_layer.object_workflow.ports.core_inference import CoreInferenceRequest


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


def _intent(*signals: dict[str, object]) -> IntentInstruction:
    return IntentInstruction(
        schema_name="nova.intent.guidance.v1",
        payload=IntentPayload(signals=list(signals)),
    )


class FakeSam2Runtime:
    def __init__(
        self,
        *,
        masks: NDArray[np.floating[Any]] | None = None,
        scores: NDArray[np.floating[Any]] | None = None,
        device: str = "fake-cpu",
        load_error: Sam2ProviderError | None = None,
        predict_error: Sam2ProviderError | None = None,
    ) -> None:
        self._masks = masks
        self._scores = scores
        self._device = device
        self._load_error = load_error
        self._predict_error = predict_error
        self.ensure_loaded_calls = 0
        self.predict_calls = 0

    @property
    def device(self) -> str:
        return self._device

    def ensure_loaded(self) -> None:
        self.ensure_loaded_calls += 1
        if self._load_error is not None:
            raise self._load_error

    def predict(
        self,
        *,
        image_rgb: NDArray[np.uint8],
        point_coords: NDArray[np.float32] | None,
        point_labels: NDArray[np.int32] | None,
        box: NDArray[np.float32] | None,
        image_fingerprint: str | None = None,
    ) -> tuple[NDArray[np.floating[Any]], NDArray[np.floating[Any]]]:
        self.predict_calls += 1
        if self._predict_error is not None:
            raise self._predict_error
        assert self._masks is not None and self._scores is not None
        assert image_rgb.ndim == 3
        _ = point_coords, point_labels, box, image_fingerprint
        return self._masks, self._scores


class ProviderSelectionTests(TestCase):
    def test_mock_is_default(self) -> None:
        self.assertEqual(DEFAULT_PROVIDER, "mock")
        self.assertEqual("mock", resolve_provider_name(None))
        engine = create_core_inference_engine()
        self.assertIsInstance(engine, MockCoreInferenceEngine)

    def test_unknown_provider_rejected(self) -> None:
        with self.assertRaises(ApplicationError) as ctx:
            resolve_provider_name("cloud-magic")
        self.assertEqual("INVALID_PROVIDER_CONFIG", ctx.exception.code)


class MaskConversionTests(TestCase):
    def test_argmax_selection_threshold_and_resize(self) -> None:
        masks = np.zeros((3, 4, 6), dtype=np.float32)
        masks[0, :, :] = 0.1
        masks[1, 1:3, 2:5] = 0.9
        masks[2, :, :] = 0.2
        scores = np.asarray([0.2, 0.95, 0.4], dtype=np.float32)
        mask, confidence, index = convert_sam_masks_to_binary_mask(
            masks=masks,
            scores=scores,
            source_width=12,
            source_height=8,
            mask_threshold=0.5,
        )
        self.assertEqual(1, index)
        self.assertAlmostEqual(0.95, confidence, places=5)
        self.assertEqual(12, mask.width)
        self.assertEqual(8, mask.height)
        self.assertEqual(1, mask.channels)
        self.assertTrue(set(mask.data).issubset({0, 255}))
        self.assertIn(255, set(mask.data))

    def test_invalid_provider_output(self) -> None:
        with self.assertRaises(Sam2ProviderError) as ctx:
            convert_sam_masks_to_binary_mask(
                masks=np.zeros((0, 2, 2), dtype=np.float32),
                scores=np.zeros((0,), dtype=np.float32),
                source_width=2,
                source_height=2,
                mask_threshold=0.5,
            )
        self.assertEqual("INVALID_PROVIDER_OUTPUT", ctx.exception.code)


class Sam2AdapterFakeRuntimeTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.source = Path(self._tmp.name) / "plate.png"
        self.source.write_bytes(_png_bytes(6, 4, fill=90))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _request(self, **options: object) -> CoreInferenceRequest:
        return CoreInferenceRequest(
            request_id=str(uuid4()),
            source_image_path=str(self.source),
            source_width=6,
            source_height=4,
            media_type="image/png",
            content_fingerprint="abc",
            intent_instruction=_intent({"type": "positive_point", "x": 0.5, "y": 0.5}),
            provider_options=dict(options),
        )

    def test_missing_model_artefact_maps_to_inference_failed(self) -> None:
        runtime = FakeSam2Runtime(
            load_error=Sam2ProviderError(
                "MODEL_NOT_AVAILABLE",
                "checkpoint missing",
            )
        )
        engine = Sam2CoreInferenceEngine(
            checkpoint=Path(self._tmp.name) / "missing.pt",
            runtime=runtime,
        )
        result = engine.generate_hypothesis(self._request())
        assert not isinstance(result, type(None))
        self.assertEqual("INFERENCE_FAILED", result.error_code)  # type: ignore[union-attr]
        self.assertIn("MODEL_NOT_AVAILABLE", result.message)  # type: ignore[union-attr]

    def test_load_failure_mapping(self) -> None:
        runtime = FakeSam2Runtime(
            load_error=Sam2ProviderError("MODEL_LOAD_FAILED", "corrupt weights")
        )
        engine = Sam2CoreInferenceEngine(checkpoint=self.source, runtime=runtime)
        result = engine.generate_hypothesis(self._request())
        self.assertEqual("INFERENCE_FAILED", result.error_code)  # type: ignore[union-attr]
        self.assertIn("MODEL_LOAD_FAILED", result.message)  # type: ignore[union-attr]

    def test_invalid_output_mapping(self) -> None:
        runtime = FakeSam2Runtime(
            masks=np.zeros((1, 4, 6), dtype=np.float32),
            scores=np.asarray([0.5, 0.1], dtype=np.float32),
        )
        engine = Sam2CoreInferenceEngine(checkpoint=self.source, runtime=runtime)
        result = engine.generate_hypothesis(self._request())
        self.assertEqual("INFERENCE_FAILED", result.error_code)  # type: ignore[union-attr]
        self.assertIn("INVALID_PROVIDER_OUTPUT", result.message)  # type: ignore[union-attr]

    def test_success_converts_to_binary_mask(self) -> None:
        masks = np.zeros((2, 4, 6), dtype=np.float32)
        masks[1, 1:3, 2:4] = 0.8
        runtime = FakeSam2Runtime(
            masks=masks,
            scores=np.asarray([0.1, 0.9], dtype=np.float32),
        )
        engine = Sam2CoreInferenceEngine(checkpoint=self.source, runtime=runtime)
        result = engine.generate_hypothesis(self._request())
        self.assertEqual("sam2.1_hiera_tiny", result.provider_id)  # type: ignore[union-attr]
        self.assertEqual(6, result.mask.width)  # type: ignore[union-attr]
        self.assertEqual(4, result.mask.height)  # type: ignore[union-attr]
        self.assertTrue(set(result.mask.data).issubset({0, 255}))  # type: ignore[union-attr]

    def test_cancel_before_inference(self) -> None:
        runtime = FakeSam2Runtime(
            masks=np.ones((1, 4, 6), dtype=np.float32),
            scores=np.asarray([0.9], dtype=np.float32),
        )
        engine = Sam2CoreInferenceEngine(checkpoint=self.source, runtime=runtime)
        result = engine.generate_hypothesis(self._request(should_cancel=lambda: True))
        self.assertEqual("CANCELLED", result.error_code)  # type: ignore[union-attr]
        self.assertEqual(0, runtime.predict_calls)

    def test_result_discarded_after_cancellation_flag(self) -> None:
        armed = {"cancel": False}

        class CancellingRuntime(FakeSam2Runtime):
            def predict(  # type: ignore[no-untyped-def]
                self,
                *,
                image_rgb,
                point_coords,
                point_labels,
                box,
                image_fingerprint=None,
            ):
                masks, scores = super().predict(
                    image_rgb=image_rgb,
                    point_coords=point_coords,
                    point_labels=point_labels,
                    box=box,
                    image_fingerprint=image_fingerprint,
                )
                armed["cancel"] = True
                return masks, scores

        masks = np.ones((1, 4, 6), dtype=np.float32)
        runtime = CancellingRuntime(masks=masks, scores=np.asarray([0.8], dtype=np.float32))
        engine = Sam2CoreInferenceEngine(checkpoint=self.source, runtime=runtime)
        result = engine.generate_hypothesis(
            self._request(should_cancel=lambda: armed["cancel"])
        )
        self.assertEqual("CANCELLED", result.error_code)  # type: ignore[union-attr]
        self.assertEqual(1, runtime.predict_calls)


class RealProviderWorkflowTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        masks = np.zeros((1, 30, 40), dtype=np.float32)
        masks[0, 5:20, 8:25] = 0.9
        self.runtime = FakeSam2Runtime(
            masks=masks,
            scores=np.asarray([0.88], dtype=np.float32),
        )
        self.engine = Sam2CoreInferenceEngine(
            checkpoint=Path(self._tmp.name) / "unused.pt",
            runtime=self.runtime,
        )
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=self.engine,
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_failure_preserves_workflow_and_duplicate_guard(self) -> None:
        failing = Sam2CoreInferenceEngine(
            checkpoint=Path(self._tmp.name) / "missing.pt",
            runtime=FakeSam2Runtime(
                load_error=Sam2ProviderError("MODEL_NOT_AVAILABLE", "missing")
            ),
        )
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=failing,
            extraction=MockPrecisionExtractionEngine(),
        )
        service.create_project("fail")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(40, 30))
        service.load_source(source)
        service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.4, "y": 0.4}]},
            }
        )
        before = service.project.workflow_state
        with self.assertRaises(ApplicationError) as ctx:
            service.generate_hypothesis()
        self.assertEqual("INFERENCE_FAILED", ctx.exception.code)
        self.assertEqual(before, service.project.workflow_state)
        self.assertIsNone(service.project.active_hypothesis_id)
        self.assertEqual(OperationStatus.FAILED, service.list_operations()[-1].status)

    def test_extraction_accepts_real_provider_style_mask(self) -> None:
        self.service.create_project("real-style")
        source = Path(self._tmp.name) / "plate.png"
        source.write_bytes(_png_bytes(40, 30, fill=100))
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
        hypothesis = self.service.select_candidate(cset.candidates[0].id)
        self.assertEqual("sam2.1_hiera_tiny", hypothesis.provider_id)
        self.assertEqual(WorkflowState.HYPOTHESIS_READY, self.service.project.workflow_state)
        self.service.confirm_hypothesis()
        extraction = self.service.generate_extraction()
        self.assertEqual(WorkflowState.EXTRACTION_READY, self.service.project.workflow_state)
        self.assertTrue(extraction.relative_asset_path.endswith(".png"))

    def test_project_load_without_real_provider(self) -> None:
        self.service.create_project("persist")
        source = Path(self._tmp.name) / "plate.png"
        source.write_bytes(_png_bytes(40, 30))
        self.service.load_source(source)
        self.service.create_artist_intent(
            {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
            }
        )
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()
        package = Path(self._tmp.name) / "proj.nova"
        self.service.save_project(package)

        loaded = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        project = loaded.load_project(package)
        self.assertEqual(WorkflowState.OBJECT_CONFIRMED, project.workflow_state)
        self.assertIsNotNone(project.active_confirmed_object_id)
        hyp = next(item for item in project.hypotheses if item.id == project.active_hypothesis_id)
        self.assertEqual("sam2.1_hiera_tiny", hyp.provider_id)
