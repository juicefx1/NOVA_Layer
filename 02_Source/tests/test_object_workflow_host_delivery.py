from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pytest

from nova_layer.object_workflow.adapters.host_adapter_registry import (
    build_default_host_adapter_registry,
)
from nova_layer.object_workflow.adapters.host_filesystem_export import FilesystemExportAdapter
from nova_layer.object_workflow.adapters.host_naming import (
    sanitize_filename_component,
    suggested_export_filename,
    to_file_uri,
    unique_destination,
)
from nova_layer.object_workflow.adapters.host_platform import (
    open_file_argv_for_platform,
    reveal_argv_for_platform,
)
from nova_layer.object_workflow.adapters.host_reveal import FakeHostAdapter, RevealAdapter
from nova_layer.object_workflow.adapters.image_codec import decode_rgba_png_bytes, write_rgba_png
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.mock_core_inference import MockCoreInferenceEngine
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.mock_precision_extraction import (
    MockPrecisionExtractionEngine,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.ports.host_delivery import HostDeliveryRequest
from tests.object_workflow_test_helpers import generate_and_select


@pytest.mark.real_host
def test_real_host_bridge_not_configured() -> None:
    """Separately marked smoke placeholder — no approved local Host bridge."""
    pytest.skip("Real Host tests not run: no approved local Host bridge available.")


def _png_source(path: Path, width: int = 8, height: int = 6) -> Path:
    import struct
    import zlib

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


class MemoryClipboard:
    def __init__(self) -> None:
        self.text = ""

    def write_text(self, text: str) -> None:
        self.text = text


class RecordingLauncher:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, timeout_seconds: float = 30.0) -> int:
        self.calls.append(list(argv))
        return 0


def _service(*, include_fake_host: bool = True) -> ObjectWorkflowService:
    launcher = RecordingLauncher()
    registry = build_default_host_adapter_registry(
        launcher=launcher,  # type: ignore[arg-type]
        include_fake_host=include_fake_host,
    )
    service = ObjectWorkflowService(
        store=JsonProjectStore(),
        inference=MockCoreInferenceEngine(),
        extraction=MockPrecisionExtractionEngine(),
        executor=MockOperationExecutor(step_delay_seconds=0.0),
        host_registry=registry,
        clipboard=MemoryClipboard(),
        process_launcher=launcher,  # type: ignore[arg-type]
        include_fake_host=include_fake_host,
    )
    service._test_launcher = launcher  # type: ignore[attr-defined]
    service._test_clipboard = service._clipboard  # type: ignore[attr-defined]
    return service


def _reach_extraction(service: ObjectWorkflowService, source: Path) -> None:
    service.create_project("host-delivery")
    service.load_source(source)
    service.create_artist_intent(_intent())
    generate_and_select(service)
    service.confirm_hypothesis()
    service.generate_extraction()


