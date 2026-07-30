"""Official Plugin SDK for extending NOVA Layer registries without modifying Core."""

from __future__ import annotations

from nova_layer.object_workflow.plugin_sdk.constants import (
    ENV_PLUGINS_DIR,
    SDK_VERSION,
    SUPPORTED_PLUGIN_TYPES,
    SUPPORTED_SDK_VERSIONS,
)
from nova_layer.object_workflow.plugin_sdk.context import PluginRegistrationContext
from nova_layer.object_workflow.plugin_sdk.errors import (
    PluginDependencyError,
    PluginError,
    PluginLoadError,
    PluginRuntimeError,
    PluginValidationError,
)
from nova_layer.object_workflow.plugin_sdk.manager import PluginManager
from nova_layer.object_workflow.plugin_sdk.manifest import PluginManifest, load_manifest
from nova_layer.object_workflow.plugin_sdk.package import (
    ENV_PLUGIN_INSTALL_DIR,
    PACKAGE_EXTENSION,
    PACKAGE_FORMAT_VERSION,
    InstalledPluginRecord,
    PackageValidationResult,
    PluginPackageCompatibilityError,
    PluginPackageError,
    PluginPackageInstallError,
    PluginPackageManager,
    PluginPackageManifest,
    PluginPackageValidationError,
    build_nova_plugin_package,
    default_plugin_install_root,
    validate_plugin_package,
)
from nova_layer.object_workflow.plugin_sdk.types import PluginInfo

__all__ = [
    "ENV_PLUGIN_INSTALL_DIR",
    "ENV_PLUGINS_DIR",
    "PACKAGE_EXTENSION",
    "PACKAGE_FORMAT_VERSION",
    "InstalledPluginRecord",
    "PackageValidationResult",
    "PluginDependencyError",
    "PluginError",
    "PluginInfo",
    "PluginLoadError",
    "PluginManager",
    "PluginManifest",
    "PluginPackageCompatibilityError",
    "PluginPackageError",
    "PluginPackageInstallError",
    "PluginPackageManager",
    "PluginPackageManifest",
    "PluginPackageValidationError",
    "PluginRegistrationContext",
    "PluginRuntimeError",
    "PluginValidationError",
    "SDK_VERSION",
    "SUPPORTED_PLUGIN_TYPES",
    "SUPPORTED_SDK_VERSIONS",
    "build_nova_plugin_package",
    "default_plugin_install_root",
    "load_manifest",
    "validate_plugin_package",
]
