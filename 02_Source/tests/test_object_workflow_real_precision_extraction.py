from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.local_precision_extraction import (
    LocalPrecisionExtractionEngine,
    build_refined_rgba,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    build_default_precision_extraction_registry,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.models import ExtractionSettings
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
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


def _rgb(width: int, height: int, r: int = 10, g: int = 20, b: int = 30) -> bytes:
    return bytes([r, g, b]) * (width * height)


def _mask_rect(width: int, height: int) -> BinaryMask:
    data = bytearray(width * height)
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            data[y * width + x] = 255
    return BinaryMask.from_pixels(width, height, bytes(data))


def _intent() -> dict[str, object]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {"signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}]},
    }


class RealPrecisionExtractionProviderTests(TestCase):
    def test_rgb_preserved_alpha_from_mask(self) -> None:
        width, height = 12, 8
        rgb = _rgb(width, height)
        mask = _mask_rect(width, height)
        image, meta = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
        )
        self.assertEqual([width, height], meta["output_dimensions"])
        for index in range(width * height):
            rgba_i = index * 4
            self.assertEqual(10, image.data[rgba_i])
            self.assertEqual(20, image.data[rgba_i + 1])
            self.assertEqual(30, image.data[rgba_i + 2])
            self.assertEqual(mask.data[index], image.data[rgba_i + 3])

    def test_expand_and_contract(self) -> None:
        width, height = 16, 16
        rgb = _rgb(width, height)
        mask = _mask_rect(width, height)
        base, _ = build_refined_rgba(
            width=width, height=height, source_rgb=rgb, mask=mask
        )
        expanded, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            expand_contract_pixels=2,
        )
        contracted, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            expand_contract_pixels=-2,
        )
        base_fg = sum(1 for i in range(0, len(base.data), 4) if base.data[i + 3] > 0)
        exp_fg = sum(1 for i in range(0, len(expanded.data), 4) if expanded.data[i + 3] > 0)
        con_fg = sum(1 for i in range(0, len(contracted.data), 4) if contracted.data[i + 3] > 0)
        self.assertGreater(exp_fg, base_fg)
        self.assertLess(con_fg, base_fg)
        noop, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            expand_contract_pixels=0,
        )
        self.assertEqual(base.data, noop.data)

    def test_feather_and_blur(self) -> None:
        width, height = 20, 16
        rgb = _rgb(width, height)
        mask = _mask_rect(width, height)
        plain, _ = build_refined_rgba(
            width=width, height=height, source_rgb=rgb, mask=mask
        )
        feathered, meta = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            feather_radius=2.0,
        )
        self.assertNotEqual(plain.data, feathered.data)
        self.assertEqual("chamfer_distance_soft_edge", meta["feather_algorithm"])
        blurred, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            edge_blur_radius=2.0,
        )
        self.assertNotEqual(plain.data, blurred.data)
        for index in range(width * height):
            alpha = feathered.data[index * 4 + 3]
            self.assertGreaterEqual(alpha, 0)
            self.assertLessEqual(alpha, 255)

    def test_premultiply_alpha(self) -> None:
        width, height = 8, 8
        rgb = _rgb(width, height, r=100, g=100, b=100)
        mask = _mask_rect(width, height)
        straight, _ = build_refined_rgba(
            width=width, height=height, source_rgb=rgb, mask=mask
        )
        premult, meta = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            premultiply_alpha=True,
        )
        self.assertTrue(meta["premultiplied_alpha"])
        # Transparent pixels should have zero RGB when premultiplied.
        for index in range(width * height):
            if premult.data[index * 4 + 3] == 0:
                self.assertEqual(0, premult.data[index * 4])
            if straight.data[index * 4 + 3] == 255:
                self.assertEqual(100, straight.data[index * 4])

    def test_dimension_mismatch_rejected(self) -> None:
        engine = LocalPrecisionExtractionEngine()
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=8,
                source_height=8,
                source_rgb=_rgb(8, 8),
                mask=_mask_rect(4, 4),
            )
        )
        self.assertIsInstance(result, PrecisionExtractionError)
        self.assertEqual("INVALID_REQUEST", result.error_code)  # type: ignore[union-attr]

    def test_empty_mask_rejected(self) -> None:
        engine = LocalPrecisionExtractionEngine()
        empty = BinaryMask.from_pixels(4, 4, bytes([0] * 16))
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=4,
                source_height=4,
                source_rgb=_rgb(4, 4),
                mask=empty,
            )
        )
        self.assertIsInstance(result, PrecisionExtractionError)
        self.assertEqual("EMPTY_MASK", result.error_code)  # type: ignore[union-attr]

    def test_deterministic_output(self) -> None:
        width, height = 10, 10
        rgb = _rgb(width, height)
        mask = _mask_rect(width, height)
        first, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            feather_radius=1.5,
            expand_contract_pixels=1,
            edge_blur_radius=1.0,
        )
        second, _ = build_refined_rgba(
            width=width,
            height=height,
            source_rgb=rgb,
            mask=mask,
            feather_radius=1.5,
            expand_contract_pixels=1,
            edge_blur_radius=1.0,
        )
        self.assertEqual(first.data, second.data)


