"""Feature 13 — Automation API (transport-independent orchestration).

Reuses ObjectWorkflowService, OperationExecutor, BatchManager, WorkspaceManager,
and PluginManager. Never duplicates Domain workflow logic.
"""

from __future__ import annotations

from nova_layer.object_workflow.automation.commands import BUILTIN_COMMANDS, AutomationCommandName
from nova_layer.object_workflow.automation.errors import AutomationError
from nova_layer.object_workflow.automation.events import (
    AutomationEvent,
    AutomationEventBus,
    AutomationEventType,
)
from nova_layer.object_workflow.automation.models import (
    AutomationOperation,
    AutomationPermission,
    AutomationResult,
    AutomationStatus,
)
from nova_layer.object_workflow.automation.registry import AutomationCommandRegistry
from nova_layer.object_workflow.automation.service import AutomationService
from nova_layer.object_workflow.automation.session import AutomationSession

__all__ = [
    "BUILTIN_COMMANDS",
    "AutomationCommandName",
    "AutomationCommandRegistry",
    "AutomationError",
    "AutomationEvent",
    "AutomationEventBus",
    "AutomationEventType",
    "AutomationOperation",
    "AutomationPermission",
    "AutomationResult",
    "AutomationService",
    "AutomationSession",
    "AutomationStatus",
]
