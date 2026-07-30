from __future__ import annotations

import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.local_matting_extraction import (
    PROVIDER_ID as MATTING_PROVIDER_ID,
)
from nova_layer.object_workflow.adapters.local_matting_extraction import (
    ColorAffinityMattingBackend,
    LocalMattingExtractionEngine,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    build_default_precision_extraction_registry,
)
from nova_layer.object_workflow.adapters.trimap import (
    TRIMAP_BACKGROUND,
    TRIMAP_FOREGROUND,
    TRIMAP_UNKNOWN,
    build_trimap_from_binary_mask,
    trimap_region_counts,
)
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


def _square_mask(width: int, height: int) -> BinaryMask:
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


class FakeSoftAlphaBackend:
    algorithm_name = "fake_soft_alpha"

    def __init__(self, fill: float = 128 / 255.0) -> None:
        self.fill = float(fill)

    def estimate_alpha(self, *, source_rgb, trimap, should_cancel):
        height, width, _ = source_rgb.shape
        labels = trimap.as_array()
        alpha = np.zeros((height, width), dtype=np.float32)
        alpha[labels == TRIMAP_FOREGROUND] = 1.0
        alpha[labels == TRIMAP_UNKNOWN] = self.fill
        return alpha


class TrimapTests(TestCase):
    def test_square_mask_unknown_band(self) -> None:
        width, height = 32, 24
        mask = np.zeros((height, width), dtype=bool)
        mask[6:18, 8:24] = True
        trimap = build_trimap_from_binary_mask(
            width=width,
            height=height,
            binary_foreground=mask,
            unknown_radius=2,
        )
        arr = trimap.as_array()
        self.assertEqual(TRIMAP_FOREGROUND, int(arr[12, 16]))
        self.assertEqual(TRIMAP_BACKGROUND, int(arr[0, 0]))
        self.assertTrue(np.any(arr == TRIMAP_UNKNOWN))
        counts = trimap_region_counts(trimap)
        self.assertGreater(counts["foreground"], 0)
        self.assertGreater(counts["background"], 0)
        self.assertGreater(counts["unknown"], 0)

    def test_zero_radius_is_binary(self) -> None:
        mask = np.zeros((8, 8), dtype=bool)
        mask[2:6, 2:6] = True
        trimap = build_trimap_from_binary_mask(
            width=8,
            height=8,
            binary_foreground=mask,
            unknown_radius=0,
        )
        arr = trimap.as_array()
        self.assertFalse(np.any(arr == TRIMAP_UNKNOWN))
        self.assertTrue(np.array_equal(arr == TRIMAP_FOREGROUND, mask))

    def test_full_background_and_full_foreground(self) -> None:
        empty = build_trimap_from_binary_mask(
            width=4,
            height=4,
            binary_foreground=np.zeros((4, 4), dtype=bool),
            unknown_radius=2,
        )
        self.assertEqual(16, trimap_region_counts(empty)["background"])
        full = build_trimap_from_binary_mask(
            width=4,
            height=4,
            binary_foreground=np.ones((4, 4), dtype=bool),
            unknown_radius=1,
        )
        counts = trimap_region_counts(full)
        self.assertEqual(0, counts["background"])
        self.assertGreater(counts["foreground"] + counts["unknown"], 0)

    def test_boundary_no_wraparound(self) -> None:
        mask = np.zeros((10, 10), dtype=bool)
        mask[0, 0] = True
        trimap = build_trimap_from_binary_mask(
            width=10,
            height=10,
            binary_foreground=mask,
            unknown_radius=3,
        )
        arr = trimap.as_array()
        self.assertEqual(TRIMAP_UNKNOWN, int(arr[0, 1]))
        self.assertEqual(TRIMAP_BACKGROUND, int(arr[9, 9]))

    def test_invalid_radius(self) -> None:
        with self.assertRaises(ValueError):
            build_trimap_from_binary_mask(
                width=4,
                height=4,
                binary_foreground=np.ones((4, 4), dtype=bool),
                unknown_radius=-1,
            )