class RealPrecisionExtractionApplicationTests(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        registry = build_default_precision_extraction_registry()
        self.service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=registry.create(
                "real",
                ExtractionRuntimeConfig(
                    selected_provider_id="real",
                    feather_radius=1.0,
                ),
            ),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        self.service.set_extraction_settings(
            ExtractionSettings(feather_radius=1.0, edge_blur_radius=0.0)
        )
        self.service.create_project("real-extract")
        source = Path(self._tmp.name) / "a.png"
        source.write_bytes(_png_bytes(48, 36, fill=90))
        self.service.load_source(source)
        self.service.create_artist_intent(_intent())
        cset = self.service.generate_candidates()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_extraction_binds_confirmed_generation_and_candidate(self) -> None:
        confirmed = self.service.project.confirmed_objects[0]
        hypothesis = next(
            item
            for item in self.service.project.hypotheses
            if item.id == confirmed.hypothesis_id
        )
        result = self.service.generate_extraction()
        self.assertEqual(hypothesis.generation_id, result.confirmed_generation_id)
        self.assertEqual(hypothesis.candidate_id, result.confirmed_candidate_id)
        self.assertEqual(hypothesis.candidate_set_id, result.confirmed_candidate_set_id)
        self.assertIsNotNone(result.settings)
        self.assertEqual(1.0, result.settings.feather_radius)
        self.assertEqual("local.precision_extraction", result.provider_id)
        self.assertEqual(48, result.width)
        self.assertEqual(36, result.height)

    def test_browsing_other_generation_does_not_change_binding(self) -> None:
        first = self.service.generate_candidates()
        second = self.service.generate_candidates()
        self.service.restore_generation(first.generation_id)
        self.service.select_candidate(first.candidates[0].id)
        self.service.confirm_hypothesis()
        first_summary = self.service.get_confirmed_extraction_source_summary()
        assert first_summary is not None
        first_gen = first_summary["confirmed_generation_id"]
        self.service.restore_generation(second.generation_id)
        after = self.service.get_confirmed_extraction_source_summary()
        assert after is not None
        self.assertEqual(first_gen, after["confirmed_generation_id"])
        result = self.service.generate_extraction()
        self.assertEqual(first_gen, str(result.confirmed_generation_id))

    def test_cannot_extract_without_confirmation(self) -> None:
        early = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        early.create_project("early")
        with self.assertRaises(ApplicationError) as ctx:
            early.generate_extraction()
        self.assertEqual("NO_ACTIVE_CONFIRMED_OBJECT", ctx.exception.code)

    def test_persistence_round_trip_with_binding(self) -> None:
        result = self.service.generate_extraction()
        package = Path(self._tmp.name) / "bound.nova"
        self.service.save_project(package)
        other = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        other.load_project(package)
        loaded = other.get_active_extraction_result()
        assert loaded is not None
        self.assertEqual(result.confirmed_generation_id, loaded.confirmed_generation_id)
        self.assertEqual(result.confirmed_candidate_id, loaded.confirmed_candidate_id)
        self.assertEqual(result.provider_id, loaded.provider_id)
        self.assertIsNotNone(loaded.settings)
        self.assertEqual(result.width, loaded.width)
