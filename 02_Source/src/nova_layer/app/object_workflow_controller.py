from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import UUID

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from nova_layer.app.user_facing_errors import cancellation_status
from nova_layer.object_workflow.adapters.core_inference_registry import (
    DEFAULT_PROVIDER,
    CoreInferenceProviderRegistry,
    build_default_core_inference_registry,
    runtime_config_from_environ,
)
from nova_layer.object_workflow.adapters.host_adapter_registry import (
    HostAdapterRegistry,
    build_default_host_adapter_registry,
)
from nova_layer.object_workflow.adapters.image_codec import decode_rgba_png_bytes
from nova_layer.object_workflow.adapters.json_project_store import JsonProjectStore
from nova_layer.object_workflow.adapters.neural_matting import (
    probe_neural_matting_availability,
)
from nova_layer.object_workflow.adapters.precision_extraction_registry import (
    DEFAULT_EXTRACTION_PROVIDER,
    PrecisionExtractionProviderRegistry,
    build_default_precision_extraction_registry,
    extraction_runtime_config_from_environ,
)
from nova_layer.object_workflow.application.batch_manager import BatchManager
from nova_layer.object_workflow.application.batch_models import BatchJob, BatchStatistics
from nova_layer.object_workflow.application.errors import ApplicationError
from nova_layer.object_workflow.application.host_delivery import DeliverySummary
from nova_layer.object_workflow.application.service import ObjectWorkflowService
from nova_layer.object_workflow.application.workspace_manager import WorkspaceManager
from nova_layer.object_workflow.domain.models import WorkflowState
from nova_layer.object_workflow.plugin_sdk import (
    InstalledPluginRecord,
    PackageValidationResult,
    PluginInfo,
    PluginManager,
    PluginPackageManager,
    default_plugin_install_root,
)
from nova_layer.object_workflow.plugin_sdk.package.errors import PluginPackageError
from nova_layer.object_workflow.ports.extraction_provider import (
    ExtractionProviderDescriptor,
    ExtractionRuntimeConfig,
)
from nova_layer.object_workflow.ports.host_delivery import (
    HostAdapterCapabilities,
    HostAdapterDescriptor,
    ReferenceType,
)
from nova_layer.object_workflow.ports.provider_registry import (
    ProviderDescriptor,
    ProviderRuntimeConfig,
)
from nova_layer.object_workflow.runtime import RuntimeCacheBundle
from nova_layer.object_workflow.runtime.caches import ThumbnailCache
from nova_layer.object_workflow.runtime.lru_cache import CacheStats


@dataclass(frozen=True, slots=True)
class ObjectWorkflowViewState:
    workflow_state: str
    project_name: str | None
    active_intent_revision: int | None
    intent_revision_count: int
    prompt_summary: str
    can_create_project: bool
    can_load_source: bool
    can_edit_guidance: bool
    can_apply_intent: bool
    can_cancel_edit: bool
    can_generate: bool
    can_confirm: bool
    can_reject_generation: bool
    can_retry_generation: bool
    can_reactivate_generation: bool
    can_extract: bool
    can_cancel_operation: bool
    can_save: bool
    can_load_project: bool
    is_busy: bool
    progress_current: int
    progress_total: int
    progress_message: str
    core_inference_provider: str
    core_inference_provider_display_name: str
    core_inference_provider_version: str
    core_inference_device: str
    core_inference_available: bool
    core_inference_availability_message: str
    core_inference_requires_model: bool
    core_inference_capability_summary: str
    precision_extraction_provider: str
    precision_extraction_provider_display_name: str
    precision_extraction_provider_version: str
    precision_extraction_available: bool
    precision_extraction_availability_message: str
    precision_extraction_requires_model: bool
    precision_extraction_edge_blur_radius: float
    precision_extraction_feather_radius: float
    precision_extraction_cleanup_radius: int
    precision_extraction_expand_contract_pixels: int
    precision_extraction_premultiply_alpha: bool
    precision_extraction_matting_unknown_radius: int
    precision_extraction_matting_refinement_strength: float
    precision_extraction_matting_preserve_known_regions: bool
    precision_extraction_matting_backend: str
    neural_matting_available: bool
    neural_matting_availability_message: str
    precision_extraction_supports_matting: bool
    confirmed_extraction_summary: str
    can_export_extraction: bool
    can_reveal_extraction: bool
    can_copy_extraction_reference: bool
    can_deliver_to_host: bool
    host_adapter_id: str
    host_adapter_display_name: str
    host_adapter_available: bool
    host_adapter_availability_message: str
    host_action: str
    suggested_export_filename: str
    delivery_summary: str
    plugin_summary: str
    batch_summary: str
    batch_running: bool
    batch_awaiting_confirmation: bool
    batch_current_image: str
    batch_confirmation_mode: str
    can_start_batch: bool
    can_cancel_batch: bool
    can_retry_batch_failed: bool
    status_message: str


@dataclass(frozen=True, slots=True)
class IntentRevisionInfo:
    id: UUID
    revision: int
    is_active: bool


@dataclass(frozen=True, slots=True)
class PromptPointView:
    x: float
    y: float
    polarity: str


@dataclass(frozen=True, slots=True)
class CandidateViewItem:
    id: UUID
    index: int
    confidence: float | None
    confidence_label: str
    is_active: bool
    is_previewed: bool
    is_focused: bool
    thumbnail_mask: NDArray[np.uint8] | None
    accessible_name: str


@dataclass(frozen=True, slots=True)
class GenerationHistoryItem:
    generation_id: UUID
    sequence_number: int
    artist_intent_revision: int
    provider_id: str
    provider_display_name: str
    candidate_count: int
    active_candidate_confidence: float | None
    status: str
    is_active: bool
    created_at: str | None