class MattingProviderTests(TestCase):
    def test_soft_alpha_and_rgb_preserved(self) -> None:
        width, height = 24, 18
        rgb = _rgb(width, height, r=40, g=80, b=120)
        mask = _square_mask(width, height)
        engine = LocalMattingExtractionEngine(
            matting_unknown_radius=3,
            matting_refinement_strength=1.0,
            backend=FakeSoftAlphaBackend(fill=128 / 255.0),
        )
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=width,
                source_height=height,
                source_rgb=rgb,
                mask=mask,
            )
        )
        self.assertEqual(MATTING_PROVIDER_ID, result.provider_id)  # type: ignore[union-attr]
        image = result.image  # type: ignore[union-attr]
        soft_values = {
            image.data[i + 3]
            for i in range(0, len(image.data), 4)
            if 0 < image.data[i + 3] < 255
        }
        self.assertIn(128, soft_values)
        for index in range(width * height):
            rgba_i = index * 4
            if image.data[rgba_i + 3] in (0, 255, 128):
                self.assertEqual(40, image.data[rgba_i])
                self.assertEqual(80, image.data[rgba_i + 1])
                self.assertEqual(120, image.data[rgba_i + 2])

    def test_known_region_preservation(self) -> None:
        width, height = 20, 16
        engine = LocalMattingExtractionEngine(
            matting_unknown_radius=2,
            matting_preserve_known_regions=True,
            backend=FakeSoftAlphaBackend(fill=0.5),
        )
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=width,
                source_height=height,
                source_rgb=_rgb(width, height),
                mask=_square_mask(width, height),
            )
        )
        image = result.image  # type: ignore[union-attr]
        # Corners are definite background.
        self.assertEqual(0, image.data[3])
        self.assertTrue(result.diagnostics["known_region_preservation"])  # type: ignore[union-attr]

    def test_refinement_strength_endpoints(self) -> None:
        width, height = 16, 12
        request_kwargs = dict(
            request_id=str(uuid4()),
            source_width=width,
            source_height=height,
            source_rgb=_rgb(width, height),
            mask=_square_mask(width, height),
        )
        full = LocalMattingExtractionEngine(
            matting_unknown_radius=2,
            matting_refinement_strength=1.0,
            backend=FakeSoftAlphaBackend(fill=0.5),
        ).extract(PrecisionExtractionRequest(**request_kwargs))
        none = LocalMattingExtractionEngine(
            matting_unknown_radius=2,
            matting_refinement_strength=0.0,
            backend=FakeSoftAlphaBackend(fill=0.5),
        ).extract(PrecisionExtractionRequest(**request_kwargs))
        mid = LocalMattingExtractionEngine(
            matting_unknown_radius=2,
            matting_refinement_strength=0.5,
            backend=FakeSoftAlphaBackend(fill=0.5),
        ).extract(PrecisionExtractionRequest(**request_kwargs))
        self.assertNotEqual(full.image.data, none.image.data)  # type: ignore[union-attr]
        self.assertNotEqual(full.image.data, mid.image.data)  # type: ignore[union-attr]

    def test_dimension_mismatch_and_empty_mask(self) -> None:
        engine = LocalMattingExtractionEngine()
        mismatch = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=8,
                source_height=8,
                source_rgb=_rgb(8, 8),
                mask=_square_mask(4, 4),
            )
        )
        self.assertIsInstance(mismatch, PrecisionExtractionError)
        empty = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=4,
                source_height=4,
                source_rgb=_rgb(4, 4),
                mask=BinaryMask.from_pixels(4, 4, bytes([0] * 16)),
            )
        )
        self.assertEqual("EMPTY_MASK", empty.error_code)  # type: ignore[union-attr]

    def test_cancel_before_inference(self) -> None:
        engine = LocalMattingExtractionEngine()
        result = engine.extract(
            PrecisionExtractionRequest(
                request_id=str(uuid4()),
                source_width=8,
                source_height=8,
                source_rgb=_rgb(8, 8),
                mask=_square_mask(8, 8),
                provider_options={"should_cancel": lambda: True},
            )
        )
        self.assertEqual("CANCELLED", result.error_code)  # type: ignore[union-attr]

    def test_color_affinity_deterministic(self) -> None:
        width, height = 20, 16
        rgb = bytearray(_rgb(width, height, r=20, g=20, b=20))
        mask = _square_mask(width, height)
        # Distinct FG interior colour and BG exterior colour.
        for y in range(height):
            for x in range(width):
                i = (y * width + x) * 3
                if mask.data[y * width + x] == 255:
                    rgb[i : i + 3] = bytes([220, 40, 40])
                else:
                    rgb[i : i + 3] = bytes([40, 40, 220])
        # Mid-tone colours on the morphological unknown band encourage soft alpha.
        binary = np.frombuffer(mask.data, dtype=np.uint8).reshape((height, width)) > 0
        from nova_layer.object_workflow.adapters.trimap import build_trimap_from_binary_mask

        trimap = build_trimap_from_binary_mask(
            width=width,
            height=height,
            binary_foreground=binary,
            unknown_radius=2,
        )
        labels = trimap.as_array()
        for y in range(height):
            for x in range(width):
                if labels[y, x] == TRIMAP_UNKNOWN:
                    i = (y * width + x) * 3
                    rgb[i : i + 3] = bytes([130, 40, 130])
        engine = LocalMattingExtractionEngine(
            matting_unknown_radius=2,
            backend=ColorAffinityMattingBackend(),
        )
        request = PrecisionExtractionRequest(
            request_id=str(uuid4()),
            source_width=width,
            source_height=height,
            source_rgb=bytes(rgb),
            mask=mask,
        )
        first = engine.extract(request)
        second = engine.extract(request)
        self.assertEqual(first.image.data, second.image.data)  # type: ignore[union-attr]
        soft = first.diagnostics["soft_alpha_pixel_count"]  # type: ignore[union-attr]
        self.assertGreater(soft, 0)


