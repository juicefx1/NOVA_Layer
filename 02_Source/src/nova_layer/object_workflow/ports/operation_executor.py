from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

OperationStatusName = Literal["running", "succeeded", "failed", "cancelled"]
ProgressReporter = Callable[[int, int, str], None]
CancelChecker = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class OperationProgress:
    operation_id: str
    current: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: str
    operation_type: str
    status: OperationStatusName
    progress_current: int
    progress_total: int
    message: str
    error_code: str | None = None
    error_message: str | None = None
    result_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationWorkResult:
    status: Literal["succeeded", "failed", "cancelled"]
    payload: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class OperationWork(Protocol):
    def run(
        self,
        *,
        should_cancel: CancelChecker,
        report_progress: ProgressReporter,
    ) -> OperationWorkResult: ...


class OperationExecutorListener(Protocol):
    def on_progress(self, progress: OperationProgress) -> None: ...

    def on_terminal(self, snapshot: OperationSnapshot) -> None: ...


class OperationExecutor(Protocol):
    def set_listener(self, listener: OperationExecutorListener | None) -> None: ...

    def submit(
        self,
        *,
        operation_id: str,
        operation_type: str,
        work: OperationWork,
    ) -> None: ...

    def cancel(self, operation_id: str) -> bool: ...

    def query(self, operation_id: str) -> OperationSnapshot | None: ...
