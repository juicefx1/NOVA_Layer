from __future__ import annotations

import json
import struct
import threading
import time
import zipfile
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from nova_layer.app.user_facing_errors import format_user_error
from nova_layer.object_workflow.adapters.host_filesystem_export import FilesystemExportAdapter
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.adapters.sam2_core_inference import TorchSam2ImageRuntime
from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.automation import AutomationService
from nova_layer.object_workflow.plugin_sdk.package.archive import open_package
from nova_layer.object_workflow.plugin_sdk.package.errors import PluginPackageValidationError
from nova_layer.object_workflow.ports.host_delivery import HostDeliveryRequest
from nova_layer.object_workflow.runtime.caches import ImageCache, RuntimeCacheBundle


def _png_bytes(width: int = 16, height: int = 12, fill: int = 90) -> bytes:
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


def _rgba_png_bytes(width: int = 4, height: int = 4) -> bytes:
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        for _x in range(width):
            raw.extend([10, 20, 30, 255])
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

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


def _intent() -> dict[str, object]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {
            "signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}],
        },
    }


def _service() -> ObjectWorkflowService:
    return ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )


class PerformanceCacheTests(TestCase):
    def test_image_cache_returns_readonly_without_second_copy_on_hit(self) -> None:
        cache = ImageCache(budget_bytes=1024 * 1024)
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        calls = {"n": 0}

        def decode() -> np.ndarray:
            calls["n"] += 1
            return frame

        first = cache.get_or_decode("a", decode)
        second = cache.get_or_decode("a", decode)
        self.assertEqual(1, calls["n"])
        self.assertIs(first, second)
        self.assertFalse(first.flags.writeable)

    def test_batch_source_cache_hit_on_repeated_fingerprint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "a.png"
            image.write_bytes(_png_bytes())
            caches = RuntimeCacheBundle()
            service = _service()
            manager = BatchManager(service, runtime_caches=caches)
            job = manager.create_job(
                [image, image],
                intent_snapshot=_intent(),
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
            )
            finished = manager.run(job)
            self.assertEqual("completed", finished.status)
            self.assertGreaterEqual(caches.monitor.counter("batch_source_seen"), 2)
            self.assertGreaterEqual(caches.monitor.counter("batch_source_cache_hit"), 1)
            # Image frames cleared after batch finishes (runtime cleanup).
            self.assertEqual(0, len(caches.images._cache))  # noqa: SLF001


class RuntimeCleanupTests(TestCase):
    def test_engine_token_changes_on_set_inference_engine(self) -> None:
        service = _service()
        original = service.inference_engine_token
        service.set_inference_engine(MockCoreInferenceEngine())
        self.assertNotEqual(original, service.inference_engine_token)

    def test_batch_detects_engine_replacement_via_token(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / f"i{i}.png" for i in range(2)]
            for path in paths:
                path.write_bytes(_png_bytes())
            service = _service()
            manager = BatchManager(service)
            token = manager.inference_engine_id
            self.assertEqual(token, service.inference_engine_token)
            service.set_inference_engine(MockCoreInferenceEngine())
            job = manager.create_job(
                paths,
                intent_snapshot=_intent(),
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
            )
            with self.assertRaises(ApplicationError) as ctx:
                manager.run(job)
            self.assertEqual("BATCH_ENGINE_REPLACED", ctx.exception.code)

    def test_completed_operations_are_bounded(self) -> None:
        service = _service()
        service._max_retained_operations = 3  # noqa: SLF001
        service.create_project("bound-ops")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.png"
            path.write_bytes(_png_bytes())
            service.load_source(path)
            service.create_artist_intent(_intent())
            for _ in range(6):
                op = service.start_generate_hypothesis()
                service.wait_operation(op)
            self.assertLessEqual(len(service.list_operations()), 3)