class HostNamingTests(TestCase):
    def test_suggested_filename_and_sanitisation(self) -> None:
        name = suggested_export_filename(
            source_name="My Portrait.jpg",
            generation_number=2,
            candidate_number=1,
            extraction_provider="local.matting",
        )
        self.assertEqual(name, "My_Portrait_nova_g2_c1_local-matting.png")
        self.assertEqual(sanitize_filename_component('a/b:c*d'), "a_b_c_d")

    def test_unique_destination_suffix(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.png"
            path.write_bytes(b"x")
            unique = unique_destination(path, allow_overwrite=False)
            self.assertEqual(unique.name, "out_1.png")
            self.assertEqual(unique_destination(path, allow_overwrite=True), path)

    def test_file_uri(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(b"1")
            self.assertTrue(to_file_uri(path).startswith("file:"))


class HostPlatformTests(TestCase):
    def test_reveal_and_open_argv_no_shell_string(self) -> None:
        path = Path("/tmp/example.png")
        darwin = reveal_argv_for_platform(path, platform="darwin")
        self.assertEqual(darwin, ["open", "-R", str(path.resolve())])
        self.assertEqual(open_file_argv_for_platform(path, platform="linux")[0], "xdg-open")
        self.assertNotIn(";", " ".join(reveal_argv_for_platform(path, platform="win")))


class HostRegistryTests(TestCase):
    def test_default_registry_order_and_capabilities(self) -> None:
        registry = build_default_host_adapter_registry(include_fake_host=True)
        ids = [item.adapter_id for item in registry.list()]
        self.assertEqual(ids[:3], ["filesystem", "reveal", "generic_open_file"])
        self.assertIn("fake_host", ids)
        filesystem = registry.get("filesystem").descriptor
        self.assertTrue(filesystem.capabilities.export_copy)
        self.assertEqual(filesystem.availability, "available")
        # Listing must not launch hosts.
        launcher = RecordingLauncher()
        build_default_host_adapter_registry(launcher=launcher, include_fake_host=True).list()
        self.assertEqual(launcher.calls, [])


class FilesystemExportAdapterTests(TestCase):
    def test_atomic_export_preserves_pixels_and_source(self) -> None:
        adapter = FilesystemExportAdapter()
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "committed.png"
            rgba = bytearray()
            for y in range(4):
                for x in range(4):
                    rgba.extend([x * 10, y * 10, 50, 200 if x == y else 0])
            write_rgba_png(source, 4, 4, bytes(rgba))
            original = source.read_bytes()
            destination = Path(tmp) / "exported.png"
            request = HostDeliveryRequest(
                source_project_id="p",
                extraction_id="e",
                rgba_asset_bytes=original,
                rgba_relative_path="assets/extractions/x.png",
                display_name="demo",
                width=4,
                height=4,
                premultiplied_alpha=False,
                crop_mode="full_source",
                action="export_copy",
                destination=str(destination),
                allow_overwrite=False,
            )
            success = adapter.deliver(request)
            self.assertEqual(Path(success.output_reference).read_bytes(), original)
            self.assertEqual(source.read_bytes(), original)
            width, height, out_rgba = decode_rgba_png_bytes(destination.read_bytes())
            self.assertEqual((width, height), (4, 4))
            self.assertEqual(out_rgba, bytes(rgba))
            self.assertFalse(any(Path(tmp).glob("*.tmp")))

    def test_overwrite_denied(self) -> None:
        adapter = FilesystemExportAdapter()
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "exists.png"
            destination.write_bytes(b"keep")
            request = HostDeliveryRequest(
                source_project_id="p",
                extraction_id="e",
                rgba_asset_bytes=b"\x89PNG\r\n\x1a\n",
                rgba_relative_path="assets/extractions/x.png",
                display_name="demo",
                width=1,
                height=1,
                premultiplied_alpha=False,
                crop_mode="full_source",
                action="export_copy",
                destination=str(destination),
                allow_overwrite=False,
            )
            with self.assertRaises(ApplicationError) as ctx:
                adapter.deliver(request)
            self.assertEqual(ctx.exception.code, "DESTINATION_EXISTS")
            self.assertEqual(destination.read_bytes(), b"keep")


class FakeHostAdapterTests(TestCase):
    def test_fake_host_delivery_and_unavailable(self) -> None:
        adapter = FakeHostAdapter()
        request = HostDeliveryRequest(
            source_project_id="p",
            extraction_id="e",
            rgba_asset_bytes=b"png",
            rgba_relative_path="assets/extractions/x.png",
            display_name="demo",
            width=2,
            height=2,
            premultiplied_alpha=False,
            crop_mode="full_source",
            action="import_as_layer",
        )
        success = adapter.deliver(request)
        self.assertEqual(success.action, "import_as_layer")
        self.assertEqual(len(adapter.calls), 1)
        unavailable = FakeHostAdapter(available=False)
        with self.assertRaises(ApplicationError) as ctx:
            unavailable.deliver(request)
        self.assertEqual(ctx.exception.code, "HOST_ADAPTER_UNAVAILABLE")


class HostApplicationDeliveryTests(TestCase):
    def test_export_uses_committed_extraction_not_browsed_generation(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "portrait.png")
            _reach_extraction(service, source)
            committed = service.get_active_extraction_result()
            assert committed is not None
            committed_bytes = service.get_asset_bytes(committed.relative_asset_path)
            destination = Path(tmp) / "out.png"
            success = service.export_active_extraction(destination)
            self.assertEqual(destination.read_bytes(), committed_bytes)
            self.assertEqual(success.action, "export_copy")
            # Project asset unchanged
            self.assertEqual(
                service.get_asset_bytes(committed.relative_asset_path),
                committed_bytes,
            )
            # Active extraction remains the delivery binding source.
            active_after = service.get_active_extraction_result()
            assert active_after is not None
            self.assertEqual(active_after.id, committed.id)

    def test_cannot_export_without_extraction(self) -> None:
        service = _service()
        service.create_project("empty")
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ApplicationError) as ctx:
                service.export_active_extraction(Path(tmp) / "x.png")
            self.assertEqual(ctx.exception.code, "NO_ACTIVE_EXTRACTION")

    def test_missing_asset_rejected_before_adapter(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            extraction = service.get_active_extraction_result()
            assert extraction is not None
            del service._assets[extraction.relative_asset_path]
            with self.assertRaises(ApplicationError) as ctx:
                service.export_active_extraction(Path(tmp) / "missing.png")
            self.assertEqual(ctx.exception.code, "EXTRACTION_ASSET_MISSING")

    def test_wrong_dimensions_rejected(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            extraction = service.get_active_extraction_result()
            assert extraction is not None
            extraction.width = 999
            with self.assertRaises(ApplicationError) as ctx:
                service.export_active_extraction(Path(tmp) / "bad.png")
            self.assertEqual(ctx.exception.code, "EXTRACTION_ASSET_DIMENSION_MISMATCH")

    def test_host_failure_preserves_extraction_and_confirmation(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            project = service.project
            assert project is not None
            confirmation = project.active_confirmation_id
            extraction = service.get_active_extraction_result()
            assert extraction is not None
            extraction_id = extraction.id
            asset = service.get_asset_bytes(extraction.relative_asset_path)
            with self.assertRaises(ApplicationError):
                service.deliver_active_extraction("fake_host", "replace_selected_layer")
            self.assertEqual(project.active_confirmation_id, confirmation)
            self.assertEqual(service.get_active_extraction_result().id, extraction_id)
            self.assertEqual(service.get_asset_bytes(extraction.relative_asset_path), asset)

    def test_fake_host_success_bound_to_original_extraction(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            first = service.get_active_extraction_result()
            assert first is not None
            success = service.deliver_active_extraction("fake_host", "import_as_layer")
            self.assertIn(str(first.id), success.output_reference)
            delivery = service.get_last_successful_delivery()
            assert delivery is not None
            self.assertEqual(delivery.extraction_id, str(first.id))

    def test_copy_reference_and_suggested_filename(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "portrait.png")
            _reach_extraction(service, source)
            name = service.get_suggested_export_filename()
            self.assertTrue(name.endswith(".png"))
            self.assertIn("nova_g", name)
            text = service.copy_active_extraction_reference("project_relative")
            self.assertTrue(text.startswith("assets/extractions/"))
            clipboard = service._clipboard
            assert isinstance(clipboard, MemoryClipboard)
            self.assertEqual(clipboard.text, text)

    def test_reveal_uses_launcher_argv(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            service.reveal_active_extraction()
            launcher = service._test_launcher  # type: ignore[attr-defined]
            self.assertEqual(len(launcher.calls), 1)
            self.assertIsInstance(launcher.calls[0], list)
            self.assertNotIn(True, launcher.calls[0])

    def test_no_operation_record_for_export(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            project = service.project
            assert project is not None
            before = len(project.operations)
            service.export_active_extraction(Path(tmp) / "sync.png")
            self.assertEqual(len(project.operations), before)

    def test_schema_unchanged_after_export(self) -> None:
        service = _service()
        with TemporaryDirectory() as tmp:
            source = _png_source(Path(tmp) / "src.png")
            _reach_extraction(service, source)
            service.export_active_extraction(Path(tmp) / "x.png")
            package = Path(tmp) / "proj.nova"
            service.save_project(package)
            loaded = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=MockCoreInferenceEngine(),
                extraction=MockPrecisionExtractionEngine(),
                include_fake_host=True,
            )
            project = loaded.load_project(package)
            self.assertEqual(project.schema_version, "2.0")
            self.assertTrue(loaded.can_export_active_extraction())


class RevealAdapterUnitTests(TestCase):
    def test_reveal_missing_target(self) -> None:
        adapter = RevealAdapter(launcher=RecordingLauncher())  # type: ignore[arg-type]
        request = HostDeliveryRequest(
            source_project_id="p",
            extraction_id="e",
            rgba_asset_bytes=b"x",
            rgba_relative_path="assets/extractions/x.png",
            display_name="demo",
            width=1,
            height=1,
            premultiplied_alpha=False,
            crop_mode="full_source",
            action="reveal_file",
            destination="/no/such/file.png",
        )
        with self.assertRaises(ApplicationError) as ctx:
            adapter.deliver(request)
        self.assertEqual(ctx.exception.code, "REVEAL_TARGET_MISSING")
