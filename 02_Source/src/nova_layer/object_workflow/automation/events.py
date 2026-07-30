from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

AutomationEventType = Literal[
    "OperationStarted",
    "OperationProgress",
    "OperationCompleted",
    "OperationFailed",
    "WorkspaceChanged",
    "ProjectChanged",
    "BatchChanged",
    "PluginChanged",
]

AutomationEventListener = Callable[["AutomationEvent"], None]


@dataclass(frozen=True, slots=True)
class AutomationEvent:
    event_type: AutomationEventType
    session_id: UUID | None = None
    operation_id: UUID | None = None
    command: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "session_id": None if self.session_id is None else str(self.session_id),
            "operation_id": None if self.operation_id is None else str(self.operation_id),
            "command": self.command,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


class AutomationEventBus:
    """In-process observable event bus (no remote transports)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: list[AutomationEventListener] = []

    def subscribe(self, listener: AutomationEventListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: AutomationEventListener) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not listener]

    def publish(self, event: AutomationEvent) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 — isolate listener faults
                pass


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
