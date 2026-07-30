from __future__ import annotations

import json
import shutil
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from nova_layer.app.object_workflow_controller import ObjectWorkflowController
from nova_layer.object_workflow.adapters.core_inference_registry import (
    build_default_core_inference_registry,
)
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.plugin_sdk import (
    PACKAGE_FORMAT_VERSION,
    PluginManager,
    PluginPackageInstallError,
    PluginPackageManager,
    build_nova_plugin_package,
    validate_plugin_package,
)
from nova_layer.object_workflow.plugin_sdk.package.constants import PACKAGE_EXTENSION

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "plugins"


def _stage_plugin(tmp: Path, fixture_name: str = "fake_inference") -> Path:
    src = FIXTURES / fixture_name
    dest = tmp / fixture_name
    shutil.copytree(src, dest)
    return dest


class PluginPackageValidationTests(TestCase):
    def test_build_and_validate_package(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = _stage_plugin(root)
            package = build_nova_plugin_package(plugin_dir, root / "fake")
            self.assertTrue(str(package).endswith(PACKAGE_EXTENSION))
            result = validate_plugin_package(package)
            self.assertTrue(result.ok, result.errors)
            assert result.package_manifest is not None
            assert result.plugin_manifest is not None
            self.assertEqual(PACKAGE_FORMAT_VERSION, result.package_manifest.package_format)
            self.assertEqual("test.fake_inference", result.plugin_manifest.plugin_id)
            self.assertTrue(result.compatibility and result.compatibility.compatible)

    def test_rejects_sdk_mismatch(self) -> None:
        import zipfile

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = _stage_plugin(root, "bad_sdk")
            package = root / f"bad{PACKAGE_EXTENSION}"
            with zipfile.ZipFile(package, "w") as zf:
                zf.writestr(
                    "package.json",
                    json.dumps(
                        {
                            "package_format": PACKAGE_FORMAT_VERSION,
                            "plugin_id": "test.bad_sdk",
                            "version": "1.0.0",
                            "sdk_version": "99.0",
                        },
                        indent=2,
                    )
                    + "\n",
                )
                for path in sorted(plugin_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, arcname=path.relative_to(plugin_dir).as_posix())
            result = validate_plugin_package(package)
            self.assertFalse(result.ok)
            self.assertTrue(any("PLUGIN_SDK_INCOMPATIBLE" in err for err in result.errors))

    def test_rejects_id_mismatch_between_package_and_plugin_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = _stage_plugin(root)
            package = build_nova_plugin_package(
                plugin_dir,
                root / "mismatch",
                package_manifest={
                    "package_format": PACKAGE_FORMAT_VERSION,
                    "plugin_id": "other.id",
                    "version": "1.0.0",
                    "sdk_version": "1.0",
                },
            )
            result = validate_plugin_package(package)
            self.assertFalse(result.ok)
            self.assertTrue(any("plugin_id" in err for err in result.errors))

    def test_rejects_path_traversal_zip(self) -> None:
        import zipfile

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evil = root / f"evil{PACKAGE_EXTENSION}"
            with zipfile.ZipFile(evil, "w") as zf:
                zf.writestr(
                    "package.json",
                    json.dumps(
                        {
                            "package_format": PACKAGE_FORMAT_VERSION,
                            "plugin_id": "evil",
                            "version": "1.0.0",
                            "sdk_version": "1.0",
                        }
                    ),
                )
                zf.writestr("../escape.txt", "nope")
            result = validate_plugin_package(evil)
            self.assertFalse(result.ok)
            self.assertTrue(
                any("UNSAFE_PATH" in err or "unsafe" in err.lower() for err in result.errors)
            )


class PluginPackageManagerTests(TestCase):
    def test_install_update_uninstall_with_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            install_root = root / "installed"
            manager = PluginPackageManager(install_root=install_root, workspace=workspace)
            plugin_dir = _stage_plugin(root)
            package_v1 = build_nova_plugin_package(plugin_dir, root / "v1")

            record = manager.install(package_v1)
            self.assertEqual("test.fake_inference", record.plugin_id)
            self.assertTrue(Path(record.install_path).is_dir())
            self.assertEqual(1, len(manager.list_installed()))
            self.assertEqual(1, len(workspace.installed_plugins()))
            self.assertEqual(str(install_root), workspace.plugin_install_root())

            with self.assertRaises(PluginPackageInstallError) as ctx:
                manager.install(package_v1)
            self.assertEqual("PLUGIN_PACKAGE_ALREADY_INSTALLED", ctx.exception.code)

            # Bump version for update.
            manifest_path = plugin_dir / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["version"] = "1.1.0"
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            package_v2 = build_nova_plugin_package(plugin_dir, root / "v2")
            updated = manager.update(package_v2)
            self.assertEqual("1.1.0", updated.version)
            self.assertEqual("1.1.0", manager.get_installed("test.fake_inference").version)

            removed = manager.uninstall("test.fake_inference")
            self.assertEqual("test.fake_inference", removed.plugin_id)
            self.assertEqual([], manager.list_installed())
            self.assertFalse(Path(record.install_path).exists())

    def test_installed_package_discovered_by_plugin_manager(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_root = root / "installed"
            packages = PluginPackageManager(install_root=install_root)
            package = build_nova_plugin_package(_stage_plugin(root), root / "pkg")
            record = packages.install(package)

            inference = build_default_core_inference_registry()
            manager = PluginManager(
                plugin_roots=root / "empty_dev_plugins",
                include_default_roots=False,
                install_roots=install_root,
            )
            infos = manager.load_and_register(inference_registry=inference)
            self.assertTrue(any(item.plugin_id == record.plugin_id for item in infos))
            available = [item for item in infos if item.plugin_id == record.plugin_id][0]
            self.assertEqual("available", available.availability)
            self.assertTrue(inference.contains("plugin.test.fake_inference"))


class PluginPackageSecurityTests(TestCase):
    def test_failed_update_leaves_previous_version_usable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_root = root / "installed"
            manager = PluginPackageManager(install_root=install_root)
            plugin_dir = _stage_plugin(root)
            package_v1 = build_nova_plugin_package(plugin_dir, root / "v1")
            record = manager.install(package_v1)
            install_path = Path(record.install_path)
            marker = install_path / "manifest.json"
            before = marker.read_text(encoding="utf-8")

            # Force the atomic swap to fail after the previous install was moved aside.
            original_rename = Path.rename

            def boom_rename(self: Path, target: Path) -> Path:
                if self.name.startswith(".staging_"):
                    raise OSError("simulated swap failure")
                return original_rename(self, target)

            package_v2_dir = _stage_plugin(root / "v2src")
            manifest_path = package_v2_dir / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["version"] = "9.9.9"
            manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            package_v2 = build_nova_plugin_package(package_v2_dir, root / "v2")

            with self.assertRaises(PluginPackageInstallError):
                with unittest.mock.patch.object(Path, "rename", boom_rename):
                    manager.update(package_v2)

            self.assertTrue(install_path.is_dir())
            self.assertEqual(before, marker.read_text(encoding="utf-8"))
            self.assertEqual("1.0.0", manager.get_installed("test.fake_inference").version)
            # No leftover staging/backup directories under the install root.
            leftovers = [
                path
                for path in install_root.iterdir()
                if path.name.startswith(".staging_") or path.name.startswith(".backup_")
            ]
            self.assertEqual([], leftovers)

    def test_uninstall_refuses_path_outside_install_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            install_root = root / "installed"
            manager = PluginPackageManager(install_root=install_root, workspace=workspace)
            package = build_nova_plugin_package(_stage_plugin(root), root / "pkg")
            record = manager.install(package)

            outside = root / "not_managed" / "precious"
            outside.mkdir(parents=True)
            (outside / "keep.txt").write_text("do-not-delete", encoding="utf-8")
            poisoned = record.to_dict()
            poisoned["install_path"] = str(outside)
            workspace.record_installed_plugin(poisoned)

            with self.assertRaises(PluginPackageInstallError) as ctx:
                manager.uninstall("test.fake_inference")
            self.assertEqual("PLUGIN_PACKAGE_UNINSTALL_PATH_UNSAFE", ctx.exception.code)
            self.assertTrue((outside / "keep.txt").is_file())
            # Canonical managed install remains until a safe uninstall succeeds.
            self.assertTrue(Path(record.install_path).is_dir())

    def test_uninstall_only_removes_managed_destination(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            install_root = root / "installed"
            manager = PluginPackageManager(install_root=install_root, workspace=workspace)
            package = build_nova_plugin_package(_stage_plugin(root), root / "pkg")
            record = manager.install(package)
            sibling = install_root / "unrelated_keep"
            sibling.mkdir()
            (sibling / "ok.txt").write_text("keep", encoding="utf-8")

            manager.uninstall("test.fake_inference")
            self.assertFalse(Path(record.install_path).exists())
            self.assertTrue((sibling / "ok.txt").is_file())
            self.assertEqual([], workspace.installed_plugins())
    def test_controller_install_activates_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceManager(root / "workspace.json")
            workspace.load()
            workspace.set_plugin_install_root(root / "installed")
            controller = ObjectWorkflowController(
                workspace=workspace,
                plugins_root=root / "no_dev_plugins",
                enable_batch=False,
            )
            package = build_nova_plugin_package(_stage_plugin(root), root / "pkg")
            record = controller.install_plugin_package(package)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertTrue(
                any(item.plugin_id == record.plugin_id for item in controller.list_plugins())
            )
            self.assertTrue(
                any(
                    item.provider_id == "plugin.test.fake_inference"
                    for item in controller.list_core_inference_providers()
                )
            )
            self.assertTrue(controller.uninstall_plugin_package(record.plugin_id))
            self.assertEqual([], controller.list_installed_plugin_packages())
