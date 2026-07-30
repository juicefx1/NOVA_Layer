from __future__ import annotations

import struct
import threading
import time
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

import numpy as np

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mask_io import (
    read_binary_mask_png_bytes,
    write_binary_mask_png,
)
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.domain.binary_mask import BinaryMask, BinaryMaskError
from nova_layer.object_workflow.runtime import (
    BackgroundDecodeService,
    ImageCache,
    InFlightDeduper,
    LruMemoryCache,
    MaskCache,
    PerformanceMonitor,
    PreviewCache,
    RuntimeCacheBundle,
    ThumbnailCache,
)
from tests.object_workflow_test_helpers import generate_and_select


def _rgb_png(path: Path, width: int = 8, height: int = 6) -> Path:
    from nova_layer.object_workflow.adapters.image_codec import PNG_SIGNATURE

    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        for _x in range(width):
            raw.extend([10, 20, 30])
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    path.write_bytes(
        PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    )
    return path


def _intent() -> dict[str, object]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {
            "signals": [
                {"type": "positive_point", "x": 0.5, "y": 0.5},
                {"type": "bounding_box", "x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4},
            ]
        },
    }


class LruMemoryCacheTests(TestCase):
    def test_lru_eviction_and_stats(self) -> None:
        cache: LruMemoryCache[bytes] = LruMemoryCache(budget_bytes=10, name="t")
        cache.put("a", b"12345", size_bytes=5)
        cache.put("b", b"12345", size_bytes=5)
        self.assertEqual(len(cache), 2)
        cache.put("c", b"12345", size_bytes=5)
        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("b"))
        stats = cache.stats()
        self.assertGreaterEqual(stats.evictions, 1)
        self.assertGreaterEqual(stats.hits, 1)
        self.assertGreaterEqual(stats.misses, 1)


class TypedCacheTests(TestCase):
    def test_image_mask_thumbnail_preview_hit_miss(self) -> None:
        monitor = PerformanceMonitor()
        images = ImageCache(budget_bytes=1024 * 1024, monitor=monitor)
        masks = MaskCache(budget_bytes=1024 * 1024, monitor=monitor)
        thumbs = ThumbnailCache(budget_bytes=1024 * 1024, monitor=monitor)
        previews = PreviewCache(budget_bytes=1024 * 1024, monitor=monitor)

        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        calls = {"n": 0}

        def decode_frame() -> np.ndarray:
            calls["n"] += 1
            return frame

        first = images.get_or_decode("asset-1", decode_frame)
        second = images.get_or_decode("asset-1", decode_frame)
        self.assertEqual(calls["n"], 1)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(monitor.counter("image_cache_hit"), 1)
        self.assertEqual(monitor.counter("image_cache_miss"), 1)

        mask = np.zeros((4, 4), dtype=np.uint8)
        mask_calls = {"n": 0}

        def decode_mask() -> np.ndarray:
            mask_calls["n"] += 1
            return mask

        masks.get_or_decode("mask-1", decode_mask)
        masks.get_or_decode("mask-1", decode_mask)
        self.assertEqual(mask_calls["n"], 1)

        candidate_id = uuid4()
        key = ThumbnailCache.make_key(candidate_id, preview_path="assets/masks/a.png")
        thumb_calls = {"n": 0}

        def decode_thumb() -> np.ndarray:
            thumb_calls["n"] += 1
            return mask

        thumbs.get_or_decode(key, decode_thumb)
        thumbs.get_or_decode(key, decode_thumb)
        self.assertEqual(thumb_calls["n"], 1)

        extraction_id = uuid4()
        preview_key = PreviewCache.make_key(extraction_id, scale=1.0)
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        preview_calls = {"n": 0}

        def decode_preview() -> np.ndarray:
            preview_calls["n"] += 1
            return rgba

        previews.invalidate_unless(extraction_id)
        previews.get_or_decode(preview_key, decode_preview)
        previews.get_or_decode(preview_key, decode_preview)
        self.assertEqual(preview_calls["n"], 1)
        previews.invalidate_unless(uuid4())
        self.assertEqual(len(previews._cache), 0)  # noqa: SLF001