class ObjectWorkflowController(QObject):
    """Qt-facing facade over ObjectWorkflowService. UI must not bypass this layer."""

    state_changed = Signal()
    error_occurred = Signal(str)
    operation_progress = Signal(str, int, int, str)
    operation_finished = Signal(str, str)
    batch_progress = Signal(str)
    _operation_event = Signal(object)

    def __init__(
        self,
        service: ObjectWorkflowService | None = None,
        *,
        core_inference_provider: str | None = None,
        registry: CoreInferenceProviderRegistry | None = None,
        runtime_config: ProviderRuntimeConfig | None = None,
        extraction_registry: PrecisionExtractionProviderRegistry | None = None,
        extraction_runtime_config: ExtractionRuntimeConfig | None = None,
        precision_extraction_provider: str | None = None,
        host_registry: HostAdapterRegistry | None = None,
        include_fake_host: bool = False,
        plugin_manager: PluginManager | None = None,
        enable_plugins: bool = True,
        plugins_root: Path | str | Sequence[Path | str] | None = None,
        workspace: WorkspaceManager | None = None,
        enable_batch: bool = True,
    ) -> None:
        super().__init__()
        self._registry = registry or build_default_core_inference_registry()
        self._runtime_config = runtime_config or runtime_config_from_environ(
            selected_provider_id=core_inference_provider
        )
        if core_inference_provider is not None:
            self._runtime_config = self._runtime_config.with_provider(
                str(core_inference_provider).strip().lower()
            )
        self._extraction_registry = (
            extraction_registry or build_default_precision_extraction_registry()
        )
        self._extraction_runtime_config = (
            extraction_runtime_config
            or extraction_runtime_config_from_environ(
                selected_provider_id=precision_extraction_provider
            )
        )
        if precision_extraction_provider is not None:
            self._extraction_runtime_config = self._extraction_runtime_config.with_provider(
                str(precision_extraction_provider).strip().lower()
            )
        self._host_registry = host_registry or build_default_host_adapter_registry(
            include_fake_host=include_fake_host
        )
        # Workspace first so Feature 12 install root / configs feed PluginManager.
        if workspace is not None:
            self._workspace = workspace
            if not getattr(workspace, "_loaded", False):
                self._workspace.load()
        elif os.environ.get("PYTEST_CURRENT_TEST"):
            # Isolate unit tests from the process-wide shared workspace.
            self._workspace = WorkspaceManager(
                Path(tempfile.mkdtemp(prefix="nova_ws_test_")) / "workspace.json"
            )
            self._workspace.load()
        else:
            self._workspace = WorkspaceManager.shared()
        # Restore provider selections from Workspace before engine creation.
        if core_inference_provider is None:
            saved_provider = self._workspace.selected_provider_id()
            if saved_provider:
                self._runtime_config = self._runtime_config.with_provider(saved_provider)
        if precision_extraction_provider is None:
            saved_extraction = self._workspace.selected_extraction_provider_id()
            if saved_extraction:
                self._extraction_runtime_config = self._extraction_runtime_config.with_provider(
                    saved_extraction
                )
        configured_install_root = self._workspace.plugin_install_root()
        resolved_install_root = (
            Path(configured_install_root)
            if configured_install_root
            else default_plugin_install_root()
        )
        self._plugin_package_manager = PluginPackageManager(
            install_root=resolved_install_root,
            workspace=self._workspace,
        )
        self._plugin_manager = plugin_manager or PluginManager(
            plugin_roots=plugins_root,
            include_default_roots=plugins_root is None,
            install_roots=resolved_install_root,
            configurations=self._workspace.plugin_configurations(),
        )
        if enable_plugins:
            try:
                self._plugin_manager.load_and_register(
                    inference_registry=self._registry,
                    extraction_registry=self._extraction_registry,
                    host_registry=self._host_registry,
                )
            except Exception:  # noqa: BLE001 — never block startup on plugin system faults
                pass
        self._selected_host_adapter_id = "generic_open_file"
        self._selected_host_action = "open_file"
        saved_host = self._workspace.selected_host_adapter_id()
        if saved_host:
            self._selected_host_adapter_id = saved_host
        self._last_export_destination: str | None = None
        self._shut_down = False
        if service is None:
            provider_name = self._runtime_config.selected_provider_id
            if not self._registry.contains(provider_name):
                provider_name = DEFAULT_PROVIDER
                self._runtime_config = self._runtime_config.with_provider(provider_name)
            descriptor = self._registry.get(provider_name)
            inference = self._registry.create(provider_name, self._runtime_config)
            extraction_name = self._extraction_runtime_config.selected_provider_id
            if not self._extraction_registry.contains(extraction_name):
                extraction_name = DEFAULT_EXTRACTION_PROVIDER
                self._extraction_runtime_config = self._extraction_runtime_config.with_provider(
                    extraction_name
                )
            extraction = self._extraction_registry.create(
                extraction_name,
                self._extraction_runtime_config,
            )
            self._service = ObjectWorkflowService(
                store=JsonProjectStore(),
                inference=inference,
                extraction=extraction,
                inference_capabilities=descriptor.capabilities,
                host_registry=self._host_registry,
                clipboard=_QtClipboardWriter(),
                include_fake_host=include_fake_host,
            )
            self._service.set_extraction_settings(
                self._extraction_runtime_config.settings_snapshot()
            )
            self._core_inference_provider = provider_name
            self._precision_extraction_provider = extraction_name
        else:
            self._service = service
            self._core_inference_provider = self._runtime_config.selected_provider_id
            if not self._registry.contains(self._core_inference_provider):
                self._core_inference_provider = DEFAULT_PROVIDER
                self._runtime_config = self._runtime_config.with_provider(DEFAULT_PROVIDER)
            self._precision_extraction_provider = (
                self._extraction_runtime_config.selected_provider_id
            )
            if not self._extraction_registry.contains(self._precision_extraction_provider):
                self._precision_extraction_provider = DEFAULT_EXTRACTION_PROVIDER
                self._extraction_runtime_config = self._extraction_runtime_config.with_provider(
                    DEFAULT_EXTRACTION_PROVIDER
                )
            try:
                self._service.set_extraction_settings(
                    self._extraction_runtime_config.settings_snapshot()
                )
            except ApplicationError:
                pass
        self._sync_host_selection_defaults()
        self._runtime_caches = RuntimeCacheBundle()
        self._batch_manager: BatchManager | None = None
        if enable_batch:
            self._batch_manager = BatchManager(
                self._service,
                workspace=self._workspace,
                runtime_caches=self._runtime_caches,
                listener=self._on_batch_progress,
            )
        self._batch_thread: Thread | None = None
        self._batch_confirmation_mode = "interactive"
        self._batch_enable_automatic_confirmation = False
        self._batch_selection_policy = "highest_confidence"
        self._source_frame: NDArray[np.uint8] | None = None
        self._mask_overlay: NDArray[np.uint8] | None = None
        self._preview_mask: NDArray[np.uint8] | None = None
        self._preview_candidate_id: UUID | None = None
        self._focused_candidate_id: UUID | None = None
        self._comparison_mode: bool = False
        self._extraction_preview: NDArray[np.uint8] | None = None
        self._intent_points: list[PromptPointView] = []
        self._intent_box: tuple[float, float, float, float] | None = None
        self._status = "Create or load an object-workflow project."
        self._active_operation_id: UUID | None = None
        self._progress_current = 0
        self._progress_total = 1
        self._progress_message = ""
        self._operation_event.connect(
            self._handle_operation_event,
            Qt.ConnectionType.QueuedConnection,
        )
        self._service.add_operation_event_handler(self._on_operation_event)

    @property
    def source_frame(self) -> NDArray[np.uint8] | None:
        return None if self._source_frame is None else self._source_frame.copy()

    @property
    def mask_overlay(self) -> NDArray[np.uint8] | None:
        """Mask shown in the main viewer (temporary preview overrides committed)."""
        if self._preview_mask is not None:
            return self._preview_mask.copy()
        return None if self._mask_overlay is None else self._mask_overlay.copy()

    @property
    def committed_mask_overlay(self) -> NDArray[np.uint8] | None:
        return None if self._mask_overlay is None else self._mask_overlay.copy()

    @property
    def preview_candidate_id(self) -> UUID | None:
        return self._preview_candidate_id

    @property
    def focused_candidate_id(self) -> UUID | None:
        return self._focused_candidate_id

    @property
    def comparison_mode(self) -> bool:
        return self._comparison_mode

    @property
    def extraction_preview(self) -> NDArray[np.uint8] | None:
        return None if self._extraction_preview is None else self._extraction_preview.copy()

    @property
    def intent_points(self) -> list[tuple[float, float]]:
        """Backward-compatible positive points only."""
        return [(p.x, p.y) for p in self._intent_points if p.polarity == "positive"]

    @property
    def prompt_points(self) -> list[PromptPointView]:
        return list(self._intent_points)

    @property
    def intent_box(self) -> tuple[float, float, float, float] | None:
        return self._intent_box

    def prompt_summary_text(self) -> str:
        positives = sum(1 for point in self._intent_points if point.polarity == "positive")
        negatives = sum(1 for point in self._intent_points if point.polarity == "negative")
        box = "box" if self._intent_box is not None else "no-box"
        return f"+{positives}/-{negatives}/{box}"

    def view_state(self) -> ObjectWorkflowViewState:
        project = self._service.project
        descriptor = self._selected_descriptor()
        extraction_descriptor = self._selected_extraction_descriptor()
        device = self._runtime_config.device
        provider = self._core_inference_provider
        extraction_provider = self._precision_extraction_provider
        prompt_summary = self.prompt_summary_text()
        neural_status, neural_message = self._neural_matting_probe()
        if project is None:
            return ObjectWorkflowViewState(
                workflow_state=WorkflowState.NO_SOURCE.value,
                project_name=None,
                active_intent_revision=None,
                intent_revision_count=0,
                prompt_summary=prompt_summary,
                can_create_project=True,
                can_load_source=False,
                can_edit_guidance=False,
                can_apply_intent=False,
                can_cancel_edit=False,
                can_generate=False,
                can_confirm=False,
                can_reject_generation=False,
                can_retry_generation=False,
                can_reactivate_generation=False,
                can_extract=False,
                can_cancel_operation=False,
                can_save=False,
                can_load_project=True,
                is_busy=False,
                progress_current=0,
                progress_total=1,
                progress_message="",
                core_inference_provider=provider,
                core_inference_provider_display_name=descriptor.display_name,
                core_inference_provider_version=descriptor.provider_version,
                core_inference_device=device,
                core_inference_available=descriptor.availability == "available",
                core_inference_availability_message=descriptor.availability_message,
                core_inference_requires_model=descriptor.requires_model_artifact,
                core_inference_capability_summary=_capability_summary(descriptor),
                precision_extraction_provider=extraction_provider,
                precision_extraction_provider_display_name=extraction_descriptor.display_name,
                precision_extraction_provider_version=extraction_descriptor.provider_version,
                precision_extraction_available=extraction_descriptor.availability == "available",
                precision_extraction_availability_message=(
                    extraction_descriptor.availability_message
                ),
                precision_extraction_requires_model=extraction_descriptor.requires_model,
                precision_extraction_edge_blur_radius=(
                    self._extraction_runtime_config.edge_blur_radius
                ),
                precision_extraction_feather_radius=self._extraction_runtime_config.feather_radius,
                precision_extraction_cleanup_radius=(
                    self._extraction_runtime_config.cleanup_radius
                ),
                precision_extraction_expand_contract_pixels=(
                    self._extraction_runtime_config.expand_contract_pixels
                ),
                precision_extraction_premultiply_alpha=(
                    self._extraction_runtime_config.premultiply_alpha
                ),
                precision_extraction_matting_unknown_radius=(
                    self._extraction_runtime_config.matting_unknown_radius
                ),
                precision_extraction_matting_refinement_strength=(
                    self._extraction_runtime_config.matting_refinement_strength
                ),
                precision_extraction_matting_preserve_known_regions=(
                    self._extraction_runtime_config.matting_preserve_known_regions
                ),
                precision_extraction_matting_backend=(
                    self._extraction_runtime_config.matting_backend
                ),
                neural_matting_available=neural_status == "available",
                neural_matting_availability_message=neural_message,
                precision_extraction_supports_matting=False,
                confirmed_extraction_summary="No confirmed candidate",
                can_export_extraction=False,
                can_reveal_extraction=False,
                can_copy_extraction_reference=False,
                can_deliver_to_host=False,
                host_adapter_id=self._selected_host_adapter_id,
                host_adapter_display_name=self._host_descriptor().display_name,
                host_adapter_available=False,
                host_adapter_availability_message="No committed extraction",
                host_action=self._selected_host_action,
                suggested_export_filename="",
                delivery_summary=self._delivery_summary_text(),
                plugin_summary=self._plugin_summary_text(),
                batch_summary=self._batch_summary_text(),
                batch_running=bool(self._batch_manager and self._batch_manager.is_running),
                batch_awaiting_confirmation=bool(
                    self._batch_manager and self._batch_manager.is_awaiting_confirmation
                ),
                batch_current_image=self._batch_current_image_name(),
                batch_confirmation_mode=self._batch_confirmation_mode,
                can_start_batch=self._can_start_batch(),
                can_cancel_batch=bool(self._batch_manager and self._batch_manager.is_running),
                can_retry_batch_failed=self._can_retry_batch_failed(),
                status_message=self._status,
            )
        state = project.workflow_state
        active_revision = None
        if project.active_intent_id is not None:
            active = next(item for item in project.intents if item.id == project.active_intent_id)
            active_revision = active.revision
        batch_running = bool(self._batch_manager and self._batch_manager.is_running)
        batch_awaiting = bool(
            self._batch_manager and self._batch_manager.is_awaiting_confirmation
        )
        busy = self._service.has_running_operation() or (
            batch_running and not batch_awaiting
        )
        has_committed_intent = project.active_intent_id is not None
        intent_ok = self._service.active_intent_supported_by_provider()
        provider_ok = descriptor.availability == "available"
        extraction_ok = extraction_descriptor.availability == "available"
        can_edit = (not busy) and state in {
            WorkflowState.SOURCE_READY,
            WorkflowState.INTENT_PROVIDED,
            WorkflowState.CANDIDATE_SET_READY,
            WorkflowState.HYPOTHESIS_READY,
            WorkflowState.OBJECT_CONFIRMED,
            WorkflowState.EXTRACTION_READY,
        }
        can_generate = (
            (not busy)
            and provider_ok
            and intent_ok
            and state
            in {
                WorkflowState.INTENT_PROVIDED,
                WorkflowState.CANDIDATE_SET_READY,
                WorkflowState.HYPOTHESIS_READY,
            }
        )
        return ObjectWorkflowViewState(
            workflow_state=state.value,
            project_name=project.name,
            active_intent_revision=active_revision,
            intent_revision_count=len(project.intents),
            prompt_summary=prompt_summary,
            can_create_project=not busy and not batch_running,
            can_load_source=not busy and not batch_running,
            can_edit_guidance=can_edit and not batch_awaiting,
            can_apply_intent=can_edit and not batch_awaiting,
            can_cancel_edit=can_edit and has_committed_intent and not batch_awaiting,
            can_generate=can_generate and not batch_running,
            can_confirm=((not busy) or batch_awaiting)
            and self._service.can_confirm_generation(),
            can_reject_generation=(not busy)
            and self._service.can_reject_generation()
            and not batch_running,
            can_retry_generation=can_generate and not batch_running,
            can_reactivate_generation=(not busy)
            and self._generation_is_rejected_active()
            and not batch_running,
            can_extract=(not busy)
            and extraction_ok
            and self._service.can_start_precision_extraction()
            and not batch_running,
            can_cancel_operation=busy or batch_running,
            can_save=(not busy)
            and state in {WorkflowState.OBJECT_CONFIRMED, WorkflowState.EXTRACTION_READY}
            and not batch_running,
            can_load_project=not busy and not batch_running,
            is_busy=busy or batch_running,
            progress_current=self._progress_current,
            progress_total=self._progress_total,
            progress_message=self._progress_message,
            core_inference_provider=provider,
            core_inference_provider_display_name=descriptor.display_name,
            core_inference_provider_version=descriptor.provider_version,
            core_inference_device=device,
            core_inference_available=provider_ok,
            core_inference_availability_message=descriptor.availability_message,
            core_inference_requires_model=descriptor.requires_model_artifact,
            core_inference_capability_summary=_capability_summary(descriptor),
            precision_extraction_provider=extraction_provider,
            precision_extraction_provider_display_name=extraction_descriptor.display_name,
            precision_extraction_provider_version=extraction_descriptor.provider_version,
            precision_extraction_available=extraction_ok,
            precision_extraction_availability_message=(
                extraction_descriptor.availability_message
            ),
            precision_extraction_requires_model=extraction_descriptor.requires_model,
            precision_extraction_edge_blur_radius=(
                self._extraction_runtime_config.edge_blur_radius
            ),
            precision_extraction_feather_radius=self._extraction_runtime_config.feather_radius,
            precision_extraction_cleanup_radius=self._extraction_runtime_config.cleanup_radius,
            precision_extraction_expand_contract_pixels=(
                self._extraction_runtime_config.expand_contract_pixels
            ),
            precision_extraction_premultiply_alpha=(
                self._extraction_runtime_config.premultiply_alpha
            ),
            precision_extraction_matting_unknown_radius=(
                self._extraction_runtime_config.matting_unknown_radius
            ),
            precision_extraction_matting_refinement_strength=(
                self._extraction_runtime_config.matting_refinement_strength
            ),
            precision_extraction_matting_preserve_known_regions=(
                self._extraction_runtime_config.matting_preserve_known_regions
            ),
            precision_extraction_matting_backend=self._extraction_runtime_config.matting_backend,
            neural_matting_available=neural_status == "available",
            neural_matting_availability_message=neural_message,
            precision_extraction_supports_matting=(
                extraction_descriptor.capabilities.supports_alpha_matting
            ),
            confirmed_extraction_summary=self._confirmed_extraction_summary_text(),
            can_export_extraction=(not busy) and self._service.can_export_active_extraction(),
            can_reveal_extraction=(not busy) and self._service.can_export_active_extraction(),
            can_copy_extraction_reference=(not busy)
            and self._service.can_export_active_extraction(),
            can_deliver_to_host=(not busy)
            and self._service.can_export_active_extraction()
            and self._host_descriptor().availability == "available"
            and bool(self._service.get_available_host_actions(self._selected_host_adapter_id)),
            host_adapter_id=self._selected_host_adapter_id,
            host_adapter_display_name=self._host_descriptor().display_name,
            host_adapter_available=self._host_descriptor().availability == "available",
            host_adapter_availability_message=self._host_descriptor().availability_message,
            host_action=self._selected_host_action,
            suggested_export_filename=self._suggested_export_filename_safe(),
            delivery_summary=self._delivery_summary_text(),
            plugin_summary=self._plugin_summary_text(),
            batch_summary=self._batch_summary_text(),
            batch_running=bool(self._batch_manager and self._batch_manager.is_running),
            batch_awaiting_confirmation=bool(
                self._batch_manager and self._batch_manager.is_awaiting_confirmation
            ),
            batch_current_image=self._batch_current_image_name(),
            batch_confirmation_mode=self._batch_confirmation_mode,
            can_start_batch=self._can_start_batch(),
            can_cancel_batch=bool(self._batch_manager and self._batch_manager.is_running),
            can_retry_batch_failed=self._can_retry_batch_failed(),
            status_message=self._status,
        )

    def list_core_inference_providers(self) -> list[ProviderDescriptor]:
        return self._registry.list(self._runtime_config)

    def supported_core_inference_providers(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.list_core_inference_providers())

    def set_core_inference_provider(self, provider: str) -> None:
        try:
            if self._service.has_running_operation():
                raise ApplicationError(
                    "OPERATION_IN_PROGRESS",
                    "cannot switch core inference provider while Generate is running",
                )
            provider_id = str(provider).strip().lower()
            if not self._registry.contains(provider_id):
                raise ApplicationError(
                    "INVALID_PROVIDER_CONFIG",
                    f"unknown core inference provider: {provider_id!r}",
                )
            descriptor = self._registry.get(provider_id)
            if descriptor.availability != "available":
                raise ApplicationError(
                    "PROVIDER_UNAVAILABLE",
                    descriptor.availability_message
                    or f"provider unavailable: {provider_id}",
                )
            config = self._runtime_config.with_provider(provider_id)
            engine = self._registry.create(provider_id, config)
            self._service.set_inference_engine(
                engine,
                capabilities=descriptor.capabilities,
            )
            self._runtime_config = config
            self._core_inference_provider = provider_id
            self._workspace.set_selected_provider_id(provider_id)
            self._status = f"Core Inference provider set to '{descriptor.display_name}'."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def list_precision_extraction_providers(self) -> list[ExtractionProviderDescriptor]:
        return self._extraction_registry.list(self._extraction_runtime_config)

    def set_precision_extraction_provider(self, provider: str) -> None:
        try:
            if self._service.has_running_operation():
                raise ApplicationError(
                    "OPERATION_IN_PROGRESS",
                    "cannot switch extraction provider while an operation is running",
                )
            provider_id = str(provider).strip().lower()
            if not self._extraction_registry.contains(provider_id):
                raise ApplicationError(
                    "INVALID_PROVIDER_CONFIG",
                    f"unknown extraction provider: {provider_id!r}",
                )
            descriptor = self._extraction_registry.get(provider_id)
            if descriptor.availability != "available":
                raise ApplicationError(
                    "PROVIDER_UNAVAILABLE",
                    descriptor.availability_message
                    or f"provider unavailable: {provider_id}",
                )
            config = self._extraction_runtime_config.with_provider(provider_id)
            engine = self._extraction_registry.create(provider_id, config)
            self._service.set_extraction_engine(engine)
            self._service.set_extraction_settings(config.settings_snapshot())
            self._extraction_runtime_config = config
            self._precision_extraction_provider = provider_id
            self._workspace.set_selected_extraction_provider_id(provider_id)
            self._status = f"Precision Extraction provider set to '{descriptor.display_name}'."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def set_extraction_refinement(
        self,
        *,
        edge_blur_radius: float | None = None,
        feather_radius: float | None = None,
        cleanup_radius: int | None = None,
        expand_contract_pixels: int | None = None,
        premultiply_alpha: bool | None = None,
        matting_unknown_radius: int | None = None,
        matting_refinement_strength: float | None = None,
        matting_preserve_known_regions: bool | None = None,
        matting_backend: str | None = None,
    ) -> None:
        try:
            if self._service.has_running_operation():
                raise ApplicationError(
                    "OPERATION_IN_PROGRESS",
                    "cannot change extraction settings while an operation is running",
                )
            backend = None
            if matting_backend is not None:
                normalized = str(matting_backend).strip().lower()
                if normalized not in {"color_affinity", "neural_onnx"}:
                    raise ApplicationError(
                        "INVALID_PROVIDER_CONFIG",
                        f"unsupported matting backend: {matting_backend!r}",
                    )
                backend = normalized  # type: ignore[assignment]
            config = self._extraction_runtime_config.with_refinement(
                edge_blur_radius=edge_blur_radius,
                feather_radius=feather_radius,
                cleanup_radius=cleanup_radius,
                expand_contract_pixels=expand_contract_pixels,
                premultiply_alpha=premultiply_alpha,
                matting_unknown_radius=matting_unknown_radius,
                matting_refinement_strength=matting_refinement_strength,
                matting_preserve_known_regions=matting_preserve_known_regions,
                matting_backend=backend,
            )
            # Keep the existing provider instance; settings are applied via
            # ExtractionSettings on the Application and provider_options on extract.
            # Recreate only when matting backend id changes so Neural session cache
            # follows the selected backend without silent fallback.
            if backend is not None and backend != self._extraction_runtime_config.matting_backend:
                engine = self._extraction_registry.create(
                    self._precision_extraction_provider,
                    config,
                )
                self._service.set_extraction_engine(engine)
            self._service.set_extraction_settings(config.settings_snapshot())
            self._extraction_runtime_config = config
            self._status = "Extraction refinement settings updated."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def confirmed_extraction_source_summary(self) -> dict[str, Any] | None:
        return self._service.get_confirmed_extraction_source_summary()

    def _confirmed_extraction_summary_text(self) -> str:
        summary = self._service.get_confirmed_extraction_source_summary()
        if summary is None:
            active = self._service.get_active_extraction_result()
            if active is None:
                return "No confirmed candidate"
            dims = ""
            if active.width and active.height:
                dims = f" · output {active.width}x{active.height}"
            return (
                f"Legacy extraction · {active.provider_id} · "
                f"rev {active.revision}{dims}"
            )
        seq = summary.get("sequence_number")
        cand = summary.get("candidate_index")
        conf = summary.get("confidence")
        parts = [
            f"Gen #{seq}" if seq is not None else "Confirmed generation",
            f"candidate {cand}" if cand is not None else "candidate",
        ]
        if conf is not None:
            parts.append(f"conf {conf:.2f}")
        parts.append(f"mask {summary.get('mask_provider_id')}")
        if summary.get("artist_intent_revision") is not None:
            parts.append(f"intent r{summary['artist_intent_revision']}")
        active = self._service.get_active_extraction_result()
        if active is not None and active.width and active.height:
            parts.append(f"output {active.width}x{active.height}")
            parts.append(active.provider_id)
            if active.provider_id == "local.matting":
                parts.append("Alpha Matting")
            elif active.provider_metadata.get("quality_mode") == "alpha_matting":
                parts.append("Alpha Matting")
        return " · ".join(str(part) for part in parts if part)

    def available_host_actions(self, adapter_id: str | None = None) -> tuple[str, ...]:
        target = adapter_id or self._selected_host_adapter_id
        return self._service.get_available_host_actions(target)

    def list_host_adapters(self) -> list[HostAdapterDescriptor]:
        return self._service.get_host_adapters()

    def set_host_adapter(self, adapter_id: str) -> None:
        try:
            descriptor = self._service.get_host_adapter(adapter_id)
            self._selected_host_adapter_id = descriptor.adapter_id
            self._workspace.set_selected_host_adapter_id(descriptor.adapter_id)
            actions = self._service.get_available_host_actions(adapter_id)
            if actions and self._selected_host_action not in actions:
                self._selected_host_action = actions[0]
            self._status = f"Host set to '{descriptor.display_name}'."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def set_host_action(self, action: str) -> None:
        actions = self._service.get_available_host_actions(self._selected_host_adapter_id)
        if action not in actions:
            self.error_occurred.emit(f"UNSUPPORTED_HOST_ACTION: {action}")
            self.state_changed.emit()
            return
        self._selected_host_action = action
        self.state_changed.emit()

    def refresh_host_adapters(self) -> None:
        try:
            self._service.refresh_host_availability()
            self._sync_host_selection_defaults()
            self._status = "Host adapter availability refreshed."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def suggested_export_filename(self) -> str:
        return self._suggested_export_filename_safe()

    def export_confirmed_extraction(
        self,
        destination: str | Path,
        *,
        allow_overwrite: bool = False,
    ) -> bool:
        try:
            success = self._service.export_active_extraction(
                destination,
                allow_overwrite=allow_overwrite,
            )
            self._last_export_destination = success.output_reference
            self._status = f"Exported to {success.output_reference}"
            self.state_changed.emit()
            return True
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def reveal_committed_extraction(self) -> bool:
        try:
            success = self._service.reveal_active_extraction()
            self._status = f"Revealed {success.output_reference}"
            self.state_changed.emit()
            return True
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def reveal_last_export(self) -> bool:
        try:
            success = self._service.reveal_last_export()
            self._status = f"Revealed {success.output_reference}"
            self.state_changed.emit()
            return True
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def copy_extraction_path(self) -> bool:
        return self._copy_reference("absolute_path")

    def copy_extraction_file_uri(self) -> bool:
        return self._copy_reference("file_uri")

    def deliver_to_host(self, adapter_id: str | None = None, action: str | None = None) -> bool:
        try:
            selected_adapter = adapter_id or self._selected_host_adapter_id
            selected_action = action or self._selected_host_action
            success = self._service.deliver_active_extraction(
                selected_adapter,
                selected_action,
            )
            self._status = (
                f"{success.host_display_name}: {success.action} → {success.output_reference}"
            )
            self.state_changed.emit()
            return True
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def last_delivery_summary(self) -> DeliverySummary | None:
        return self._service.get_last_successful_delivery()

    def _copy_reference(self, reference_type: ReferenceType) -> bool:
        try:
            text = self._service.copy_active_extraction_reference(reference_type)
            self._status = f"Copied {reference_type}: {text}"
            self.state_changed.emit()
            return True
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def list_plugins(self) -> list[PluginInfo]:
        return self._plugin_manager.list_plugins()

    def set_plugin_configuration(
        self,
        plugin_id: str,
        configuration: dict[str, Any],
    ) -> None:
        self._plugin_manager.set_plugin_configuration(plugin_id, configuration)
        self._workspace.set_plugin_configuration(plugin_id, configuration)

    def validate_plugin_package(self, package_path: str | Path) -> PackageValidationResult | None:
        try:
            return self._plugin_package_manager.validate(package_path)
        except PluginPackageError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return None

    def list_installed_plugin_packages(self) -> list[InstalledPluginRecord]:
        return self._plugin_package_manager.list_installed()

    def install_plugin_package(
        self,
        package_path: str | Path,
        *,
        replace: bool = False,
        activate: bool = True,
    ) -> InstalledPluginRecord | None:
        try:
            record = self._plugin_package_manager.install(package_path, replace=replace)
            already = self._plugin_manager.get_plugin(record.plugin_id)
            if activate and already is None:
                info = self._plugin_manager.register_plugin_directory(record.install_path)
                if info.availability != "available":
                    self._status = (
                        f"Plugin package installed: {record.plugin_id} v{record.version}. "
                        f"Activation incomplete ({info.failure_reason or info.availability}). "
                        "Fix the plugin or restart, then retry activation."
                    )
                else:
                    self._status = (
                        f"Plugin package installed and activated: "
                        f"{record.plugin_id} v{record.version}."
                    )
            elif already is not None:
                self._status = (
                    f"Plugin package installed: {record.plugin_id} v{record.version}. "
                    "Restart the application to reload the already-registered plugin."
                )
            else:
                self._status = (
                    f"Plugin package installed: {record.plugin_id} v{record.version} "
                    "(activation deferred)."
                )
            self.state_changed.emit()
            return record
        except PluginPackageError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self._status = (
                f"Plugin install failed ({exc.code}). "
                "Validate the package, then retry install."
            )
            self.state_changed.emit()
            return None

    def update_plugin_package(self, package_path: str | Path) -> InstalledPluginRecord | None:
        try:
            record = self._plugin_package_manager.update(package_path)
            self._status = (
                f"Updated {record.plugin_id} to v{record.version}. "
                "Restart required to reload plugin code into registries."
            )
            self.state_changed.emit()
            return record
        except PluginPackageError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return None

    def uninstall_plugin_package(self, plugin_id: str) -> bool:
        try:
            record = self._plugin_package_manager.uninstall(plugin_id)
            self._status = (
                f"Uninstalled {record.plugin_id}. "
                "Provider unregister requires application restart."
            )
            self.state_changed.emit()
            return True
        except PluginPackageError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return False

    def create_batch_job(
        self,
        image_paths: Sequence[str | Path],
        *,
        intent_snapshot: dict[str, Any] | None = None,
        export_directory: str | Path | None = None,
        confirmation_mode: str | None = None,
        enable_automatic_confirmation: bool | None = None,
        selection_policy: str | None = None,
    ) -> BatchJob | None:
        if self._batch_manager is None:
            self.error_occurred.emit("BATCH_UNAVAILABLE: batch manager disabled")
            return None
        try:
            snapshot = intent_snapshot or self._current_intent_snapshot()
            mode = confirmation_mode or self._batch_confirmation_mode
            auto_enabled = (
                self._batch_enable_automatic_confirmation
                if enable_automatic_confirmation is None
                else enable_automatic_confirmation
            )
            policy = selection_policy or self._batch_selection_policy
            job = self._batch_manager.create_job(
                image_paths,
                snapshot,
                export_directory=export_directory,
                confirmation_mode=mode,  # type: ignore[arg-type]
                enable_automatic_confirmation=bool(auto_enabled),
                selection_policy=policy,  # type: ignore[arg-type]
            )
            self._batch_confirmation_mode = job.confirmation_mode
            self._batch_enable_automatic_confirmation = job.enable_automatic_confirmation
            self._batch_selection_policy = job.selection_policy
            self._status = (
                f"Batch queued ({len(job.queue)} images, mode={job.confirmation_mode})."
            )
            self.state_changed.emit()
            return job
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()
            return None

    def set_batch_confirmation_mode(
        self,
        *,
        confirmation_mode: str = "interactive",
        enable_automatic_confirmation: bool = False,
        selection_policy: str = "highest_confidence",
    ) -> None:
        mode = str(confirmation_mode).strip().lower()
        if mode not in {"interactive", "automatic"}:
            self.error_occurred.emit(
                f"INVALID_BATCH_CONFIRMATION_MODE: {confirmation_mode!r}"
            )
            return
        if mode == "automatic" and not enable_automatic_confirmation:
            self.error_occurred.emit(
                "AUTOMATIC_CONFIRMATION_NOT_ENABLED: "
                "automatic mode requires enable_automatic_confirmation=True"
            )
            return
        self._batch_confirmation_mode = mode
        self._batch_enable_automatic_confirmation = bool(enable_automatic_confirmation)
        self._batch_selection_policy = str(selection_policy).strip().lower()
        self._status = (
            f"Batch confirmation mode={mode} "
            f"(automatic_enabled={self._batch_enable_automatic_confirmation})."
        )
        self.state_changed.emit()

    def start_batch(self) -> None:
        if self._batch_manager is None:
            self.error_occurred.emit("BATCH_UNAVAILABLE: batch manager disabled")
            return
        if self._batch_manager.is_running:
            self.error_occurred.emit("BATCH_IN_PROGRESS: batch already running")
            return
        job = self._batch_manager.current_job()
        if job is None:
            self.error_occurred.emit("NO_BATCH_JOB: create a batch queue first")
            return
        self._status = "Batch running…"
        self.state_changed.emit()

        def _worker() -> None:
            try:
                assert self._batch_manager is not None
                finished = self._batch_manager.run(job)
                self._status = (
                    f"Batch {finished.status}: "
                    f"{finished.statistics().completed} completed, "
                    f"{finished.statistics().failed} failed"
                )
            except ApplicationError as exc:
                self.error_occurred.emit(f"{exc.code}: {exc.message}")
            except Exception as exc:  # noqa: BLE001
                self.error_occurred.emit(f"BATCH_FAILED: {exc}")
            finally:
                self.state_changed.emit()

        self._batch_thread = Thread(target=_worker, name="nova-batch", daemon=True)
        self._batch_thread.start()

    def cancel_batch(self) -> None:
        if self._batch_manager is None:
            return
        self._batch_manager.cancel()
        self._status = cancellation_status("batch")
        self.state_changed.emit()

    def retry_batch_failed(self) -> None:
        if self._batch_manager is None:
            return
        try:
            self._batch_manager.retry_failed()
            self._status = "Failed batch items re-queued."
            self.state_changed.emit()
            self.start_batch()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def batch_statistics(self) -> BatchStatistics:
        if self._batch_manager is None:
            return BatchStatistics()
        return self._batch_manager.statistics()

    def recent_batch_history(self) -> list[dict[str, Any]]:
        return self._workspace.recent_batch_history()

    def restore_batch_queue_from_workspace(self) -> BatchJob | None:
        if self._batch_manager is None:
            return None
        try:
            job = self._batch_manager.restore_queue_from_workspace()
            if job is not None:
                self._status = f"Restored batch queue ({len(job.queue)} images)."
                self.state_changed.emit()
            return job
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            return None

    def _on_batch_progress(self, job: BatchJob, item: Any) -> None:
        summary = self._batch_summary_text()
        self.batch_progress.emit(summary)
        self.state_changed.emit()

    def _current_intent_snapshot(self) -> dict[str, Any]:
        project = self._service.project
        if project is not None and project.active_intent_id is not None:
            intent = next(
                (item for item in project.intents if item.id == project.active_intent_id),
                None,
            )
            if intent is not None:
                return intent.instruction.model_dump(by_alias=True)
        # Fall back to pending UI guidance points.
        signals: list[dict[str, Any]] = [
            {"type": "positive_point", "x": point.x, "y": point.y}
            if point.polarity == "positive"
            else {"type": "negative_point", "x": point.x, "y": point.y}
            for point in self._intent_points
        ]
        if self._intent_box is not None:
            x0, y0, x1, y1 = self._intent_box
            left = min(x0, x1)
            top = min(y0, y1)
            signals.append(
                {
                    "type": "bounding_box",
                    "x": left,
                    "y": top,
                    "width": max(x0, x1) - left,
                    "height": max(y0, y1) - top,
                }
            )
        if not signals:
            signals = [{"type": "positive_point", "x": 0.5, "y": 0.5}]
        return {"schema": "nova.intent.guidance.v1", "payload": {"signals": signals}}

    def _batch_summary_text(self) -> str:
        if self._batch_manager is None:
            return "Batch disabled"
        job = self._batch_manager.current_job()
        if job is None:
            history = self._workspace.recent_batch_history()
            if history:
                latest = history[0]
                return (
                    f"No active batch · last job {latest.get('status')} "
                    f"({latest.get('completed', 0)}/{latest.get('image_count', 0)} completed)"
                )
            return "No batch queued"
        stats = job.statistics()
        current = job.current_item()
        current_name = Path(current.image_path).name if current is not None else "—"
        lines = [
            f"Batch {job.status} · {stats.completed}/{stats.total} completed · "
            f"failed={stats.failed} cancelled={stats.cancelled} remaining={stats.remaining}",
            f"Current: {current_name}",
        ]
        if stats.average_time_ms is not None:
            lines.append(f"Avg {stats.average_time_ms:.0f} ms/image")
        if stats.eta_ms is not None:
            lines.append(f"ETA ~{stats.eta_ms:.0f} ms")
        failures = job.failure_summary()
        if failures:
            lines.append("Failures: " + "; ".join(failures[:5]))
        for item in job.queue:
            lines.append(f"- {Path(item.image_path).name}: {item.status}")
        return "\n".join(lines)

    def _batch_current_image_name(self) -> str:
        if self._batch_manager is None:
            return ""
        job = self._batch_manager.current_job()
        if job is None:
            return ""
        current = job.current_item()
        return "" if current is None else Path(current.image_path).name

    def _can_start_batch(self) -> bool:
        if self._batch_manager is None or self._batch_manager.is_running:
            return False
        if self._service.has_running_operation():
            return False
        job = self._batch_manager.current_job()
        if job is None:
            return False
        return any(item.status == "waiting" for item in job.queue)

    def _can_retry_batch_failed(self) -> bool:
        if self._batch_manager is None or self._batch_manager.is_running:
            return False
        job = self._batch_manager.current_job()
        if job is None:
            return False
        return any(item.status == "failed" for item in job.queue)

    def _plugin_summary_text(self) -> str:
        plugins = self._plugin_manager.list_plugins()
        if not plugins:
            return "No plugins discovered"
        available = sum(1 for item in plugins if item.availability == "available")
        unavailable = len(plugins) - available
        lines = [f"{len(plugins)} plugin(s) · {available} available · {unavailable} unavailable"]
        for item in plugins:
            caps = ", ".join(item.capabilities) if item.capabilities else "none"
            reason = f" · {item.failure_reason}" if item.failure_reason else ""
            lines.append(
                f"{item.display_name} v{item.version} [{item.plugin_type}] · "
                f"{item.availability} · caps={caps}{reason}"
            )
        return "\n".join(lines)

    def _neural_matting_probe(self) -> tuple[str, str]:
        return probe_neural_matting_availability(
            model_path=self._extraction_runtime_config.matting_onnx_model_path,
        )

    def _host_descriptor(self) -> HostAdapterDescriptor:
        try:
            return self._service.get_host_adapter(self._selected_host_adapter_id)
        except ApplicationError:
            adapters = self._service.get_host_adapters()
            if not adapters:
                return HostAdapterDescriptor(
                    adapter_id="none",
                    display_name="No Host",
                    adapter_version="0",
                    availability="unavailable",
                    availability_message="No host adapters registered",
                    capabilities=HostAdapterCapabilities(),
                )
            self._selected_host_adapter_id = adapters[0].adapter_id
            return adapters[0]

    def _sync_host_selection_defaults(self) -> None:
        adapters = self._service.get_host_adapters()
        delivery_adapters = [
            item
            for item in adapters
            if item.adapter_id not in {"filesystem", "reveal"}
        ]
        preferred = delivery_adapters or adapters
        if not preferred:
            return
        if not any(item.adapter_id == self._selected_host_adapter_id for item in preferred):
            available = next(
                (item for item in preferred if item.availability == "available"),
                preferred[0],
            )
            self._selected_host_adapter_id = available.adapter_id
        actions = self._service.get_available_host_actions(self._selected_host_adapter_id)
        if actions and self._selected_host_action not in actions:
            self._selected_host_action = actions[0]

    def _suggested_export_filename_safe(self) -> str:
        try:
            return self._service.get_suggested_export_filename()
        except ApplicationError:
            return ""

    def _delivery_summary_text(self) -> str:
        delivery = self._service.get_last_successful_delivery()
        if delivery is None:
            return "No delivery yet"
        alpha = (
            "Premultiplied Alpha"
            if delivery.premultiply_alpha
            else "Straight Alpha"
        )
        dims = ""
        if delivery.width and delivery.height:
            dims = f"{delivery.width} × {delivery.height} RGBA · {alpha}"
        source_bits = []
        if delivery.generation_number is not None:
            source_bits.append(f"Generation {delivery.generation_number}")
        if delivery.candidate_number is not None:
            source_bits.append(f"Candidate {delivery.candidate_number}")
        if delivery.extraction_provider:
            source_bits.append(delivery.extraction_provider)
        lines = []
        if source_bits:
            lines.append("Extraction source: " + " · ".join(source_bits))
        if dims:
            lines.append(f"Output: {dims}")
        lines.append(f"Delivery: {delivery.message}")
        return "\n".join(lines)

    def _selected_descriptor(self) -> ProviderDescriptor:
        provider_id = self._core_inference_provider
        if not self._registry.contains(provider_id):
            provider_id = DEFAULT_PROVIDER
        return next(
            item
            for item in self._registry.list(self._runtime_config)
            if item.provider_id == provider_id
        )

    def _selected_extraction_descriptor(self) -> ExtractionProviderDescriptor:
        provider_id = self._precision_extraction_provider
        if not self._extraction_registry.contains(provider_id):
            provider_id = DEFAULT_EXTRACTION_PROVIDER
        return next(
            item
            for item in self._extraction_registry.list(self._extraction_runtime_config)
            if item.provider_id == provider_id
        )

    def list_intent_revisions(self) -> list[IntentRevisionInfo]:
        project = self._service.project
        if project is None:
            return []
        return [
            IntentRevisionInfo(
                id=item.id,
                revision=item.revision,
                is_active=item.id == project.active_intent_id,
            )
            for item in sorted(project.intents, key=lambda intent: intent.revision)
        ]

    def create_project(self, name: str) -> None:
        try:
            self._service.create_project(name.strip())
            self._runtime_caches.clear()
            self._source_frame = None
            self._mask_overlay = None
            self._extraction_preview = None
            self._clear_preview_state()
            self._intent_points = []
            self._intent_box = None
            self._status = f"Project '{name.strip()}' created (NoSource)."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")

    def load_source(self, path: Path) -> None:
        try:
            source = self._service.load_source(path)
            self._runtime_caches.clear()
            self._source_frame = self._cached_rgb_frame(source.relative_asset_path)
            self._mask_overlay = None
            self._extraction_preview = None
            self._clear_preview_state()
            self._intent_points = []
            self._intent_box = None
            self._status = f"Source loaded: {source.original_filename}"
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")

    def apply_artist_intent(
        self,
        *,
        positive_points: list[tuple[float, float]] | None = None,
        negative_points: list[tuple[float, float]] | None = None,
        points: Sequence[tuple[float, float, str]] | None = None,
        bounding_box: tuple[float, float, float, float] | None,
    ) -> None:
        if points is not None:
            ordered = list(points)
        else:
            ordered = [(x, y, "positive") for x, y in (positive_points or [])]
            ordered.extend((x, y, "negative") for x, y in (negative_points or []))
        instruction = _build_instruction(ordered, bounding_box)
        project = self._service.project
        try:
            previous_id = None if project is None else project.active_intent_id
            previous_revision_count = 0 if project is None else len(project.intents)
            if project is None or project.active_intent_id is None:
                intent = self._service.create_artist_intent(instruction)
                self._status = f"ArtistIntent created (revision {intent.revision})."
            else:
                intent = self._service.update_artist_intent(instruction)
                if previous_id == intent.id and previous_revision_count == len(
                    self._service.project.intents  # type: ignore[union-attr]
                ):
                    self._status = "No effective ArtistIntent changes."
                else:
                    self._mask_overlay = None
                    self._extraction_preview = None
                    self._clear_preview_state()
                    self._status = (
                        f"ArtistIntent updated to revision {intent.revision}; "
                        "hypothesis invalidated."
                    )
            self._intent_points = [
                PromptPointView(x=x, y=y, polarity=polarity) for x, y, polarity in ordered
            ]
            self._intent_box = bounding_box
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")

    def cancel_pending_edits(self) -> None:
        """Discard unapplied viewer edits by restoring the active committed intent."""
        project = self._service.project
        if project is None or project.active_intent_id is None:
            self._intent_points = []
            self._intent_box = None
            self._status = "Pending edits discarded."
            self.state_changed.emit()
            return
        self._load_active_intent_into_view()
        self._status = "Pending edits discarded; active intent restored."
        self.state_changed.emit()

    def generate_hypothesis(self) -> None:
        """Synchronous Generate: produces a CandidateSet without auto-selecting."""
        try:
            candidate_set = self._service.generate_candidates()
            self._clear_preview_state()
            self._mask_overlay = None
            self._focused_candidate_id = (
                candidate_set.candidates[0].id if candidate_set.candidates else None
            )
            self._status = (
                f"Candidate set ready ({len(candidate_set.candidates)} candidates)."
            )
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def select_candidate(self, candidate_id: UUID | str) -> None:
        try:
            hypothesis = self._service.select_candidate(candidate_id)
            self._mask_overlay = self._cached_mask_frame(hypothesis.mask_relative_path)
            self._extraction_preview = None
            self._clear_preview_state()
            self._focused_candidate_id = UUID(str(candidate_id))
            self._status = (
                f"Candidate selected (confidence {hypothesis.confidence:.2f})."
            )
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def reject_active_generation(self) -> None:
        try:
            self._service.reject_generation()
            self._clear_generation_preview_state()
            self._mask_overlay = None
            self._status = "Generation rejected."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def retry_generation(self) -> None:
        self.start_generate_hypothesis()

    def restore_generation(self, generation_id: UUID | str) -> None:
        try:
            self._service.restore_generation(generation_id)
            self._clear_generation_preview_state()
            self._refresh_mask_from_active_generation()
            self._status = "Generation restored for browsing."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def reactivate_generation(self, generation_id: UUID | str) -> None:
        try:
            self._service.reactivate_generation(generation_id)
            self._clear_generation_preview_state()
            self._refresh_mask_from_active_generation()
            self._status = "Generation reactivated."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def select_previous_generation(self) -> None:
        try:
            previous_id = self._service.get_previous_generation_id()
            if previous_id is None:
                return
            active = self._service.get_active_generation()
            if active is not None and active.generation_id == previous_id:
                return
            self.restore_generation(previous_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def select_next_generation(self) -> None:
        try:
            next_id = self._service.get_next_generation_id()
            if next_id is None:
                return
            active = self._service.get_active_generation()
            if active is not None and active.generation_id == next_id:
                return
            self.restore_generation(next_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def clear_generation_preview_state(self) -> None:
        self._clear_generation_preview_state()
        self.state_changed.emit()

    def list_generation_history(self) -> list[GenerationHistoryItem]:
        project = self._service.project
        if project is None:
            return []
        descriptor = self._selected_descriptor()
        provider_names = {descriptor.provider_id: descriptor.display_name}
        for item in self.list_core_inference_providers():
            provider_names[item.provider_id] = item.display_name
        items: list[GenerationHistoryItem] = []
        for record in self._service.get_generation_history():
            try:
                candidate_set = self._service.get_generation_candidate_set(record.generation_id)
            except ApplicationError:
                continue
            active_confidence: float | None = None
            if candidate_set.active_candidate_id is not None:
                for candidate in candidate_set.candidates:
                    if candidate.id == candidate_set.active_candidate_id:
                        active_confidence = float(candidate.confidence)
                        break
            items.append(
                GenerationHistoryItem(
                    generation_id=record.generation_id,
                    sequence_number=record.sequence_number,
                    artist_intent_revision=record.artist_intent_revision,
                    provider_id=record.provider_id,
                    provider_display_name=provider_names.get(
                        record.provider_id,
                        record.provider_id,
                    ),
                    candidate_count=len(candidate_set.candidates),
                    active_candidate_confidence=active_confidence,
                    status=record.status,
                    is_active=project.active_generation_id == record.generation_id,
                    created_at=record.created_at.isoformat(),
                )
            )
        return items

    def select_next_candidate(self) -> None:
        try:
            anchor = self._navigation_anchor_id()
            next_id = self._service.get_next_candidate_id(anchor)
            if next_id is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            self.select_candidate(next_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def select_previous_candidate(self) -> None:
        try:
            anchor = self._navigation_anchor_id()
            prev_id = self._service.get_previous_candidate_id(anchor)
            if prev_id is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            self.select_candidate(prev_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def focus_next_candidate(self) -> None:
        """Move focus/preview forward without committing selection (Option A clamp)."""
        try:
            anchor = self._navigation_anchor_id()
            next_id = self._service.get_next_candidate_id(anchor)
            if next_id is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            self._focused_candidate_id = next_id
            self.preview_candidate(next_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def focus_previous_candidate(self) -> None:
        """Move focus/preview backward without committing selection (Option A clamp)."""
        try:
            anchor = self._navigation_anchor_id()
            prev_id = self._service.get_previous_candidate_id(anchor)
            if prev_id is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            self._focused_candidate_id = prev_id
            self.preview_candidate(prev_id)
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def preview_candidate(self, candidate_id: UUID | str) -> None:
        try:
            if self._service.get_active_candidate_set() is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            candidate = self._service.get_candidate(candidate_id)
            self._preview_mask = self._cached_mask_frame(candidate.mask_relative_path)
            self._preview_candidate_id = candidate.id
            self._focused_candidate_id = candidate.id
            self.state_changed.emit()
        except ApplicationError as exc:
            # Preserve committed active preview; do not clear active_candidate_id.
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def clear_candidate_preview(self) -> None:
        changed = (
            self._preview_candidate_id is not None
            or self._preview_mask is not None
            or self._comparison_mode
        )
        self._clear_preview_state()
        if changed:
            self.state_changed.emit()

    def toggle_candidate_comparison(self) -> None:
        """Compare toggle: show focused candidate vs committed active candidate."""
        try:
            if self._service.get_active_candidate_set() is None:
                raise ApplicationError("NO_ACTIVE_CANDIDATE_SET", "no active CandidateSet")
            if self._comparison_mode:
                self._comparison_mode = False
                self._clear_preview_state(keep_focus=True)
                self.state_changed.emit()
                return
            focus_id = self._focused_candidate_id
            if focus_id is None:
                focus_id = self._service.get_next_candidate_id()
            if focus_id is None:
                raise ApplicationError("CANDIDATE_NOT_FOUND", "no candidate available to compare")
            active = self._service.get_active_candidate()
            if active is not None and active.id == focus_id:
                # Prefer a different focused candidate when possible.
                nxt = self._service.get_next_candidate_id(focus_id)
                if nxt is not None and nxt != focus_id:
                    focus_id = nxt
            self._comparison_mode = True
            self._focused_candidate_id = focus_id
            self.preview_candidate(focus_id)
            self._status = "Comparison preview (toggle again to restore active)."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def commit_focused_or_previewed_candidate(self) -> None:
        target = self._preview_candidate_id or self._focused_candidate_id
        if target is None:
            active = self._service.get_active_candidate()
            if active is None:
                self.error_occurred.emit("NO_ACTIVE_CANDIDATE: no candidate to select")
                return
            target = active.id
        self.select_candidate(target)

    def select_candidate_by_index(self, index: int) -> None:
        candidate_set = self._service.get_active_candidate_set()
        if candidate_set is None:
            self.error_occurred.emit("NO_ACTIVE_CANDIDATE_SET: no active CandidateSet")
            self.state_changed.emit()
            return
        if index < 0 or index >= len(candidate_set.candidates):
            self.error_occurred.emit(f"CANDIDATE_NOT_FOUND: no candidate at index {index + 1}")
            self.state_changed.emit()
            return
        self.select_candidate(candidate_set.candidates[index].id)

    def list_candidates(self) -> list[CandidateViewItem]:
        project = self._service.project
        if project is None or project.active_candidate_set_id is None:
            return []
        candidate_set = next(
            item for item in project.candidate_sets if item.id == project.active_candidate_set_id
        )
        items: list[CandidateViewItem] = []
        for index, candidate in enumerate(candidate_set.candidates):
            thumb = None
            try:
                preview_path = candidate.preview_relative_path
                thumb_key = ThumbnailCache.make_key(
                    candidate.id,
                    preview_path=preview_path,
                )

                def _load_thumb(path: str = preview_path) -> NDArray[np.uint8]:
                    return self._cached_mask_frame(path)

                thumb = self._runtime_caches.thumbnails.get_or_decode(thumb_key, _load_thumb)
            except ApplicationError:
                thumb = None
            confidence = float(candidate.confidence)
            confidence_label = f"{confidence:.2f}"
            accessible = (
                f"Candidate {index + 1}, confidence {confidence_label}"
                + (", active" if candidate.id == candidate_set.active_candidate_id else "")
            )
            items.append(
                CandidateViewItem(
                    id=candidate.id,
                    index=index,
                    confidence=confidence,
                    confidence_label=confidence_label,
                    is_active=candidate.id == candidate_set.active_candidate_id,
                    is_previewed=candidate.id == self._preview_candidate_id,
                    is_focused=candidate.id == self._focused_candidate_id,
                    thumbnail_mask=thumb,
                    accessible_name=accessible,
                )
            )
        return items

    def _navigation_anchor_id(self) -> UUID | None:
        if self._focused_candidate_id is not None:
            return self._focused_candidate_id
        if self._preview_candidate_id is not None:
            return self._preview_candidate_id
        active = self._service.get_active_candidate()
        return None if active is None else active.id

    def _clear_preview_state(self, *, keep_focus: bool = False) -> None:
        self._preview_candidate_id = None
        self._preview_mask = None
        self._comparison_mode = False
        if not keep_focus:
            active = self._service.get_active_candidate()
            self._focused_candidate_id = None if active is None else active.id

    def _clear_generation_preview_state(self) -> None:
        self._preview_candidate_id = None
        self._preview_mask = None
        self._comparison_mode = False
        candidate_set = self._service.get_active_candidate_set()
        if candidate_set is not None and candidate_set.candidates:
            if candidate_set.active_candidate_id is not None:
                self._focused_candidate_id = candidate_set.active_candidate_id
            else:
                self._focused_candidate_id = candidate_set.candidates[0].id
        else:
            self._focused_candidate_id = None

    def _refresh_mask_from_active_generation(self) -> None:
        project = self._service.project
        self._mask_overlay = None
        if project is None:
            return
        if project.active_hypothesis_id is not None:
            hypothesis = next(
                item for item in project.hypotheses if item.id == project.active_hypothesis_id
            )
            self._mask_overlay = self._cached_mask_frame(hypothesis.mask_relative_path)
            return
        active = self._service.get_active_candidate()
        if active is not None:
            self._mask_overlay = self._cached_mask_frame(active.mask_relative_path)

    def _generation_is_rejected_active(self) -> bool:
        active = self._service.get_active_generation()
        return active is not None and active.status == "rejected"

    def start_generate_hypothesis(self) -> None:
        try:
            operation_id = self._service.start_generate_hypothesis()
            self._active_operation_id = operation_id
            self._progress_current = 0
            self._progress_total = 3
            self._progress_message = "starting"
            self._status = "Generating hypothesis…"
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def confirm_hypothesis(self) -> None:
        try:
            confirmed = self._service.confirm_hypothesis()
            self._extraction_preview = None
            self._status = f"Object confirmed (revision {confirmed.revision})."
            if self._batch_manager is not None and self._batch_manager.is_awaiting_confirmation:
                self._batch_manager.notify_user_confirmation()
                self._status = (
                    f"Object confirmed (revision {confirmed.revision}); "
                    "batch continuing."
                )
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")

    def generate_extraction(self) -> None:
        """Synchronous convenience wrapper used by headless-style callers."""
        try:
            with self._runtime_caches.monitor.measure("extraction"):
                extraction = self._service.generate_extraction()
            self._extraction_preview = self._cached_extraction_preview(extraction)
            self._status = (
                f"Extraction ready (revision {extraction.revision}, "
                f"confidence {extraction.confidence:.2f})."
            )
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def start_generate_extraction(self) -> None:
        try:
            operation_id = self._service.start_generate_extraction()
            self._active_operation_id = operation_id
            self._progress_current = 0
            self._progress_total = 3
            self._progress_message = "starting"
            self._status = "Generating extraction…"
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    def cancel_running_operation(self) -> None:
        if self._active_operation_id is None:
            return
        cancelled = self._service.cancel_operation(self._active_operation_id)
        if cancelled:
            self._status = cancellation_status("operation")
            self.state_changed.emit()

    def _on_operation_event(self, event: object) -> None:
        self._operation_event.emit(event)

    def _handle_operation_event(self, event: object) -> None:
        from nova_layer.object_workflow.ports.operation_executor import (
            OperationProgress,
            OperationSnapshot,
        )

        if isinstance(event, OperationProgress):
            self._progress_current = event.current
            self._progress_total = event.total
            self._progress_message = event.message
            self.operation_progress.emit(
                event.operation_id,
                event.current,
                event.total,
                event.message,
            )
            self.state_changed.emit()
            return
        if isinstance(event, OperationSnapshot):
            self._active_operation_id = None
            self._progress_message = event.status
            if event.status == "succeeded":
                self._refresh_outputs_after_operation(event.operation_type)
                self._status = f"Operation succeeded ({event.operation_type})."
            elif event.status == "cancelled":
                self._status = (
                    f"Operation cancelled ({event.operation_type}). "
                    "You can retry when ready."
                )
            else:
                self._status = (
                    f"Operation failed ({event.operation_type}): "
                    f"{event.error_message or event.error_code}"
                )
                if event.error_message:
                    self.error_occurred.emit(
                        f"{event.error_code or 'FAILED'}: {event.error_message}"
                    )
            self.operation_finished.emit(event.operation_id, event.status)
            self.state_changed.emit()

    def _refresh_outputs_after_operation(self, operation_type: str) -> None:
        project = self._service.project
        if project is None:
            return
        if operation_type == "generate_hypothesis":
            # New candidates invalidate thumbnail/mask entries for prior sets.
            self._runtime_caches.thumbnails.clear()
            self._runtime_caches.masks.clear()
            self._clear_preview_state()
            self._mask_overlay = None
            if project.active_hypothesis_id is not None:
                hypothesis = next(
                    item for item in project.hypotheses if item.id == project.active_hypothesis_id
                )
                self._mask_overlay = self._cached_mask_frame(hypothesis.mask_relative_path)
            candidate_set = self._service.get_active_candidate_set()
            if candidate_set is not None and candidate_set.candidates:
                if candidate_set.active_candidate_id is not None:
                    self._focused_candidate_id = candidate_set.active_candidate_id
                else:
                    self._focused_candidate_id = candidate_set.candidates[0].id
            self._runtime_caches.monitor.increment("generation_completed")
        if (
            operation_type == "generate_extraction"
            and project.active_extraction_result_id is not None
        ):
            extraction = next(
                item
                for item in project.extraction_results
                if item.id == project.active_extraction_result_id
            )
            self._extraction_preview = self._cached_extraction_preview(extraction)
            self._runtime_caches.monitor.increment("extraction_completed")

    def save_project(self, package_path: Path) -> None:
        try:
            self._service.save_project(package_path)
            self._workspace.set_active_project(package_path)
            self._status = f"Saved: {package_path.name}"
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")

    def load_project(self, package_path: Path) -> None:
        try:
            project = self._service.load_project(package_path)
            self._runtime_caches.clear()
            self._restore_visualization()
            self._workspace.set_active_project(package_path)
            self._status = f"Loaded project '{project.name}'."
            self.state_changed.emit()
        except ApplicationError as exc:
            self.error_occurred.emit(f"{exc.code}: {exc.message}")
            self.state_changed.emit()

    # --- Feature 10 workspace session helpers (RC Sprint 1) ---

    def workspace_manager(self) -> WorkspaceManager:
        return self._workspace

    def recent_projects(self) -> list[str]:
        return self._workspace.recent_projects()

    def persist_window_geometry(self, geometry: Mapping[str, Any]) -> None:
        self._workspace.set_window_geometry(geometry)

    def restore_window_geometry(self) -> dict[str, Any] | None:
        return self._workspace.window_geometry()

    def persist_dock_layout(self, layout: Mapping[str, Any]) -> None:
        self._workspace.set_dock_layout(layout)

    def restore_dock_layout(self) -> dict[str, Any] | None:
        return self._workspace.dock_layout()

    def reset_workspace_session(self) -> None:
        """Clear application workspace state. Projects on disk are untouched."""
        self._workspace.reset_workspace()
        self._status = "Workspace reset."
        self.state_changed.emit()

    def restore_active_project(self) -> bool:
        """Restore the workspace active project if the package still exists."""
        active = self._workspace.active_project()
        if not active:
            return False
        path = Path(active)
        if not path.exists():
            self._workspace.remove_project_reference(path)
            self._status = f"Active project missing; removed reference: {path.name}"
            self.state_changed.emit()
            return False
        try:
            self.load_project(path)
            return True
        except Exception:  # noqa: BLE001
            return False

    def reopen_last_project(self) -> bool:
        """Open the most recent project from workspace history."""
        recent = self._workspace.recent_projects()
        for item in recent:
            path = Path(item)
            if path.exists():
                self.load_project(path)
                return True
            self._workspace.remove_project_reference(path)
        self._status = "No recent projects available."
        self.state_changed.emit()
        return False

    def shutdown(self) -> None:
        """Coordinated application shutdown — no resource leaks."""
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        try:
            if self._active_operation_id is not None:
                self._service.cancel_operation(self._active_operation_id)
        except Exception:  # noqa: BLE001
            pass
        if self._batch_manager is not None and self._batch_manager.is_running:
            try:
                self._batch_manager.cancel()
            except Exception:  # noqa: BLE001
                pass
        if self._batch_thread is not None and self._batch_thread.is_alive():
            self._batch_thread.join(timeout=2.0)
        try:
            self._workspace.save()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._plugin_manager.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._runtime_caches.clear()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._service.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def _restore_visualization(self) -> None:
        project = self._service.project
        self._source_frame = None
        self._mask_overlay = None
        self._extraction_preview = None
        self._clear_preview_state()
        self._intent_points = []
        self._intent_box = None
        if project is None:
            return
        if project.active_source_image_id is not None:
            source = next(
                item for item in project.source_images if item.id == project.active_source_image_id
            )
            self._source_frame = self._cached_rgb_frame(source.relative_asset_path)
        self._load_active_intent_into_view()
        mask_path = None
        if project.active_confirmed_object_id is not None:
            confirmed = next(
                item
                for item in project.confirmed_objects
                if item.id == project.active_confirmed_object_id
            )
            mask_path = confirmed.mask_relative_path
        elif project.active_hypothesis_id is not None:
            hypothesis = next(
                item for item in project.hypotheses if item.id == project.active_hypothesis_id
            )
            mask_path = hypothesis.mask_relative_path
        if mask_path is not None:
            self._mask_overlay = self._cached_mask_frame(mask_path)
        if project.active_extraction_result_id is not None:
            extraction = next(
                item
                for item in project.extraction_results
                if item.id == project.active_extraction_result_id
            )
            self._extraction_preview = self._cached_extraction_preview(extraction)

    def performance_snapshot(self) -> dict[str, CacheStats | int]:
        """Runtime-only debug metrics. Not part of Domain or persistence."""
        snapshot: dict[str, CacheStats | int] = dict(self._runtime_caches.snapshot())
        snapshot["image_cache_hit"] = self._runtime_caches.monitor.counter("image_cache_hit")
        snapshot["image_cache_miss"] = self._runtime_caches.monitor.counter("image_cache_miss")
        snapshot["mask_cache_hit"] = self._runtime_caches.monitor.counter("mask_cache_hit")
        snapshot["mask_cache_miss"] = self._runtime_caches.monitor.counter("mask_cache_miss")
        snapshot["thumbnail_cache_hit"] = self._runtime_caches.monitor.counter(
            "thumbnail_cache_hit"
        )
        snapshot["thumbnail_cache_miss"] = self._runtime_caches.monitor.counter(
            "thumbnail_cache_miss"
        )
        snapshot["preview_cache_hit"] = self._runtime_caches.monitor.counter("preview_cache_hit")
        snapshot["preview_cache_miss"] = self._runtime_caches.monitor.counter(
            "preview_cache_miss"
        )
        return snapshot

    def _cached_rgb_frame(self, relative_path: str) -> NDArray[np.uint8]:
        return self._runtime_caches.images.get_or_decode(
            relative_path,
            lambda: _decode_rgb_image(self._service.get_asset_bytes(relative_path)),
        )

    def _cached_mask_frame(self, relative_path: str) -> NDArray[np.uint8]:
        return self._runtime_caches.masks.get_or_decode(
            relative_path,
            lambda: _decode_grayscale_mask(self._service.get_asset_bytes(relative_path)),
        )

    def _cached_extraction_preview(self, extraction: object) -> NDArray[np.uint8]:
        from nova_layer.object_workflow.domain.models import ExtractionResult

        assert isinstance(extraction, ExtractionResult)
        self._runtime_caches.previews.invalidate_unless(extraction.id)
        key = self._runtime_caches.previews.make_key(extraction.id, scale=1.0)

        def _decode() -> NDArray[np.uint8]:
            width, height, data = decode_rgba_png_bytes(
                self._service.get_asset_bytes(extraction.relative_asset_path)
            )
            return np.frombuffer(data, dtype=np.uint8).reshape((height, width, 4)).copy()

        return self._runtime_caches.previews.get_or_decode(key, _decode)

    def _load_active_intent_into_view(self) -> None:
        project = self._service.project
        self._intent_points = []
        self._intent_box = None
        if project is None or project.active_intent_id is None:
            return
        intent = next(item for item in project.intents if item.id == project.active_intent_id)
        for signal in intent.instruction.payload.signals:
            signal_type = signal.get("type")
            if signal_type == "positive_point":
                self._intent_points.append(
                    PromptPointView(
                        x=float(signal["x"]),
                        y=float(signal["y"]),
                        polarity="positive",
                    )
                )
            elif signal_type == "negative_point":
                self._intent_points.append(
                    PromptPointView(
                        x=float(signal["x"]),
                        y=float(signal["y"]),
                        polarity="negative",
                    )
                )
            elif signal_type == "bounding_box" and self._intent_box is None:
                self._intent_box = (
                    float(signal["x"]),
                    float(signal["y"]),
                    float(signal["width"]),
                    float(signal["height"]),
                )


def _capability_summary(descriptor: ProviderDescriptor) -> str:
    caps = descriptor.capabilities
    parts: list[str] = []
    if caps.supports_positive_point:
        parts.append("point")
    if caps.supports_bounding_box:
        parts.append("box")
    if caps.supports_negative_point:
        parts.append("neg")
    if caps.supports_scribble:
        parts.append("scribble")
    if caps.supports_mask_prompt:
        parts.append("mask")
    devices: list[str] = []
    if caps.supports_cpu:
        devices.append("cpu")
    if caps.supports_mps:
        devices.append("mps")
    if caps.supports_gpu:
        devices.append("gpu")
    prompt = "+".join(parts) if parts else "none"
    device = "/".join(devices) if devices else "n/a"
    return f"{prompt}; devices={device}"


def _build_instruction(
    points: list[tuple[float, float, str]],
    bounding_box: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    """Build engine-neutral ArtistIntent.

    Ordering: points in the supplied order (PositivePoint / NegativePoint), then
    a single BoundingBox when present.
    """
    signals: list[dict[str, Any]] = []
    for x, y, polarity in points:
        if polarity == "negative":
            signals.append({"type": "negative_point", "x": x, "y": y})
        else:
            signals.append({"type": "positive_point", "x": x, "y": y})
    if bounding_box is not None:
        signals.append(
            {
                "type": "bounding_box",
                "x": bounding_box[0],
                "y": bounding_box[1],
                "width": bounding_box[2],
                "height": bounding_box[3],
            }
        )
    return {"schema": "nova.intent.guidance.v1", "payload": {"signals": signals}}


def _decode_rgb_image(payload: bytes) -> NDArray[np.uint8]:
    image = QImage.fromData(payload)
    if image.isNull():
        raise ApplicationError("IMAGE_DECODE_FAILED", "could not decode source image")
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    width = image.width()
    height = image.height()
    bytes_per_line = image.bytesPerLine()
    ptr = image.constBits()
    buffer = np.frombuffer(ptr, dtype=np.uint8, count=bytes_per_line * height).reshape(
        (height, bytes_per_line)
    )
    rgb = np.ascontiguousarray(buffer[:, : width * 3]).reshape((height, width, 3))
    return rgb.copy()


def _decode_grayscale_mask(payload: bytes) -> NDArray[np.uint8]:
    image = QImage.fromData(payload)
    if image.isNull():
        raise ApplicationError("IMAGE_DECODE_FAILED", "could not decode mask")
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width = image.width()
    height = image.height()
    bytes_per_line = image.bytesPerLine()
    ptr = image.constBits()
    buffer = np.frombuffer(ptr, dtype=np.uint8, count=bytes_per_line * height).reshape(
        (height, bytes_per_line)
    )
    return np.ascontiguousarray(buffer[:, :width]).copy()


class _QtClipboardWriter:
    def write_text(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Qt clipboard is unavailable")
        clipboard.setText(text)
