from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.automation.models import (
    ALL_PERMISSIONS,
    AutomationOperation,
    AutomationPermission,
)


@dataclass
class AutomationSession:
    """One automation client. Uses the current Workspace — no hidden sessions."""

    workspace: WorkspaceManager
    session_id: UUID = field(default_factory=uuid4)
    user_context: dict[str, Any] = field(default_factory=dict)
    permissions: frozenset[AutomationPermission] = field(default=ALL_PERMISSIONS)
    active_operations: dict[UUID, AutomationOperation] = field(default_factory=dict)
    closed: bool = False

    def has_permission(self, permission: AutomationPermission) -> bool:
        return permission in self.permissions

    def track(self, operation: AutomationOperation) -> None:
        self.active_operations[operation.operation_id] = operation

    def untrack(self, operation_id: UUID) -> None:
        self.active_operations.pop(operation_id, None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "permissions": sorted(self.permissions),
            "user_context": dict(self.user_context),
            "active_operations": [str(item) for item in self.active_operations],
            "workspace_path": str(self.workspace.path),
            "active_project": self.workspace.active_project(),
            "closed": self.closed,
        }
