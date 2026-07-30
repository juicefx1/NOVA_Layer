from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.object_workflow.adapters.image_codec import decode_rgba_png_bytes
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
    build_deterministic_rgba,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
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


def _service() -> ObjectWorkflowService:
    return ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )


class PrecisionExtractionTests(TestCase):
    def setUp(self) -> None:
        self.service = _service()
        self.service.create_project("extract")
        self._tmp = TemporaryDirectory()
        source = Path(self._tmp.name) / "plate.png"
        source.write_bytes(_png_bytes(40, 30, fill=90))
        self.service.load_source(source)
        self.service.create_artist_intent(
            _intent(
                {"type": "positive_point", "x": 0.5, "y": 0.5},
                {"type": "bounding_box", "x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4},
            )
        )
        cset = self.service.generate_hypothesis()
        self.service.select_candidate(cset.candidates[0].id)
        self.service.confirm_hypothesis()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_extraction_requires_confirmed_object(self) -> None:
        early = _service()
        early.create_project("early")
        with self.assertRaises(ApplicationError) as ctx:
            early.generate_extraction()
        self.assertEqual("NO_ACTIVE_CONFIRMED_OBJECT", ctx.exception.code)

    def test_deterministic_rgba_alpha_equals_mask(self) -> None:
        project = self.service.project
        assert project is not None
        confirmed = project.confirmed_objects[0]
        mask_bytes = self.service.get_asset_bytes(confirmed.mask_relative_path)
        from nova_layer.object_workflow.adapters.mask_io import read_binary_mask_png

        mask_path = Path(self._tmp.name) / "mask.png"
        mask_path.write_bytes(mask_bytes)
        width, height, mask_data = read_binary_mask_png(mask_path)
        mask = BinaryMask.from_pixels(width, height, mask_data)
        source_rgb = bytes([10, 20, 30]) * (width * height)
        first = build_deterministic_rgba(
            width=width,
            height=height,
            source_rgb=source_rgb,
            mask=mask,
        )
        second = build_deterministic_rgba(
            width=width,
            height=height,
            source_rgb=source_rgb,
            mask=mask,
        )
        self.assertEqual(first.data, second.data)
        for index in range(width * height):
            self.assertEqual(mask.data[index], first.data[index * 4 + 3])
            self.assertEqual(10, first.data[index * 4])
            self.assertEqual(20, first.data[index * 4 + 1])
            self.assertEqual(30, first.data[index * 4 + 2])

    def test_generate_extraction_and_history(self) -> None:
        extraction = self.service.generate_extraction()
        project = self.service.project
        assert project is not None
        self.assertEqual(WorkflowState.EXTRACTION_READY, project.workflow_state)
        self.assertEqual(extraction.id, project.active_extraction_result_id)
        self.assertTrue(extraction.relative_asset_path.startswith("assets/extractions/"))
        self.assertEqual(1, extraction.revision)
        self.assertEqual(project.confirmed_objects[0].id, extraction.confirmed_object_id)
        self.assertEqual(project.source_images[0].id, extraction.source_image_id)
        rgba = self.service.get_asset_bytes(extraction.relative_asset_path)
        width, height, data = decode_rgba_png_bytes(rgba)
        self.assertEqual(40, width)
        self.assertEqual(30, height)
        self.assertEqual(width * height * 4, len(data))

    def test_save_load_restores_extraction_preview_asset(self) -> None:
        extraction = self.service.generate_extraction()
        package = Path(self._tmp.name) / "extract.nova"
        self.service.save_project(package)
        asset_on_disk = package / Path(extraction.relative_asset_path)
        self.assertTrue(asset_on_disk.is_file())

        restored = _service()
        project = restored.load_project(package)
        self.assertEqual(WorkflowState.EXTRACTION_READY, project.workflow_state)
        self.assertEqual(extraction.id, project.active_extraction_result_id)
        self.assertEqual(1, len(project.extraction_results))
        loaded = restored.get_asset_bytes(project.extraction_results[0].relative_asset_path)
        self.assertEqual(
            self.service.get_asset_bytes(extraction.relative_asset_path),
            loaded,
        )
