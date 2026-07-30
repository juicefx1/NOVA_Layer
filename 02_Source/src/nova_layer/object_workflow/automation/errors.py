from __future__ import annotations

from nova_layer.object_workflow.application.errors import ApplicationError


class AutomationError(ApplicationError):
    """Automation-layer errors (Feature 13). Reuses ApplicationError shape."""


def invalid_command(message: str) -> AutomationError:
    return AutomationError("InvalidCommand", message)


def invalid_state(message: str) -> AutomationError:
    return AutomationError("InvalidState", message)


def permission_denied(message: str) -> AutomationError:
    return AutomationError("PermissionDenied", message)


def operation_failed(message: str, *, code: str = "OperationFailed") -> AutomationError:
    return AutomationError(code, message)


def timeout_error(message: str) -> AutomationError:
    return AutomationError("Timeout", message)


def cancelled_error(message: str = "automation operation cancelled") -> AutomationError:
    return AutomationError("Cancelled", message)
