from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.core_inference_registry import (
    build_default_core_inference_registry,
)
from nova_layer.object_workflow.adapters.host_adapter_registry import (
    build_default_host_adapter_registry,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    build_default_precision_extraction_registry,
)
from nova_layer.object_workflow.plugin_sdk import (
    SDK_VERSION,
    PluginManager,
    load_manifest,
)
from nova_layer.object_workflow.plugin_sdk.errors import PluginValidationError
from nova_layer.object_workflow.plugin_sdk.manifest import parse_manifest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "plugins"


def _copy_plugin(src_name: str, dest_root: Path) -> Path:
    src = FIXTURES / src_name
    dest = dest_root / src_name
    shutil.copytree(src, dest)
    return dest


class ManifestTests(TestCase):
    def test_parse_valid_manifest(self) -> None:
        manifest = load_manifest(FIXTURES / "fake_inference")
        self.assertEqual("test.fake_inference", manifest.plugin_id)
        self.assertEqual(SDK_VERSION, manifest.sdk_version)
        self.assertEqual(("cpu",), manifest.capabilities)

    def test_invalid_plugin_type(self) -> None:
        with self.assertRaises(PluginValidationError):
            load_manifest(FIXTURES / "invalid_manifest")

    def test_incompatible_sdk_version(self) -> None:
        with self.assertRaises(PluginValidationError) as ctx:
            load_manifest(FIXTURES / "bad_sdk")
        self.assertEqual("PLUGIN_SDK_INCOMPATIBLE", ctx.exception.code)

    def test_capability_parsing_requires_non_empty(self) -> None:
        with self.assertRaises(PluginValidationError):
            parse_manifest(
                {
                    "plugin_id": "x",
                    "display_name": "X",
                    "version": "1",
                    "sdk_version": "1.0",
                    "plugin_type": "inference",
                    "capabilities": [],
                    "entry_module": "plugin",
                }
            )


class PluginManagerTests(TestCase):
    def test_discovery_and_registration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("fake_inference", root)
            _copy_plugin("fake_matting", root)
            _copy_plugin("fake_host", root)
            inference = build_default_core_inference_registry()
            extraction = build_default_precision_extraction_registry()
            host = build_default_host_adapter_registry(include_fake_host=False)
            builtin_inference = {item.provider_id for item in inference.list()}
            builtin_extraction = {item.provider_id for item in extraction.list()}
            builtin_host = {item.adapter_id for item in host.list()}

            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(
                inference_registry=inference,
                extraction_registry=extraction,
                host_registry=host,
            )
            self.assertEqual(3, len(infos))
            self.assertTrue(all(item.availability == "available" for item in infos))
            self.assertTrue(inference.contains("plugin.test.fake_inference"))
            self.assertTrue(extraction.contains("plugin.test.fake_matting"))
            self.assertTrue(host.contains("plugin.test.fake_host"))
            # Builtins preserved.
            self.assertTrue(builtin_inference.issubset({p.provider_id for p in inference.list()}))
            self.assertTrue(
                builtin_extraction.issubset({p.provider_id for p in extraction.list()})
            )
            self.assertTrue(builtin_host.issubset({p.adapter_id for p in host.list()}))

    def test_duplicate_ids_isolated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("dup_a", root)
            _copy_plugin("dup_b", root)
            inference = build_default_core_inference_registry()
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(inference_registry=inference)
            statuses = {item.plugin_id: item for item in infos}
            # First wins; second fails with duplicate id (both share test.duplicate).
            available = [item for item in infos if item.availability == "available"]
            failed = [item for item in infos if item.availability == "unavailable"]
            self.assertEqual(1, len(available))
            self.assertEqual(1, len(failed))
            self.assertIn("PLUGIN_DUPLICATE_ID", failed[0].failure_reason)
            self.assertTrue(inference.contains("plugin.test.duplicate_a"))
            self.assertFalse(inference.contains("plugin.test.duplicate_b"))
            _ = statuses

    def test_missing_entry_module(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("missing_entry", root)
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(
                inference_registry=build_default_core_inference_registry()
            )
            self.assertEqual(1, len(infos))
            self.assertEqual("unavailable", infos[0].availability)
            self.assertIn("PLUGIN_ENTRY_MISSING", infos[0].failure_reason)

    def test_runtime_error_isolated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("runtime_boom", root)
            _copy_plugin("fake_inference", root)
            inference = build_default_core_inference_registry()
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(inference_registry=inference)
            by_id = {item.plugin_id: item for item in infos}
            self.assertEqual("unavailable", by_id["test.runtime_boom"].availability)
            self.assertIn(
                "intentional plugin runtime failure",
                by_id["test.runtime_boom"].failure_reason,
            )
            self.assertEqual("available", by_id["test.fake_inference"].availability)
            self.assertTrue(inference.contains("plugin.test.fake_inference"))
            self.assertTrue(inference.contains("mock"))

    def test_invalid_manifest_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("invalid_manifest", root)
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(
                inference_registry=build_default_core_inference_registry()
            )
            self.assertEqual(1, len(infos))
            self.assertEqual("unavailable", infos[0].availability)

    def test_optional_dependency_missing_disables_plugin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = _copy_plugin("fake_inference", root)
            manifest_path = dest / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["plugin_id"] = "test.missing_dep"
            payload["optional_dependencies"] = ["definitely_not_a_real_package_xyz"]
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            infos = manager.load_and_register(
                inference_registry=build_default_core_inference_registry()
            )
            self.assertEqual(1, len(infos))
            self.assertEqual("unavailable", infos[0].availability)
            self.assertIn("PLUGIN_DEPENDENCY_ERROR", infos[0].failure_reason)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("fake_inference", root)
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
                configurations={"test.fake_inference": {"model_path": "/tmp/x", "device": "cpu"}},
            )
            manager.load_and_register(
                inference_registry=build_default_core_inference_registry()
            )
            config = manager.get_plugin_configuration("test.fake_inference")
            self.assertEqual("/tmp/x", config["model_path"])
            info = manager.get_plugin("test.fake_inference")
            assert info is not None
            self.assertEqual("cpu", info.configuration["device"])

    def test_controller_startup_survives_bad_plugins(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("runtime_boom", root)
            _copy_plugin("bad_sdk", root)
            controller = ObjectWorkflowController(
                enable_plugins=True,
                plugins_root=root,
                plugin_manager=PluginManager(
                    plugin_roots=root,
                    include_default_roots=False,
                    environ={},
                ),
            )
            # Built-in mock still selected and usable.
            self.assertEqual("mock", controller.view_state().core_inference_provider)
            plugins = controller.list_plugins()
            self.assertGreaterEqual(len(plugins), 2)
            self.assertTrue(controller.view_state().plugin_summary)
            self.assertNotIn("No plugins discovered", controller.view_state().plugin_summary)


class FakePluginEngineTests(TestCase):
    def test_registered_fake_inference_creates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_plugin("fake_inference", root)
            inference = build_default_core_inference_registry()
            manager = PluginManager(
                plugin_roots=root,
                include_default_roots=False,
                environ={},
            )
            manager.load_and_register(inference_registry=inference)
            engine = inference.create("plugin.test.fake_inference")
            self.assertIsNotNone(engine)
