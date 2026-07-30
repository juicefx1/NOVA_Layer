from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.automation.errors import (
    AutomationError,
    cancelled_error,
    invalid_state,
    operation_failed,
    permission_denied,
    timeout_error,
)
from nova_layer.object_workflow.automation.events import (
    AutomationEvent,
    AutomationEventBus,
    AutomationEventListener,
)
from nova_layer.object_workflow.automation.handlers import BuiltinCommandHandlers
from nova_layer.object_workflow.automation.models import (
    ALL_PERMISSIONS,
    AutomationOperation,
    AutomationPermission,
    AutomationResult,
    new_operation_id,
)
from nova_layer.object_workflow.automation.models import _utc_now as utc_now
from nova_layer.object_workflow.automation.registry import AutomationCommandRegistry
from nova_layer.object_workflow.automation.session import AutomationSession
from nova_layer.object_workflow.plugin_sdk.manager import PluginManager
from nova_layer.object_workflow.ports.operation_executor import (
    OperationProgress,
    OperationSnapshot,
)

_CURRENT_OPERATION: ContextVar[AutomationOperation | None] = ContextVar(
    "nova_automation_operation",
    default=None,
)

# Bound completed automation operation history (runtime-only).
_MAX_RETAINED_OPERATIONS = 64


def bind_workflow_operation(operation_id: UUID) -> None:
    """Allow builtin handlers to attach the underlying OperationExecutor id."""
    current = _CURRENT_OPERATION.get()
    if current is not None:
        current.workflow_operation_id = operation_id



