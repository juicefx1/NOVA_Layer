from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from nova_layer.object_workflow.adapters.image_codec import decode_rgb_image_bytes
from nova_layer.object_workflow.application.batch_models import (
    BatchConfirmationMode,
    BatchJob,
    BatchQueueItem,
    BatchSelectionPolicy,
    BatchStatistics,
    _utc_now,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.domain.models import IntentInstruction
from nova_layer.object_workflow.domain.validation import (
    IntentValidationError,
    validate_intent_instruction,
)
from nova_layer.object_workflow.runtime.caches import RuntimeCacheBundle

BatchProgressListener = Callable[[BatchJob, BatchQueueItem | None], None]


class BatchManager:
    """Orchestrates the existing single-image workflow across a deterministic queue.

    Confirmation modes:
    - interactive (default): generate candidates, then wait for explicit user
      confirmation via the normal confirm_hypothesis path. Never auto-confirms.
    - automatic (optional): only when enable_automatic_confirmation=True; applies
      selection_policy then calls confirm_hypothesis().
    """

    def __init__(
        self,
        service: ObjectWorkflowService,
        *,
        workspace: WorkspaceManager | None = None,
        runtime_caches: RuntimeCacheBundle | None = None,
        listener: BatchProgressListener | None = None,
    ) -> None:
        self._service = service
        self._workspace = workspace
        self._runtime_caches = runtime_caches
        self._listener = listener
        self._lock = threading.RLock()
        self._job: BatchJob | None = None
        self._cancel_requested = False
        self._running = False
        self._active_operation_id: UUID | None = None
        self._confirm_event = threading.Event()
        self._confirm_event.set()
        self._awaiting_item_id: UUID | None = None
        self._inference_engine_id = service.inference_engine_token
        self._extraction_engine_id = service.extraction_engine_token

    @property
    def service(self) -> ObjectWorkflowService:
        return self._service

    @property
    def runtime_caches(self) -> RuntimeCacheBundle | None:
        return self._runtime_caches

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_awaiting_confirmation(self) -> bool:
        job = self._job
        if job is None:
            return False
        return job.status == "awaiting_confirmation"

    @property
    def inference_engine_id(self) -> str:
        return self._inference_engine_id

    @property
    def extraction_engine_id(self) -> str | None:
        return self._extraction_engine_id

    def current_job(self) -> BatchJob | None:
        return self._job

    def set_listener(self, listener: BatchProgressListener | None) -> None:
        self._listener = listener

    def create_job(
        self,
        image_paths: Sequence[str | Path],
        intent_snapshot: Mapping[str, Any] | IntentInstruction,
        *,
        export_directory: str | Path | None = None,
        host_adapter_id: str | None = None,
        host_action: str | None = None,
        confirmation_mode: BatchConfirmationMode = "interactive",
        enable_automatic_confirmation: bool = False,
        selection_policy: BatchSelectionPolicy = "highest_confidence",
    ) -> BatchJob:
        with self._lock:
            if self._running:
                raise ApplicationError(
                    "BATCH_IN_PROGRESS",
                    "cannot create a new batch while another batch is running",
                )
            paths = [str(Path(path)) for path in image_paths]
            if not paths:
                raise ApplicationError("BATCH_EMPTY", "batch requires at least one image")
            mode = str(confirmation_mode).strip().lower()
            if mode not in {"interactive", "automatic"}:
                raise ApplicationError(
                    "INVALID_BATCH_CONFIRMATION_MODE",
                    f"unsupported confirmation_mode: {confirmation_mode!r}",
                )
            if mode == "automatic" and not enable_automatic_confirmation:
                raise ApplicationError(
                    "AUTOMATIC_CONFIRMATION_NOT_ENABLED",
                    "automatic mode requires enable_automatic_confirmation=True",
                )
            policy = str(selection_policy).strip().lower()
            if policy not in {"highest_confidence", "first_candidate"}:
                raise ApplicationError(
                    "INVALID_BATCH_SELECTION_POLICY",
                    f"unsupported selection_policy: {selection_policy!r}",
                )
            snapshot = _freeze_intent_snapshot(intent_snapshot)
            job = BatchJob(
                image_paths=paths,
                intent_snapshot=snapshot,
                export_directory=(
                    None if export_directory is None else str(Path(export_directory))
                ),
                host_adapter_id=host_adapter_id,
                host_action=host_action,
                confirmation_mode=mode,  # type: ignore[arg-type]
                enable_automatic_confirmation=bool(enable_automatic_confirmation),
                selection_policy=policy,  # type: ignore[arg-type]
            )
            self._job = job
            self._cancel_requested = False
            self._awaiting_item_id = None
            self._confirm_event.set()
            if self._workspace is not None:
                self._workspace.save_batch_queue_metadata(job.queue_metadata())
            return job

    def restore_queue_from_workspace(self) -> BatchJob | None:
        if self._workspace is None:
            return None
        metadata = self._workspace.restore_batch_queue_metadata()
        if metadata is None:
            return None
        items = metadata.get("items") or []
        paths = [str(item.get("image_path", "")) for item in items if item.get("image_path")]
        if not paths:
            return None
        intent = metadata.get("intent_snapshot") or {}
        mode = metadata.get("confirmation_mode", "interactive")
        auto_enabled = bool(metadata.get("enable_automatic_confirmation", False))
        if mode == "automatic" and not auto_enabled:
            mode = "interactive"
            auto_enabled = False
        job = self.create_job(
            paths,
            intent,
            export_directory=metadata.get("export_directory"),
            host_adapter_id=metadata.get("host_adapter_id"),
            host_action=metadata.get("host_action"),
            confirmation_mode=mode,
            enable_automatic_confirmation=auto_enabled,
            selection_policy=metadata.get("selection_policy", "highest_confidence"),
        )
        by_path = {str(item.get("image_path")): item for item in items}
        for queue_item in job.queue:
            meta = by_path.get(queue_item.image_path)
            if not isinstance(meta, dict):
                continue
            status = meta.get("status")
            if status in {"completed", "failed", "cancelled", "skipped"}:
                queue_item.status = status  # type: ignore[assignment]
                queue_item.error_code = meta.get("error_code")
                queue_item.error_message = meta.get("error_message")
            elif status == "awaiting_confirmation":
                queue_item.status = "waiting"
        job.status = "idle"
        return job

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            op_id = self._active_operation_id
            job = self._job
            if job is not None and job.status in {"running", "awaiting_confirmation"}:
                job.append_summary("Cancel requested")
            if op_id is not None:
                try:
                    self._service.cancel_operation(op_id)
                except Exception:  # noqa: BLE001
                    pass
            if job is not None:
                for item in job.queue:
                    if item.status in {"waiting", "awaiting_confirmation"}:
                        item.status = "cancelled"
                        item.error_code = "BATCH_CANCELLED"
                        item.error_message = "cancelled before completion"
                        item.append_log("Cancelled")
            self._confirm_event.set()

    def notify_user_confirmation(self) -> None:
        """Resume interactive batch after the user explicitly confirmed via service API."""
        with self._lock:
            job = self._job
            if job is None or not self._running:
                return
            item = job.current_item()
            if item is None or item.status != "awaiting_confirmation":
                return
            confirmed = self._service.get_active_confirmed_object()
            if confirmed is None:
                raise ApplicationError(
                    "GENERATION_NOT_CONFIRMABLE",
                    "interactive batch resume requires an active ConfirmedObject",
                )
            candidate = self._service.get_active_candidate()
            if candidate is not None:
                item.selected_candidate_id = str(candidate.id)
            item.append_log("User confirmation received")
            job.status = "running"
            self._awaiting_item_id = None
            self._confirm_event.set()

    def retry_failed(self) -> BatchJob:
        return self._retry_statuses({"failed"})

    def retry_cancelled(self) -> BatchJob:
        return self._retry_statuses({"cancelled"})

    def run(self, job: BatchJob | None = None) -> BatchJob:
        with self._lock:
            if self._running:
                raise ApplicationError("BATCH_IN_PROGRESS", "batch already running")
            active = job or self._job
            if active is None:
                raise ApplicationError("NO_BATCH_JOB", "no batch job to run")
            self._job = active
            self._running = True
            self._cancel_requested = False
            active.status = "running"
            active.started_at = active.started_at or _utc_now()
            active.finished_at = None
            active.append_summary(
                f"Batch started ({len(active.queue)} images, "
                f"mode={active.confirmation_mode})"
            )
        try:
            self._run_queue(active)
        finally:
            with self._lock:
                self._running = False
                self._active_operation_id = None
                self._awaiting_item_id = None
                self._confirm_event.set()
                stats = active.statistics()
                if self._cancel_requested or (
                    stats.cancelled and stats.completed + stats.failed < stats.total
                ):
                    active.status = "cancelled"
                elif stats.failed and stats.completed == 0 and stats.waiting == 0:
                    active.status = "failed"
                else:
                    active.status = "completed"
                active.finished_at = _utc_now()
                active.current_item_id = None
                active.append_summary(
                    f"Batch finished · completed={stats.completed} "
                    f"failed={stats.failed} cancelled={stats.cancelled}"
                )
                if self._workspace is not None:
                    self._workspace.record_batch_history(active.to_history_entry())
                    self._workspace.save_batch_queue_metadata(active.queue_metadata())
                if self._runtime_caches is not None:
                    # Drop batch-populated frames after the job ends (keep metrics).
                    self._runtime_caches.images.clear()
                    self._runtime_caches.masks.clear()
                    self._runtime_caches.thumbnails.clear()
                    self._runtime_caches.previews.clear()
                self._emit(active, None)
        return active

    def statistics(self) -> BatchStatistics:
        job = self._job
        if job is None:
            return BatchStatistics()
        return job.statistics()

    def _retry_statuses(self, statuses: set[str]) -> BatchJob:
        with self._lock:
            if self._running:
                raise ApplicationError(
                    "BATCH_IN_PROGRESS",
                    "cannot retry while a batch is running",
                )
            job = self._job
            if job is None:
                raise ApplicationError("NO_BATCH_JOB", "no batch job to retry")
            reset = 0
            for item in job.queue:
                if item.status in statuses:
                    item.status = "waiting"
                    item.error_code = None
                    item.error_message = None
                    item.started_at = None
                    item.finished_at = None
                    item.duration_ms = None
                    item.append_log(f"Queued for retry (was {statuses})")
                    reset += 1
            if reset == 0:
                raise ApplicationError(
                    "NOTHING_TO_RETRY",
                    f"no items with status in {sorted(statuses)}",
                )
            job.status = "idle"
            job.finished_at = None
            job.append_summary(f"Retry queued for {reset} item(s)")
            if self._workspace is not None:
                self._workspace.save_batch_queue_metadata(job.queue_metadata())
            return job

    def _run_queue(self, job: BatchJob) -> None:
        for item in job.queue:
            if self._cancel_requested:
                if item.status == "waiting":
                    item.status = "cancelled"
                    item.error_code = "BATCH_CANCELLED"
                    item.error_message = "cancelled before start"
                    item.append_log("Cancelled (queued)")
                continue
            if item.status != "waiting":
                continue
            self._process_item(job, item)
            if self._service.inference_engine_token != self._inference_engine_id:
                raise ApplicationError(
                    "BATCH_ENGINE_REPLACED",
                    "inference engine identity changed during batch",
                )
            if (
                self._extraction_engine_id is not None
                and self._service.extraction_engine_token != self._extraction_engine_id
            ):
                raise ApplicationError(
                    "BATCH_ENGINE_REPLACED",
                    "extraction engine identity changed during batch",
                )

    def _process_item(self, job: BatchJob, item: BatchQueueItem) -> None:
        job.current_item_id = item.item_id
        item.status = "running"
        item.started_at = _utc_now()
        item.append_log(f"Running {Path(item.image_path).name}")
        self._emit(job, item)
        started = time.perf_counter()
        try:
            if self._cancel_requested:
                raise ApplicationError("CANCELLED", "batch cancelled")
            self._service.create_project(f"batch-{job.job_id.hex[:8]}-{item.item_id.hex[:8]}")
            source = self._service.load_source(item.image_path)
            item.append_log(
                f"Loaded source {source.original_filename} "
                f"({source.width}x{source.height})"
            )
            self._maybe_cache_source(source.relative_asset_path, source.content_fingerprint)
            intent_payload = deepcopy(job.intent_snapshot)
            self._service.create_artist_intent(intent_payload)
            item.append_log("Applied shared ArtistIntent snapshot")

            if self._cancel_requested:
                raise ApplicationError("CANCELLED", "batch cancelled")
            op_id = self._service.start_generate_hypothesis()
            self._active_operation_id = op_id
            snapshot = self._service.wait_operation(op_id)
            self._active_operation_id = None
            if snapshot.status == "cancelled" or self._cancel_requested:
                raise ApplicationError("CANCELLED", snapshot.error_message or "cancelled")
            if snapshot.status == "failed":
                raise ApplicationError(
                    snapshot.error_code or "INFERENCE_FAILED",
                    snapshot.error_message or "hypothesis generation failed",
                )
            candidate_set = self._service.get_active_candidate_set()
            if candidate_set is None or not candidate_set.candidates:
                raise ApplicationError("NO_CANDIDATES", "inference produced no candidates")
            item.append_log(f"Generated {len(candidate_set.candidates)} candidate(s)")

            if job.confirmation_mode == "automatic":
                self._automatic_confirm(job, item, candidate_set)
            else:
                self._wait_for_interactive_confirmation(job, item)

            if self._cancel_requested:
                raise ApplicationError("CANCELLED", "batch cancelled")
            if self._service.get_active_confirmed_object() is None:
                raise ApplicationError(
                    "NO_ACTIVE_CONFIRMED_OBJECT",
                    "extraction requires explicit confirmation",
                )

            extract_id = self._service.start_generate_extraction()
            self._active_operation_id = extract_id
            extract_snapshot = self._service.wait_operation(extract_id)
            self._active_operation_id = None
            if extract_snapshot.status == "cancelled" or self._cancel_requested:
                raise ApplicationError(
                    "CANCELLED",
                    extract_snapshot.error_message or "cancelled",
                )
            if extract_snapshot.status == "failed":
                raise ApplicationError(
                    extract_snapshot.error_code or "EXTRACTION_FAILED",
                    extract_snapshot.error_message or "extraction failed",
                )
            extraction = self._service.get_active_extraction_result()
            if extraction is None:
                raise ApplicationError("EXTRACTION_FAILED", "no active extraction result")
            item.extraction_id = str(extraction.id)
            item.append_log(f"Extracted RGBA asset {extraction.id}")

            if job.export_directory:
                dest_dir = Path(job.export_directory)
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f"{Path(item.image_path).stem}_extraction.png"
                exported = self._service.export_active_extraction(dest)
                item.export_path = str(exported)
                item.append_log(f"Exported {exported}")
                if self._workspace is not None:
                    self._workspace.set_recent_export_directory(dest_dir)

            if job.host_adapter_id and job.host_action:
                self._service.deliver_active_extraction(
                    adapter_id=job.host_adapter_id,
                    action=job.host_action,
                )
                item.append_log(
                    f"Delivered via {job.host_adapter_id}/{job.host_action}"
                )

            item.status = "completed"
            item.append_log("Completed")
        except ApplicationError as exc:
            if exc.code == "CANCELLED" or self._cancel_requested:
                item.status = "cancelled"
                item.error_code = "CANCELLED"
                item.error_message = exc.message
                item.append_log(f"Cancelled: {exc.message}")
            else:
                item.status = "failed"
                item.error_code = exc.code
                item.error_message = exc.message
                item.append_log(f"Failed: {exc.code}: {exc.message}")
        except Exception as exc:  # noqa: BLE001
            item.status = "failed"
            item.error_code = "BATCH_ITEM_FAILED"
            item.error_message = str(exc)
            item.append_log(f"Failed: {exc}")
        finally:
            item.finished_at = _utc_now()
            item.duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self._active_operation_id = None
            if job.status == "awaiting_confirmation":
                job.status = "running"
            self._emit(job, item)

    def _automatic_confirm(self, job: BatchJob, item: BatchQueueItem, candidate_set: Any) -> None:
        if not job.enable_automatic_confirmation:
            raise ApplicationError(
                "AUTOMATIC_CONFIRMATION_NOT_ENABLED",
                "refusing automatic confirm_hypothesis without explicit enable",
            )
        if job.selection_policy == "first_candidate":
            chosen = candidate_set.candidates[0]
        else:
            chosen = max(candidate_set.candidates, key=lambda c: float(c.confidence))
        self._service.select_candidate(chosen.id)
        item.selected_candidate_id = str(chosen.id)
        item.append_log(
            f"Automatic selection ({job.selection_policy}): "
            f"{chosen.id} confidence={float(chosen.confidence):.3f}"
        )
        self._service.confirm_hypothesis()
        item.append_log("Automatic confirmation applied")

    def _wait_for_interactive_confirmation(self, job: BatchJob, item: BatchQueueItem) -> None:
        item.status = "awaiting_confirmation"
        job.status = "awaiting_confirmation"
        item.append_log("Awaiting explicit user confirmation (interactive mode)")
        self._awaiting_item_id = item.item_id
        self._confirm_event.clear()
        self._emit(job, item)
        while not self._confirm_event.wait(timeout=0.05):
            if self._cancel_requested:
                raise ApplicationError("CANCELLED", "batch cancelled while awaiting confirmation")
        if self._cancel_requested:
            raise ApplicationError("CANCELLED", "batch cancelled while awaiting confirmation")
        if self._service.get_active_confirmed_object() is None:
            raise ApplicationError(
                "GENERATION_NOT_CONFIRMABLE",
                "interactive mode requires user confirmation before extraction",
            )
        item.status = "running"
        job.status = "running"

    def _maybe_cache_source(self, relative_path: str, fingerprint: str) -> None:
        caches = self._runtime_caches
        if caches is None:
            return
        caches.monitor.increment("batch_source_seen")
        fingerprint_key = f"fp:{fingerprint}"
        cached = caches.images.get(fingerprint_key)
        if cached is not None:
            caches.monitor.increment("batch_source_cache_hit")
            # Alias under the project-relative path so UI decode can hit without rework.
            caches.images.put(relative_path, cached)
            return
        try:
            payload = self._service.get_asset_bytes(relative_path)
        except ApplicationError:
            return

        def _decode() -> NDArray[np.uint8]:
            width, height, rgb = decode_rgb_image_bytes(payload)
            return (
                np.frombuffer(rgb, dtype=np.uint8)
                .reshape((height, width, 3))
                .copy()
            )

        frame = caches.images.get_or_decode(fingerprint_key, _decode)
        caches.images.put(relative_path, frame)
        caches.monitor.increment("batch_source_cache_store")
    def _emit(self, job: BatchJob, item: BatchQueueItem | None) -> None:
        listener = self._listener
        if listener is not None:
            try:
                listener(job, item)
            except Exception:  # noqa: BLE001
                pass


def _freeze_intent_snapshot(
    intent_snapshot: Mapping[str, Any] | IntentInstruction,
) -> dict[str, Any]:
    try:
        if isinstance(intent_snapshot, IntentInstruction):
            validated = intent_snapshot
        else:
            validated = validate_intent_instruction(dict(intent_snapshot))
    except IntentValidationError as exc:
        raise ApplicationError(exc.code, exc.message) from exc
    return validated.model_dump(by_alias=True)
