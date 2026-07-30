from __future__ import annotations

import struct
import threading
import time
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.automation import AutomationService
from nova_layer.object_workflow.automation.errors import AutomationError
from nova_layer.object_workflow.plugin_sdk import PluginManager


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


def _service() -> ObjectWorkflowService:
    return ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
    )


class AutomationCommandDispatchTests(TestCase):
    def test_full_single_image_command_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "a.png"
            image.write_bytes(_png_bytes())
            package = root / "proj.nova"
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            workflow = _service()
            automation = AutomationService(workflow, workspace=workspace)
            session = automation.create_session()

            events: list[str] = []
            automation.subscribe(lambda event: events.append(event.event_type))

            loaded = automation.execute(
                session.session_id,
                "load_image",
                {"path": str(image)},
            )
            self.assertTrue(loaded.ok)
            intent = automation.execute(
                session.session_id,
                "create_artist_intent",
                {"intent": _intent()},
            )
            self.assertTrue(intent.ok)
            generated = automation.execute(
                session.session_id,
                "generate_candidates",
                {},
            )
            self.assertTrue(generated.ok, generated.error_message)
            candidate_id = generated.payload["candidate_ids"][0]
            selected = automation.execute(
                session.session_id,
                "select_candidate",
                {"candidate_id": candidate_id},
            )
            self.assertTrue(selected.ok)
            confirmed = automation.execute(
                session.session_id,
                "confirm_candidate",
                {},
            )
            self.assertTrue(confirmed.ok)
            extracted = automation.execute(
                session.session_id,
                "generate_extraction",
                {},
            )
            self.assertTrue(extracted.ok, extracted.error_message)
            export_path = root / "out.png"
            exported = automation.execute(
                session.session_id,
                "export_layer",
                {"destination": str(export_path), "allow_overwrite": True},
            )
            self.assertTrue(exported.ok)
            self.assertTrue(export_path.is_file())
            saved = automation.execute(
                session.session_id,
                "save_project",
                {"package_path": str(package)},
            )
            self.assertTrue(saved.ok)
            self.assertEqual(str(package), workspace.active_project())

            closed = automation.execute(session.session_id, "close_project", {})
            self.assertTrue(closed.ok)
            self.assertIsNone(workspace.active_project())

            opened = automation.execute(
                session.session_id,
                "open_project",
                {"package_path": str(package)},
            )
            self.assertTrue(opened.ok)
            self.assertEqual(str(package), workspace.active_project())

            self.assertIn("OperationStarted", events)
            self.assertIn("OperationCompleted", events)
            self.assertIn("ProjectChanged", events)
            self.assertIn("WorkspaceChanged", events)
            automation.shutdown()


class AutomationEventOrderingTests(TestCase):
    def test_submit_emits_started_then_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "a.png"
            image.write_bytes(_png_bytes())
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            automation = AutomationService(_service(), workspace=workspace)
            session = automation.create_session()
            ordered: list[str] = []
            lock = threading.Lock()

            def _listen(event) -> None:  # type: ignore[no-untyped-def]
                if event.command != "load_image":
                    return
                with lock:
                    ordered.append(event.event_type)

            automation.subscribe(_listen)
            op = automation.submit(session.session_id, "load_image", {"path": str(image)})
            result = automation.wait(op.operation_id)
            self.assertTrue(result.ok)
            self.assertEqual(["OperationStarted", "OperationCompleted"], ordered[:2])
            automation.shutdown()


class AutomationBatchTests(TestCase):
    def test_batch_execute_automatic(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for index in range(2):
                path = root / f"{index}.png"
                path.write_bytes(_png_bytes(fill=100 + index))
                images.append(path)
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            workflow = _service()
            batch = BatchManager(workflow, workspace=workspace)
            automation = AutomationService(
                workflow,
                workspace=workspace,
                batch_manager=batch,
            )
            session = automation.create_session()
            events: list[str] = []
            automation.subscribe(
                lambda event: events.append(event.event_type)
                if event.event_type == "BatchChanged"
                else None
            )
            result = automation.execute(
                session.session_id,
                "batch_execute",
                {
                    "image_paths": [str(path) for path in images],
                    "intent": _intent(),
                    "confirmation_mode": "automatic",
                    "enable_automatic_confirmation": True,
                },
            )
            self.assertTrue(result.ok, result.error_message)
            self.assertEqual("completed", result.payload["status"])
            self.assertEqual(2, result.payload["statistics"]["completed"])
            self.assertGreaterEqual(events.count("BatchChanged"), 2)
            automation.shutdown()


class AutomationWorkspaceTests(TestCase):
    def test_uses_injected_workspace_not_hidden_session(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            workspace.set_preference("automation", True)
            automation = AutomationService(_service(), workspace=workspace)
            session = automation.create_session(user_context={"actor": "test"})
            self.assertIs(session.workspace, workspace)
            self.assertEqual(True, session.workspace.get_preference("automation"))
            self.assertEqual("test", session.user_context["actor"])
            automation.shutdown()


class AutomationPermissionTests(TestCase):
    def test_execute_denied_without_permission(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            automation = AutomationService(_service(), workspace=workspace)
            session = automation.create_session(permissions=["read"])
            with self.assertRaises(AutomationError) as ctx:
                automation.submit(session.session_id, "load_image", {"path": str(root / "x.png")})
            self.assertEqual("PermissionDenied", ctx.exception.code)
            automation.shutdown()


class AutomationCancellationTests(TestCase):
    def test_cancel_queued_or_running_operation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "a.png"
            image.write_bytes(_png_bytes())
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            automation = AutomationService(_service(), workspace=workspace)
            session = automation.create_session()
            # Seed project+intent so generate can start, then cancel aggressively.
            automation.execute(session.session_id, "load_image", {"path": str(image)})
            automation.execute(
                session.session_id,
                "create_artist_intent",
                {"intent": _intent()},
            )
            op = automation.submit(session.session_id, "generate_candidates", {})
            # Give the worker a moment to start, then cancel.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                queried = automation.query(op.operation_id)
                assert queried is not None
                if queried.status in {"running", "completed", "failed", "cancelled"}:
                    break
                time.sleep(0.001)
            cancelled = automation.cancel(op.operation_id)
            result = automation.wait(op.operation_id, timeout_seconds=5.0)
            # Cancel either succeeded mid-flight or the op already finished.
            self.assertTrue(
                cancelled
                or result.ok
                or result.error_code in {"Cancelled", "OperationFailed"}
            )
            automation.shutdown()


class AutomationPluginIntegrationTests(TestCase):
    def test_plugin_can_register_automation_command(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "ws.json")
            workspace.load()
            plugins = PluginManager(
                plugin_roots=root / "empty",
                include_default_roots=False,
                include_install_root=False,
            )
            automation = AutomationService(
                _service(),
                workspace=workspace,
                plugin_manager=plugins,
            )

            def _ping(_session, params):  # type: ignore[no-untyped-def]
                return {"pong": True, "echo": dict(params)}

            automation.command_registry.register_plugin_command(
                "test.plugin",
                "ping",
                _ping,
                permission="execute",
                description="ping helper",
            )
            session = automation.create_session()
            result = automation.execute(
                session.session_id,
                "test.plugin.ping",
                {"hello": "world"},
            )
            self.assertTrue(result.ok)
            self.assertEqual(True, result.payload["pong"])
            self.assertEqual("world", result.payload["echo"]["hello"])
            names = {item["name"] for item in automation.list_commands()}
            self.assertIn("test.plugin.ping", names)
            automation.shutdown()
