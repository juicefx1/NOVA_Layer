from __future__ import annotations


class PluginError(Exception):
    """Base class for Plugin SDK failures (isolated from Core exceptions)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PluginValidationError(PluginError):
    def __init__(self, message: str, *, code: str = "PLUGIN_VALIDATION_ERROR") -> None:
        super().__init__(code, message)


class PluginLoadError(PluginError):
    def __init__(self, message: str, *, code: str = "PLUGIN_LOAD_ERROR") -> None:
        super().__init__(code, message)


class PluginRuntimeError(PluginError):
    def __init__(self, message: str, *, code: str = "PLUGIN_RUNTIME_ERROR") -> None:
        super().__init__(code, message)


class PluginDependencyError(PluginError):
    def __init__(self, message: str, *, code: str = "PLUGIN_DEPENDENCY_ERROR") -> None:
        super().__init__(code, message)