class AutomationService:
    """Feature 13 orchestration layer over existing workflow services.

    Commands map 1:1 to existing user actions. Async commands reuse OperationExecutor
    through ObjectWorkflowService.start_*/wait_operation. No HTTP/REST/WebSocket.
    """

    def __init__(
        self,
        workflow: ObjectWorkflowService,
        *,
        workspace: WorkspaceManager | None = None,
        batch_manager: BatchManager | None = None,
        plugin_manager: PluginManager | None = None,
        max_workers: int = 4,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        self._workflow = workflow
        self._workspace = workspace or WorkspaceManager.shared()
        if not getattr(self._workspace, "_loaded", False):
            self._workspace.load()
        self._batch = batch_manager
        self._plugin_manager = plugin_manager
        self._events = AutomationEventBus()
        self._registry = AutomationCommandRegistry(events=self._events)
        self._handlers = BuiltinCommandHandlers(
            workflow,
            batch_manager=batch_manager,
            events=self._events,
            default_operation_timeout=default_timeout_seconds,
        )
        for name, handler in self._handlers.bind().items():
            self._registry.register_builtin(name, handler)

        self._sessions: dict[UUID, AutomationSession] = {}
        self._operations: dict[UUID, AutomationOperation] = {}
        self._futures: dict[UUID, Future[AutomationResult]] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="nova-auto")
        self._default_timeout = default_timeout_seconds
        self._helpers: dict[str, dict[str, Any]] = {}

        # Bridge OperationExecutor progress into Automation events.
        self._workflow.add_operation_event_handler(self._on_workflow_operation_event)

        if plugin_manager is not None:
            self.bind_plugin_manager(plugin_manager)

    @property
    def workspace(self) -> WorkspaceManager:
        return self._workspace

    @property
    def workflow(self) -> ObjectWorkflowService:
        return self._workflow

    @property
    def events(self) -> AutomationEventBus:
        return self._events

    @property
    def command_registry(self) -> AutomationCommandRegistry:
        return self._registry

    @property
    def plugin_manager(self) -> PluginManager | None:
        return self._plugin_manager

    def bind_plugin_manager(self, plugin_manager: PluginManager) -> None:
        """Integrate PluginManager so plugins may register commands / helpers."""
        self._plugin_manager = plugin_manager
        plugin_manager.set_automation_registry(self._registry)
        plugin_manager.set_automation_event_bus(self._events)
        self._events.publish(
            AutomationEvent(
                event_type="PluginChanged",
                payload={
                    "action": "automation_bound",
                    "plugin_count": len(plugin_manager.list_plugins()),
                },
            )
        )

    def register_helper(self, plugin_id: str, name: str, payload: Mapping[str, Any]) -> None:
        key = f"{plugin_id}.{name}"
        self._helpers[key] = dict(payload)
        self._events.publish(
            AutomationEvent(
                event_type="PluginChanged",
                payload={"action": "register_helper", "helper": key},
            )
        )

    def list_helpers(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._helpers.items()}

    def create_session(
        self,
        *,
        permissions: Sequence[AutomationPermission] | None = None,
        user_context: Mapping[str, Any] | None = None,
    ) -> AutomationSession:
        perms = (
            ALL_PERMISSIONS
            if permissions is None
            else frozenset(permissions)  # type: ignore[arg-type]
        )
        session = AutomationSession(
            workspace=self._workspace,
            permissions=perms,
            user_context=dict(user_context or {}),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: UUID | str) -> AutomationSession | None:
        key = UUID(str(session_id))
        with self._lock:
            return self._sessions.get(key)

    def close_session(self, session_id: UUID | str) -> None:
        key = UUID(str(session_id))
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return
            session.closed = True
            for operation in list(session.active_operations.values()):
                if operation.status in {"queued", "running"}:
                    self.cancel(operation.operation_id)
            self._sessions.pop(key, None)

    def subscribe(self, listener: AutomationEventListener) -> None:
        self._events.subscribe(listener)

    def unsubscribe(self, listener: AutomationEventListener) -> None:
        self._events.unsubscribe(listener)

    def list_commands(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "permission": spec.permission,
                "description": spec.description,
                "builtin": spec.builtin,
                "plugin_id": spec.plugin_id,
            }
            for spec in self._registry.list_commands()
        ]

    def submit(
        self,
        session_id: UUID | str,
        command: str,
        params: Mapping[str, Any] | None = None,
    ) -> AutomationOperation:
        """Validate + queue command on a worker thread (never blocks the UI thread)."""
        session = self._require_session(session_id)
        if session.closed:
            raise invalid_state("automation session is closed")
        spec = self._registry.get_spec(command)
        if not session.has_permission(spec.permission):
            raise permission_denied(
                f"session lacks {spec.permission!r} permission for command {command!r}"
            )
        operation = AutomationOperation(
            operation_id=new_operation_id(),
            session_id=session.session_id,
            command=command,
            status="queued",
            params=dict(params or {}),
            message="queued",
        )
        with self._lock:
            self._operations[operation.operation_id] = operation
            session.track(operation)
            future = self._pool.submit(self._run_operation, operation.operation_id)
            self._futures[operation.operation_id] = future
        return operation

    def execute(
        self,
        session_id: UUID | str,
        command: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> AutomationResult:
        operation = self.submit(session_id, command, params)
        return self.wait(operation.operation_id, timeout_seconds=timeout_seconds)

    def wait(
        self,
        operation_id: UUID | str,
        *,
        timeout_seconds: float | None = None,
    ) -> AutomationResult:
        key = UUID(str(operation_id))
        with self._lock:
            future = self._futures.get(key)
            operation = self._operations.get(key)
        if future is None or operation is None:
            raise invalid_state(f"unknown automation operation: {operation_id}")
        timeout = self._default_timeout if timeout_seconds is None else timeout_seconds
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            self.cancel(key)
            raise timeout_error(
                f"automation operation timed out after {timeout}s"
            ) from exc

    def cancel(self, operation_id: UUID | str) -> bool:
        key = UUID(str(operation_id))
        with self._lock:
            operation = self._operations.get(key)
            future = self._futures.get(key)
        if operation is None:
            return False
        if operation.status in {"completed", "failed", "cancelled"}:
            return False
        operation.cancel_requested = True
        if operation.workflow_operation_id is not None:
            self._workflow.cancel_operation(operation.workflow_operation_id)
        self._handlers.request_cancel(str(operation.workflow_operation_id or key))
        if self._batch is not None and operation.command == "batch_execute":
            self._batch.cancel()
        future_cancelled = False
        if future is not None and not future.done():
            future_cancelled = future.cancel()
        # Only the worker may write a terminal status once the job is running,
        # except when the future was cancelled before it started.
        if future_cancelled or operation.status == "queued":
            operation.status = "cancelled"
            operation.message = "cancelled"
            operation.finished_at = operation.finished_at or utc_now()
            operation.result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code="Cancelled",
                error_message="automation operation cancelled",
            )
            self._events.publish(
                AutomationEvent(
                    event_type="OperationFailed",
                    session_id=operation.session_id,
                    operation_id=operation.operation_id,
                    command=operation.command,
                    payload={"status": "cancelled"},
                )
            )
            with self._lock:
                self._futures.pop(key, None)
                self._prune_operations_locked()
        return True

    def query(self, operation_id: UUID | str) -> AutomationOperation | None:
        key = UUID(str(operation_id))
        with self._lock:
            operation = self._operations.get(key)
            return None if operation is None else operation

    def shutdown(self) -> None:
        with self._lock:
            for operation_id in list(self._operations):
                self.cancel(operation_id)
            self._sessions.clear()
            self._operations.clear()
            self._futures.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _prune_operations_locked(self) -> None:
        terminal = [
            op_id
            for op_id, op in self._operations.items()
            if op.status in {"completed", "failed", "cancelled"}
        ]
        if len(terminal) <= _MAX_RETAINED_OPERATIONS:
            return
        # Drop oldest finished operations beyond the retention bound.
        terminal_sorted = sorted(
            terminal,
            key=lambda op_id: self._operations[op_id].finished_at
            or self._operations[op_id].created_at,
        )
        overflow = len(terminal_sorted) - _MAX_RETAINED_OPERATIONS
        for op_id in terminal_sorted[:overflow]:
            self._operations.pop(op_id, None)
            self._futures.pop(op_id, None)

    def _run_operation(self, operation_id: UUID) -> AutomationResult:
        with self._lock:
            operation = self._operations[operation_id]
            session = self._sessions.get(operation.session_id)
        if session is None or session.closed:
            result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code="InvalidState",
                error_message="session closed",
            )
            operation.status = "failed"
            operation.result = result
            return result

        if operation.cancel_requested:
            result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code="Cancelled",
                error_message="automation operation cancelled",
            )
            operation.status = "cancelled"
            operation.message = "cancelled"
            operation.result = result
            operation.finished_at = utc_now()
            return result

        operation.status = "running"
        operation.message = "running"
        self._events.publish(
            AutomationEvent(
                event_type="OperationStarted",
                session_id=session.session_id,
                operation_id=operation.operation_id,
                command=operation.command,
                payload={"params": dict(operation.params)},
            )
        )
        try:
            if operation.cancel_requested:
                raise cancelled_error()
            token = _CURRENT_OPERATION.set(operation)
            try:
                payload = self._registry.dispatch(session, operation.command, operation.params)
            finally:
                _CURRENT_OPERATION.reset(token)
            if operation.cancel_requested:
                raise cancelled_error()
            result = AutomationResult(ok=True, command=operation.command, payload=payload)
            operation.status = "completed"
            operation.progress_current = operation.progress_total
            operation.message = "completed"
            operation.result = result
            operation.finished_at = utc_now()
            self._events.publish(
                AutomationEvent(
                    event_type="OperationCompleted",
                    session_id=session.session_id,
                    operation_id=operation.operation_id,
                    command=operation.command,
                    payload=payload,
                )
            )
            return result
        except AutomationError as exc:
            result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code=exc.code,
                error_message=exc.message,
            )
            operation.status = "cancelled" if exc.code == "Cancelled" else "failed"
            operation.message = exc.message
            operation.result = result
            operation.finished_at = utc_now()
            self._events.publish(
                AutomationEvent(
                    event_type="OperationFailed",
                    session_id=session.session_id,
                    operation_id=operation.operation_id,
                    command=operation.command,
                    payload={"error_code": exc.code, "error_message": exc.message},
                )
            )
            return result
        except ApplicationError as exc:
            mapped = operation_failed(f"{exc.code}: {exc.message}", code=exc.code)
            result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code=mapped.code,
                error_message=mapped.message,
            )
            operation.status = "failed"
            operation.message = mapped.message
            operation.result = result
            operation.finished_at = utc_now()
            self._events.publish(
                AutomationEvent(
                    event_type="OperationFailed",
                    session_id=session.session_id,
                    operation_id=operation.operation_id,
                    command=operation.command,
                    payload={"error_code": mapped.code, "error_message": mapped.message},
                )
            )
            return result
        except Exception as exc:  # noqa: BLE001
            result = AutomationResult(
                ok=False,
                command=operation.command,
                error_code="OperationFailed",
                error_message=str(exc),
            )
            operation.status = "failed"
            operation.message = str(exc)
            operation.result = result
            operation.finished_at = utc_now()
            self._events.publish(
                AutomationEvent(
                    event_type="OperationFailed",
                    session_id=session.session_id,
                    operation_id=operation.operation_id,
                    command=operation.command,
                    payload={"error_code": "OperationFailed", "error_message": str(exc)},
                )
            )
            return result
        finally:
            with self._lock:
                session.untrack(operation_id)
                self._futures.pop(operation_id, None)
                self._prune_operations_locked()

    def _require_session(self, session_id: UUID | str) -> AutomationSession:
        session = self.get_session(session_id)
        if session is None:
            raise invalid_state(f"unknown automation session: {session_id}")
        return session

    def _on_workflow_operation_event(
        self,
        event: OperationProgress | OperationSnapshot,
    ) -> None:
        if isinstance(event, OperationProgress):
            self._events.publish(
                AutomationEvent(
                    event_type="OperationProgress",
                    payload={
                        "workflow_operation_id": event.operation_id,
                        "current": event.current,
                        "total": event.total,
                        "message": event.message,
                    },
                )
            )
            return
        self._events.publish(
            AutomationEvent(
                event_type="OperationProgress",
                payload={
                    "workflow_operation_id": event.operation_id,
                    "status": event.status,
                    "current": event.progress_current,
                    "total": event.progress_total,
                    "message": event.message,
                    "error_code": event.error_code,
                },
            )
        )
