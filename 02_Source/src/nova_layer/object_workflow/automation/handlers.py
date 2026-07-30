"""Builtin automation command handlers — thin wrappers over existing services."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.automation.errors import (
    cancelled_error,
    invalid_command,
    invalid_state,
    operation_failed,
    timeout_error,
)
from nova_layer.object_workflow.automation.events import AutomationEvent, AutomationEventBus
from nova_layer.object_workflow.automation.session import AutomationSession
from nova_layer.object_workflow.ports.operation_executor import OperationSnapshot


def _bind_workflow_operation(operation_id: UUID) -> None:
    # Late import avoids circular dependency with AutomationService.
    from nova_layer.object_workflow.automation.service import bind_workflow_operation

    bind_workflow_operation(operation_id)


class BuiltinCommandHandlers:
    def __init__(
        self,
        workflow: ObjectWorkflowService,
        *,
        batch_manager: BatchManager | None = None,
        events: AutomationEventBus | None = None,
        default_operation_timeout: float = 60.0,
    ) -> None:
        self._workflow = workflow
        self._batch = batch_manager
        self._events = events
        self._default_timeout = default_operation_timeout
        self._cancel_flags: dict[str, bool] = {}

    def bind(self) -> dict[str, Any]:
        return {
            "open_project": self.open_project,
            "load_image": self.load_image,
            "create_artist_intent": self.create_artist_intent,
            "generate_candidates": self.generate_candidates,
            "select_candidate": self.select_candidate,
            "confirm_candidate": self.confirm_candidate,
            "generate_extraction": self.generate_extraction,
            "export_layer": self.export_layer,
            "save_project": self.save_project,
            "close_project": self.close_project,
            "batch_execute": self.batch_execute,
        }

    def request_cancel(self, operation_key: str) -> None:
        self._cancel_flags[operation_key] = True

    def open_project(self, session: AutomationSession, params: Mapping[str, Any]) -> dict[str, Any]:
        path = _require_path(params, "package_path")
        project = self._workflow.load_project(path)
        session.workspace.set_active_project(path)
        self._emit_project_changed(session, action="open", package_path=str(path))
        self._emit_workspace_changed(session)
        return {
            "project_id": str(project.id),
            "name": project.name,
            "package_path": str(path),
            "summary": self._workflow.get_project_summary(),
        }

    def load_image(self, session: AutomationSession, params: Mapping[str, Any]) -> dict[str, Any]:
        _ = session
        path = _require_path(params, "path", aliases=("image_path",))
        if self._workflow.project is None:
            self._workflow.create_project(str(params.get("project_name") or "Automation"))
        source = self._workflow.load_source(path)
        self._emit_project_changed(session, action="load_image", source_id=str(source.id))
        return {
            "source_image_id": str(source.id),
            "original_filename": source.original_filename,
            "width": source.width,
            "height": source.height,
        }

    def create_artist_intent(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        _ = session
        instruction = params.get("intent") or params.get("instruction") or params
        if not isinstance(instruction, Mapping):
            raise invalid_command("create_artist_intent requires intent/instruction mapping")
        # Accept either full intent document or payload-only for convenience.
        payload = dict(instruction)
        if "schema" not in payload and "payload" not in payload:
            payload = {
                "schema": "nova.intent.guidance.v1",
                "payload": {"signals": list(instruction.get("signals", []))},
            }
        intent = self._workflow.create_artist_intent(payload)
        self._emit_project_changed(session, action="create_artist_intent", intent_id=str(intent.id))
        return {
            "intent_id": str(intent.id),
            "revision": intent.revision,
        }

    def generate_candidates(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        timeout = float(params.get("timeout_seconds", self._default_timeout))
        op_id = self._workflow.start_generate_hypothesis()
        _bind_workflow_operation(op_id)
        snapshot = self._wait_workflow_operation(
            session,
            op_id,
            command="generate_candidates",
            timeout_seconds=timeout,
        )
        candidate_set = self._workflow.get_active_candidate_set()
        if candidate_set is None:
            raise operation_failed("generate_candidates produced no candidate set")
        return {
            "workflow_operation_id": str(op_id),
            "candidate_set_id": str(candidate_set.id),
            "candidate_ids": [str(item.id) for item in candidate_set.candidates],
            "operation_status": snapshot.status,
        }

    def select_candidate(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        _ = session
        raw = params.get("candidate_id")
        if raw is None:
            raise invalid_command("select_candidate requires candidate_id")
        hypothesis = self._workflow.select_candidate(str(raw))
        self._emit_project_changed(
            session,
            action="select_candidate",
            hypothesis_id=str(hypothesis.id),
        )
        return {
            "hypothesis_id": str(hypothesis.id),
            "candidate_id": str(raw),
        }

    def confirm_candidate(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        _ = params
        hypothesis_id = params.get("hypothesis_id")
        confirmed = self._workflow.confirm_hypothesis(
            None if hypothesis_id is None else UUID(str(hypothesis_id))
        )
        if self._batch is not None and self._batch.is_awaiting_confirmation:
            self._batch.notify_user_confirmation()
        self._emit_project_changed(
            session,
            action="confirm_candidate",
            confirmed_object_id=str(confirmed.id),
        )
        return {
            "confirmed_object_id": str(confirmed.id),
            "revision": confirmed.revision,
        }

    def generate_extraction(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        timeout = float(params.get("timeout_seconds", self._default_timeout))
        settings = params.get("settings")
        op_id = self._workflow.start_generate_extraction(
            settings if isinstance(settings, Mapping) else None
        )
        _bind_workflow_operation(op_id)
        snapshot = self._wait_workflow_operation(
            session,
            op_id,
            command="generate_extraction",
            timeout_seconds=timeout,
        )
        extraction = self._workflow.get_active_extraction_result()
        if extraction is None:
            raise operation_failed("generate_extraction produced no extraction result")
        return {
            "workflow_operation_id": str(op_id),
            "extraction_id": str(extraction.id),
            "confidence": float(extraction.confidence),
            "operation_status": snapshot.status,
        }

    def export_layer(self, session: AutomationSession, params: Mapping[str, Any]) -> dict[str, Any]:
        destination = _require_path(params, "destination", aliases=("path", "export_path"))
        allow_overwrite = bool(params.get("allow_overwrite", False))
        delivered = self._workflow.export_active_extraction(
            destination,
            allow_overwrite=allow_overwrite,
        )
        session.workspace.set_recent_export_directory(Path(destination).parent)
        self._emit_project_changed(session, action="export_layer", destination=str(destination))
        return {
            "destination": str(destination),
            "adapter_id": delivered.adapter_id,
            "action": delivered.action,
        }

    def save_project(self, session: AutomationSession, params: Mapping[str, Any]) -> dict[str, Any]:
        path = _require_path(params, "package_path")
        saved = self._workflow.save_project(path)
        session.workspace.set_active_project(saved)
        self._emit_project_changed(session, action="save", package_path=str(saved))
        self._emit_workspace_changed(session)
        return {"package_path": str(saved)}

    def close_project(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        name = str(params.get("project_name") or "Untitled")
        # Equivalent to the UI "new/empty project" action after closing.
        project = self._workflow.create_project(name)
        session.workspace.set_active_project(None)
        self._emit_project_changed(session, action="close", project_id=str(project.id))
        self._emit_workspace_changed(session)
        return {"project_id": str(project.id), "name": project.name, "closed": True}

    def batch_execute(
        self,
        session: AutomationSession,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self._batch is None:
            raise invalid_state("batch manager is not configured for automation")
        paths = params.get("image_paths") or params.get("images")
        if not isinstance(paths, (list, tuple)) or not paths:
            raise invalid_command("batch_execute requires non-empty image_paths")
        intent = params.get("intent") or params.get("intent_snapshot")
        if not isinstance(intent, Mapping):
            raise invalid_command("batch_execute requires intent / intent_snapshot")
        mode = str(params.get("confirmation_mode") or "automatic").strip().lower()
        auto_enabled = bool(
            params.get(
                "enable_automatic_confirmation",
                mode == "automatic",
            )
        )
        job = self._batch.create_job(
            [Path(item) for item in paths],
            dict(intent),
            export_directory=params.get("export_directory"),
            host_adapter_id=params.get("host_adapter_id"),
            host_action=params.get("host_action"),
            confirmation_mode=mode,  # type: ignore[arg-type]
            enable_automatic_confirmation=auto_enabled,
            selection_policy=str(params.get("selection_policy") or "highest_confidence"),  # type: ignore[arg-type]
        )
        if self._events is not None:
            self._events.publish(
                AutomationEvent(
                    event_type="BatchChanged",
                    session_id=session.session_id,
                    command="batch_execute",
                    payload={"action": "started", "job_id": job.job_id, "count": len(job.queue)},
                )
            )
        finished = self._batch.run(job)
        stats = finished.statistics()
        if self._events is not None:
            self._events.publish(
                AutomationEvent(
                    event_type="BatchChanged",
                    session_id=session.session_id,
                    command="batch_execute",
                    payload={
                        "action": "finished",
                        "job_id": finished.job_id,
                        "status": finished.status,
                        "completed": stats.completed,
                        "failed": stats.failed,
                        "cancelled": stats.cancelled,
                    },
                )
            )
        return {
            "job_id": finished.job_id,
            "status": finished.status,
            "statistics": {
                "completed": stats.completed,
                "failed": stats.failed,
                "cancelled": stats.cancelled,
                "total": stats.total,
            },
        }

    def _wait_workflow_operation(
        self,
        session: AutomationSession,
        operation_id: UUID,
        *,
        command: str,
        timeout_seconds: float,
    ) -> OperationSnapshot:
        key = str(operation_id)
        self._cancel_flags.pop(key, None)
        try:
            snapshot = self._workflow.wait_operation(
                operation_id,
                timeout_seconds=timeout_seconds,
            )
        except ApplicationError as exc:
            if exc.code == "OPERATION_TIMEOUT":
                raise timeout_error(exc.message) from exc
            if exc.code == "CANCELLED":
                raise cancelled_error(exc.message) from exc
            raise operation_failed(f"{exc.code}: {exc.message}", code=exc.code) from exc

        if self._cancel_flags.pop(key, False):
            self._workflow.cancel_operation(operation_id)
            raise cancelled_error()

        if snapshot.status == "cancelled":
            raise cancelled_error(snapshot.error_message or "operation cancelled")
        if snapshot.status == "failed":
            raise operation_failed(
                snapshot.error_message or "operation failed",
                code=snapshot.error_code or "OperationFailed",
            )
        _ = session, command
        return snapshot

    def _emit_project_changed(self, session: AutomationSession, **payload: Any) -> None:
        if self._events is None:
            return
        self._events.publish(
            AutomationEvent(
                event_type="ProjectChanged",
                session_id=session.session_id,
                payload=dict(payload),
            )
        )

    def _emit_workspace_changed(self, session: AutomationSession) -> None:
        if self._events is None:
            return
        self._events.publish(
            AutomationEvent(
                event_type="WorkspaceChanged",
                session_id=session.session_id,
                payload={
                    "active_project": session.workspace.active_project(),
                    "workspace_path": str(session.workspace.path),
                },
            )
        )


def _require_path(params: Mapping[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> Path:
    raw = params.get(key)
    if raw is None:
        for alias in aliases:
            raw = params.get(alias)
            if raw is not None:
                break
    if raw is None or str(raw).strip() == "":
        names = ", ".join((key, *aliases))
        raise invalid_command(f"missing required path parameter ({names})")
    return Path(str(raw))
