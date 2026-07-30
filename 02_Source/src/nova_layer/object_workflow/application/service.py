from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid4

from nova_layer.object_workflow.adapters.host_adapter_registry import (
    HostAdapterRegistry,
    build_default_host_adapter_registry,
)
from nova_layer.object_workflow.adapters.host_asset_validation import ValidatedExtractionAsset
from nova_layer.object_workflow.adapters.image_codec import decode_rgb_image_bytes, write_rgba_png
from nova_layer.object_workflow.adapters.mask_io import (
    read_binary_mask_png_bytes,
    write_binary_mask_png,
)
from nova_layer.object_workflow.adapters.mock_operation_executor import MockOperationExecutor
from nova_layer.object_workflow.adapters.source_probe import (
    SourceProbeError,
    extension_is_supported,
    probe_source_bytes,
)
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.host_delivery import (
    DeliverySummary,
    adapter_actions,
    build_host_delivery_request,
    delivery_binding_metadata,
    format_delivery_summary,
    materialize_asset_under_workspace,
    resolve_reference_text,
    suggested_filename_for_extraction,
    validate_committed_extraction_asset,
)
from nova_layer.object_workflow.domain.binary_mask import BinaryMask
from nova_layer.object_workflow.domain.generation import (
    append_generation_status_record,
    latest_candidate_set_for_generation,
    latest_generation_record,
    migrate_project_generation_history,
    next_sequence_number,
    ordered_generations,
)
from nova_layer.object_workflow.domain.models import (
    ArtistIntent,
    BoundingBox,
    ConfirmationRecord,
    ConfirmedObject,
    ExtractionResult,
    ExtractionSettings,
    GenerationRecord,
    HypothesisCandidate,
    HypothesisCandidateSet,
    IntentInstruction,
    NegativePoint,
    ObjectHypothesis,
    OperationRecord,
    OperationStatus,
    PositivePoint,
    Project,
    SourceImage,
    utc_now,
)
from nova_layer.object_workflow.domain.validation import (
    IntentValidationError,
    instruction_signal_fingerprint,
    parse_intent_signals,
    validate_intent_instruction,
)
from nova_layer.object_workflow.domain.workflow import apply_derived_workflow_state
from nova_layer.object_workflow.ports.core_inference import (
    CandidateResult,
    CoreInferenceEngine,
    CoreInferenceError,
    CoreInferenceRequest,
)
from nova_layer.object_workflow.ports.host_delivery import (
    ClipboardWriter,
    HostAdapterDescriptor,
    HostDeliverySuccess,
    ProcessLauncher,
    ReferenceType,
)
from nova_layer.object_workflow.ports.operation_executor import (
    CancelChecker,
    OperationExecutor,
    OperationProgress,
    OperationSnapshot,
    OperationWorkResult,
    ProgressReporter,
)
from nova_layer.object_workflow.ports.precision_extraction import (
    PrecisionExtractionEngine,
    PrecisionExtractionError,
    PrecisionExtractionRequest,
    PrecisionExtractionSuccess,
)
from nova_layer.object_workflow.ports.project_store import ProjectStore, ProjectStoreError
from nova_layer.object_workflow.ports.provider_registry import ProviderCapabilities

OperationEventHandler = Callable[[OperationProgress | OperationSnapshot], None]

_DEFAULT_INFERENCE_CAPABILITIES = ProviderCapabilities(
    supports_positive_point=True,
    supports_bounding_box=True,
    supports_negative_point=True,
    supports_scribble=False,
    supports_mask_prompt=False,
    supports_cpu=True,
    supports_gpu=False,
    supports_mps=False,
    requires_local_checkpoint=False,
)


class _HasId(Protocol):
    id: UUID


TEntity = TypeVar("TEntity", bound=_HasId)