class MattingRegistryAndApplicationTests(TestCase):
    def test_registry_includes_matting(self) -> None:
        registry = build_default_precision_extraction_registry()
        ids = [item.provider_id for item in registry.list()]
        self.assertEqual(["mock", "real", "matting"], ids)
        matting = registry.get("matting")
        self.assertTrue(matting.capabilities.supports_alpha_matting)
        self.assertFalse(registry.get("real").capabilities.supports_alpha_matting)
        self.assertFalse(registry.get("mock").capabilities.supports_alpha_matting)
        self.assertIsInstance(registry.create("matting"), LocalMattingExtractionEngine)

    def test_application_binds_confirmed_generation(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        registry = build_default_precision_extraction_registry()
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=registry.create(
                "matting",
                ExtractionRuntimeConfig(
                    selected_provider_id="matting",
                    matting_unknown_radius=4,
                ),
            ),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        service.set_extraction_settings(
            ExtractionSettings(matting_unknown_radius=4, matting_refinement_strength=1.0)
        )
        service.create_project("matting")
        source = Path(tmp.name) / "a.png"
        source.write_bytes(_png_bytes(48, 36, fill=90))
        service.load_source(source)
        service.create_artist_intent(_intent())
        cset = service.generate_candidates()
        service.select_candidate(cset.candidates[0].id)
        service.confirm_hypothesis()
        result = service.generate_extraction()
        self.assertEqual(MATTING_PROVIDER_ID, result.provider_id)
        self.assertEqual(cset.generation_id, result.confirmed_generation_id)
        self.assertIsNotNone(result.settings)
        assert result.settings is not None
        self.assertEqual(4, result.settings.matting_unknown_radius)
        package = Path(tmp.name) / "matting.nova"
        service.save_project(package)
        other = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        other.load_project(package)
        loaded = other.get_active_extraction_result()
        assert loaded is not None
        self.assertEqual(MATTING_PROVIDER_ID, loaded.provider_id)
        self.assertEqual(result.confirmed_candidate_id, loaded.confirmed_candidate_id)

    def test_settings_defaults_and_validation(self) -> None:
        settings = ExtractionSettings()
        self.assertEqual(8, settings.matting_unknown_radius)
        self.assertTrue(settings.matting_preserve_known_regions)
        with self.assertRaises(ValidationError):
            ExtractionSettings(
                matting_background_threshold=0.9,
                matting_foreground_threshold=0.1,
            )


@pytest.mark.real_model
def test_optional_real_matting_smoke() -> None:
    """Marked real_model: exercises CPU affinity matting on a larger plate."""
    width, height = 96, 64
    engine = LocalMattingExtractionEngine(matting_unknown_radius=6)
    result = engine.extract(
        PrecisionExtractionRequest(
            request_id=str(uuid4()),
            source_width=width,
            source_height=height,
            source_rgb=_rgb(width, height),
            mask=_square_mask(width, height),
        )
    )
    assert result.provider_id == MATTING_PROVIDER_ID  # type: ignore[union-attr]
    assert result.image.width == width  # type: ignore[union-attr]
    assert np.isfinite(
        np.frombuffer(result.image.data, dtype=np.uint8)  # type: ignore[union-attr]
    ).all()
