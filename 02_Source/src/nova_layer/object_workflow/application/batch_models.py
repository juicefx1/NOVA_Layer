from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

BatchItemStatus = Literal[
    "waiting",
    "running",
    "awaiting_confirmation",
    "completed",
    "failed",
    "cancelled",
    "skipped",
]
BatchJobStatus = Literal[
    "idle",
    "running",
    "awaiting_confirmation",
    "completed",
    "cancelled",
    "failed",
]
BatchConfirmationMode = Literal["interactive", "automatic"]
BatchSelectionPolicy = Literal["highest_confidence", "first_candidate"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class BatchQueueItem:
    """One image in the batch queue (runtime-only)."""

    image_path: str
    item_id: UUID = field(default_factory=uuid4)
    status: BatchItemStatus = "waiting"
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None
    selected_candidate_id: str | None = None
    extraction_id: str | None = None
    export_path: str | None = None
    log_lines: list[str] = field(default_factory=list)

    def append_log(self, message: str) -> None:
        stamp = _utc_now().isoformat(timespec="seconds")
        self.log_lines.append(f"[{stamp}] {message}")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "image_path": self.image_path,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "selected_candidate_id": self.selected_candidate_id,
            "extraction_id": self.extraction_id,
            "export_path": self.export_path,
        }


@dataclass(frozen=True, slots=True)
class BatchStatistics:
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    skipped: int = 0
    waiting: int = 0
    running: int = 0
    awaiting_confirmation: int = 0
    remaining: int = 0
    average_time_ms: float | None = None
    eta_ms: float | None = None
    total: int = 0


@dataclass
class BatchJob:
    """Runtime batch orchestration object. Never persisted in Project schema."""

    image_paths: list[str]
    intent_snapshot: dict[str, Any]
    job_id: UUID = field(default_factory=uuid4)
    status: BatchJobStatus = "idle"
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue: list[BatchQueueItem] = field(default_factory=list)
    current_item_id: UUID | None = None
    export_directory: str | None = None
    host_adapter_id: str | None = None
    host_action: str | None = None
    confirmation_mode: BatchConfirmationMode = "interactive"
    enable_automatic_confirmation: bool = False
    selection_policy: BatchSelectionPolicy = "highest_confidence"
    summary_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.queue:
            self.queue = [
                BatchQueueItem(image_path=str(Path(path)))
                for path in self.image_paths
            ]

    def statistics(self) -> BatchStatistics:
        counts = {
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "skipped": 0,
            "waiting": 0,
            "running": 0,
            "awaiting_confirmation": 0,
        }
        durations: list[float] = []
        for item in self.queue:
            counts[item.status] = counts.get(item.status, 0) + 1
            if item.duration_ms is not None and item.status == "completed":
                durations.append(item.duration_ms)
        remaining = counts["waiting"] + counts["running"] + counts["awaiting_confirmation"]
        average = (sum(durations) / len(durations)) if durations else None
        eta = (average * counts["waiting"]) if average is not None else None
        return BatchStatistics(
            completed=counts["completed"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            skipped=counts["skipped"],
            waiting=counts["waiting"],
            running=counts["running"],
            awaiting_confirmation=counts["awaiting_confirmation"],
            remaining=remaining,
            average_time_ms=None if average is None else round(average, 3),
            eta_ms=None if eta is None else round(eta, 3),
            total=len(self.queue),
        )

    def current_item(self) -> BatchQueueItem | None:
        if self.current_item_id is None:
            return None
        for item in self.queue:
            if item.item_id == self.current_item_id:
                return item
        return None

    def failure_summary(self) -> list[str]:
        lines: list[str] = []
        for item in self.queue:
            if item.status in {"failed", "cancelled"}:
                reason = item.error_message or item.error_code or item.status
                lines.append(f"{Path(item.image_path).name}: {reason}")
        return lines

    def append_summary(self, message: str) -> None:
        stamp = _utc_now().isoformat(timespec="seconds")
        self.summary_lines.append(f"[{stamp}] {message}")

    def to_history_entry(self) -> dict[str, Any]:
        stats = self.statistics()
        return {
            "job_id": str(self.job_id),
            "created_at": self.created_at.isoformat(),
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "status": self.status,
            "confirmation_mode": self.confirmation_mode,
            "enable_automatic_confirmation": self.enable_automatic_confirmation,
            "selection_policy": self.selection_policy,
            "image_count": len(self.queue),
            "completed": stats.completed,
            "failed": stats.failed,
            "cancelled": stats.cancelled,
            "skipped": stats.skipped,
            "average_time_ms": stats.average_time_ms,
            "export_directory": self.export_directory,
            "queue_metadata": [item.to_metadata() for item in self.queue],
            "failure_summary": self.failure_summary(),
        }

    def queue_metadata(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "status": self.status,
            "intent_snapshot": dict(self.intent_snapshot),
            "export_directory": self.export_directory,
            "host_adapter_id": self.host_adapter_id,
            "host_action": self.host_action,
            "confirmation_mode": self.confirmation_mode,
            "enable_automatic_confirmation": self.enable_automatic_confirmation,
            "selection_policy": self.selection_policy,
            "items": [
                {
                    "item_id": str(item.item_id),
                    "image_path": item.image_path,
                    "status": (
                        item.status
                        if item.status
                        in {
                            "waiting",
                            "failed",
                            "cancelled",
                            "skipped",
                            "completed",
                            "awaiting_confirmation",
                        }
                        else "waiting"
                    ),
                }
                for item in self.queue
            ],
        }