class ObjectWorkflowService:
    def __init__(
        self,
        *,
        store: ProjectStore,
        inference: CoreInferenceEngine,
        extraction: PrecisionExtractionEngine | None = None,
        executor: OperationExecutor | None = None,
        inference_capabilities: ProviderCapabilities | None = None,
        host_registry: HostAdapterRegistry | None = None,
        clipboard: ClipboardWriter | None = None,
        process_launcher: ProcessLauncher | None = None,
        include_fake_host: bool = False,
    ) -> None:
        self._store = store
        self._inference = inference
        self._inference_capabilities = inference_capabilities or _DEFAULT_INFERENCE_CAPABILITIES
        self._extraction = extraction
        self._inference_engine_token = uuid4().hex
        self._extraction_engine_token = None if extraction is None else uuid4().hex
        self._executor = executor or MockOperationExecutor(step_delay_seconds=0.0)
        self._executor.set_listener(self)
        self._lock = threading.RLock()
        self._event_handlers: list[OperationEventHandler] = []
        self._project: Project | None = None
        self._assets: dict[str, bytes] = {}
        self._workspace = Path(tempfile.mkdtemp(prefix="nova_object_workflow_"))
        self._extraction_settings = ExtractionSettings()
        self._host_registry = host_registry or build_default_host_adapter_registry(
            launcher=process_launcher,
            include_fake_host=include_fake_host,
        )
        self._clipboard = clipboard
        self._delivery_busy = False
        self._last_delivery: DeliverySummary | None = None
        self._last_export_path: str | None = None
        self._last_materialized_path: str | None = None
        self._shut_down = False
        self._max_retained_operations = 32

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def temp_workspace(self) -> Path:
        """Ephemeral on-disk workspace used for operation artifacts."""
        return self._workspace

    @property
    def inference_capabilities(self) -> ProviderCapabilities:
        return self._inference_capabilities

    @property
    def inference_engine_token(self) -> str:
        """Stable identity for the bound inference engine (changes on replacement)."""
        return self._inference_engine_token

    @property
    def extraction_engine_token(self) -> str | None:
        """Stable identity for the bound extraction engine (changes on replacement)."""
        return self._extraction_engine_token

    def shutdown(self) -> None:
        """Release executor threads, GPU sessions, and temporary workspace files."""
        with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
            running = self._find_running_operation()
            running_id = None if running is None else running.id
        if running_id is not None:
            try:
                self.cancel_operation(running_id)
            except Exception:  # noqa: BLE001
                pass
        shutdown_executor = getattr(self._executor, "shutdown", None)
        if callable(shutdown_executor):
            try:
                shutdown_executor(wait=True)
            except Exception:  # noqa: BLE001
                pass
        for engine in (self._inference, self._extraction):
            if engine is None:
                continue
            closer = getattr(engine, "shutdown", None) or getattr(engine, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass
        try:
            if self._workspace.exists():
                shutil.rmtree(self._workspace, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    def add_operation_event_handler(self, handler: OperationEventHandler) -> None:
        self._event_handlers.append(handler)

    def create_project(self, name: str) -> Project:
        project = Project(name=name)
        apply_derived_workflow_state(project)
        self._project = project
        self._assets = {}
        self._reset_delivery_state()
        return project

    def load_source(self, path: str | Path) -> SourceImage:
        project = self._require_project()
        source_path = Path(path)
        if not extension_is_supported(source_path):
            raise ApplicationError(
                "UNSUPPORTED_MEDIA_TYPE",
                f"unsupported source extension: {source_path.suffix}",
            )
        if not source_path.is_file():
            raise ApplicationError("SOURCE_NOT_FOUND", f"source file not found: {source_path}")

        operation = self._begin_operation(
            "load_source",
            {"path": source_path.name},
        )
        try:
            data = source_path.read_bytes()
            probed = probe_source_bytes(data, original_filename=source_path.name)
            fingerprint = hashlib.sha256(data).hexdigest()
            extension = ".png" if probed.media_type == "image/png" else ".jpg"
            relative = f"assets/source/{uuid4().hex}{extension}"
            source = SourceImage(
                original_filename=source_path.name,
                relative_asset_path=relative,
                media_type=probed.media_type,  # type: ignore[arg-type]
                width=probed.width,
                height=probed.height,
                byte_size=len(data),
                content_fingerprint=fingerprint,
            )
            project.source_images.append(source)
            project.active_source_image_id = source.id
            project.active_intent_id = None
            project.active_candidate_set_id = None
            project.active_generation_id = None
            project.generation_records = []
            project.active_hypothesis_id = None
            project.active_confirmation_id = None
            project.active_confirmed_object_id = None
            project.active_extraction_result_id = None
            self._assets[relative] = data
            apply_derived_workflow_state(project)
            project.touch()
            self._finish_operation(operation, OperationStatus.SUCCEEDED)
            return source
        except SourceProbeError as exc:
            self._finish_operation(operation, OperationStatus.FAILED, exc.message)
            raise ApplicationError(exc.code, exc.message) from exc
        except ApplicationError:
            raise
        except Exception as exc:
            self._finish_operation(operation, OperationStatus.FAILED, str(exc))
            raise ApplicationError("LOAD_SOURCE_FAILED", str(exc)) from exc

    def create_artist_intent(self, instruction: dict[str, Any] | IntentInstruction) -> ArtistIntent:
        project = self._require_project()
        if project.active_intent_id is not None:
            raise ApplicationError(
                "ARTIST_INTENT_ALREADY_EXISTS",
                "an active ArtistIntent already exists; use UpdateArtistIntent",
            )
        source = self._active_source(project)
        try:
            validated = validate_intent_instruction(instruction)
        except IntentValidationError as exc:
            raise ApplicationError(exc.code, exc.message) from exc

        intent = ArtistIntent(
            revision=1,
            source_image_id=source.id,
            instruction=validated,
        )
        project.intents.append(intent)
        project.active_intent_id = intent.id
        project.active_candidate_set_id = None
        project.active_generation_id = None
        project.active_hypothesis_id = None
        project.active_confirmation_id = None
        project.active_confirmed_object_id = None
        project.active_extraction_result_id = None
        apply_derived_workflow_state(project)
        project.touch()
        return intent

    def update_artist_intent(self, instruction: dict[str, Any] | IntentInstruction) -> ArtistIntent:
        project = self._require_project()
        if project.active_intent_id is None:
            raise ApplicationError(
                "NO_ACTIVE_INTENT",
                "no active ArtistIntent exists; use CreateArtistIntent",
            )
        source = self._active_source(project)
        try:
            validated = validate_intent_instruction(instruction)
        except IntentValidationError as exc:
            raise ApplicationError(exc.code, exc.message) from exc

        active = self._active_intent(project)
        if (
            validated.schema_name == active.instruction.schema_name
            and instruction_signal_fingerprint(validated)
            == instruction_signal_fingerprint(active.instruction)
        ):
            # No-op Apply: do not create a duplicate revision or invalidate outputs.
            return active

        next_revision = max(item.revision for item in project.intents) + 1
        intent = ArtistIntent(
            revision=next_revision,
            source_image_id=source.id,
            instruction=validated,
        )
        project.intents.append(intent)
        project.active_intent_id = intent.id
        project.active_candidate_set_id = None
        project.active_generation_id = None
        project.active_hypothesis_id = None
        project.active_confirmation_id = None
        project.active_confirmed_object_id = None
        project.active_extraction_result_id = None
        apply_derived_workflow_state(project)
        project.touch()
        return intent

    def start_generate_candidates(self) -> UUID:
        return self.start_generate_hypothesis()

    def start_generate_hypothesis(self) -> UUID:
        with self._lock:
            project = self._require_project()
            self._reject_if_busy()
            source = self._active_source(project)
            intent = self._active_intent(project)
            # Capability checks happen before OperationRecord creation.
            self._validate_intent_against_provider(intent.instruction)
            bound_inference = self._inference
            operation = self._begin_operation(
                "generate_hypothesis",
                {
                    "source_image_id": str(source.id),
                    "intent_id": str(intent.id),
                    "intent_revision": intent.revision,
                },
            )
            request_id = str(uuid4())
            source_bytes = self._assets[source.relative_asset_path]
            local_source = self._workspace / f"{operation.id.hex}_source"
            local_source.write_bytes(source_bytes)
            work = _HypothesisWork(
                inference=bound_inference,
                request_id=request_id,
                source_image_path=str(local_source),
                source_width=source.width,
                source_height=source.height,
                media_type=source.media_type,
                content_fingerprint=source.content_fingerprint,
                intent_instruction=intent.instruction,
                source_image_id=str(source.id),
                intent_id=str(intent.id),
                intent_revision=intent.revision,
            )
            operation_id = operation.id
        self._executor.submit(
            operation_id=str(operation_id),
            operation_type="generate_hypothesis",
            work=work,
        )
        return operation_id

    def start_generate_extraction(
        self,
        settings: ExtractionSettings | dict[str, Any] | None = None,
    ) -> UUID:
        with self._lock:
            project = self._require_project()
            self._reject_if_busy()
            if self._extraction is None:
                raise ApplicationError(
                    "EXTRACTION_UNAVAILABLE",
                    "Precision Extraction engine is not configured",
                )
            snapshot = self._validate_and_snapshot_settings(settings)
            binding = self._resolve_confirmed_extraction_binding(project)
            bound_extraction = self._extraction
            operation = self._begin_operation(
                "generate_extraction",
                {
                    "confirmed_object_id": str(binding["confirmed_object_id"]),
                    "source_image_id": str(binding["source_image_id"]),
                    "confirmed_generation_id": _uuid_str(binding["confirmed_generation_id"]),
                    "confirmed_candidate_set_id": _uuid_str(
                        binding["confirmed_candidate_set_id"]
                    ),
                    "confirmed_candidate_id": _uuid_str(binding["confirmed_candidate_id"]),
                    "confirmed_hypothesis_id": str(binding["confirmed_hypothesis_id"]),
                    "mask_relative_path": binding["mask_relative_path"],
                    "settings": snapshot.model_dump(mode="json"),
                },
            )
            request_id = str(uuid4())
            source_bytes = self._assets[binding["source_relative_path"]]
            mask_png = self._assets[binding["mask_relative_path"]]
            work = _ExtractionWork(
                extraction=bound_extraction,
                request_id=request_id,
                source_width=int(binding["source_width"]),
                source_height=int(binding["source_height"]),
                source_bytes=source_bytes,
                mask_png=mask_png,
                confirmed_object_id=str(binding["confirmed_object_id"]),
                source_image_id=str(binding["source_image_id"]),
                confirmed_generation_id=_uuid_str(binding["confirmed_generation_id"]),
                confirmed_candidate_set_id=_uuid_str(binding["confirmed_candidate_set_id"]),
                confirmed_candidate_id=_uuid_str(binding["confirmed_candidate_id"]),
                confirmed_hypothesis_id=str(binding["confirmed_hypothesis_id"]),
                artist_intent_revision=binding["artist_intent_revision"],
                mask_provider_id=binding["mask_provider_id"],
                mask_provider_version=binding["mask_provider_version"],
                mask_relative_path=binding["mask_relative_path"],
                settings=snapshot,
            )
            operation_id = operation.id
        self._executor.submit(
            operation_id=str(operation_id),
            operation_type="generate_extraction",
            work=work,
        )
        return operation_id

    def start_precision_extraction(
        self,
        settings: ExtractionSettings | dict[str, Any] | None = None,
    ) -> UUID:
        return self.start_generate_extraction(settings)

    def cancel_precision_extraction(self) -> bool:
        running = self._find_running_operation()
        if running is None or running.operation_type != "generate_extraction":
            return False
        return self.cancel_operation(running.id)

    def cancel_operation(self, operation_id: UUID | str) -> bool:
        return self._executor.cancel(str(operation_id))

    def query_operation(self, operation_id: UUID | str) -> OperationSnapshot | None:
        return self._executor.query(str(operation_id))

    def wait_operation(
        self,
        operation_id: UUID | str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.01,
    ) -> OperationSnapshot:
        deadline = time.monotonic() + timeout_seconds
        op_key = str(operation_id)
        while time.monotonic() < deadline:
            snapshot = self._executor.query(op_key)
            if snapshot is not None and snapshot.status != "running":
                # Ensure Application commit finished (listener may still be applying).
                with self._lock:
                    operation = next(
                        (
                            item
                            for item in (self._project.operations if self._project else [])
                            if str(item.id) == op_key
                        ),
                        None,
                    )
                    if operation is not None and operation.status != OperationStatus.RUNNING:
                        return snapshot
            time.sleep(poll_interval_seconds)
        raise ApplicationError("OPERATION_TIMEOUT", f"operation timed out: {op_key}")

    def generate_candidates(self) -> HypothesisCandidateSet:
        operation_id = self.start_generate_candidates()
        snapshot = self.wait_operation(operation_id)
        if snapshot.status == "failed":
            raise ApplicationError(
                snapshot.error_code or "INFERENCE_FAILED",
                snapshot.error_message or "candidate generation failed",
            )
        if snapshot.status == "cancelled":
            raise ApplicationError("CANCELLED", snapshot.error_message or "cancelled")
        project = self._require_project()
        if project.active_candidate_set_id is None:
            raise ApplicationError("INFERENCE_FAILED", "candidate set was not activated")
        return self._require_entity(
            project.candidate_sets,
            project.active_candidate_set_id,
            "candidate_set",
        )

    def generate_hypothesis(self) -> HypothesisCandidateSet:
        """Generate candidates (does not auto-select a hypothesis)."""
        return self.generate_candidates()

    def select_candidate(self, candidate_id: UUID | str) -> ObjectHypothesis:
        """Activate a candidate as the active ObjectHypothesis without calling the provider."""
        project = self._require_project()
        self._reject_if_busy()
        if project.active_candidate_set_id is None:
            raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active HypothesisCandidateSet")
        current = self._require_entity(
            project.candidate_sets,
            project.active_candidate_set_id,
            "candidate_set",
        )
        target_id = UUID(str(candidate_id))
        selected = next((item for item in current.candidates if item.id == target_id), None)
        if selected is None:
            raise ApplicationError(
                "CANDIDATE_NOT_FOUND",
                f"candidate not found in active set: {target_id}",
            )

        # No-op when the requested candidate is already the committed active selection.
        if (
            current.active_candidate_id == target_id
            and project.active_hypothesis_id is not None
        ):
            active_hyp = self._require_entity(
                project.hypotheses,
                project.active_hypothesis_id,
                "hypothesis",
            )
            if active_hyp.candidate_id == target_id:
                return active_hyp

        # Immutable selection: append a new CandidateSet revision with the new active id.
        revised = HypothesisCandidateSet(
            artist_intent_revision=current.artist_intent_revision,
            intent_id=current.intent_id,
            source_image_id=current.source_image_id,
            provider_id=current.provider_id,
            provider_version=current.provider_version,
            candidates=list(current.candidates),
            active_candidate_id=selected.id,
            operation_id=current.operation_id,
            generation_id=current.generation_id,
        )
        project.candidate_sets.append(revised)
        project.active_candidate_set_id = revised.id

        hypothesis = ObjectHypothesis(
            revision=len(project.hypotheses) + 1,
            source_image_id=current.source_image_id,
            intent_id=current.intent_id,
            status="ready",
            mask_relative_path=selected.mask_relative_path,
            confidence=selected.confidence,
            provider_id=current.provider_id,
            provider_version=current.provider_version,
            operation_id=current.operation_id,
            candidate_set_id=revised.id,
            candidate_id=selected.id,
            generation_id=current.generation_id,
        )
        project.hypotheses.append(hypothesis)
        project.active_hypothesis_id = hypothesis.id
        project.active_confirmation_id = None
        project.active_confirmed_object_id = None
        project.active_extraction_result_id = None
        apply_derived_workflow_state(project)
        project.touch()
        return hypothesis

    def get_active_candidate_set(self) -> HypothesisCandidateSet | None:
        project = self._project
        if project is None or project.active_candidate_set_id is None:
            return None
        return self._require_entity(
            project.candidate_sets,
            project.active_candidate_set_id,
            "candidate_set",
        )

    def get_active_candidate(self) -> HypothesisCandidate | None:
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None or candidate_set.active_candidate_id is None:
            return None
        return next(
            (
                item
                for item in candidate_set.candidates
                if item.id == candidate_set.active_candidate_id
            ),
            None,
        )

    def get_candidate(self, candidate_id: UUID | str) -> HypothesisCandidate:
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None:
            raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active HypothesisCandidateSet")
        target_id = UUID(str(candidate_id))
        for candidate in candidate_set.candidates:
            if candidate.id == target_id:
                return candidate
        raise ApplicationError(
            "CANDIDATE_NOT_FOUND",
            f"candidate not found in active set: {target_id}",
        )

    def get_candidate_index(self, candidate_id: UUID | str) -> int:
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None:
            raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active HypothesisCandidateSet")
        target_id = UUID(str(candidate_id))
        for index, candidate in enumerate(candidate_set.candidates):
            if candidate.id == target_id:
                return index
        raise ApplicationError(
            "CANDIDATE_NOT_FOUND",
            f"candidate not found in active set: {target_id}",
        )

    def get_next_candidate_id(self, candidate_id: UUID | str | None = None) -> UUID | None:
        """Next candidate in provider order. Option A: clamp at last (no wrap)."""
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None or not candidate_set.candidates:
            return None
        if candidate_id is None:
            if candidate_set.active_candidate_id is not None:
                candidate_id = candidate_set.active_candidate_id
            else:
                return candidate_set.candidates[0].id
        index = self.get_candidate_index(candidate_id)
        if index >= len(candidate_set.candidates) - 1:
            return candidate_set.candidates[-1].id
        return candidate_set.candidates[index + 1].id

    def get_previous_candidate_id(self, candidate_id: UUID | str | None = None) -> UUID | None:
        """Previous candidate in provider order. Option A: clamp at first (no wrap)."""
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None or not candidate_set.candidates:
            return None
        if candidate_id is None:
            if candidate_set.active_candidate_id is not None:
                candidate_id = candidate_set.active_candidate_id
            else:
                return candidate_set.candidates[0].id
        index = self.get_candidate_index(candidate_id)
        if index <= 0:
            return candidate_set.candidates[0].id
        return candidate_set.candidates[index - 1].id

    def clear_candidate_set(self) -> None:
        project = self._require_project()
        self._reject_if_busy()
        project.active_candidate_set_id = None
        project.active_hypothesis_id = None
        project.active_confirmation_id = None
        project.active_confirmed_object_id = None
        project.active_extraction_result_id = None
        apply_derived_workflow_state(project)
        project.touch()

    def generate_extraction(
        self,
        settings: ExtractionSettings | dict[str, Any] | None = None,
    ) -> ExtractionResult:
        operation_id = self.start_generate_extraction(settings)
        snapshot = self.wait_operation(operation_id)
        if snapshot.status == "failed":
            raise ApplicationError(
                snapshot.error_code or "EXTRACTION_FAILED",
                snapshot.error_message or "extraction failed",
            )
        if snapshot.status == "cancelled":
            raise ApplicationError("CANCELLED", snapshot.error_message or "cancelled")
        project = self._require_project()
        if project.active_extraction_result_id is None:
            raise ApplicationError("EXTRACTION_FAILED", "extraction was not activated")
        return self._require_entity(
            project.extraction_results,
            project.active_extraction_result_id,
            "extraction",
        )

    def extract_confirmed_object(
        self,
        settings: ExtractionSettings | dict[str, Any] | None = None,
    ) -> ExtractionResult:
        return self.generate_extraction(settings)

    def set_extraction_settings(
        self,
        settings: ExtractionSettings | dict[str, Any],
    ) -> ExtractionSettings:
        self._reject_if_busy()
        self._extraction_settings = self._validate_and_snapshot_settings(settings)
        return self._extraction_settings

    def get_precision_extraction_settings(self) -> ExtractionSettings:
        return self._extraction_settings

    def get_active_extraction_result(self) -> ExtractionResult | None:
        project = self._project
        if project is None or project.active_extraction_result_id is None:
            return None
        return self._require_entity(
            project.extraction_results,
            project.active_extraction_result_id,
            "extraction",
        )

    def can_start_precision_extraction(self) -> bool:
        if self._project is None or self._extraction is None:
            return False
        if self.has_running_operation():
            return False
        try:
            self._resolve_confirmed_extraction_binding(self._project)
            self._validate_and_snapshot_settings(self._extraction_settings)
        except ApplicationError:
            return False
        return True

    def get_confirmed_extraction_source_summary(self) -> dict[str, Any] | None:
        project = self._project
        if project is None:
            return None
        try:
            binding = self._resolve_confirmed_extraction_binding(project)
        except ApplicationError:
            return None
        generation = None
        if binding["confirmed_generation_id"] is not None:
            generation = latest_generation_record(
                project,
                binding["confirmed_generation_id"],
            )
        candidate_index = None
        confidence = None
        if binding["confirmed_candidate_set_id"] is not None:
            candidate_set = next(
                (
                    item
                    for item in project.candidate_sets
                    if item.id == binding["confirmed_candidate_set_id"]
                ),
                None,
            )
            if candidate_set is not None and binding["confirmed_candidate_id"] is not None:
                for index, candidate in enumerate(candidate_set.candidates):
                    if candidate.id == binding["confirmed_candidate_id"]:
                        candidate_index = index + 1
                        confidence = float(candidate.confidence)
                        break
        return {
            "confirmed_generation_id": _uuid_str(binding["confirmed_generation_id"]),
            "sequence_number": None if generation is None else generation.sequence_number,
            "candidate_index": candidate_index,
            "confirmed_candidate_id": _uuid_str(binding["confirmed_candidate_id"]),
            "confidence": confidence,
            "mask_provider_id": binding["mask_provider_id"],
            "mask_provider_version": binding["mask_provider_version"],
            "artist_intent_revision": binding["artist_intent_revision"],
            "source_width": binding["source_width"],
            "source_height": binding["source_height"],
        }

    def get_active_extraction_for_delivery(self) -> ExtractionResult | None:
        return self.get_active_extraction_result()

    def can_export_active_extraction(self) -> bool:
        if self._project is None:
            return False
        try:
            validate_committed_extraction_asset(
                self.get_active_extraction_result(),
                self._assets,
            )
        except ApplicationError:
            return False
        return True

    def get_suggested_export_filename(self) -> str:
        project = self._require_project()
        extraction = self.get_active_extraction_result()
        if extraction is None:
            raise ApplicationError("NO_ACTIVE_EXTRACTION", "no committed ExtractionResult")
        return suggested_filename_for_extraction(project, extraction)

    def get_host_adapters(self) -> list[HostAdapterDescriptor]:
        return self._host_registry.list()

    def get_host_adapter(self, adapter_id: str) -> HostAdapterDescriptor:
        return self._host_registry.get(adapter_id).descriptor

    def get_available_host_actions(self, adapter_id: str) -> tuple[str, ...]:
        descriptor = self.get_host_adapter(adapter_id)
        if descriptor.availability != "available":
            return ()
        return adapter_actions(descriptor)

    def get_last_successful_delivery(self) -> DeliverySummary | None:
        return self._last_delivery

    def refresh_host_availability(self) -> list[HostAdapterDescriptor]:
        self._host_registry.refresh()
        return self.get_host_adapters()

    def export_active_extraction(
        self,
        destination: str | Path,
        *,
        allow_overwrite: bool = False,
    ) -> HostDeliverySuccess:
        return self._run_delivery(
            adapter_id="filesystem",
            action="export_copy",
            destination=str(Path(destination)),
            allow_overwrite=allow_overwrite,
        )

    def reveal_active_extraction(self) -> HostDeliverySuccess:
        validated = validate_committed_extraction_asset(
            self.get_active_extraction_result(),
            self._assets,
        )
        materialized = materialize_asset_under_workspace(
            self._workspace,
            validated.relative_path,
            validated.png_bytes,
        )
        self._last_materialized_path = str(materialized)
        return self._run_delivery(
            adapter_id="reveal",
            action="reveal_file",
            destination=str(materialized),
            allow_overwrite=False,
            skip_asset_revalidation=validated,
        )

    def reveal_last_export(self) -> HostDeliverySuccess:
        if not self._last_export_path:
            raise ApplicationError("REVEAL_TARGET_MISSING", "no successful export to reveal")
        path = Path(self._last_export_path)
        if not path.is_file():
            raise ApplicationError(
                "REVEAL_TARGET_MISSING",
                f"last export file is missing: {path}",
            )
        return self._run_delivery(
            adapter_id="reveal",
            action="reveal_file",
            destination=str(path),
            allow_overwrite=False,
        )

    def copy_active_extraction_reference(
        self,
        reference_type: ReferenceType = "absolute_path",
    ) -> str:
        project = self._require_project()
        validated = validate_committed_extraction_asset(
            self.get_active_extraction_result(),
            self._assets,
        )
        absolute: str | None = self._last_export_path
        if reference_type in {"absolute_path", "file_uri"} and absolute is None:
            materialized = materialize_asset_under_workspace(
                self._workspace,
                validated.relative_path,
                validated.png_bytes,
            )
            absolute = str(materialized)
            self._last_materialized_path = absolute
        text = resolve_reference_text(
            reference_type=reference_type,
            relative_path=validated.relative_path,
            absolute_path=absolute,
            last_export_path=self._last_export_path,
        )
        if self._clipboard is None:
            raise ApplicationError(
                "CLIPBOARD_UNAVAILABLE",
                "clipboard writer is not configured",
            )
        try:
            self._clipboard.write_text(text)
        except Exception as exc:  # noqa: BLE001
            raise ApplicationError("CLIPBOARD_FAILED", str(exc)) from exc
        binding = delivery_binding_metadata(project, validated.extraction)
        self._last_delivery = DeliverySummary(
            extraction_id=str(validated.extraction.id),
            adapter_id="clipboard",
            adapter_version="1.0.0",
            action="copy_reference",
            output_reference=text,
            host_display_name="Clipboard",
            message=f"Copied {reference_type}: {text}",
            generation_number=binding.get("generation_number"),
            candidate_number=binding.get("candidate_number"),
            extraction_provider=validated.extraction.provider_id,
            width=validated.width,
            height=validated.height,
            premultiply_alpha=binding.get("premultiply_alpha"),
            source_name=binding.get("source_name"),
        )
        return text

    def deliver_active_extraction(
        self,
        adapter_id: str,
        action: str,
        *,
        target: str | Path | None = None,
        allow_overwrite: bool = False,
    ) -> HostDeliverySuccess:
        destination = None if target is None else str(Path(target))
        if adapter_id in {"reveal", "generic_open_file"} and destination is None:
            validated = validate_committed_extraction_asset(
                self.get_active_extraction_result(),
                self._assets,
            )
            materialized = materialize_asset_under_workspace(
                self._workspace,
                validated.relative_path,
                validated.png_bytes,
            )
            destination = str(materialized)
            self._last_materialized_path = destination
            return self._run_delivery(
                adapter_id=adapter_id,
                action=action,
                destination=destination,
                allow_overwrite=allow_overwrite,
                skip_asset_revalidation=validated,
            )
        return self._run_delivery(
            adapter_id=adapter_id,
            action=action,
            destination=destination,
            allow_overwrite=allow_overwrite,
        )

    def _run_delivery(
        self,
        *,
        adapter_id: str,
        action: str,
        destination: str | None,
        allow_overwrite: bool,
        skip_asset_revalidation: ValidatedExtractionAsset | None = None,
    ) -> HostDeliverySuccess:
        project = self._require_project()
        if self._delivery_busy:
            raise ApplicationError(
                "HOST_DELIVERY_IN_PROGRESS",
                "another Host delivery is already in progress",
            )
        self._delivery_busy = True
        try:
            if skip_asset_revalidation is not None:
                validated = skip_asset_revalidation
            else:
                validated = validate_committed_extraction_asset(
                    self.get_active_extraction_result(),
                    self._assets,
                )
            # Capture immutable binding before adapter execution.
            binding = delivery_binding_metadata(project, validated.extraction)
            source_bytes_fingerprint = hash(validated.png_bytes)
            adapter = self._host_registry.create(adapter_id)
            if not adapter.descriptor.capabilities.supports(action):
                raise ApplicationError(
                    "UNSUPPORTED_HOST_ACTION",
                    f"adapter {adapter_id!r} does not support action {action!r}",
                )
            request = build_host_delivery_request(
                project=project,
                validated=validated,
                action=action,
                destination=destination,
                allow_overwrite=allow_overwrite,
            )
            success = adapter.deliver(request)
            # Ensure project asset bytes were not mutated by the adapter.
            current = self._assets.get(validated.relative_path)
            if current is None or hash(current) != source_bytes_fingerprint:
                raise ApplicationError(
                    "ASSET_MUTATION_DETECTED",
                    "host adapter mutated the committed project asset",
                )
            if success.action == "export_copy":
                self._last_export_path = success.output_reference
            self._last_delivery = format_delivery_summary(
                success=success,
                extraction=validated.extraction,
                binding=binding,
            )
            return success
        finally:
            self._delivery_busy = False

    def _reset_delivery_state(self) -> None:
        self._last_delivery = None
        self._last_export_path = None
        self._last_materialized_path = None
        self._delivery_busy = False

    def retry_generation(self) -> UUID:
        """Start a new Generate using the current ArtistIntent (same as generate)."""
        return self.start_generate_hypothesis()

    def reject_generation(self, generation_id: UUID | None = None) -> GenerationRecord:
        project = self._require_project()
        self._reject_if_busy()
        target_id = (
            project.active_generation_id
            if generation_id is None
            else UUID(str(generation_id))
        )
        if target_id is None:
            raise ApplicationError("NO_ACTIVE_GENERATION", "no generation to reject")
        record = latest_generation_record(project, target_id)
        if record is None:
            raise ApplicationError("GENERATION_NOT_FOUND", f"unknown generation: {target_id}")
        if record.status == "confirmed":
            raise ApplicationError(
                "GENERATION_ALREADY_CONFIRMED",
                "confirmed generations cannot be rejected",
            )
        if record.status == "rejected":
            raise ApplicationError(
                "GENERATION_ALREADY_REJECTED",
                "generation is already rejected",
            )
        rejected = append_generation_status_record(
            project,
            base=record,
            status="rejected",
            rejected_at=utc_now(),
        )
        self._clear_workflow_for_generation(project, target_id)
        apply_derived_workflow_state(project)
        project.touch()
        return rejected

    def restore_generation(self, generation_id: UUID | str) -> None:
        project = self._require_project()
        self._reject_if_busy()
        target_id = UUID(str(generation_id))
        record = latest_generation_record(project, target_id)
        if record is None:
            raise ApplicationError("GENERATION_NOT_FOUND", f"unknown generation: {target_id}")
        candidate_set = latest_candidate_set_for_generation(project, target_id)
        if candidate_set is None:
            raise ApplicationError(
                "CANDIDATE_SET_NOT_FOUND",
                f"no candidate set for generation: {target_id}",
            )
        project.active_generation_id = target_id
        project.active_candidate_set_id = candidate_set.id
        self._sync_hypothesis_to_active_generation(project, target_id, candidate_set)
        apply_derived_workflow_state(project)
        project.touch()

    def reactivate_generation(self, generation_id: UUID | str) -> GenerationRecord:
        project = self._require_project()
        self._reject_if_busy()
        target_id = UUID(str(generation_id))
        record = latest_generation_record(project, target_id)
        if record is None:
            raise ApplicationError("GENERATION_NOT_FOUND", f"unknown generation: {target_id}")
        if record.status != "rejected":
            raise ApplicationError(
                "GENERATION_NOT_REJECTED",
                "only rejected generations can be reactivated",
            )
        reactivated = append_generation_status_record(
            project,
            base=record,
            status="available",
        )
        candidate_set = latest_candidate_set_for_generation(project, target_id)
        if candidate_set is not None:
            project.active_generation_id = target_id
            project.active_candidate_set_id = candidate_set.id
            self._clear_hypothesis_outside_generation(project, target_id)
            self._sync_hypothesis_to_active_generation(project, target_id, candidate_set)
        apply_derived_workflow_state(project)
        project.touch()
        return reactivated

    def select_generation_candidate(
        self,
        generation_id: UUID | str,
        candidate_id: UUID | str,
    ) -> ObjectHypothesis:
        target_id = UUID(str(generation_id))
        if self._project is not None and self._project.active_generation_id != target_id:
            self.restore_generation(target_id)
        return self.select_candidate(candidate_id)

    def get_generation(self, generation_id: UUID | str) -> GenerationRecord:
        project = self._require_project()
        target_id = UUID(str(generation_id))
        record = latest_generation_record(project, target_id)
        if record is None:
            raise ApplicationError("GENERATION_NOT_FOUND", f"unknown generation: {target_id}")
        return record

    def get_generation_history(self) -> list[GenerationRecord]:
        return ordered_generations(self._require_project())

    def get_active_generation(self) -> GenerationRecord | None:
        project = self._project
        if project is None or project.active_generation_id is None:
            return None
        return latest_generation_record(project, project.active_generation_id)

    def get_generation_candidate_set(self, generation_id: UUID | str) -> HypothesisCandidateSet:
        project = self._require_project()
        target_id = UUID(str(generation_id))
        candidate_set = latest_candidate_set_for_generation(project, target_id)
        if candidate_set is None:
            raise ApplicationError(
                "CANDIDATE_SET_NOT_FOUND",
                f"no candidate set for generation: {target_id}",
            )
        return candidate_set

    def get_previous_generation_id(self) -> UUID | None:
        project = self._require_project()
        if project.active_generation_id is None:
            return None
        history = ordered_generations(project)
        ids = [item.generation_id for item in history]
        if project.active_generation_id not in ids:
            return None
        index = ids.index(project.active_generation_id)
        if index <= 0:
            return ids[0]
        return ids[index - 1]

    def get_next_generation_id(self) -> UUID | None:
        project = self._require_project()
        if project.active_generation_id is None:
            return None
        history = ordered_generations(project)
        ids = [item.generation_id for item in history]
        if project.active_generation_id not in ids:
            return None
        index = ids.index(project.active_generation_id)
        if index >= len(ids) - 1:
            return ids[-1]
        return ids[index + 1]

    def can_reject_generation(self, generation_id: UUID | None = None) -> bool:
        project = self._project
        if project is None:
            return False
        target_id = project.active_generation_id if generation_id is None else generation_id
        if target_id is None:
            return False
        record = latest_generation_record(project, target_id)
        return record is not None and record.status == "available"

    def can_confirm_generation(self) -> bool:
        project = self._project
        if project is None or project.active_generation_id is None:
            return False
        record = latest_generation_record(project, project.active_generation_id)
        if record is None or record.status != "available":
            return False
        candidate_set = self.get_active_candidate_set()
        if candidate_set is None or candidate_set.active_candidate_id is None:
            return False
        if project.active_hypothesis_id is None:
            return False
        hypothesis = next(
            (item for item in project.hypotheses if item.id == project.active_hypothesis_id),
            None,
        )
        if hypothesis is None or hypothesis.status != "ready":
            return False
        return (
            hypothesis.candidate_set_id == candidate_set.id
            and hypothesis.candidate_id == candidate_set.active_candidate_id
        )

    def confirm_hypothesis(self, hypothesis_id: UUID | None = None) -> ConfirmedObject:
        project = self._require_project()
        if not self.can_confirm_generation():
            raise ApplicationError(
                "GENERATION_NOT_CONFIRMABLE",
                "confirm requires an active available generation with a committed candidate",
            )
        hypothesis = self._resolve_hypothesis(project, hypothesis_id)
        if hypothesis.status != "ready":
            raise ApplicationError(
                "HYPOTHESIS_NOT_READY",
                "only a ready ObjectHypothesis can be confirmed",
            )
        active_set = self.get_active_candidate_set()
        if active_set is None or hypothesis.candidate_set_id != active_set.id:
            raise ApplicationError(
                "HYPOTHESIS_STALE",
                "active hypothesis does not match the active candidate selection",
            )
        generation_id = project.active_generation_id
        assert generation_id is not None
        record = latest_generation_record(project, generation_id)
        assert record is not None
        intent = self._require_entity(project.intents, hypothesis.intent_id, "intent")
        source = self._require_entity(project.source_images, hypothesis.source_image_id, "source")

        confirmation = ConfirmationRecord(hypothesis_id=hypothesis.id)
        confirmed = ConfirmedObject(
            revision=len(project.confirmed_objects) + 1,
            source_image_id=source.id,
            intent_id=intent.id,
            hypothesis_id=hypothesis.id,
            confirmation_id=confirmation.id,
            mask_relative_path=hypothesis.mask_relative_path,
            confidence=hypothesis.confidence,
        )
        project.confirmations.append(confirmation)
        project.confirmed_objects.append(confirmed)
        project.active_confirmation_id = confirmation.id
        project.active_confirmed_object_id = confirmed.id
        project.active_extraction_result_id = None
        for other in ordered_generations(project):
            if other.generation_id == generation_id:
                append_generation_status_record(project, base=other, status="confirmed")
            elif other.status == "confirmed":
                append_generation_status_record(project, base=other, status="available")
        apply_derived_workflow_state(project)
        project.touch()
        return confirmed

    def save_project(self, package_path: str | Path) -> Path:
        project = self._require_project()
        target = Path(package_path)
        previous_assets = dict(self._assets)
        operation = self._begin_operation("save_project", {"package_path": str(target)})
        self._finish_operation(operation, OperationStatus.SUCCEEDED)
        try:
            self._store.save(project, target, dict(self._assets))
            return target
        except ProjectStoreError as exc:
            self._assets = previous_assets
            self._finish_operation(operation, OperationStatus.FAILED, exc.message)
            raise ApplicationError(exc.code, exc.message) from exc
        except Exception as exc:
            self._assets = previous_assets
            self._finish_operation(operation, OperationStatus.FAILED, str(exc))
            raise ApplicationError("SAVE_FAILED", str(exc)) from exc

    def load_project(self, package_path: str | Path) -> Project:
        previous = self._project
        previous_assets = dict(self._assets)
        target = Path(package_path)
        try:
            loaded, assets = self._store.load(target)
        except ProjectStoreError as exc:
            self._project = previous
            self._assets = previous_assets
            raise ApplicationError(exc.code, exc.message) from exc
        except Exception as exc:
            self._project = previous
            self._assets = previous_assets
            raise ApplicationError("LOAD_FAILED", str(exc)) from exc

        migrate_project_generation_history(loaded)

        operation = OperationRecord(
            operation_type="load_project",
            status=OperationStatus.RUNNING,
            request_summary={"package_path": str(target)},
        )
        loaded.operations.append(operation)
        apply_derived_workflow_state(loaded)
        loaded.touch()
        operation.status = OperationStatus.SUCCEEDED
        operation.finished_at = utc_now()
        self._project = loaded
        self._assets = assets
        self._reset_delivery_state()
        return loaded

    def get_project_summary(self) -> dict[str, Any]:
        project = self._require_project()
        return {
            "id": str(project.id),
            "name": project.name,
            "schema_version": project.schema_version,
            "workflow_state": project.workflow_state.value,
            "active_source_image_id": _uuid_str(project.active_source_image_id),
            "active_intent_id": _uuid_str(project.active_intent_id),
            "active_candidate_set_id": _uuid_str(project.active_candidate_set_id),
            "active_hypothesis_id": _uuid_str(project.active_hypothesis_id),
            "active_confirmation_id": _uuid_str(project.active_confirmation_id),
            "active_confirmed_object_id": _uuid_str(project.active_confirmed_object_id),
            "operation_count": len(project.operations),
        }

    def list_operations(self) -> list[OperationRecord]:
        return list(self._require_project().operations)

    def has_running_operation(self) -> bool:
        return self._find_running_operation() is not None

    def set_inference_engine(
        self,
        inference: CoreInferenceEngine,
        *,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        with self._lock:
            self._reject_if_busy()
            self._inference = inference
            self._inference_engine_token = uuid4().hex
            if capabilities is not None:
                self._inference_capabilities = capabilities

    def set_extraction_engine(self, extraction: PrecisionExtractionEngine) -> None:
        with self._lock:
            self._reject_if_busy()
            self._extraction = extraction
            self._extraction_engine_token = uuid4().hex

    def active_intent_supported_by_provider(self) -> bool:
        project = self._project
        if project is None or project.active_intent_id is None:
            return True
        intent = self._require_entity(project.intents, project.active_intent_id, "intent")
        try:
            self._validate_intent_against_provider(intent.instruction)
        except ApplicationError:
            return False
        return True

    def _validate_intent_against_provider(self, instruction: IntentInstruction) -> None:
        capabilities = self._inference_capabilities
        try:
            signals = parse_intent_signals(instruction.payload.signals)
        except IntentValidationError as exc:
            raise ApplicationError(exc.code, exc.message) from exc
        for signal in signals:
            if isinstance(signal, PositivePoint) and not capabilities.supports_positive_point:
                raise ApplicationError(
                    "UNSUPPORTED_PROVIDER_CAPABILITY",
                    "selected provider does not support positive_point signals",
                )
            if isinstance(signal, NegativePoint) and not capabilities.supports_negative_point:
                raise ApplicationError(
                    "UNSUPPORTED_PROVIDER_CAPABILITY",
                    "selected provider does not support negative_point signals",
                )
            if isinstance(signal, BoundingBox) and not capabilities.supports_bounding_box:
                raise ApplicationError(
                    "UNSUPPORTED_PROVIDER_CAPABILITY",
                    "selected provider does not support bounding_box signals",
                )

    def get_active_confirmed_object(self) -> ConfirmedObject | None:
        project = self._require_project()
        if project.active_confirmed_object_id is None:
            return None
        return self._require_entity(
            project.confirmed_objects,
            project.active_confirmed_object_id,
            "confirmed_object",
        )

    def get_asset_bytes(self, relative_path: str) -> bytes:
        try:
            return self._assets[relative_path]
        except KeyError as exc:
            raise ApplicationError("ASSET_NOT_FOUND", relative_path) from exc

    def on_progress(self, progress: OperationProgress) -> None:
        for handler in list(self._event_handlers):
            handler(progress)

    def on_terminal(self, snapshot: OperationSnapshot) -> None:
        with self._lock:
            self._apply_terminal_snapshot(snapshot)
        for handler in list(self._event_handlers):
            handler(snapshot)

    def _apply_terminal_snapshot(self, snapshot: OperationSnapshot) -> None:
        project = self._project
        if project is None:
            return
        operation = next(
            (item for item in project.operations if str(item.id) == snapshot.operation_id),
            None,
        )
        if operation is None:
            return
        if snapshot.status == "cancelled":
            self._finish_operation(operation, OperationStatus.CANCELLED, snapshot.error_message)
            apply_derived_workflow_state(project)
            return
        if snapshot.status == "failed":
            self._finish_operation(operation, OperationStatus.FAILED, snapshot.error_message)
            apply_derived_workflow_state(project)
            return
        if snapshot.operation_type == "generate_hypothesis":
            self._commit_candidate_set(operation, snapshot.result_payload)
        elif snapshot.operation_type == "generate_extraction":
            self._commit_extraction(operation, snapshot.result_payload)
        else:
            self._finish_operation(operation, OperationStatus.SUCCEEDED)

    def _commit_candidate_set(self, operation: OperationRecord, payload: dict[str, Any]) -> None:
        project = self._require_project()
        bound_intent_id = UUID(str(payload["intent_id"]))
        if project.active_intent_id != bound_intent_id:
            self._finish_operation(
                operation,
                OperationStatus.CANCELLED,
                "obsolete: active ArtistIntent changed during generate",
            )
            apply_derived_workflow_state(project)
            return

        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            self._finish_operation(
                operation,
                OperationStatus.FAILED,
                "provider returned no candidates",
            )
            apply_derived_workflow_state(project)
            return

        candidates: list[HypothesisCandidate] = []
        for index, item in enumerate(raw_candidates):
            mask_relative = f"assets/masks/{uuid4().hex}.png"
            mask_path = self._workspace / Path(mask_relative).name
            write_binary_mask_png(
                mask_path,
                int(item["mask_width"]),
                int(item["mask_height"]),
                item["mask_data"],
            )
            self._assets[mask_relative] = mask_path.read_bytes()
            metadata = item.get("provider_metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {"index": index}
            else:
                metadata = {**metadata, "index": index}
            candidates.append(
                HypothesisCandidate(
                    confidence=float(item["confidence"]),
                    mask_relative_path=mask_relative,
                    preview_relative_path=mask_relative,
                    provider_metadata=metadata,
                )
            )

        generation_id = uuid4()
        candidate_set = HypothesisCandidateSet(
            artist_intent_revision=int(payload["intent_revision"]),
            intent_id=bound_intent_id,
            source_image_id=UUID(str(payload["source_image_id"])),
            provider_id=str(payload["provider_id"]),
            provider_version=str(payload["provider_version"]),
            candidates=candidates,
            active_candidate_id=None,
            operation_id=operation.id,
            generation_id=generation_id,
        )
        provider_meta = payload.get("provider_metadata")
        if not isinstance(provider_meta, dict):
            provider_meta = {}
        generation_record = GenerationRecord(
            generation_id=generation_id,
            sequence_number=next_sequence_number(project),
            artist_intent_id=bound_intent_id,
            artist_intent_revision=int(payload["intent_revision"]),
            provider_id=str(payload["provider_id"]),
            provider_version=str(payload["provider_version"]),
            candidate_set_id=candidate_set.id,
            operation_id=operation.id,
            status="available",
            provider_metadata=dict(provider_meta),
        )
        project.candidate_sets.append(candidate_set)
        project.generation_records.append(generation_record)
        project.active_candidate_set_id = candidate_set.id
        project.active_generation_id = generation_id
        project.active_hypothesis_id = None
        project.active_confirmation_id = None
        project.active_confirmed_object_id = None
        project.active_extraction_result_id = None
        apply_derived_workflow_state(project)
        project.touch()
        self._finish_operation(operation, OperationStatus.SUCCEEDED)

    def _commit_extraction(self, operation: OperationRecord, payload: dict[str, Any]) -> None:
        project = self._require_project()
        bound_confirmed_id = UUID(str(payload["confirmed_object_id"]))
        if project.active_confirmed_object_id != bound_confirmed_id:
            self._finish_operation(
                operation,
                OperationStatus.CANCELLED,
                "obsolete: confirmed object changed during extraction",
            )
            apply_derived_workflow_state(project)
            return
        bound_hypothesis_id = payload.get("confirmed_hypothesis_id")
        if bound_hypothesis_id is not None:
            confirmed = self._require_entity(
                project.confirmed_objects,
                bound_confirmed_id,
                "confirmed_object",
            )
            if str(confirmed.hypothesis_id) != str(bound_hypothesis_id):
                self._finish_operation(
                    operation,
                    OperationStatus.CANCELLED,
                    "obsolete: confirmed hypothesis changed during extraction",
                )
                apply_derived_workflow_state(project)
                return
        bound_mask = payload.get("mask_relative_path")
        if bound_mask is not None:
            confirmed = self._require_entity(
                project.confirmed_objects,
                bound_confirmed_id,
                "confirmed_object",
            )
            if confirmed.mask_relative_path != bound_mask:
                self._finish_operation(
                    operation,
                    OperationStatus.CANCELLED,
                    "obsolete: confirmed mask changed during extraction",
                )
                apply_derived_workflow_state(project)
                return

        relative = f"assets/extractions/{uuid4().hex}.png"
        tmp_path = self._workspace / f"{Path(relative).name}.tmp"
        out_path = self._workspace / Path(relative).name
        try:
            write_rgba_png(
                tmp_path,
                int(payload["width"]),
                int(payload["height"]),
                payload["rgba_data"],
            )
            tmp_bytes = tmp_path.read_bytes()
            if len(tmp_bytes) < 8:
                raise ApplicationError("OUTPUT_VALIDATION_FAILED", "empty extraction output")
            out_path.write_bytes(tmp_bytes)
            self._assets[relative] = tmp_bytes
        except ApplicationError:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            self._finish_operation(operation, OperationStatus.FAILED, str(exc))
            apply_derived_workflow_state(project)
            return
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        settings_payload = payload.get("settings") or {}
        settings = None
        if isinstance(settings_payload, dict) and settings_payload:
            settings = ExtractionSettings.model_validate(settings_payload)
        metadata = payload.get("provider_metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        extraction = ExtractionResult(
            revision=len(project.extraction_results) + 1,
            confirmed_object_id=bound_confirmed_id,
            source_image_id=UUID(str(payload["source_image_id"])),
            relative_asset_path=relative,
            confidence=float(payload["confidence"]),
            provider_id=str(payload["provider_id"]),
            provider_version=str(payload["provider_version"]),
            operation_id=operation.id,
            width=int(payload["width"]),
            height=int(payload["height"]),
            confirmed_generation_id=(
                UUID(str(payload["confirmed_generation_id"]))
                if payload.get("confirmed_generation_id")
                else None
            ),
            confirmed_candidate_set_id=(
                UUID(str(payload["confirmed_candidate_set_id"]))
                if payload.get("confirmed_candidate_set_id")
                else None
            ),
            confirmed_candidate_id=(
                UUID(str(payload["confirmed_candidate_id"]))
                if payload.get("confirmed_candidate_id")
                else None
            ),
            confirmed_hypothesis_id=(
                UUID(str(payload["confirmed_hypothesis_id"]))
                if payload.get("confirmed_hypothesis_id")
                else None
            ),
            artist_intent_revision=(
                int(payload["artist_intent_revision"])
                if payload.get("artist_intent_revision") is not None
                else None
            ),
            mask_provider_id=(
                str(payload["mask_provider_id"]) if payload.get("mask_provider_id") else None
            ),
            mask_provider_version=(
                str(payload["mask_provider_version"])
                if payload.get("mask_provider_version")
                else None
            ),
            settings=settings,
            provider_metadata=dict(metadata),
        )
        project.extraction_results.append(extraction)
        project.active_extraction_result_id = extraction.id
        apply_derived_workflow_state(project)
        project.touch()
        self._finish_operation(operation, OperationStatus.SUCCEEDED)

    def _reject_if_busy(self) -> None:
        running = self._find_running_operation()
        if running is not None:
            raise ApplicationError(
                "OPERATION_IN_PROGRESS",
                f"operation already running: {running.operation_type}",
            )

    def _find_running_operation(self) -> OperationRecord | None:
        project = self._project
        if project is None:
            return None
        for operation in reversed(project.operations):
            if operation.status == OperationStatus.RUNNING and operation.operation_type in {
                "generate_hypothesis",
                "generate_extraction",
            }:
                return operation
        return None

    def _require_project(self) -> Project:
        if self._project is None:
            raise ApplicationError("NO_PROJECT", "no project is loaded")
        return self._project

    def _active_source(self, project: Project) -> SourceImage:
        if project.active_source_image_id is None:
            raise ApplicationError("NO_ACTIVE_SOURCE", "no active SourceImage")
        return self._require_entity(project.source_images, project.active_source_image_id, "source")

    def _active_intent(self, project: Project) -> ArtistIntent:
        if project.active_intent_id is None:
            raise ApplicationError("NO_ACTIVE_INTENT", "no active ArtistIntent")
        return self._require_entity(project.intents, project.active_intent_id, "intent")

    def _validate_and_snapshot_settings(
        self,
        settings: ExtractionSettings | dict[str, Any] | None,
    ) -> ExtractionSettings:
        if settings is None:
            candidate = self._extraction_settings
        elif isinstance(settings, ExtractionSettings):
            candidate = settings
        else:
            try:
                candidate = ExtractionSettings.model_validate(settings)
            except Exception as exc:
                raise ApplicationError(
                    "INVALID_EXTRACTION_SETTINGS",
                    f"invalid extraction settings: {exc}",
                ) from exc
        if candidate.remove_small_regions:
            raise ApplicationError(
                "UNSUPPORTED_EXTRACTION_SETTING",
                "remove_small_regions is not supported by the current CPU extractor",
            )
        if candidate.crop_mode != "full_source":
            raise ApplicationError(
                "UNSUPPORTED_EXTRACTION_SETTING",
                f"unsupported crop_mode: {candidate.crop_mode}",
            )
        self._extraction_settings = candidate
        return candidate

    def _resolve_confirmed_extraction_binding(self, project: Project) -> dict[str, Any]:
        if project.active_confirmed_object_id is None:
            raise ApplicationError(
                "NO_ACTIVE_CONFIRMED_OBJECT",
                "extraction requires an active ConfirmedObject",
            )
        confirmed = self._require_entity(
            project.confirmed_objects,
            project.active_confirmed_object_id,
            "confirmed_object",
        )
        source = self._require_entity(
            project.source_images,
            confirmed.source_image_id,
            "source",
        )
        hypothesis = self._require_entity(
            project.hypotheses,
            confirmed.hypothesis_id,
            "hypothesis",
        )
        if confirmed.mask_relative_path not in self._assets:
            raise ApplicationError(
                "MASK_ASSET_MISSING",
                f"confirmed mask asset missing: {confirmed.mask_relative_path}",
            )
        if source.relative_asset_path not in self._assets:
            raise ApplicationError(
                "SOURCE_ASSET_MISSING",
                f"source asset missing: {source.relative_asset_path}",
            )

        candidate_set_id = hypothesis.candidate_set_id
        candidate_id = hypothesis.candidate_id
        generation_id = hypothesis.generation_id
        mask_provider_id = hypothesis.provider_id
        mask_provider_version = hypothesis.provider_version
        artist_intent_revision: int | None = None

        if candidate_set_id is not None:
            candidate_set = next(
                (item for item in project.candidate_sets if item.id == candidate_set_id),
                None,
            )
            if candidate_set is None:
                raise ApplicationError(
                    "CANDIDATE_SET_NOT_FOUND",
                    f"confirmed candidate set missing: {candidate_set_id}",
                )
            if generation_id is None:
                generation_id = candidate_set.generation_id
            if candidate_id is None:
                candidate_id = candidate_set.active_candidate_id
            artist_intent_revision = candidate_set.artist_intent_revision
            if candidate_id is not None:
                match = next(
                    (item for item in candidate_set.candidates if item.id == candidate_id),
                    None,
                )
                if match is None:
                    raise ApplicationError(
                        "CANDIDATE_NOT_FOUND",
                        f"confirmed candidate missing from set: {candidate_id}",
                    )
                if match.mask_relative_path != confirmed.mask_relative_path:
                    raise ApplicationError(
                        "CANDIDATE_MASK_MISMATCH",
                        "confirmed object mask does not match confirmed candidate mask",
                    )
            if generation_id is not None and candidate_set.generation_id not in {
                None,
                generation_id,
            }:
                raise ApplicationError(
                    "CANDIDATE_GENERATION_MISMATCH",
                    "confirmed candidate set does not belong to confirmed generation",
                )

        if generation_id is not None:
            record = latest_generation_record(project, generation_id)
            if record is None:
                raise ApplicationError(
                    "GENERATION_NOT_FOUND",
                    f"confirmed generation missing: {generation_id}",
                )
            if artist_intent_revision is None:
                artist_intent_revision = record.artist_intent_revision
            if record.status == "rejected":
                raise ApplicationError(
                    "GENERATION_REJECTED",
                    "cannot extract from a rejected confirmed generation",
                )

        return {
            "confirmed_object_id": confirmed.id,
            "source_image_id": source.id,
            "source_relative_path": source.relative_asset_path,
            "source_width": source.width,
            "source_height": source.height,
            "mask_relative_path": confirmed.mask_relative_path,
            "confirmed_hypothesis_id": hypothesis.id,
            "confirmed_generation_id": generation_id,
            "confirmed_candidate_set_id": candidate_set_id,
            "confirmed_candidate_id": candidate_id,
            "artist_intent_revision": artist_intent_revision,
            "mask_provider_id": mask_provider_id,
            "mask_provider_version": mask_provider_version,
        }

    def _hypothesis_belongs_to_generation(
        self,
        project: Project,
        hypothesis: ObjectHypothesis,
        generation_id: UUID,
    ) -> bool:
        if hypothesis.generation_id == generation_id:
            return True
        if hypothesis.candidate_set_id is not None:
            for candidate_set in project.candidate_sets:
                if candidate_set.id == hypothesis.candidate_set_id:
                    return candidate_set.generation_id == generation_id
        record = latest_generation_record(project, generation_id)
        if record is None:
            return False
        return hypothesis.operation_id == record.operation_id

    def _clear_workflow_for_generation(self, project: Project, generation_id: UUID) -> None:
        if project.active_hypothesis_id is not None:
            hypothesis = next(
                (item for item in project.hypotheses if item.id == project.active_hypothesis_id),
                None,
            )
            if hypothesis is not None and self._hypothesis_belongs_to_generation(
                project,
                hypothesis,
                generation_id,
            ):
                project.active_hypothesis_id = None
        if project.active_confirmed_object_id is not None:
            confirmed = next(
                (
                    item
                    for item in project.confirmed_objects
                    if item.id == project.active_confirmed_object_id
                ),
                None,
            )
            if confirmed is not None:
                hypothesis = next(
                    (item for item in project.hypotheses if item.id == confirmed.hypothesis_id),
                    None,
                )
                if hypothesis is not None and self._hypothesis_belongs_to_generation(
                    project,
                    hypothesis,
                    generation_id,
                ):
                    project.active_confirmation_id = None
                    project.active_confirmed_object_id = None
                    project.active_extraction_result_id = None

    def _clear_hypothesis_outside_generation(self, project: Project, generation_id: UUID) -> None:
        if project.active_hypothesis_id is None:
            return
        hypothesis = next(
            (item for item in project.hypotheses if item.id == project.active_hypothesis_id),
            None,
        )
        if hypothesis is None:
            project.active_hypothesis_id = None
            return
        if not self._hypothesis_belongs_to_generation(project, hypothesis, generation_id):
            project.active_hypothesis_id = None
            project.active_confirmation_id = None
            project.active_confirmed_object_id = None
            project.active_extraction_result_id = None

    def _sync_hypothesis_to_active_generation(
        self,
        project: Project,
        generation_id: UUID,
        candidate_set: HypothesisCandidateSet,
    ) -> None:
        # Browsing history must not invalidate confirmation or extraction (Feature 4).
        project.active_hypothesis_id = None
        if candidate_set.active_candidate_id is None:
            return
        for hypothesis in reversed(project.hypotheses):
            if (
                hypothesis.candidate_set_id == candidate_set.id
                and hypothesis.candidate_id == candidate_set.active_candidate_id
                and hypothesis.status == "ready"
            ):
                project.active_hypothesis_id = hypothesis.id
                return

    def _resolve_hypothesis(self, project: Project, hypothesis_id: UUID | None) -> ObjectHypothesis:
        target_id = hypothesis_id or project.active_hypothesis_id
        if target_id is None:
            raise ApplicationError("NO_ACTIVE_HYPOTHESIS", "no active ObjectHypothesis")
        return self._require_entity(project.hypotheses, target_id, "hypothesis")

    def _require_entity(self, items: list[TEntity], entity_id: UUID, label: str) -> TEntity:
        for item in items:
            if item.id == entity_id:
                return item
        raise ApplicationError("ENTITY_NOT_FOUND", f"{label} not found: {entity_id}")

    def _begin_operation(self, operation_type: str, summary: dict[str, Any]) -> OperationRecord:
        project = self._require_project()
        operation = OperationRecord(
            operation_type=operation_type,
            status=OperationStatus.RUNNING,
            request_summary=summary,
        )
        project.operations.append(operation)
        project.touch()
        return operation

    def _finish_operation(
        self,
        operation: OperationRecord,
        status: OperationStatus,
        error_message: str | None = None,
    ) -> None:
        if status == OperationStatus.RUNNING:
            raise RuntimeError("operation must finish as succeeded, failed, or cancelled")
        operation.status = status
        operation.error_message = error_message
        operation.finished_at = utc_now()
        if self._project is not None:
            self._project.touch()
            self._prune_completed_operations(self._project)

    def _prune_completed_operations(self, project: Project) -> None:
        """Bound completed operation history while keeping any still-running record."""
        limit = self._max_retained_operations
        if len(project.operations) <= limit:
            return
        running = [op for op in project.operations if op.status == OperationStatus.RUNNING]
        finished = [op for op in project.operations if op.status != OperationStatus.RUNNING]
        keep_finished = finished[-max(0, limit - len(running)) :]
        project.operations[:] = keep_finished + running


class _HypothesisWork:
    def __init__(
        self,
        *,
        inference: CoreInferenceEngine,
        request_id: str,
        source_image_path: str,
        source_width: int,
        source_height: int,
        media_type: str,
        content_fingerprint: str,
        intent_instruction: IntentInstruction,
        source_image_id: str,
        intent_id: str,
        intent_revision: int,
    ) -> None:
        self._inference = inference
        self._request_id = request_id
        self._source_image_path = source_image_path
        self._source_width = source_width
        self._source_height = source_height
        self._media_type = media_type
        self._content_fingerprint = content_fingerprint
        self._intent_instruction = intent_instruction
        self._source_image_id = source_image_id
        self._intent_id = intent_id
        self._intent_revision = intent_revision

    def run(
        self,
        *,
        should_cancel: CancelChecker,
        report_progress: ProgressReporter,
    ) -> OperationWorkResult:
        report_progress(0, 3, "preparing")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        report_progress(1, 3, "running core inference")
        result = self._inference.generate_hypothesis(
            CoreInferenceRequest(
                request_id=self._request_id,
                source_image_path=self._source_image_path,
                source_width=self._source_width,
                source_height=self._source_height,
                media_type=self._media_type,
                content_fingerprint=self._content_fingerprint,
                intent_instruction=self._intent_instruction,
                provider_options={"should_cancel": should_cancel},
            )
        )
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        if isinstance(result, CoreInferenceError):
            return OperationWorkResult(
                status="failed",
                error_code=result.error_code,
                error_message=result.message,
            )
        assert isinstance(result, CandidateResult)
        report_progress(2, 3, "finalizing")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        candidates_payload = []
        for index, (mask, confidence) in enumerate(
            zip(result.masks, result.confidences, strict=True)
        ):
            candidates_payload.append(
                {
                    "mask_width": mask.width,
                    "mask_height": mask.height,
                    "mask_data": mask.data,
                    "confidence": float(confidence),
                    "provider_metadata": {
                        **result.provider_metadata,
                        "index": index,
                    },
                }
            )
        return OperationWorkResult(
            status="succeeded",
            payload={
                "source_image_id": self._source_image_id,
                "intent_id": self._intent_id,
                "intent_revision": self._intent_revision,
                "provider_id": result.provider_id,
                "provider_version": result.provider_version,
                "provider_metadata": dict(result.provider_metadata),
                "candidates": candidates_payload,
            },
        )


class _ExtractionWork:
    def __init__(
        self,
        *,
        extraction: PrecisionExtractionEngine,
        request_id: str,
        source_width: int,
        source_height: int,
        source_bytes: bytes,
        mask_png: bytes,
        confirmed_object_id: str,
        source_image_id: str,
        confirmed_generation_id: str | None,
        confirmed_candidate_set_id: str | None,
        confirmed_candidate_id: str | None,
        confirmed_hypothesis_id: str,
        artist_intent_revision: int | None,
        mask_provider_id: str | None,
        mask_provider_version: str | None,
        mask_relative_path: str,
        settings: ExtractionSettings,
    ) -> None:
        self._extraction = extraction
        self._request_id = request_id
        self._source_width = source_width
        self._source_height = source_height
        self._source_bytes = source_bytes
        self._mask_png = mask_png
        self._confirmed_object_id = confirmed_object_id
        self._source_image_id = source_image_id
        self._confirmed_generation_id = confirmed_generation_id
        self._confirmed_candidate_set_id = confirmed_candidate_set_id
        self._confirmed_candidate_id = confirmed_candidate_id
        self._confirmed_hypothesis_id = confirmed_hypothesis_id
        self._artist_intent_revision = artist_intent_revision
        self._mask_provider_id = mask_provider_id
        self._mask_provider_version = mask_provider_version
        self._mask_relative_path = mask_relative_path
        self._settings = settings

    def run(
        self,
        *,
        should_cancel: CancelChecker,
        report_progress: ProgressReporter,
    ) -> OperationWorkResult:
        report_progress(0, 4, "preparing")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        try:
            _width, _height, source_rgb = decode_rgb_image_bytes(self._source_bytes)
        except Exception as exc:  # noqa: BLE001
            return OperationWorkResult(
                status="failed",
                error_code="SOURCE_UNREADABLE",
                error_message=str(exc),
            )
        try:
            mask_w, mask_h, mask_data = read_binary_mask_png_bytes(self._mask_png)
        except Exception as exc:  # noqa: BLE001
            return OperationWorkResult(
                status="failed",
                error_code="MASK_UNREADABLE",
                error_message=str(exc),
            )
        if mask_w != self._source_width or mask_h != self._source_height:
            return OperationWorkResult(
                status="failed",
                error_code="DIMENSION_MISMATCH",
                error_message=(
                    f"mask {mask_w}x{mask_h} does not match source "
                    f"{self._source_width}x{self._source_height}"
                ),
            )
        if not any(mask_data):
            return OperationWorkResult(
                status="failed",
                error_code="EMPTY_MASK",
                error_message="confirmed mask contains no foreground pixels",
            )
        try:
            mask = BinaryMask.from_pixels(mask_w, mask_h, mask_data)
        except Exception as exc:  # noqa: BLE001
            return OperationWorkResult(
                status="failed",
                error_code="UNSUPPORTED_MASK_FORMAT",
                error_message=str(exc),
            )
        report_progress(1, 4, "running precision extraction")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        settings_dict = self._settings.model_dump(mode="json")
        result = self._extraction.extract(
            PrecisionExtractionRequest(
                request_id=self._request_id,
                source_width=self._source_width,
                source_height=self._source_height,
                source_rgb=source_rgb,
                mask=mask,
                provider_options={
                    "should_cancel": should_cancel,
                    "extraction_settings": settings_dict,
                },
            )
        )
        report_progress(2, 4, "validating output")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        if isinstance(result, PrecisionExtractionError):
            return OperationWorkResult(
                status="failed",
                error_code=result.error_code,
                error_message=result.message,
            )
        assert isinstance(result, PrecisionExtractionSuccess)
        report_progress(3, 4, "finalizing")
        if should_cancel():
            return OperationWorkResult(status="cancelled", error_message="cancelled")
        return OperationWorkResult(
            status="succeeded",
            payload={
                "confirmed_object_id": self._confirmed_object_id,
                "source_image_id": self._source_image_id,
                "confirmed_generation_id": self._confirmed_generation_id,
                "confirmed_candidate_set_id": self._confirmed_candidate_set_id,
                "confirmed_candidate_id": self._confirmed_candidate_id,
                "confirmed_hypothesis_id": self._confirmed_hypothesis_id,
                "artist_intent_revision": self._artist_intent_revision,
                "mask_provider_id": self._mask_provider_id,
                "mask_provider_version": self._mask_provider_version,
                "mask_relative_path": self._mask_relative_path,
                "width": result.image.width,
                "height": result.image.height,
                "rgba_data": result.image.data,
                "confidence": result.confidence,
                "provider_id": result.provider_id,
                "provider_version": result.provider_version,
                "settings": settings_dict,
                "provider_metadata": dict(result.diagnostics),
            },
        )


def _uuid_str(value: UUID | None) -> str | None:
    return None if value is None else str(value)
