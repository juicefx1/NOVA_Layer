from __future__ import annotations

import json
import struct
import threading
import time
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.runtime.caches import RuntimeCacheBundle


def _png_bytes(width: int = 32, height: int = 24, fill: int = 128) -> bytes:
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


def _intent() -> dict[str, object]:
    return {
        "schema": "nova.intent.guidance.v1",
        "payload": {
            "signals": [{"type": "positive_point", "x": 0.5, "y": 0.5}],
        },
    }


def _write_images(root: Path, count: int) -> list[Path]:
    paths: list[Path] = []
    for index in range(count):
        path = root / f"image_{index}.png"
        path.write_bytes(_png_bytes(fill=100 + index))
        paths.append(path)
    return paths


def _service() -> ObjectWorkflowService:
    return ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )


def _confirm_interactively(manager: BatchManager, *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if manager.is_awaiting_confirmation:
            cset = manager.service.get_active_candidate_set()
            assert cset is not None and cset.candidates
            manager.service.select_candidate(cset.candidates[0].id)
            manager.service.confirm_hypothesis()
            manager.notify_user_confirmation()
            return
        threading.Event().wait(0.01)
    raise TimeoutError("timed out waiting for interactive batch confirmation")


class WorkspaceManagerTests(TestCase):
    def tearDown(self) -> None:
        WorkspaceManager.reset_shared_for_tests()

    def test_save_restore_preferences_and_projects(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            ws = WorkspaceManager(path)
            ws.load()
            ws.set_selected_provider_id("mock")
            ws.set_preference("theme", "dark")
            ws.set_window_geometry({"x": 10, "y": 20, "w": 800, "h": 600})
            ws.set_active_project(Path(tmp) / "a.nova")
            ws.set_plugin_configuration("plug.a", {"device": "cpu"})

            restored = WorkspaceManager(path)
            restored.load()
            self.assertEqual("mock", restored.selected_provider_id())
            self.assertEqual("dark", restored.get_preference("theme"))
            assert restored.window_geometry() is not None
            self.assertEqual(800, restored.window_geometry()["w"])
            self.assertTrue(str(restored.active_project()).endswith("a.nova"))
            self.assertEqual({"device": "cpu"}, restored.get_plugin_configuration("plug.a"))

    def test_corrupt_workspace_recovers_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            path.write_text("{not-json", encoding="utf-8")
            ws = WorkspaceManager(path)
            data = ws.load()
            self.assertIsNotNone(ws.load_error)
            self.assertEqual([], data["recent_projects"])
            ws.set_preference("ok", True)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(True, raw["preferences"]["ok"])

    def test_shared_singleton(self) -> None:
        with TemporaryDirectory() as tmp:
            WorkspaceManager.reset_shared_for_tests()
            path = Path(tmp) / "shared.json"
            first = WorkspaceManager.shared(path)
            second = WorkspaceManager.shared()
            self.assertIs(first, second)
            WorkspaceManager.reset_shared_for_tests()


class BatchManagerTests(TestCase):
    def test_interactive_default_never_auto_confirms(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 1)
            service = _service()
            manager = BatchManager(service, workspace=WorkspaceManager(root / "ws.json"))
            job = manager.create_job(images, _intent())
            self.assertEqual("interactive", job.confirmation_mode)
            self.assertFalse(job.enable_automatic_confirmation)

            helper = threading.Thread(target=_confirm_interactively, args=(manager,), daemon=True)
            helper.start()
            finished = manager.run(job)
            helper.join(timeout=5)
            self.assertEqual("completed", finished.status)
            self.assertEqual(1, finished.statistics().completed)
            logs = "\n".join(finished.queue[0].log_lines)
            self.assertIn("Awaiting explicit user confirmation", logs)
            self.assertIn("User confirmation received", logs)
            self.assertNotIn("Automatic confirmation applied", logs)

    def test_automatic_requires_explicit_enable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 1)
            manager = BatchManager(_service())
            with self.assertRaises(ApplicationError) as ctx:
                manager.create_job(
                    images,
                    _intent(),
                    confirmation_mode="automatic",
                    enable_automatic_confirmation=False,
                )
            self.assertEqual("AUTOMATIC_CONFIRMATION_NOT_ENABLED", ctx.exception.code)

    def test_automatic_mode_with_explicit_enable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 2)
            missing = root / "missing.png"
            workspace = WorkspaceManager(root / "workspace.json")
            caches = RuntimeCacheBundle()
            service = _service()
            inference_id = id(service._inference)
            manager = BatchManager(service, workspace=workspace, runtime_caches=caches)
            job = manager.create_job(
                [*images, missing],
                _intent(),
                export_directory=root / "exports",
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
                selection_policy="highest_confidence",
            )
            finished = manager.run(job)
            stats = finished.statistics()
            self.assertEqual(2, stats.completed)
            self.assertEqual(1, stats.failed)
            self.assertEqual(inference_id, id(service._inference))
            self.assertEqual(2, len(list((root / "exports").glob("*.png"))))
            self.assertIn(
                "Automatic confirmation applied",
                "\n".join(finished.queue[0].log_lines),
            )

    def test_cancellation_while_awaiting_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 2)
            service = _service()
            manager = BatchManager(service, workspace=WorkspaceManager(root / "ws.json"))
            job = manager.create_job(images, _intent())

            def _cancel_when_waiting() -> None:
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    if manager.is_awaiting_confirmation:
                        manager.cancel()
                        return
                    threading.Event().wait(0.01)
                raise TimeoutError("timed out waiting to cancel interactive batch")

            helper = threading.Thread(target=_cancel_when_waiting, daemon=True)
            helper.start()
            finished = manager.run(job)
            helper.join(timeout=5)
            self.assertEqual("cancelled", finished.status)
            self.assertGreaterEqual(finished.statistics().cancelled, 1)

    def test_retry_failed_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = _write_images(root, 1)[0]
            missing = root / "gone.png"
            service = _service()
            manager = BatchManager(service, workspace=WorkspaceManager(root / "ws.json"))
            job = manager.create_job(
                [good, missing],
                _intent(),
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
            )
            manager.run(job)
            self.assertEqual(1, job.statistics().failed)
            missing.write_bytes(_png_bytes())
            manager.retry_failed()
            manager.run(job)
            self.assertEqual(2, job.statistics().completed)

    def test_workspace_restore_queue_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 2)
            workspace = WorkspaceManager(root / "workspace.json")
            service = _service()
            manager = BatchManager(service, workspace=workspace)
            job = manager.create_job(
                images,
                _intent(),
                confirmation_mode="automatic",
                enable_automatic_confirmation=True,
            )
            manager.run(job)
            manager2 = BatchManager(_service(), workspace=workspace)
            restored = manager2.restore_queue_from_workspace()
            assert restored is not None
            self.assertEqual(2, len(restored.queue))
            self.assertTrue(all(item.status == "completed" for item in restored.queue))
            self.assertEqual("automatic", restored.confirmation_mode)
            self.assertTrue(restored.enable_automatic_confirmation)

    def test_empty_batch_rejected(self) -> None:
        manager = BatchManager(_service())
        with self.assertRaises(ApplicationError):
            manager.create_job([], _intent())


class ControllerBatchTests(TestCase):
    def test_controller_defaults_to_interactive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = _write_images(root, 1)
            workspace = WorkspaceManager(root / "ws.json")
            controller = ObjectWorkflowController(
                enable_plugins=False,
                workspace=workspace,
            )
            self.assertEqual("interactive", controller.view_state().batch_confirmation_mode)
            job = controller.create_batch_job(images, intent_snapshot=_intent())
            assert job is not None
            self.assertEqual("interactive", job.confirmation_mode)
            self.assertFalse(job.enable_automatic_confirmation)
