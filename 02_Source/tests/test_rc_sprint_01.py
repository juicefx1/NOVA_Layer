from __future__ import annotations

import json
import struct
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
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager


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


class RuntimeLifecycleTests(TestCase):
    def test_service_shutdown_removes_temp_workspace(self) -> None:
        service = ObjectWorkflowService(
            store=JsonProjectStore(),
            inference=MockCoreInferenceEngine(),
            extraction=MockPrecisionExtractionEngine(),
        )
        temp = service.temp_workspace
        self.assertTrue(temp.is_dir())
        (temp / "artifact.bin").write_bytes(b"x")
        service.shutdown()
        self.assertFalse(temp.exists())
        # Idempotent.
        service.shutdown()

    def test_controller_shutdown_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp) / "workspace.json")
            workspace.load()
            controller = ObjectWorkflowController(
                workspace=workspace,
                plugins_root=Path(tmp) / "no_plugins",
                enable_batch=False,
            )
            controller.shutdown()
            controller.shutdown()


class AtomicWorkspacePersistenceTests(TestCase):
    def test_save_is_atomic_and_preserves_previous_on_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "workspace.json"
            ws = WorkspaceManager(path)
            ws.load()
            ws.set_preference("theme", "dark")
            original = path.read_text(encoding="utf-8")
            self.assertIn("dark", original)

            # Simulate a failed save by pointing at an unwritable parent mid-flight:
            # replace path's parent with a file so mkdir/write fails; previous file remains.
            ws._data["preferences"]["theme"] = "light"
            blocked = Path(tmp) / "blocked"
            blocked.write_text("not-a-dir", encoding="utf-8")
            ws._path = blocked / "workspace.json"
            with self.assertRaises(OSError):
                ws.save()
            # Original document untouched.
            restored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("dark", restored["preferences"]["theme"])


class WorkspaceCompletionTests(TestCase):
    def test_geometry_and_active_project_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            package = root / "demo.nova"
            package.mkdir()
            workspace.set_window_geometry({"x": 12, "y": 24, "w": 1024, "h": 768})
            workspace.set_dock_layout({"recent_panel_height": 96})
            workspace.set_active_project(package)

            restored = WorkspaceManager(root / "workspace.json")
            restored.load()
            self.assertEqual(1024, restored.window_geometry()["w"])
            self.assertEqual(96, restored.dock_layout()["recent_panel_height"])
            self.assertTrue(str(restored.active_project()).endswith("demo.nova"))
            self.assertIn(str(package), restored.recent_projects())

    def test_controller_restore_active_project(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            controller = ObjectWorkflowController(
                workspace=workspace,
                plugins_root=root / "no_plugins",
                enable_batch=False,
            )
            controller.create_project("RC")
            image = root / "a.png"
            image.write_bytes(_png_bytes())
            controller.load_source(image)
            package = root / "rc.nova"
            controller.save_project(package)
            controller.shutdown()

            again = ObjectWorkflowController(
                workspace=WorkspaceManager(root / "workspace.json"),
                plugins_root=root / "no_plugins",
                enable_batch=False,
            )
            self.assertTrue(again.restore_active_project())
            self.assertIsNotNone(again.view_state().project_name)
            again.shutdown()