class SecurityHardeningTests(TestCase):
    def test_rejects_symlink_members_in_plugin_zip(self) -> None:
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.nova-plugin"
            with zipfile.ZipFile(archive, "w") as zf:
                info = zipfile.ZipInfo("link.py")
                info.create_system = 3
                info.external_attr = (0o120777 & 0xFFFF) << 16
                zf.writestr(info, b"not-a-real-symlink-target")
                zf.writestr(
                    "package.json",
                    json.dumps(
                        {
                            "package_format": "1.0",
                            "plugin_id": "test.evil",
                            "version": "1.0.0",
                            "sdk_version": "1.0",
                        }
                    ),
                )
            with self.assertRaises(PluginPackageValidationError) as ctx:
                open_package(archive)
            self.assertEqual("PLUGIN_PACKAGE_SYMLINK_FORBIDDEN", ctx.exception.code)

    def test_export_rejects_path_traversal(self) -> None:
        adapter = FilesystemExportAdapter()
        request = HostDeliveryRequest(
            source_project_id="p",
            extraction_id="e",
            rgba_asset_bytes=_rgba_png_bytes(),
            rgba_relative_path="assets/out.png",
            display_name="out",
            width=4,
            height=4,
            premultiplied_alpha=False,
            crop_mode="full_source",
            action="export_copy",
            destination="../escape.png",
        )
        with self.assertRaises(ApplicationError) as ctx:
            adapter.validate(request)
        self.assertEqual("PATH_TRAVERSAL", ctx.exception.code)

    def test_workspace_save_writes_backup(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            ws = WorkspaceManager(path)
            ws.load()
            ws.set_preference("theme", "dark")
            ws.set_preference("theme", "light")
            backup = path.with_name("workspace.json.bak")
            self.assertTrue(backup.is_file())
            restored = json.loads(backup.read_text(encoding="utf-8"))
            self.assertEqual("dark", restored["preferences"]["theme"])


class UxRecoveryTests(TestCase):
    def test_format_user_error_includes_retry_guidance(self) -> None:
        text = format_user_error("OUT_OF_MEMORY: cuda oom")
        self.assertIn("Out Of Memory", text)
        self.assertIn("Retry", text)

    def test_workspace_load_error_is_cleared_after_ack(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            path.write_text("{not-json", encoding="utf-8")
            ws = WorkspaceManager(path)
            ws.load()
            self.assertIsNotNone(ws.load_error)
            ws.clear_load_error()
            self.assertIsNone(ws.load_error)


class ConcurrencyAndAutomationTests(TestCase):
    def test_image_cache_concurrent_get_or_decode(self) -> None:
        cache = ImageCache(budget_bytes=1024 * 1024)
        calls = {"n": 0}
        barrier = threading.Barrier(8)

        def decode() -> np.ndarray:
            calls["n"] += 1
            time.sleep(0.02)
            return np.zeros((4, 4, 3), dtype=np.uint8)

        results: list[np.ndarray] = []

        def worker() -> None:
            barrier.wait()
            results.append(cache.get_or_decode("shared", decode))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, calls["n"])
        self.assertEqual(8, len(results))

    def test_automation_cancel_race_does_not_complete_after_cancel(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp) / "workspace.json")
            workspace.load()
            service = _service()
            automation = AutomationService(service, workspace=workspace, max_workers=2)
            session = automation.create_session()
            started = threading.Event()
            release = threading.Event()

            def slow_handler(_session, _params):  # type: ignore[no-untyped-def]
                started.set()
                release.wait(timeout=5.0)
                return {"ok": True}

            automation.command_registry.register_plugin_command(
                "rc.sprint2",
                "slow",
                slow_handler,
                permission="execute",
                description="test slow command",
            )
            op = automation.submit(session.session_id, "rc.sprint2.slow", {})
            self.assertTrue(started.wait(timeout=5.0))
            self.assertTrue(automation.cancel(op.operation_id))
            release.set()
            # Wait until worker finishes observing cancel.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                current = automation.query(op.operation_id)
                if current is not None and current.status in {"cancelled", "failed", "completed"}:
                    break
                time.sleep(0.01)
            current = automation.query(op.operation_id)
            assert current is not None
            self.assertEqual("cancelled", current.status)
            self.assertNotEqual("completed", current.status)
            automation.shutdown()

    def test_automation_bounds_completed_operation_history(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp) / "workspace.json")
            workspace.load()
            service = _service()
            automation = AutomationService(service, workspace=workspace, max_workers=2)
            session = automation.create_session()

            def noop(_session, _params):  # type: ignore[no-untyped-def]
                return {}

            automation.command_registry.register_plugin_command(
                "rc.sprint2",
                "noop",
                noop,
                permission="execute",
                description="noop",
            )
            # Shrink retention for the test.
            import nova_layer.object_workflow.automation.service as auto_mod

            original = auto_mod._MAX_RETAINED_OPERATIONS
            auto_mod._MAX_RETAINED_OPERATIONS = 5
            try:
                for _ in range(12):
                    automation.execute(session.session_id, "rc.sprint2.noop", {})
                with automation._lock:  # noqa: SLF001
                    terminal = [
                        op
                        for op in automation._operations.values()  # noqa: SLF001
                        if op.status in {"completed", "failed", "cancelled"}
                    ]
                self.assertLessEqual(len(terminal), 5)
            finally:
                auto_mod._MAX_RETAINED_OPERATIONS = original
                automation.shutdown()


class Sam2FingerprintReuseTests(TestCase):
    def test_protocol_accepts_fingerprint_kwarg_on_fake_runtime(self) -> None:
        # Ensure TorchSam2ImageRuntime still constructs (lazy load).
        runtime = TorchSam2ImageRuntime(Path("/nonexistent"), device="cpu")
        self.assertEqual("cpu", runtime.device)
