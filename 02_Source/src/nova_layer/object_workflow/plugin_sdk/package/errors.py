from __future__ import annotations

from nova_layer.object_workflow.plugin_sdk.errors import PluginError


class PluginPackageError(PluginError):
    """Base class for Feature 12 package failures."""


class PluginPackageValidationError(PluginPackageError):
    def __init__(self, message: str, *, code: str = "PLUGIN_PACKAGE_VALIDATION_ERROR") -> None:
        super().__init__(code, message)


class PluginPackageCompatibilityError(PluginPackageError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "PLUGIN_PACKAGE_INCOMPATIBLE",
    ) -> None:
        super().__init__(code, message)


class PluginPackageInstallError(PluginPackageError):
    def __init__(self, message: str, *, code: str = "PLUGIN_PACKAGE_INSTALL_ERROR") -> None:
        super().__init__(code, message)
