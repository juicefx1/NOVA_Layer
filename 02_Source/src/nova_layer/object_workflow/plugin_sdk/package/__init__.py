"""Local .nova-plugin package format (Product Feature 12).

Install/uninstall/update operate on local archives only.
No marketplace, no remote downloads.
"""

from __future__ import annotations

from nova_layer.object_workflow.plugin_sdk.package.constants import (
    ENV_PLUGIN_INSTALL_DIR,
    PACKAGE_EXTENSION,
    PACKAGE_FORMAT_VERSION,
    PACKAGE_MANIFEST_FILENAME,
    SUPPORTED_PACKAGE_FORMATS,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import (
    PluginPackageCompatibilityError,
    PluginPackageError,
    PluginPackageInstallError,
    PluginPackageValidationError,
)
from nova_layer.object_workflow.plugin_sdk.package.manager import PluginPackageManager
from nova_layer.object_workflow.plugin_sdk.package.models import (
    InstalledPluginRecord,
    PackageCompatibilityReport,
    PackageValidationResult,
    PluginPackageManifest,
)
from nova_layer.object_workflow.plugin_sdk.package.packaging import build_nova_plugin_package
from nova_layer.object_workflow.plugin_sdk.package.paths import default_plugin_install_root
from nova_layer.object_workflow.plugin_sdk.package.validation import (
    check_package_compatibility,
    validate_plugin_package,
)

__all__ = [
    "ENV_PLUGIN_INSTALL_DIR",
    "PACKAGE_EXTENSION",
    "PACKAGE_FORMAT_VERSION",
    "PACKAGE_MANIFEST_FILENAME",
    "SUPPORTED_PACKAGE_FORMATS",
    "InstalledPluginRecord",
    "PackageCompatibilityReport",
    "PackageValidationResult",
    "PluginPackageCompatibilityError",
    "PluginPackageError",
    "PluginPackageInstallError",
    "PluginPackageManager",
    "PluginPackageManifest",
    "PluginPackageValidationError",
    "build_nova_plugin_package",
    "check_package_compatibility",
    "default_plugin_install_root",
    "validate_plugin_package",
]
