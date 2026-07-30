from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

AutomationPermission = Literal["read", "write", "execute"]
AutomationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

ALL_PERMISSIONS: frozenset[AutomationPermission] = frozenset({"read", "write", "execute"})


@dataclass(frozen=True, slots=True)
class AutomationResult:
    ok: bool
    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "payload": dict(self.payload),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass
class AutomationOperation:
    operation_id: UUID
    session_id: UUID
    command: str
    status: AutomationStatus = "queued"
    progress_current: int = 0
    progress_total: int = 1
    message: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result: AutomationResult | None = None
    workflow_operation_id: UUID | None = None
    created_at: str = field(default_factory=lambda: _utc_now())
    finished_at: str | None = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": str(self.operation_id),
            "session_id": str(self.session_id),
            "command": self.command,
            "status": self.status,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "message": self.message,
            "params": dict(self.params),
            "result": None if self.result is None else self.result.to_dict(),
            "workflow_operation_id": (
                None if self.workflow_operation_id is None else str(self.workflow_operation_id)
            ),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def new_operation_id() -> UUID:
    return uuid4()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