class InFlightDeduperTests(TestCase):
    def test_concurrent_identical_work_runs_once(self) -> None:
        deduper = InFlightDeduper()
        calls = {"n": 0}
        barrier = threading.Barrier(4)
        results: list[int] = []

        def worker() -> int:
            calls["n"] += 1
            time.sleep(0.05)
            return 42

        def runner() -> None:
            barrier.wait()
            results.append(deduper.run("same", worker))

        threads = [threading.Thread(target=runner) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(calls["n"], 1)
        self.assertEqual(results, [42, 42, 42, 42])


class BackgroundDecodeTests(TestCase):
    def test_run_sync_and_submit(self) -> None:
        service = BackgroundDecodeService(max_workers=1)
        try:
            value = service.run_sync("k", lambda: 7)
            self.assertEqual(value, 7)
            future = service.submit("k2", lambda: 9)
            self.assertEqual(future.result(timeout=2.0), 9)
        finally:
            service.shutdown(wait=True)


class BinaryMaskValidationTests(TestCase):
    def test_translate_validation_accepts_and_rejects(self) -> None:
        ok = BinaryMask.from_pixels(2, 2, bytes([0, 255, 0, 255]))
        self.assertEqual(ok.width, 2)
        with self.assertRaises(BinaryMaskError):
            BinaryMask.from_pixels(2, 2, bytes([0, 1, 0, 255]))


class MaskBytesDecodeTests(TestCase):
    def test_read_mask_from_bytes_without_temp_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.png"
            write_binary_mask_png(path, 3, 2, bytes([0, 255, 0, 255, 0, 255]))
            width, height, data = read_binary_mask_png_bytes(path.read_bytes())
            self.assertEqual((width, height), (3, 2))
            self.assertEqual(data, bytes([0, 255, 0, 255, 0, 255]))


class ControllerCacheRegressionTests(TestCase):
    def test_list_candidates_uses_thumbnail_cache(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        controller = ObjectWorkflowController(service)
        with TemporaryDirectory() as tmp:
            source = _rgb_png(Path(tmp) / "src.png")
            controller.create_project("cache")
            controller.load_source(source)
            controller.apply_artist_intent(
                positive_points=[(0.5, 0.5)],
                bounding_box=(0.2, 0.2, 0.4, 0.4),
            )
            controller.generate_hypothesis()
            first = controller.list_candidates()
            miss_after_first = controller.performance_snapshot()["thumbnail_cache_miss"]
            second = controller.list_candidates()
            hit_after_second = controller.performance_snapshot()["thumbnail_cache_hit"]
            self.assertEqual(len(first), len(second))
            assert isinstance(miss_after_first, int)
            assert isinstance(hit_after_second, int)
            self.assertGreaterEqual(miss_after_first, 1)
            self.assertGreaterEqual(hit_after_second, 1)
            # Behaviour unchanged: same candidate ids and ordering.
            self.assertEqual([item.id for item in first], [item.id for item in second])

    def test_refinement_does_not_require_engine_recreation_for_export_path(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
            executor=MockOperationExecutor(step_delay_seconds=0.0),
        )
        controller = ObjectWorkflowController(service)
        with TemporaryDirectory() as tmp:
            source = _rgb_png(Path(tmp) / "src.png")
            controller.create_project("refine")
            controller.load_source(source)
            controller.apply_artist_intent(
                positive_points=[(0.5, 0.5)],
                bounding_box=(0.2, 0.2, 0.4, 0.4),
            )
            generate_and_select(service)
            controller.confirm_hypothesis()
            engine_before = service._extraction  # noqa: SLF001
            controller.set_extraction_refinement(feather_radius=1.5)
            engine_after = service._extraction  # noqa: SLF001
            self.assertIs(engine_before, engine_after)
            controller.generate_extraction()
            self.assertIsNotNone(controller.extraction_preview)

    def test_schema_unchanged(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        service.create_project("perf")
        assert service.project is not None
        self.assertEqual(service.project.schema_version, "2.0")


class RuntimeBundleTests(TestCase):
    def test_bundle_clear_and_snapshot(self) -> None:
        bundle = RuntimeCacheBundle(
            image_budget=1024,
            mask_budget=1024,
            thumbnail_budget=1024,
            preview_budget=1024,
        )
        bundle.images.put("a", np.zeros((2, 2, 3), dtype=np.uint8))
        snapshot = bundle.snapshot()
        self.assertEqual(snapshot["image"].entries, 1)
        bundle.clear()
        self.assertEqual(bundle.images.stats().entries, 0)


class PerformanceMonitorTests(TestCase):
    def test_measure_records_sample(self) -> None:
        monitor = PerformanceMonitor(max_samples=8)
        with monitor.measure("decode", kind="mask"):
            time.sleep(0.001)
        samples = monitor.samples("decode")
        self.assertEqual(len(samples), 1)
        self.assertGreaterEqual(samples[0].duration_ms, 0.0)
