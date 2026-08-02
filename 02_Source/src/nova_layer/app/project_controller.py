from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from hashlib import file_digest
from pathlib import Path
from shutil import rmtree
from threading import Event
from time import perf_counter
from typing import Literal, cast
from uuid import UUID, uuid4

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, Signal

from nova_layer.adapters.capabilities.mock import (
    MockPropagationCapability,
    MockSegmentationCapability,
    MockSkeletonDetectionCapability,
    MockSkeletonTrackingCapability,
)
from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
    LegacyDisplayTransform,
)
from nova_layer.adapters.media.image_sequence_reader import (
    ImageSequenceReader,
    _load_openimageio,
    list_sequence_files,
)
from nova_layer.adapters.media.media_reader_factory import MediaReaderFactory
from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.adapters.persistence.json_store import JsonProjectStore, ProjectStoreError
from nova_layer.adapters.persistence.mask_store import MaskStoreError, PngMaskStore
from nova_layer.adapters.persistence.preview_store import PngPreviewStore, PreviewStoreError
from nova_layer.adapters.color.settings import ResolvedColorSettings
from nova_layer.app.color_pipeline_diagnostics import (
    ColorPipelineDiagnostics,
    build_color_pipeline_diagnostics,
)
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.job_service import JobResult, ProcessingJobService, ProgressCallback
from nova_layer.app.maturity import MaturityPromotionError, promote_to_production_ready
from nova_layer.app.preview_extraction import compose_rgba
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.range_decode import RangeDecodeStats, decode_frame_range
from nova_layer.app.render_color_metadata import (
    build_render_color_metadata,
    load_render_color_metadata,
    validate_render_color_policy,
    write_render_color_metadata,
)
from nova_layer.app.skeleton_fusion import create_fusion_candidate
from nova_layer.app.video_extraction_service import (
    FrameExtractionInput,
    PROVIDER_ID as BACKGROUND_REMOVAL_PROVIDER_ID,
    VideoExtractionError,
    VideoExtractionService,
    load_background_removal_engine,
    resolve_background_removal_engine_path,
)
from nova_layer.benchmark_dataset import DatasetExport, export_validated_master_case
from nova_layer.depth_pose_dataset import DepthPoseDatasetExport, export_case
from nova_layer.domain.models import (
    ArtistIntent,
    BoundingRegion,
    CapabilityProvenance,
    EvidenceRecord,
    ExtractionPreview,
    FrameResult,
    GuidancePoint,
    LifecycleState,
    MaturityState,
    MediaLinkState,
    MediaReference,
    Project,
    ReasoningRecord,
    Sequence,
    Shot,
    SkeletonCorrection,
    SkeletonFusionCandidate,
    SkeletonGuidance,
    SmartLayer,
    SmartLayerRender,
    TemporalIdentityObservation,
    TemporalSkeletonObservation,
    ValidationState,
)
from nova_layer.export.smart_layer import (
    ExportFormat,
    SmartLayerExportError,
    export_smart_layer_assets,
)
from nova_layer.object_workflow.ports.extraction_provider import ExtractionRuntimeConfig
from nova_layer.ports.capabilities import (
    InteractiveSegmentationCapability,
    PropagationResult,
    SegmentationResult,
    SkeletonDetectionCapability,
    SkeletonDetectionResult,
    SkeletonTrackingCapability,
    SkeletonTrackingResult,
    TemporalPropagationCapability,
    VideoFrame,
)
from nova_layer.ports.media import MediaReadError, MediaReader


@dataclass(frozen=True, slots=True)
class HypothesisJobOutput:
    shot_id: UUID
    master_frame: int
    result: SegmentationResult


@dataclass(frozen=True, slots=True)
class SmartLayerRenderJobOutput:
    shot_id: UUID
    layer_id: UUID
    layer_version: int
    render_version: int
    staging_path: Path
    frames: tuple[ExtractionPreview, ...]
    color_policy_metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PropagationJobOutput:
    mask_results: tuple[PropagationResult, ...]
    skeleton_results: tuple[SkeletonTrackingResult, ...]
    requested_frames: tuple[int, ...] = ()
    duplicate_frames: tuple[int, ...] = ()
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class SkeletonRetrackingJobOutput:
    shot_id: UUID
    layer_id: UUID
    layer_version: int
    results: tuple[SkeletonTrackingResult, ...]


@dataclass(frozen=True, slots=True)
class SkeletonFusionDetectionJobOutput:
    shot_id: UUID
    layer_id: UUID
    layer_version: int
    frame_number: int
    result: SkeletonDetectionResult


@dataclass(frozen=True, slots=True)
class BackgroundRemovalClipReadiness:
    """Application gate for Process Clip (Background Removal)."""

    ready: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PropagationDiagnostics:
    """Diagnostics for full-range Object Identity propagation."""

    requested_frames: tuple[int, ...]
    produced_frames: tuple[int, ...]
    duplicate_frames: tuple[int, ...]
    missing_frames: tuple[int, ...]
    materialized_file_count: int
    duration_seconds: float
    mode: Literal["mock", "real"]
    complete: bool


@dataclass(frozen=True, slots=True)
class ClipDecodeDiagnostics:
    """Diagnostics for Background Removal / Smart Layer range decode."""

    range_size: int
    cache_hits: int
    decoder_opens: int
    decoded_frames: int
    decode_seconds: float
    extraction_seconds: float
    total_seconds: float
    frame_order: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RenderIntegrityReport:
    version: int
    valid: bool
    checked_files: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RenderComparisonReport:
    base_version: int
    target_version: int
    identical: bool
    shared_frames: int
    added_frames: tuple[int, ...]
    removed_frames: tuple[int, ...]
    changed_frames: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RenderAuditReport:
    version: int
    source_layer_version: int
    frame_start: int
    frame_end: int
    frame_count: int
    storage_bytes: int
    protected: bool
    integrity_valid: bool
    issues: tuple[str, ...]
    created_at: str


class ProjectController(QObject):
    identity_confidence_threshold = 0.60
    project_changed = Signal(object)
    project_recovered = Signal(object)
    shot_changed = Signal(object)
    guidance_changed = Signal(object)
    hypothesis_ready = Signal(int, object, float)
    hypothesis_state_changed = Signal(str)
    validation_ready = Signal(object)
    validation_state_changed = Signal(object)
    correction_applied = Signal(int, object, float)
    processing_started = Signal(str)
    processing_progress = Signal(str, int, int, str)
    processing_finished = Signal(str)
    processing_cancelled = Signal(str)
    extraction_preview_ready = Signal(int, object, str)
    smart_layer_render_ready = Signal(object)
    background_removal_preview_ready = Signal(int, object)
    smart_layer_export_ready = Signal(str)
    render_integrity_ready = Signal(object)
    render_protection_changed = Signal(int, bool)
    render_comparison_ready = Signal(object)
    render_deleted = Signal(int)
    benchmark_case_exported = Signal(str, str)
    depth_pose_case_exported = Signal(str, str, str)
    skeleton_tracking_ready = Signal(object)
    skeleton_correction_applied = Signal(int, object)
    skeleton_correction_removed = Signal(int, object)
    skeleton_retracking_ready = Signal(object)
    skeleton_fusion_candidate_ready = Signal(object)
    skeleton_fusion_reviewed = Signal(object)
    production_ready_changed = Signal(object)
    media_link_state_changed = Signal(str, str)
    recovery_available = Signal(str)
    recovery_resolved = Signal(str)
    project_migrated = Signal(object)
    frame_ready = Signal(int, object)
    error_occurred = Signal(str)

    def __init__(
        self,
        store: JsonProjectStore | None = None,
        media_reader: MediaReader | None = None,
        segmentation: InteractiveSegmentationCapability | None = None,
        propagation: TemporalPropagationCapability | None = None,
        skeleton_tracking: SkeletonTrackingCapability | None = None,
        skeleton_detection: SkeletonDetectionCapability | None = None,
        mask_store: PngMaskStore | None = None,
        preview_store: PngPreviewStore | None = None,
        display_transform: DisplayTransformProtocol | None = None,
    ) -> None:
        super().__init__()
        self._store = store or JsonProjectStore()
        self._display_transform = display_transform
        self._preview_frame_number: int | None = None
        self._media_reader_injected = media_reader is not None
        self._media_reader = media_reader or PyAvMediaReader()
        self._frame_decoder = FrameDecodeService(
            self._media_reader,
            display_transform=self._display_transform,
        )
        self._frame_decoder.frame_ready.connect(self.frame_ready)
        self._frame_decoder.error_occurred.connect(self.error_occurred)
        self._segmentation = segmentation or MockSegmentationCapability()
        self._propagation = propagation or MockPropagationCapability()
        self._skeleton_tracking = skeleton_tracking or MockSkeletonTrackingCapability()
        self._skeleton_detection = skeleton_detection or MockSkeletonDetectionCapability()
        self._mask_store = mask_store or PngMaskStore()
        self._preview_store = preview_store or PngPreviewStore()
        self._jobs = ProcessingJobService()
        self._jobs.started.connect(self.processing_started)
        self._jobs.progress.connect(self.processing_progress)
        self._jobs.completed.connect(self._job_completed)
        self._jobs.cancelled.connect(self.processing_cancelled)
        self._jobs.failed.connect(self._job_failed)
        self._project: Project | None = None
        self._package_path: Path | None = None
        self._background_removal_service: VideoExtractionService | None = None
        self.last_propagation_diagnostics: PropagationDiagnostics | None = None
        self.last_clip_decode_diagnostics: ClipDecodeDiagnostics | None = None
        self._last_resolved_color_settings: ResolvedColorSettings | None = None
        self._last_render_color_policy: str | None = None

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def package_path(self) -> Path | None:
        return self._package_path

    @property
    def last_resolved_color_settings(self) -> ResolvedColorSettings | None:
        return self._last_resolved_color_settings

    @property
    def last_render_color_policy(self) -> str | None:
        return self._last_render_color_policy

    def record_resolved_color_settings(
        self,
        resolved: ResolvedColorSettings | None,
    ) -> None:
        """Remember the last Color Settings resolve result (no schema mutation)."""
        self._last_resolved_color_settings = resolved

    @property
    def color_pipeline_diagnostics(self) -> ColorPipelineDiagnostics:
        """Safe Viewer Color Pipeline snapshot (ok with no project / shot)."""
        try:
            shot = self.active_shot
        except Exception:
            shot = None
        media_path: str | None = None
        shot_name: str | None = None
        if shot is not None:
            shot_name = getattr(shot, "name", None)
            media = getattr(shot, "media", None)
            source = getattr(media, "source_path", None) if media is not None else None
            if source is not None:
                media_path = str(source)
        policy = self._last_render_color_policy
        if policy is None and shot is not None and self._package_path is not None:
            policy = self._peek_last_render_color_policy(shot)
        try:
            pipeline = self._frame_decoder.pipeline
        except Exception:
            pipeline = None
        return build_color_pipeline_diagnostics(
            pipeline=pipeline,
            transform_diagnostics=self.display_transform_diagnostics,
            transform_identity=(
                None if pipeline is None else pipeline.transform_identity
            ),
            resolved=self._last_resolved_color_settings,
            media_path=media_path,
            shot_name=shot_name,
            last_render_color_policy=policy,
            active_policy="preview",
        )

    def _peek_last_render_color_policy(self, shot: Shot) -> str | None:
        if not shot.smart_layers or self._package_path is None:
            return None
        renders = shot.smart_layers[0].renders
        if not renders:
            return None
        try:
            meta = load_render_color_metadata(self._package_path, renders[-1])
        except Exception:
            return None
        if not meta:
            return None
        value = meta.get("color_policy")
        return str(value) if value is not None else None

    @property
    def display_transform_diagnostics(self) -> DisplayTransformDiagnostics | None:
        """Effective display-transform diagnostics for the active override.

        Policy:
        - Injected transform with a ``diagnostics`` attribute → that value.
        - Injected transform without diagnostics → None.
        - No override (``None``) → LegacyDisplayTransform defaults (sequence default).
        """
        transform = self._display_transform
        if transform is None:
            return LegacyDisplayTransform().diagnostics
        return getattr(transform, "diagnostics", None)

    def set_display_transform(
        self,
        display_transform: DisplayTransformProtocol | None,
    ) -> None:
        """Update color transform; keep EXR raw cache, invalidate previews, re-request."""
        self._display_transform = display_transform
        reader = self._media_reader
        if hasattr(reader, "display_transform"):
            try:
                reader.display_transform = display_transform  # type: ignore[attr-defined]
            except Exception:
                pass
        self._frame_decoder.set_display_transform(display_transform)

        shot = self.active_shot
        if shot is None or shot.media.source_path is None:
            return

        if shot.media.link_state != MediaLinkState.LINKED:
            return

        frames: list[int] = []
        if self._preview_frame_number is not None:
            frames.append(self._preview_frame_number)
        if shot.master_frame not in frames:
            frames.append(shot.master_frame)
        for frame_number in frames:
            self.request_frame(frame_number)

    def create_project(self, name: str, parent_directory: Path) -> Project | None:
        clean_name = name.strip()
        if not clean_name:
            self.error_occurred.emit("Project name is required.")
            return None

        project = Project(name=clean_name)
        package_path = parent_directory / project.package_name
        if package_path.exists():
            self.error_occurred.emit(f"A project already exists at {package_path}.")
            return None

        try:
            self._store.save(project, package_path)
        except ProjectStoreError as exc:
            self.error_occurred.emit(str(exc))
            return None

        self._project = project
        self._package_path = package_path
        self.project_changed.emit(project)
        return project

    @property
    def active_shot(self) -> Shot | None:
        if self._project and self._project.sequences and self._project.sequences[0].shots:
            return self._project.sequences[0].shots[0]
        return None

    def _set_media_reader(self, path: Path) -> None:
        if not self._media_reader_injected:
            self._media_reader = MediaReaderFactory.create(
                path,
                display_transform=self._display_transform,
            )
        elif self._display_transform is not None and hasattr(
            self._media_reader, "display_transform"
        ):
            self._media_reader.display_transform = self._display_transform  # type: ignore[attr-defined]
        self._frame_decoder = FrameDecodeService(
            self._media_reader,
            display_transform=self._display_transform,
        )
        self._frame_decoder.frame_ready.connect(self.frame_ready)
        self._frame_decoder.error_occurred.connect(self.error_occurred)

    def import_media(self, media_path: Path) -> Shot | None:
        if self._project is None or self._package_path is None:
            self.error_occurred.emit("Create or open a project before importing media.")
            return None
        self._set_media_reader(media_path)

        try:
            info = self._media_reader.inspect(media_path)
        except (MediaReadError, OSError, ValueError) as exc:
            self.error_occurred.emit(str(exc))
            return None

        media = MediaReference(
            relative_path=f"media/{info.path.name}",
            source_path=str(info.path),
            fingerprint=info.fingerprint,
            frame_count=info.frame_count,
            frame_rate=info.frame_rate,
            width=info.width,
            height=info.height,
            time_base=info.time_base,
            pixel_format=info.pixel_format,
        )
        end = info.frame_count - 1
        shot = Shot(
            name=info.path.stem,
            media=media,
            range_start=0,
            range_end=end,
            master_frame=end // 2,
        )
        self._project.sequences = [Sequence(name="Sequence 1", shots=[shot])]
        if not self._save_current():
            return None
        self.shot_changed.emit(shot)
        self.request_frame(shot.master_frame)
        return shot

    def validate_media_link(self) -> MediaLinkState | None:
        shot = self.active_shot
        if shot is None or shot.media.source_path is None:
            return None
        source = Path(shot.media.source_path)
        if not source.exists():
            return self._set_media_link_state(
                MediaLinkState.MISSING,
                "Source media is missing. Relink is required.",
            )

        self._set_media_reader(source)

        try:
            info = self._media_reader.inspect(source)
        except (MediaReadError, OSError, ValueError) as exc:
            return self._set_media_link_state(MediaLinkState.MISSING, str(exc))
        if info.fingerprint != shot.media.fingerprint:
            return self._set_media_link_state(
                MediaLinkState.CHANGED,
                "Source media content has changed. Confirm a replacement before processing.",
            )
        return self._set_media_link_state(MediaLinkState.LINKED, "Source media linked.")

    def relink_media(self, media_path: Path, *, accept_changed: bool = False) -> bool:
        shot = self.active_shot
        if shot is None:
            self.error_occurred.emit("No Shot is available for relinking.")
            return False
        self._set_media_reader(media_path)

        try:
            info = self._media_reader.inspect(media_path)
        except (MediaReadError, OSError, ValueError) as exc:
            self.error_occurred.emit(str(exc))
            return False
        fingerprint_changed = info.fingerprint != shot.media.fingerprint
        if fingerprint_changed and not accept_changed:
            self._set_media_link_state(
                MediaLinkState.CHANGED,
                "Replacement content differs from the original. Explicit confirmation is required.",
            )
            return False
        if shot.range_end >= info.frame_count:
            self.error_occurred.emit(
                "Replacement media is shorter than the saved Shot Range and cannot be linked."
            )
            return False

        shot.media.source_path = str(info.path)
        shot.media.relative_path = f"media/{info.path.name}"
        shot.media.fingerprint = info.fingerprint
        shot.media.frame_count = info.frame_count
        shot.media.frame_rate = info.frame_rate
        shot.media.width = info.width
        shot.media.height = info.height
        shot.media.time_base = info.time_base
        shot.media.pixel_format = info.pixel_format
        shot.media.link_state = MediaLinkState.LINKED
        self._frame_decoder.clear()
        if not self._save_current():
            return False
        self.media_link_state_changed.emit(MediaLinkState.LINKED.value, "Source media relinked.")
        self.shot_changed.emit(shot)
        self.request_frame(shot.master_frame)
        return True

    def _set_media_link_state(self, state: MediaLinkState, message: str) -> MediaLinkState:
        shot = self.active_shot
        if shot is not None:
            shot.media.link_state = state
        self.media_link_state_changed.emit(state.value, message)
        return state

    def update_shot_selection(self, range_start: int, range_end: int, master_frame: int) -> bool:
        shot = self.active_shot
        if shot is None:
            self.error_occurred.emit("Import media before setting the Shot Range.")
            return False
        try:
            updated = shot.model_copy(
                update={
                    "range_start": range_start,
                    "range_end": range_end,
                    "master_frame": master_frame,
                }
            )
            updated = Shot.model_validate(updated.model_dump())
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return False
        self._project.sequences[0].shots[0] = updated  # type: ignore[union-attr]
        if not self._save_current():
            return False
        self.shot_changed.emit(updated)
        return True

    def request_frame(self, frame_number: int) -> bool:
        shot = self.active_shot
        if shot is None or shot.media.source_path is None:
            return False
        if shot.media.link_state != MediaLinkState.LINKED:
            self.error_occurred.emit("Relink source media before requesting frames.")
            return False
        try:
            self._frame_decoder.request(Path(shot.media.source_path), frame_number)
        except (OSError, ValueError) as exc:
            self.error_occurred.emit(str(exc))
            return False
        self._preview_frame_number = frame_number
        return True

    def update_artist_guidance(
        self,
        points: list[GuidancePoint],
        bounding_region: BoundingRegion | None,
        skeleton_guidance: SkeletonGuidance | None = None,
    ) -> SmartLayer | None:
        shot = self.active_shot
        if shot is None:
            self.error_occurred.emit("Import media before adding Artist Guidance.")
            return None

        intent = ArtistIntent(
            master_frame=shot.master_frame,
            points=points,
            bounding_region=bounding_region,
            skeleton_guidance=skeleton_guidance or SkeletonGuidance(),
        )
        if shot.smart_layers:
            layer = shot.smart_layers[0].model_copy(update={"artist_intent": intent})
            layer = SmartLayer.model_validate(layer.model_dump())
            shot.smart_layers[0] = layer
        else:
            layer = SmartLayer(artist_intent=intent)
            shot.smart_layers.append(layer)

        if not self._save_current():
            return None
        self.guidance_changed.emit(layer.artist_intent)
        return layer

    def generate_hypothesis(self) -> FrameResult | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit("Add Artist Guidance before generating a hypothesis.")
            return None
        layer = shot.smart_layers[0]
        intent = layer.artist_intent
        if (
            not intent.points
            and not intent.skeleton_guidance.joints
            and intent.bounding_region is None
        ):
            self.error_occurred.emit(
                "At least one point, bone joint, or Bounding Region is required."
            )
            return None

        try:
            result = self._predict_hypothesis(shot, intent)
        except Exception as exc:
            self.error_occurred.emit(f"Interactive segmentation failed: {exc}")
            return None
        return self._commit_hypothesis(result)

    def start_hypothesis(self) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit("Add Artist Guidance before generating a hypothesis.")
            return False
        intent = shot.smart_layers[0].artist_intent.model_copy(deep=True)
        if (
            not intent.points
            and not intent.skeleton_guidance.joints
            and intent.bounding_region is None
        ):
            self.error_occurred.emit(
                "At least one point, bone joint, or Bounding Region is required."
            )
            return False
        shot_snapshot = shot.model_copy(deep=True)

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            report(0, 2, "Decoding Master Frame")
            if cancel_event.is_set():
                return None
            result = self._predict_hypothesis(shot_snapshot, intent)
            report(1, 2, "SAM 2 hypothesis generated")
            if cancel_event.is_set():
                return None
            report(2, 2, "Preparing hypothesis for artist review")
            return HypothesisJobOutput(shot_snapshot.id, shot_snapshot.master_frame, result)

        if not self._jobs.start("interactive_hypothesis", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def _get_source_processing_frame(
        self,
        path: Path,
        frame_number: int,
    ) -> NDArray[np.uint8]:
        """Stable uint8 RGB for SAM / skeleton (SOURCE policy; no viewer look)."""
        frame = self._frame_decoder.get_processing_frame(
            path,
            frame_number,
            policy=ProcessingColorPolicy.SOURCE,
        )
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise TypeError(
                "SOURCE processing frame must be an uint8 ndarray; "
                f"got {type(frame).__name__} dtype={getattr(frame, 'dtype', None)}"
            )
        return frame

    def _predict_hypothesis(self, shot: Shot, intent: ArtistIntent) -> SegmentationResult:
        if shot.media.source_path is None:
            raise ValueError("Source media is not linked.")
        image = self._get_source_processing_frame(
            Path(shot.media.source_path), shot.master_frame
        )
        return self._segmentation.predict(
            frame_number=shot.master_frame,
            image=image,
            width=shot.media.width,
            height=shot.media.height,
            points=[*intent.points, *intent.skeleton_guidance.positive_points()],
            bounding_region=intent.bounding_region,
        )

    def _commit_hypothesis(self, result: SegmentationResult) -> FrameResult | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            return None
        layer = shot.smart_layers[0]
        try:
            self._mask_store.save(self._package_path, result.mask_reference, result.mask)
        except MaskStoreError as exc:
            self.error_occurred.emit(str(exc))
            return None

        evidence = EvidenceRecord(
            source_type="capability",
            frame_number=shot.master_frame,
            payload_reference=result.mask_reference,
            confidence=result.confidence,
            provenance=result.provenance,
        )
        frame_result = FrameResult(
            frame_number=shot.master_frame,
            direction="master",
            mask_reference=result.mask_reference,
            confidence=result.confidence,
            evidence_ids=[evidence.id],
            provenance=result.provenance,
        )
        layer.evidence_history.append(evidence)
        layer.frame_results = [
            existing for existing in layer.frame_results if existing.direction != "master"
        ]
        layer.frame_results.append(frame_result)
        layer.object_identity.lifecycle_state = LifecycleState.CANDIDATE
        layer.object_identity.maturity_state = MaturityState.HYPOTHESIS
        layer.object_identity.confidence = result.confidence
        if not self._save_current():
            return None
        self.hypothesis_ready.emit(shot.master_frame, result.mask, result.confidence)
        self.hypothesis_state_changed.emit("hypothesis")
        return frame_result

    def accept_hypothesis(self) -> bool:
        layer = self._hypothesis_layer()
        if layer is None:
            return False
        frame_result = layer.frame_results[-1]
        previous = layer.object_identity.maturity_state
        frame_result.validation_state = ValidationState.ACCEPTED
        layer.object_identity.maturity_state = MaturityState.CONFIRMED
        layer.object_identity.lifecycle_state = LifecycleState.CONFIRMED
        layer.object_identity.confirmed_subject_reference = frame_result.mask_reference
        layer.reasoning_history.append(
            ReasoningRecord(
                id=uuid4(),
                evidence_ids=frame_result.evidence_ids,
                decision="artist_accepted_object_hypothesis",
                confidence=frame_result.confidence,
                previous_maturity=previous,
                resulting_maturity=MaturityState.CONFIRMED,
                artist_confirmation_required=False,
            )
        )
        if not self._save_current():
            return False
        self.hypothesis_state_changed.emit("confirmed")
        return True

    def reject_hypothesis(self) -> bool:
        layer = self._hypothesis_layer()
        if layer is None:
            return False
        layer.frame_results[-1].validation_state = ValidationState.REJECTED
        layer.reasoning_history.append(
            ReasoningRecord(
                evidence_ids=layer.frame_results[-1].evidence_ids,
                decision="artist_rejected_object_hypothesis",
                confidence=layer.frame_results[-1].confidence,
                previous_maturity=MaturityState.HYPOTHESIS,
                resulting_maturity=MaturityState.HYPOTHESIS,
                artist_confirmation_required=True,
            )
        )
        if not self._save_current():
            return False
        self.hypothesis_state_changed.emit("rejected")
        return True

    def propagate_confirmed_identity(self) -> list[FrameResult]:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit("Confirm an Object Hypothesis before propagation.")
            return []
        layer = shot.smart_layers[0]
        reference = layer.object_identity.confirmed_subject_reference
        if layer.object_identity.maturity_state != MaturityState.CONFIRMED or reference is None:
            self.error_occurred.emit("Object Identity is not confirmed.")
            return []
        try:
            reference_mask = self._mask_store.load(self._package_path, reference)
        except MaskStoreError as exc:
            self.error_occurred.emit(str(exc))
            return []

        targets = self._propagation_mask_targets(shot)
        started = perf_counter()
        frames = self._decode_shot_frames(shot)
        raw_results = self._propagation.propagate(
            master_frame=shot.master_frame,
            target_frames=targets,
            reference_mask=reference,
            reference_mask_data=reference_mask,
            frames=frames,
        )
        results, duplicates = self._normalize_propagation_results(shot, raw_results)
        skeleton_results = self._track_skeleton(layer.artist_intent.skeleton_guidance, shot, frames)
        return self._commit_propagation(
            results,
            skeleton_results,
            requested_frames=targets,
            duplicate_frames=duplicates,
            duration_seconds=perf_counter() - started,
        )

    def start_propagation(self) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit("Confirm an Object Hypothesis before propagation.")
            return False
        layer = shot.smart_layers[0]
        reference = layer.object_identity.confirmed_subject_reference
        if layer.object_identity.maturity_state != MaturityState.CONFIRMED or reference is None:
            self.error_occurred.emit("Object Identity is not confirmed.")
            return False
        try:
            reference_mask = self._mask_store.load(self._package_path, reference)
        except MaskStoreError as exc:
            self.error_occurred.emit(str(exc))
            return False
        targets = self._propagation_mask_targets(shot)

        def operation(
            cancel_event: Event,
            report: ProgressCallback,
        ) -> object:
            if shot.media.source_path is None:
                raise ValueError("Source media is not linked.")
            media_path = Path(shot.media.source_path)
            frame_numbers = list(range(shot.range_start, shot.range_end + 1))
            total = len(frame_numbers) + 1
            report(0, total, "Decoding Shot Range")
            started = perf_counter()
            decoded, _stats = decode_frame_range(
                self._frame_decoder,
                self._media_reader,
                media_path,
                shot.range_start,
                shot.range_end,
                policy=ProcessingColorPolicy.SOURCE,
                should_cancel=cancel_event.is_set,
                report_progress=lambda current, _expected, message: report(
                    current, total, message
                ),
            )
            if cancel_event.is_set():
                return None
            frames = [
                VideoFrame(frame_number=frame_number, image=decoded[frame_number])
                for frame_number in frame_numbers
            ]
            report(len(frame_numbers), total, "Propagating Object Identity in both directions")
            raw_results = self._propagation.propagate(
                master_frame=shot.master_frame,
                target_frames=targets,
                reference_mask=reference,
                reference_mask_data=reference_mask,
                frames=frames,
            )
            results, duplicates = self._normalize_propagation_results(shot, raw_results)
            skeleton_results = self._track_skeleton(
                layer.artist_intent.skeleton_guidance,
                shot,
                frames,
            )
            report(total, total, "Completed bidirectional propagation")
            return PropagationJobOutput(
                tuple(results),
                tuple(skeleton_results),
                requested_frames=tuple(targets),
                duplicate_frames=tuple(duplicates),
                duration_seconds=perf_counter() - started,
            )

        if not self._jobs.start("bidirectional_propagation", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def cancel_processing(self) -> bool:
        return self._jobs.cancel()

    def start_skeleton_retracking(self) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            self.error_occurred.emit("No Smart Layer is available for skeleton retracking.")
            return False
        layer = shot.smart_layers[0]
        if not layer.artist_intent.skeleton_guidance.joints:
            self.error_occurred.emit("Draw a reference skeleton before retracking.")
            return False
        if not layer.skeleton_corrections:
            self.error_occurred.emit("Save at least one pose correction before retracking.")
            return False
        shot_snapshot = shot.model_copy(deep=True)
        layer_snapshot = shot_snapshot.smart_layers[0]

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            frames: list[VideoFrame] = []
            frame_numbers = list(range(shot_snapshot.range_start, shot_snapshot.range_end + 1))
            total = len(frame_numbers) + 1
            if shot_snapshot.media.source_path is None:
                raise ValueError("Source media is not linked.")
            media_path = Path(shot_snapshot.media.source_path)
            for index, frame_number in enumerate(frame_numbers, start=1):
                if cancel_event.is_set():
                    return None
                report(index - 1, total, f"Decoding pose frame {frame_number}")
                frames.append(
                    VideoFrame(
                        frame_number=frame_number,
                        image=self._get_source_processing_frame(media_path, frame_number),
                    )
                )
            report(len(frame_numbers), total, "Retracking from artist pose anchors")
            results = self._track_skeleton(
                layer_snapshot.artist_intent.skeleton_guidance,
                shot_snapshot,
                frames,
            )
            report(total, total, "Completed skeleton-only retracking")
            return SkeletonRetrackingJobOutput(
                shot_id=shot_snapshot.id,
                layer_id=layer_snapshot.id,
                layer_version=layer_snapshot.version,
                results=tuple(results),
            )

        if not self._jobs.start("skeleton_retracking", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def start_skeleton_fusion_detection(self, frame_number: int) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            self.error_occurred.emit("Create Artist Skeleton Guidance before automatic fusion.")
            return False
        layer = shot.smart_layers[0]
        artist_skeleton = layer.artist_intent.skeleton_guidance
        if not artist_skeleton.joints or not artist_skeleton.semantic_joint_map():
            self.error_occurred.emit(
                "Label at least one artist skeleton joint before automatic fusion."
            )
            return False
        if not shot.range_start <= frame_number <= shot.range_end:
            self.error_occurred.emit("Automatic fusion frame is outside the Shot Range.")
            return False
        if shot.media.source_path is None:
            self.error_occurred.emit("Source media is not linked.")
            return False
        shot_id = shot.id
        layer_id = layer.id
        layer_version = layer.version
        media_path = Path(shot.media.source_path)
        artist_snapshot = artist_skeleton.model_copy(deep=True)

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            report(0, 2, f"Decoding fusion frame {frame_number}")
            image = self._get_source_processing_frame(media_path, frame_number)
            if cancel_event.is_set():
                return None
            report(1, 2, "Detecting automatic depth pose")
            result = self._skeleton_detection.detect(
                frame_number=frame_number,
                image=image,
                artist_skeleton=artist_snapshot,
            )
            report(2, 2, "Automatic pose ready for fusion review")
            return SkeletonFusionDetectionJobOutput(
                shot_id=shot_id,
                layer_id=layer_id,
                layer_version=layer_version,
                frame_number=frame_number,
                result=result,
            )

        if not self._jobs.start("skeleton_fusion_detection", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def _decode_shot_frames(
        self,
        shot: Shot,
        *,
        policy: ProcessingColorPolicy = ProcessingColorPolicy.SOURCE,
    ) -> list[VideoFrame]:
        """Decode the shot range for processing (default SOURCE for propagation)."""
        if shot.media.source_path is None:
            raise ValueError("Source media is not linked.")
        media_path = Path(shot.media.source_path)
        decoded, _stats = decode_frame_range(
            self._frame_decoder,
            self._media_reader,
            media_path,
            shot.range_start,
            shot.range_end,
            policy=policy,
        )
        return [
            VideoFrame(frame_number=frame_number, image=decoded[frame_number])
            for frame_number in range(shot.range_start, shot.range_end + 1)
        ]

    @staticmethod
    def _propagation_mask_targets(shot: Shot) -> list[int]:
        """Every frame in the shot range except the accepted master (preserved separately)."""
        return [
            frame_number
            for frame_number in range(shot.range_start, shot.range_end + 1)
            if frame_number != shot.master_frame
        ]

    @staticmethod
    def _validation_endpoint_frames(shot: Shot) -> set[int]:
        return {shot.range_start, shot.range_end} - {shot.master_frame}

    @staticmethod
    def _propagation_mode(results: list[PropagationResult]) -> Literal["mock", "real"]:
        for result in results:
            adapter = (result.provenance.adapter or "").lower()
            settings = result.provenance.settings or {}
            quality = str(settings.get("quality", "")).lower()
            mode = str(settings.get("mode", "")).lower()
            if "mock" in adapter or mode == "mock" or "mock" in quality:
                return "mock"
        return "real"

    def _normalize_propagation_results(
        self,
        shot: Shot,
        results: list[PropagationResult],
    ) -> tuple[list[PropagationResult], tuple[int, ...]]:
        """Collapse duplicates deterministically; mark only Start/End as validation cards."""
        endpoints = self._validation_endpoint_frames(shot)
        by_frame: dict[int, PropagationResult] = {}
        duplicate_hits: list[int] = []
        for result in results:
            frame_number = int(result.frame_number)
            if frame_number == shot.master_frame:
                # Master mask is the accepted confirmed identity — never overwrite it.
                continue
            if frame_number < shot.range_start or frame_number > shot.range_end:
                continue
            existing = by_frame.get(frame_number)
            if existing is not None:
                duplicate_hits.append(frame_number)
                if result.confidence < existing.confidence:
                    continue
                if result.confidence == existing.confidence and result.mask_reference >= (
                    existing.mask_reference
                ):
                    continue
            by_frame[frame_number] = result
        normalized = [
            replace(
                by_frame[frame_number],
                is_validation_target=frame_number in endpoints,
            )
            for frame_number in sorted(by_frame)
        ]
        return normalized, tuple(sorted(set(duplicate_hits)))

    def _track_skeleton(
        self,
        reference: SkeletonGuidance,
        shot: Shot,
        frames: list[VideoFrame],
    ) -> list[SkeletonTrackingResult]:
        if not reference.joints:
            return []
        layer = shot.smart_layers[0] if shot.smart_layers else None
        corrections = layer.skeleton_corrections if layer is not None else []
        if not corrections:
            return self._skeleton_tracking.track(
                master_frame=shot.master_frame,
                reference_skeleton=reference,
                frames=frames,
            )
        anchors = {
            shot.master_frame: reference,
            **{correction.frame_number: correction.skeleton for correction in corrections},
        }
        frames_by_anchor: dict[int, list[VideoFrame]] = {
            frame_number: [] for frame_number in anchors
        }
        for frame in frames:
            anchor_frame = min(
                anchors,
                key=lambda candidate: (abs(frame.frame_number - candidate), candidate),
            )
            frames_by_anchor[anchor_frame].append(frame)
        results: list[SkeletonTrackingResult] = []
        for anchor_frame, anchor_skeleton in sorted(anchors.items()):
            assigned = frames_by_anchor[anchor_frame]
            if not assigned:
                continue
            tracked = self._skeleton_tracking.track(
                master_frame=anchor_frame,
                reference_skeleton=anchor_skeleton,
                frames=assigned,
            )
            anchor_source = "master" if anchor_frame == shot.master_frame else "artist_correction"
            results.extend(
                replace(
                    result,
                    provenance=result.provenance.model_copy(
                        update={
                            "settings": {
                                **result.provenance.settings,
                                "skeleton_anchor_frame": anchor_frame,
                                "skeleton_anchor_source": anchor_source,
                            }
                        }
                    ),
                )
                for result in tracked
            )
        return sorted(results, key=lambda item: item.frame_number)

    def apply_skeleton_correction(
        self,
        frame_number: int,
        skeleton: SkeletonGuidance,
    ) -> SkeletonCorrection | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            self.error_occurred.emit("Create a Smart Layer before correcting a skeleton.")
            return None
        if frame_number < shot.range_start or frame_number > shot.range_end:
            self.error_occurred.emit("Skeleton correction frame is outside the Shot Range.")
            return None
        layer = shot.smart_layers[0]
        reference = layer.artist_intent.skeleton_guidance
        if not skeleton.joints or not self._same_skeleton_topology(reference, skeleton):
            self.error_occurred.emit(
                "Skeleton correction must preserve the artist's joint identities and bone topology."
            )
            return None
        provenance = self._artist_skeleton_provenance()
        evidence = EvidenceRecord(
            source_type="artist",
            frame_number=frame_number,
            payload_reference=f"skeleton-correction:{frame_number}",
            confidence=1.0,
            provenance=provenance,
        )
        existing_correction = next(
            (item for item in layer.skeleton_corrections if item.frame_number == frame_number),
            None,
        )
        current_observation = next(
            (
                item
                for item in layer.temporal_skeleton_observations
                if item.frame_number == frame_number
            ),
            None,
        )
        correction = SkeletonCorrection(
            frame_number=frame_number,
            skeleton=skeleton.model_copy(deep=True),
            evidence_id=evidence.id,
            replaced_observation=(
                existing_correction.replaced_observation
                if existing_correction is not None
                else current_observation.model_copy(deep=True)
                if current_observation is not None
                else None
            ),
        )
        layer.skeleton_corrections = [
            item for item in layer.skeleton_corrections if item.frame_number != frame_number
        ]
        layer.skeleton_corrections.append(correction)
        layer.skeleton_corrections.sort(key=lambda item: item.frame_number)
        layer.temporal_skeleton_observations = [
            item
            for item in layer.temporal_skeleton_observations
            if item.frame_number != frame_number
        ]
        layer.temporal_skeleton_observations.append(
            TemporalSkeletonObservation(
                frame_number=frame_number,
                skeleton=skeleton.model_copy(deep=True),
                confidence=1.0,
                provenance=provenance,
            )
        )
        layer.temporal_skeleton_observations.sort(key=lambda item: item.frame_number)
        identity_observation = next(
            (item for item in layer.temporal_observations if item.frame_number == frame_number),
            None,
        )
        if identity_observation is not None:
            identity_observation.skeleton_confidence = 1.0
            identity_observation.skeleton_provenance = provenance
            if identity_observation.mask_confidence is not None:
                identity_observation.confidence = self._fused_identity_confidence(
                    identity_observation.mask_confidence,
                    1.0,
                )
        layer.evidence_history.append(evidence)
        layer.version += 1
        if not self._save_current():
            return None
        self.skeleton_correction_applied.emit(frame_number, correction.skeleton)
        return correction

    def propose_skeleton_fusion(
        self,
        *,
        frame_number: int,
        detected_skeleton: SkeletonGuidance,
        joint_confidences: dict[str, float],
        depth_confidences: dict[str, float] | None,
        provenance: CapabilityProvenance,
        joint_depths: dict[str, float] | None = None,
    ) -> SkeletonFusionCandidate | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            self.error_occurred.emit("Create Artist Skeleton Guidance before fusion.")
            return None
        if not shot.range_start <= frame_number <= shot.range_end:
            self.error_occurred.emit("Skeleton fusion frame is outside the Shot Range.")
            return None
        layer = shot.smart_layers[0]
        if frame_number == shot.master_frame:
            artist_skeleton = layer.artist_intent.skeleton_guidance
        else:
            observation = next(
                (
                    item
                    for item in layer.temporal_skeleton_observations
                    if item.frame_number == frame_number
                ),
                None,
            )
            artist_skeleton = (
                observation.skeleton
                if observation is not None
                else layer.artist_intent.skeleton_guidance
            )
        try:
            candidate = create_fusion_candidate(
                frame_number=frame_number,
                artist_skeleton=artist_skeleton,
                detected_skeleton=detected_skeleton,
                joint_confidences=joint_confidences,
                depth_confidences=depth_confidences,
                joint_depths=joint_depths,
                provenance=provenance,
            )
        except ValueError as exc:
            self.error_occurred.emit(f"Skeleton fusion failed: {exc}")
            return None
        layer.skeleton_fusion_candidates = [
            item
            for item in layer.skeleton_fusion_candidates
            if not (item.frame_number == frame_number and item.status == "pending")
        ]
        layer.skeleton_fusion_candidates.append(candidate)
        if not self._save_current():
            return None
        self.skeleton_fusion_candidate_ready.emit(candidate)
        return candidate

    def review_skeleton_fusion(self, candidate_id: UUID, *, accept: bool) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return False
        layer = shot.smart_layers[0]
        candidate = next(
            (item for item in layer.skeleton_fusion_candidates if item.id == candidate_id),
            None,
        )
        if candidate is None or candidate.status != "pending":
            self.error_occurred.emit("Pending skeleton fusion candidate was not found.")
            return False
        if accept:
            if candidate.frame_number == shot.master_frame:
                layer.artist_intent.skeleton_guidance = candidate.fused_skeleton.model_copy(
                    deep=True
                )
            elif (
                self.apply_skeleton_correction(
                    candidate.frame_number,
                    candidate.fused_skeleton,
                )
                is None
            ):
                return False
            candidate.status = "accepted"
            decision = "accepted"
        else:
            candidate.status = "rejected"
            decision = "rejected"
        evidence = EvidenceRecord(
            source_type="artist",
            frame_number=candidate.frame_number,
            payload_reference=f"skeleton-fusion:{candidate.id}:{decision}",
            confidence=1.0,
            provenance=candidate.provenance,
        )
        layer.evidence_history.append(evidence)
        layer.version += 1
        if not self._save_current():
            return False
        self.skeleton_fusion_reviewed.emit(candidate)
        return True

    def remove_skeleton_correction(self, frame_number: int) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return False
        layer = shot.smart_layers[0]
        correction = next(
            (item for item in layer.skeleton_corrections if item.frame_number == frame_number),
            None,
        )
        if correction is None:
            self.error_occurred.emit("No artist skeleton correction exists on this frame.")
            return False
        layer.skeleton_corrections = [
            item for item in layer.skeleton_corrections if item.frame_number != frame_number
        ]
        layer.temporal_skeleton_observations = [
            item
            for item in layer.temporal_skeleton_observations
            if item.frame_number != frame_number
        ]
        restored = correction.replaced_observation
        if restored is not None:
            layer.temporal_skeleton_observations.append(restored.model_copy(deep=True))
            layer.temporal_skeleton_observations.sort(key=lambda item: item.frame_number)
        identity_observation = next(
            (item for item in layer.temporal_observations if item.frame_number == frame_number),
            None,
        )
        if identity_observation is not None:
            identity_observation.skeleton_confidence = (
                restored.confidence if restored is not None else None
            )
            identity_observation.skeleton_provenance = (
                restored.provenance if restored is not None else None
            )
            if identity_observation.mask_confidence is not None:
                identity_observation.confidence = self._fused_identity_confidence(
                    identity_observation.mask_confidence,
                    restored.confidence if restored is not None else None,
                )
        evidence = EvidenceRecord(
            source_type="artist",
            frame_number=frame_number,
            payload_reference=f"skeleton-correction-removed:{frame_number}",
            confidence=1.0,
        )
        layer.evidence_history.append(evidence)
        layer.version += 1
        if not self._save_current():
            return False
        self.skeleton_correction_removed.emit(
            frame_number,
            restored.skeleton if restored is not None else None,
        )
        return True

    @staticmethod
    def _same_skeleton_topology(
        reference: SkeletonGuidance,
        candidate: SkeletonGuidance,
    ) -> bool:
        if {joint.id for joint in reference.joints} != {joint.id for joint in candidate.joints}:
            return False
        reference_bones = {
            frozenset((bone.start_joint_id, bone.end_joint_id)) for bone in reference.bones
        }
        candidate_bones = {
            frozenset((bone.start_joint_id, bone.end_joint_id)) for bone in candidate.bones
        }
        return reference_bones == candidate_bones

    @staticmethod
    def _artist_skeleton_provenance() -> CapabilityProvenance:
        return CapabilityProvenance(
            capability="skeleton_tracking",
            adapter="artist_skeleton_correction",
            adapter_version="1.0",
            device="artist",
        )

    def _commit_propagation(
        self,
        results: list[PropagationResult],
        skeleton_results: list[SkeletonTrackingResult] | None = None,
        *,
        requested_frames: list[int] | tuple[int, ...] | None = None,
        duplicate_frames: tuple[int, ...] = (),
        duration_seconds: float = 0.0,
    ) -> list[FrameResult]:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            return []
        layer = shot.smart_layers[0]
        requested = tuple(
            requested_frames
            if requested_frames is not None
            else self._propagation_mask_targets(shot)
        )
        produced = tuple(sorted({item.frame_number for item in results}))
        missing = tuple(frame for frame in requested if frame not in set(produced))
        mode = self._propagation_mode(results)
        frame_results: list[FrameResult] = []
        skeleton_results = skeleton_results or []
        correction_frames = {item.frame_number for item in layer.skeleton_corrections}
        skeleton_results = [
            item for item in skeleton_results if item.frame_number not in correction_frames
        ]
        skeleton_results.extend(
            SkeletonTrackingResult(
                frame_number=correction.frame_number,
                skeleton=correction.skeleton.model_copy(deep=True),
                confidence=1.0,
                provenance=self._artist_skeleton_provenance(),
            )
            for correction in layer.skeleton_corrections
        )
        skeleton_results.sort(key=lambda item: item.frame_number)
        skeleton_by_frame = {item.frame_number: item for item in skeleton_results}
        observations = self._build_temporal_observations(shot, results, skeleton_results)
        materialized = 0
        for result in results:
            try:
                self._mask_store.save(
                    self._package_path,
                    result.mask_reference,
                    result.mask,
                )
            except MaskStoreError as exc:
                self.error_occurred.emit(str(exc))
                self.last_propagation_diagnostics = PropagationDiagnostics(
                    requested_frames=requested,
                    produced_frames=produced,
                    duplicate_frames=duplicate_frames,
                    missing_frames=missing,
                    materialized_file_count=materialized,
                    duration_seconds=duration_seconds,
                    mode=mode,
                    complete=False,
                )
                return []
            mask_path = self._package_path / result.mask_reference
            if not mask_path.is_file():
                self.error_occurred.emit(
                    f"Propagated mask was not materialized on disk: {result.mask_reference}"
                )
                self.last_propagation_diagnostics = PropagationDiagnostics(
                    requested_frames=requested,
                    produced_frames=produced,
                    duplicate_frames=duplicate_frames,
                    missing_frames=missing,
                    materialized_file_count=materialized,
                    duration_seconds=duration_seconds,
                    mode=mode,
                    complete=False,
                )
                return []
            materialized += 1
            if not result.is_validation_target:
                continue
            skeleton_result = skeleton_by_frame.get(result.frame_number)
            fused_confidence = self._fused_identity_confidence(
                result.confidence,
                skeleton_result.confidence if skeleton_result is not None else None,
            )
            evidence = EvidenceRecord(
                source_type="temporal",
                frame_number=result.frame_number,
                payload_reference=result.mask_reference,
                confidence=fused_confidence,
                provenance=result.provenance,
            )
            direction: Literal["backward", "forward"] = (
                "backward" if result.frame_number < shot.master_frame else "forward"
            )
            frame_result = FrameResult(
                frame_number=result.frame_number,
                direction=direction,
                mask_reference=result.mask_reference,
                confidence=fused_confidence,
                evidence_ids=[evidence.id],
                provenance=result.provenance,
            )
            if fused_confidence < self.identity_confidence_threshold:
                frame_result.validation_state = ValidationState.CORRECTION_REQUIRED
            layer.evidence_history.append(evidence)
            frame_results.append(frame_result)

        complete = len(missing) == 0 and materialized == len(results) and len(results) == len(
            requested
        )
        # Master confirmed mask must remain present on disk.
        master_ref = layer.object_identity.confirmed_subject_reference
        if master_ref is None or not (self._package_path / master_ref).is_file():
            complete = False
            self.error_occurred.emit(
                "Accepted master-frame mask is missing after propagation. "
                "Re-accept the hypothesis, then propagate again."
            )

        self.last_propagation_diagnostics = PropagationDiagnostics(
            requested_frames=requested,
            produced_frames=produced,
            duplicate_frames=duplicate_frames,
            missing_frames=missing,
            materialized_file_count=materialized,
            duration_seconds=duration_seconds,
            mode=mode,
            complete=complete,
        )
        if not complete:
            preview = ", ".join(str(frame) for frame in missing[:8])
            more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
            self.error_occurred.emit(
                "Propagation did not cover the full selected range "
                f"{shot.range_start}–{shot.range_end}. Missing frame(s): {preview}{more}. "
                "Validation cannot complete until one mask exists per frame "
                f"(mode={mode})."
            )
            return []

        layer.frame_results = [item for item in layer.frame_results if item.direction == "master"]
        layer.frame_results.extend(frame_results)
        layer.temporal_observations = observations
        layer.temporal_skeleton_observations = [
            TemporalSkeletonObservation(
                frame_number=result.frame_number,
                skeleton=result.skeleton,
                confidence=result.confidence,
                provenance=result.provenance,
            )
            for result in skeleton_results
        ]
        forward_observations = [
            item for item in observations if item.frame_number > shot.master_frame
        ]
        backward_observations = [
            item for item in observations if item.frame_number < shot.master_frame
        ]
        if forward_observations:
            layer.object_identity.lifecycle_state = forward_observations[-1].lifecycle_state
        elif backward_observations:
            layer.object_identity.lifecycle_state = backward_observations[0].lifecycle_state
        else:
            layer.object_identity.lifecycle_state = LifecycleState.TRACKED
        if not self._save_current():
            return []
        if layer.temporal_skeleton_observations:
            self.skeleton_tracking_ready.emit(layer.temporal_skeleton_observations)
        self.validation_ready.emit(layer.frame_results)
        return frame_results

    def _build_temporal_observations(
        self,
        shot: Shot,
        results: list[PropagationResult],
        skeleton_results: list[SkeletonTrackingResult] | None = None,
    ) -> list[TemporalIdentityObservation]:
        observations: list[TemporalIdentityObservation] = []
        skeleton_by_frame = {item.frame_number: item for item in (skeleton_results or [])}
        directions = (
            sorted(
                (item for item in results if item.frame_number < shot.master_frame),
                key=lambda item: item.frame_number,
                reverse=True,
            ),
            sorted(
                (item for item in results if item.frame_number > shot.master_frame),
                key=lambda item: item.frame_number,
            ),
        )
        for direction in directions:
            was_lost = False
            for result in direction:
                skeleton_result = skeleton_by_frame.get(result.frame_number)
                skeleton_confidence = (
                    skeleton_result.confidence if skeleton_result is not None else None
                )
                fused_confidence = self._fused_identity_confidence(
                    result.confidence,
                    skeleton_confidence,
                )
                trusted_visible = (
                    result.visible and fused_confidence >= self.identity_confidence_threshold
                )
                if not trusted_visible:
                    state = LifecycleState.TEMPORARILY_LOST
                    was_lost = True
                elif was_lost:
                    state = LifecycleState.RECOVERED
                else:
                    state = LifecycleState.TRACKED
                observations.append(
                    TemporalIdentityObservation(
                        frame_number=result.frame_number,
                        lifecycle_state=state,
                        confidence=fused_confidence,
                        mask_confidence=result.confidence,
                        skeleton_confidence=skeleton_confidence,
                        skeleton_provenance=(
                            skeleton_result.provenance if skeleton_result is not None else None
                        ),
                        visible=result.visible,
                        area_ratio=result.area_ratio,
                        mask_reference=result.mask_reference,
                        provenance=result.provenance,
                    )
                )
        return sorted(observations, key=lambda item: item.frame_number)

    @staticmethod
    def _fused_identity_confidence(
        mask_confidence: float,
        skeleton_confidence: float | None,
    ) -> float:
        if skeleton_confidence is None:
            return mask_confidence
        return min(1.0, max(0.0, mask_confidence * 0.7 + skeleton_confidence * 0.3))

    def smart_layer_frame_sources(self) -> list[tuple[int, str]]:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return []
        layer = shot.smart_layers[0]
        master = next(
            (item for item in layer.frame_results if item.direction == "master"),
            None,
        )
        by_frame: dict[int, str] = {}
        for item in layer.temporal_observations:
            if item.mask_reference is not None:
                by_frame[item.frame_number] = item.mask_reference
        if master is not None:
            by_frame.setdefault(master.frame_number, master.mask_reference)
        return sorted(by_frame.items(), key=lambda item: item[0])

    def confirmed_mask_reference_for_frame(self, frame_number: int) -> str | None:
        """Resolve a confirmed mask reference for a frame (propagation or master)."""
        by_frame = dict(self.smart_layer_frame_sources())
        if frame_number in by_frame:
            return by_frame[frame_number]
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return None
        layer = shot.smart_layers[0]
        master = next(
            (item for item in layer.frame_results if item.direction == "master"),
            None,
        )
        if master is not None and master.frame_number == frame_number:
            return master.mask_reference
        return None

    def _background_removal(self) -> VideoExtractionService:
        if self._background_removal_service is None:
            try:
                engine = load_background_removal_engine()
            except VideoExtractionError as exc:
                raise VideoExtractionError(exc.code, exc.message) from exc
            self._background_removal_service = VideoExtractionService(engine)
        return self._background_removal_service

    def start_background_removal_preview(self, frame_number: int) -> bool:
        """Single-frame Background Removal → preview RGBA (Application orchestration)."""
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit(
                "Generate and accept a confirmed object mask before Background Removal."
            )
            return False
        if shot.media.source_path is None:
            self.error_occurred.emit("Source media is not linked.")
            return False
        mask_reference = self.confirmed_mask_reference_for_frame(frame_number)
        if mask_reference is None:
            self.error_occurred.emit(
                f"No confirmed mask for frame {frame_number}. "
                "Accept the hypothesis (and propagate for non-master frames)."
            )
            return False
        package_path = self._package_path
        media_path = Path(shot.media.source_path)
        target_frame = int(frame_number)

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            report(0, 1, f"Background Removal preview frame {target_frame}")
            if cancel_event.is_set():
                return None
            try:
                service = self._background_removal()
            except VideoExtractionError as exc:
                raise RuntimeError(f"{exc.code}: {exc.message}") from exc
            frame = self._frame_decoder.get_preview_frame(media_path, target_frame)
            mask = self._mask_store.load(package_path, mask_reference)
            output = service.extract_frame(
                FrameExtractionInput(
                    frame_number=target_frame,
                    rgb=frame,
                    mask=mask,
                ),
                should_cancel=cancel_event.is_set,
            )
            report(1, 1, f"Background Removal preview frame {target_frame} done")
            return ("background_removal_preview", target_frame, output.rgba)

        if not self._jobs.start("background_removal_preview", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def background_removal_provider_available(self) -> tuple[bool, str]:
        """Probe Background Removal plugin availability without starting extraction."""
        try:
            engine_path = resolve_background_removal_engine_path()
        except VideoExtractionError as exc:
            return False, (
                "Background Removal provider is not available: "
                f"{exc.message}. Install or locate the nova.background_removal plugin."
            )
        try:
            import importlib.util

            module_name = f"nova_bg_removal_probe_{abs(hash(str(engine_path))) & 0xFFFFFFFF:x}"
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, engine_path)
                if spec is None or spec.loader is None:
                    return False, "Background Removal provider could not be loaded."
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            probe = getattr(module, "probe_availability", None)
            if probe is None:
                return False, "Background Removal provider is missing probe_availability()."
            status, message = probe(
                ExtractionRuntimeConfig(selected_provider_id=BACKGROUND_REMOVAL_PROVIDER_ID)
            )
            if status != "available":
                return False, (
                    "Background Removal provider is unavailable: "
                    f"{message}. Fix the model/dependency, then retry."
                )
            return True, str(message)
        except Exception as exc:  # noqa: BLE001
            return False, f"Background Removal provider probe failed: {exc}"

    def background_removal_clip_readiness(self) -> BackgroundRemovalClipReadiness:
        """Validate Smart Layer state before Process Clip (Background Removal).

        Never starts extraction and never creates render/staging state.
        """
        if self._project is None:
            return BackgroundRemovalClipReadiness(
                False,
                "No active project. Create or open a project before Background Removal.",
            )
        if self._package_path is None:
            return BackgroundRemovalClipReadiness(
                False,
                "Project package path is missing. Re-open the project and try again.",
            )
        shot = self.active_shot
        if shot is None:
            return BackgroundRemovalClipReadiness(
                False,
                "No active shot. Import media to create a shot before Background Removal.",
            )
        if not shot.smart_layers:
            return BackgroundRemovalClipReadiness(
                False,
                "No active Smart Layer. Add guidance, generate a hypothesis, and confirm "
                "an object before Background Removal.",
            )
        layer = shot.smart_layers[0]
        if layer.object_identity.confirmed_subject_reference is None:
            return BackgroundRemovalClipReadiness(
                False,
                "No confirmed object mask. Accept the Object Hypothesis before continuing.",
            )
        if layer.object_identity.maturity_state not in {
            MaturityState.CONFIRMED,
            MaturityState.VALIDATED,
            MaturityState.PRODUCTION_READY,
        }:
            return BackgroundRemovalClipReadiness(
                False,
                "Object is not confirmed. Accept the hypothesis, then propagate and validate.",
            )

        # Propagation validation must be complete — never continue after a failed validation.
        validation_frames = [
            item
            for item in layer.frame_results
            if item.direction in {"master", "backward", "forward"}
        ]
        if len(validation_frames) < 3:
            return BackgroundRemovalClipReadiness(
                False,
                "Propagation validation is incomplete. Propagate to Range Ends so Start, "
                "Master, and End frames exist, then accept all three.",
            )
        rejected_or_correction = [
            item
            for item in validation_frames
            if item.validation_state
            in {ValidationState.REJECTED, ValidationState.CORRECTION_REQUIRED}
        ]
        if rejected_or_correction:
            frames = ", ".join(str(item.frame_number) for item in rejected_or_correction)
            return BackgroundRemovalClipReadiness(
                False,
                "Propagation validation failed or needs correction on frame(s) "
                f"{frames}. Resolve validation before Process Clip (Background Removal).",
            )
        if not all(
            item.validation_state == ValidationState.ACCEPTED for item in validation_frames
        ):
            return BackgroundRemovalClipReadiness(
                False,
                "Propagation validation is not complete. Accept Start, Master, and End "
                "in the validation dialog before Process Clip (Background Removal).",
            )
        if layer.object_identity.maturity_state not in {
            MaturityState.VALIDATED,
            MaturityState.PRODUCTION_READY,
        }:
            return BackgroundRemovalClipReadiness(
                False,
                "Smart Layer is not validated. Accept Start, Master, and End before "
                "Process Clip (Background Removal).",
            )

        if shot.range_start > shot.range_end:
            return BackgroundRemovalClipReadiness(
                False,
                f"Invalid shot range {shot.range_start}–{shot.range_end}. "
                "Apply a valid Range Start/End before Background Removal.",
            )
        if shot.media.source_path is None:
            return BackgroundRemovalClipReadiness(
                False,
                "Source media is not linked. Relink the video, then retry.",
            )
        max_frame = shot.media.frame_count - 1
        if shot.range_start < 0 or shot.range_end > max_frame:
            return BackgroundRemovalClipReadiness(
                False,
                f"Shot range {shot.range_start}–{shot.range_end} is outside the media "
                f"(0–{max_frame}). Apply Shot Settings within the clip, then retry.",
            )

        sources = self.smart_layer_frame_sources()
        if not sources:
            return BackgroundRemovalClipReadiness(
                False,
                "No mask source collection exists. Propagate the confirmed identity across "
                "the shot range, then validate Start/Master/End.",
            )
        expected_frames = list(range(shot.range_start, shot.range_end + 1))
        by_frame = dict(sources)
        missing = [frame for frame in expected_frames if frame not in by_frame]
        if missing:
            preview = ", ".join(str(frame) for frame in missing[:8])
            more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
            return BackgroundRemovalClipReadiness(
                False,
                "Mask source collection does not cover the requested frame range "
                f"{shot.range_start}–{shot.range_end}. Missing frame(s): {preview}{more}. "
                "Propagate must produce one usable mask per frame before Process Clip.",
            )
        for frame_number, mask_reference in sources:
            if frame_number < shot.range_start or frame_number > shot.range_end:
                continue
            mask_path = self._package_path / mask_reference
            if not mask_path.is_file():
                return BackgroundRemovalClipReadiness(
                    False,
                    f"Mask file missing for frame {frame_number} ({mask_reference}). "
                    "Propagate again, then retry Process Clip.",
                )

        provider_ok, provider_message = self.background_removal_provider_available()
        if not provider_ok:
            return BackgroundRemovalClipReadiness(False, provider_message)

        return BackgroundRemovalClipReadiness(True, provider_message)

    def start_background_removal_clip(
        self,
        *,
        color_policy: ProcessingColorPolicy = ProcessingColorPolicy.PREVIEW,
    ) -> bool:
        """Clip-range Background Removal → Smart Layer render commit → existing Export.

        ``color_policy`` defaults to PREVIEW (viewer-look bake). Pass SOURCE for
        look-independent final/host RGB.
        """
        try:
            color_policy = validate_render_color_policy(color_policy)
        except MediaReadError as exc:
            self.error_occurred.emit(str(exc))
            return False
        readiness = self.background_removal_clip_readiness()
        if not readiness.ready:
            self.error_occurred.emit(readiness.reason)
            return False

        shot = self.active_shot
        assert shot is not None and shot.smart_layers and self._package_path is not None
        layer = shot.smart_layers[0]
        sources = self.smart_layer_frame_sources()
        # Re-check coverage immediately before staging — never partially create render state.
        expected_frames = shot.range_end - shot.range_start + 1
        if len(dict(sources)) < expected_frames:
            self.error_occurred.emit(
                "Mask source collection changed and no longer covers the shot range. "
                "Propagate and validate again before Process Clip (Background Removal)."
            )
            return False
        if shot.media.source_path is None:
            self.error_occurred.emit("Source media is not linked.")
            return False

        render_version = (
            max(
                layer.render_version_counter,
                max((item.version for item in layer.renders), default=0),
            )
            + 1
        )
        package_path = self._package_path
        shot_snapshot = shot.model_copy(deep=True)
        layer_id = layer.id
        layer_version = layer.version
        media_path = Path(shot.media.source_path)
        staging_path = (
            package_path / "renders" / f".staging_bg_v{render_version:04d}_{uuid4().hex}"
        )
        color_meta = build_render_color_metadata(
            color_policy,
            display_transform=(
                (self._display_transform or LegacyDisplayTransform())
                if color_policy is ProcessingColorPolicy.PREVIEW
                else None
            ),
        )

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            generated: list[ExtractionPreview] = []
            total = len(sources)
            total_started = perf_counter()
            decode_stats: RangeDecodeStats | None = None
            extraction_seconds = 0.0
            try:
                try:
                    service = self._background_removal()
                except VideoExtractionError as exc:
                    raise RuntimeError(f"{exc.code}: {exc.message}") from exc
                report(0, total + 1, "Decoding selected clip range")
                decoded, decode_stats = decode_frame_range(
                    self._frame_decoder,
                    self._media_reader,
                    media_path,
                    shot_snapshot.range_start,
                    shot_snapshot.range_end,
                    policy=color_policy,
                    should_cancel=cancel_event.is_set,
                    report_progress=lambda current, expected, message: report(
                        current,
                        total + expected,
                        message,
                    ),
                )
                if cancel_event.is_set():
                    rmtree(staging_path, ignore_errors=True)
                    return None
                extract_started = perf_counter()
                for index, (frame_number, mask_reference) in enumerate(sources, start=1):
                    if cancel_event.is_set():
                        rmtree(staging_path, ignore_errors=True)
                        return None
                    report(
                        index - 1,
                        total,
                        f"Background Removal frame {frame_number}",
                    )
                    frame = decoded[frame_number]
                    mask = self._mask_store.load(package_path, mask_reference)
                    extracted = service.extract_frame(
                        FrameExtractionInput(
                            frame_number=frame_number,
                            rgb=frame,
                            mask=mask,
                        ),
                        should_cancel=cancel_event.is_set,
                    )
                    staged_reference = f"frame_{frame_number:06d}.png"
                    self._preview_store.save(
                        staging_path, staged_reference, extracted.rgba
                    )
                    generated.append(
                        ExtractionPreview(
                            frame_number=frame_number,
                            image_reference=staged_reference,
                            mask_reference=mask_reference,
                        )
                    )
                    report(index, total, f"Background Removal frame {frame_number} done")
                extraction_seconds = perf_counter() - extract_started
                if cancel_event.is_set():
                    rmtree(staging_path, ignore_errors=True)
                    return None
                write_render_color_metadata(staging_path, color_meta)
            except Exception:
                rmtree(staging_path, ignore_errors=True)
                raise
            finally:
                if decode_stats is not None:
                    self.last_clip_decode_diagnostics = ClipDecodeDiagnostics(
                        range_size=decode_stats.range_size,
                        cache_hits=decode_stats.cache_hits,
                        decoder_opens=decode_stats.decoder_opens,
                        decoded_frames=decode_stats.decoded_frames,
                        decode_seconds=decode_stats.decode_seconds,
                        extraction_seconds=extraction_seconds,
                        total_seconds=perf_counter() - total_started,
                        frame_order=decode_stats.frame_order,
                    )
            return SmartLayerRenderJobOutput(
                shot_id=shot_snapshot.id,
                layer_id=layer_id,
                layer_version=layer_version,
                render_version=render_version,
                staging_path=staging_path,
                frames=tuple(generated),
                color_policy_metadata=dict(color_meta),
            )

        if not self._jobs.start("background_removal_clip", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def start_smart_layer_render(
        self,
        *,
        color_policy: ProcessingColorPolicy = ProcessingColorPolicy.PREVIEW,
    ) -> bool:
        try:
            color_policy = validate_render_color_policy(color_policy)
        except MediaReadError as exc:
            self.error_occurred.emit(str(exc))
            return False
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            self.error_occurred.emit("No Smart Layer is available for rendering.")
            return False
        layer = shot.smart_layers[0]
        if layer.object_identity.maturity_state not in {
            MaturityState.VALIDATED,
            MaturityState.PRODUCTION_READY,
        }:
            self.error_occurred.emit("Validate Start, Master, and End before rendering.")
            return False
        sources = self.smart_layer_frame_sources()
        expected_frames = shot.range_end - shot.range_start + 1
        if len(sources) != expected_frames:
            self.error_occurred.emit(
                "Full-range masks are incomplete. Propagate the confirmed identity again."
            )
            return False
        render_version = (
            max(
                layer.render_version_counter,
                max((item.version for item in layer.renders), default=0),
            )
            + 1
        )
        package_path = self._package_path
        shot_snapshot = shot.model_copy(deep=True)
        layer_id = layer.id
        layer_version = layer.version
        staging_path = package_path / "renders" / f".staging_v{render_version:04d}_{uuid4().hex}"
        color_meta = build_render_color_metadata(
            color_policy,
            display_transform=(
                (self._display_transform or LegacyDisplayTransform())
                if color_policy is ProcessingColorPolicy.PREVIEW
                else None
            ),
        )

        def operation(cancel_event: Event, report: ProgressCallback) -> object:
            generated: list[ExtractionPreview] = []
            total = len(sources)
            try:
                if shot_snapshot.media.source_path is None:
                    raise ValueError("Source media is not linked.")
                media_path = Path(shot_snapshot.media.source_path)
                report(0, total + 1, "Decoding selected clip range")
                decoded, _stats = decode_frame_range(
                    self._frame_decoder,
                    self._media_reader,
                    media_path,
                    shot_snapshot.range_start,
                    shot_snapshot.range_end,
                    policy=color_policy,
                    should_cancel=cancel_event.is_set,
                    report_progress=lambda current, expected, message: report(
                        current,
                        total + expected,
                        message,
                    ),
                )
                if cancel_event.is_set():
                    rmtree(staging_path, ignore_errors=True)
                    return None
                for index, (frame_number, mask_reference) in enumerate(sources, start=1):
                    if cancel_event.is_set():
                        rmtree(staging_path, ignore_errors=True)
                        return None
                    report(index - 1, total, f"Rendering Smart Layer frame {frame_number}")
                    frame = decoded[frame_number]
                    mask = self._mask_store.load(package_path, mask_reference)
                    rgba = compose_rgba(frame, mask)
                    staged_reference = f"frame_{frame_number:06d}.png"
                    self._preview_store.save(staging_path, staged_reference, rgba)
                    generated.append(
                        ExtractionPreview(
                            frame_number=frame_number,
                            image_reference=staged_reference,
                            mask_reference=mask_reference,
                        )
                    )
                    report(index, total, f"Rendered frame {frame_number}")
                if cancel_event.is_set():
                    rmtree(staging_path, ignore_errors=True)
                    return None
                write_render_color_metadata(staging_path, color_meta)
            except Exception:
                rmtree(staging_path, ignore_errors=True)
                raise
            return SmartLayerRenderJobOutput(
                shot_id=shot_snapshot.id,
                layer_id=layer_id,
                layer_version=layer_version,
                render_version=render_version,
                staging_path=staging_path,
                frames=tuple(generated),
                color_policy_metadata=dict(color_meta),
            )

        if not self._jobs.start("smart_layer_render", operation):
            self.error_occurred.emit("Another processing job is already running.")
            return False
        return True

    def _job_completed(self, raw_result: object) -> None:
        result = cast(JobResult[object], raw_result)
        if result.name == "bidirectional_propagation":
            propagated = cast(PropagationJobOutput | None, result.value)
            if propagated is not None:
                self._commit_propagation(
                    list(propagated.mask_results),
                    list(propagated.skeleton_results),
                    requested_frames=propagated.requested_frames,
                    duplicate_frames=propagated.duplicate_frames,
                    duration_seconds=propagated.duration_seconds,
                )
        elif result.name == "interactive_hypothesis":
            hypothesis_output = cast(HypothesisJobOutput | None, result.value)
            shot = self.active_shot
            if hypothesis_output is not None and shot is not None:
                if (
                    shot.id == hypothesis_output.shot_id
                    and shot.master_frame == hypothesis_output.master_frame
                ):
                    self._commit_hypothesis(hypothesis_output.result)
                else:
                    self.error_occurred.emit(
                        "Shot state changed during processing; the hypothesis was discarded."
                    )
        elif result.name == "skeleton_retracking":
            retracking = cast(SkeletonRetrackingJobOutput | None, result.value)
            if retracking is not None:
                self._commit_skeleton_retracking(retracking)
        elif result.name == "skeleton_fusion_detection":
            detection = cast(SkeletonFusionDetectionJobOutput | None, result.value)
            if detection is not None:
                self._commit_skeleton_fusion_detection(detection)
        elif result.name == "smart_layer_render":
            render_output = cast(SmartLayerRenderJobOutput | None, result.value)
            if render_output is not None:
                self._commit_smart_layer_render(render_output)
        elif result.name == "background_removal_clip":
            render_output = cast(SmartLayerRenderJobOutput | None, result.value)
            if render_output is not None:
                self._commit_smart_layer_render(render_output)
        elif result.name == "background_removal_preview":
            preview = cast(tuple[str, int, NDArray[np.uint8]] | None, result.value)
            if preview is not None:
                _label, frame_number, rgba = preview
                self.background_removal_preview_ready.emit(frame_number, rgba)
        self.processing_finished.emit(result.name)

    def _commit_skeleton_fusion_detection(
        self,
        output: SkeletonFusionDetectionJobOutput,
    ) -> None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return
        layer = shot.smart_layers[0]
        if (
            shot.id != output.shot_id
            or layer.id != output.layer_id
            or layer.version != output.layer_version
        ):
            self.error_occurred.emit(
                "Smart Layer changed during automatic pose detection; the result was discarded."
            )
            return
        self.propose_skeleton_fusion(
            frame_number=output.frame_number,
            detected_skeleton=output.result.skeleton,
            joint_confidences=output.result.joint_confidences,
            depth_confidences=output.result.depth_confidences,
            provenance=output.result.provenance,
            joint_depths=output.result.joint_depths,
        )

    def _commit_skeleton_retracking(self, output: SkeletonRetrackingJobOutput) -> None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return
        layer = shot.smart_layers[0]
        if (
            shot.id != output.shot_id
            or layer.id != output.layer_id
            or layer.version != output.layer_version
        ):
            self.error_occurred.emit(
                "Smart Layer changed during pose retracking; the result was discarded."
            )
            return
        correction_frames = {item.frame_number for item in layer.skeleton_corrections}
        results = [item for item in output.results if item.frame_number not in correction_frames]
        results.extend(
            SkeletonTrackingResult(
                frame_number=correction.frame_number,
                skeleton=correction.skeleton.model_copy(deep=True),
                confidence=1.0,
                provenance=self._artist_skeleton_provenance(),
            )
            for correction in layer.skeleton_corrections
        )
        results.sort(key=lambda item: item.frame_number)
        layer.temporal_skeleton_observations = [
            TemporalSkeletonObservation(
                frame_number=item.frame_number,
                skeleton=item.skeleton,
                confidence=item.confidence,
                provenance=item.provenance,
            )
            for item in results
        ]
        by_frame = {item.frame_number: item for item in results}
        for observation in layer.temporal_observations:
            skeleton_result = by_frame.get(observation.frame_number)
            observation.skeleton_confidence = (
                skeleton_result.confidence if skeleton_result is not None else None
            )
            observation.skeleton_provenance = (
                skeleton_result.provenance if skeleton_result is not None else None
            )
            if observation.mask_confidence is not None:
                observation.confidence = self._fused_identity_confidence(
                    observation.mask_confidence,
                    observation.skeleton_confidence,
                )
        self._refresh_temporal_lifecycle(shot, layer)
        for frame_result in layer.frame_results:
            frame_observation = next(
                (
                    item
                    for item in layer.temporal_observations
                    if item.frame_number == frame_result.frame_number
                ),
                None,
            )
            if frame_observation is not None:
                frame_result.confidence = frame_observation.confidence
                if frame_result.validation_state in {
                    ValidationState.PENDING,
                    ValidationState.CORRECTION_REQUIRED,
                }:
                    frame_result.validation_state = (
                        ValidationState.PENDING
                        if frame_observation.confidence >= self.identity_confidence_threshold
                        else ValidationState.CORRECTION_REQUIRED
                    )
        layer.version += 1
        if not self._save_current():
            return
        self.skeleton_retracking_ready.emit(layer.temporal_skeleton_observations)

    def _refresh_temporal_lifecycle(self, shot: Shot, layer: SmartLayer) -> None:
        directions = (
            sorted(
                (
                    item
                    for item in layer.temporal_observations
                    if item.frame_number < shot.master_frame
                ),
                key=lambda item: item.frame_number,
                reverse=True,
            ),
            sorted(
                (
                    item
                    for item in layer.temporal_observations
                    if item.frame_number > shot.master_frame
                ),
                key=lambda item: item.frame_number,
            ),
        )
        for direction in directions:
            was_lost = False
            for observation in direction:
                trusted_visible = (
                    observation.visible
                    and observation.confidence >= self.identity_confidence_threshold
                )
                if not trusted_visible:
                    observation.lifecycle_state = LifecycleState.TEMPORARILY_LOST
                    was_lost = True
                elif was_lost:
                    observation.lifecycle_state = LifecycleState.RECOVERED
                else:
                    observation.lifecycle_state = LifecycleState.TRACKED
        forward = [
            item for item in layer.temporal_observations if item.frame_number > shot.master_frame
        ]
        backward = [
            item for item in layer.temporal_observations if item.frame_number < shot.master_frame
        ]
        if forward:
            layer.object_identity.lifecycle_state = max(
                forward,
                key=lambda item: item.frame_number,
            ).lifecycle_state
        elif backward:
            layer.object_identity.lifecycle_state = min(
                backward,
                key=lambda item: item.frame_number,
            ).lifecycle_state

    def _commit_smart_layer_render(self, output: SmartLayerRenderJobOutput) -> None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            rmtree(output.staging_path, ignore_errors=True)
            return
        layer = shot.smart_layers[0]
        if (
            shot.id != output.shot_id
            or layer.id != output.layer_id
            or layer.version != output.layer_version
        ):
            rmtree(output.staging_path, ignore_errors=True)
            self.error_occurred.emit(
                "Smart Layer changed during rendering; staged output discarded."
            )
            return
        final_relative = f"renders/v{output.render_version:04d}"
        final_path = self._package_path / final_relative
        final_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output.staging_path.replace(final_path)
        except OSError as exc:
            rmtree(output.staging_path, ignore_errors=True)
            self.error_occurred.emit(f"Could not commit Smart Layer render: {exc}")
            return
        # Ensure color policy sidecar exists (staging write may be absent on older jobs).
        if output.color_policy_metadata:
            write_render_color_metadata(final_path, output.color_policy_metadata)
        elif not (final_path / "color_policy.json").is_file():
            write_render_color_metadata(
                final_path,
                build_render_color_metadata(
                    ProcessingColorPolicy.PREVIEW,
                    display_transform=self._display_transform,
                ),
            )
        frames = [
            item.model_copy(update={"image_reference": f"{final_relative}/{item.image_reference}"})
            for item in output.frames
        ]
        render = SmartLayerRender(
            version=output.render_version,
            source_layer_version=output.layer_version,
            frame_start=frames[0].frame_number,
            frame_end=frames[-1].frame_number,
            frames=frames,
            checksums={
                item.image_reference: self._sha256(self._package_path / item.image_reference)
                for item in frames
            },
        )
        previous_counter = layer.render_version_counter
        layer.renders.append(render)
        layer.render_version_counter = render.version
        if not self._save_current():
            layer.renders.pop()
            layer.render_version_counter = previous_counter
            rmtree(final_path, ignore_errors=True)
            return
        if output.color_policy_metadata:
            policy_value = output.color_policy_metadata.get("color_policy")
            self._last_render_color_policy = (
                str(policy_value) if policy_value is not None else None
            )
        else:
            self._last_render_color_policy = ProcessingColorPolicy.PREVIEW.value
        self.smart_layer_render_ready.emit(render)

    @staticmethod
    def _sha256(path: Path) -> str:
        with path.open("rb") as stream:
            return file_digest(stream, "sha256").hexdigest()

    def verify_smart_layer_render(self, version: int | None = None) -> RenderIntegrityReport:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            report = RenderIntegrityReport(version or 0, False, 0, ("No active Smart Layer.",))
            self.render_integrity_ready.emit(report)
            return report
        layer = shot.smart_layers[0]
        render = (
            next((item for item in layer.renders if item.version == version), None)
            if version is not None
            else (layer.renders[-1] if layer.renders else None)
        )
        if render is None:
            report = RenderIntegrityReport(
                version or 0, False, 0, ("Requested render version does not exist.",)
            )
            self.render_integrity_ready.emit(report)
            return report
        issues: list[str] = []
        checked = 0
        if not render.checksums:
            issues.append("Render predates checksum metadata and must be regenerated.")
        for frame in render.frames:
            path = self._package_path / frame.image_reference
            expected = render.checksums.get(frame.image_reference)
            if not path.is_file():
                issues.append(f"Missing frame: {frame.image_reference}")
                continue
            checked += 1
            if expected is None:
                issues.append(f"Missing checksum: {frame.image_reference}")
            elif self._sha256(path) != expected:
                issues.append(f"Checksum mismatch: {frame.image_reference}")
        report = RenderIntegrityReport(render.version, not issues, checked, tuple(issues))
        self.render_integrity_ready.emit(report)
        return report

    def set_render_protected(self, version: int, protected: bool) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return False
        render = next(
            (item for item in shot.smart_layers[0].renders if item.version == version), None
        )
        if render is None:
            self.error_occurred.emit(f"Smart Layer render v{version} does not exist.")
            return False
        previous = render.protected
        render.protected = protected
        if not self._save_current():
            render.protected = previous
            return False
        self.render_protection_changed.emit(version, protected)
        return True

    def compare_render_versions(
        self, base_version: int, target_version: int
    ) -> RenderComparisonReport | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return None
        renders = {item.version: item for item in shot.smart_layers[0].renders}
        base = renders.get(base_version)
        target = renders.get(target_version)
        if base is None or target is None:
            self.error_occurred.emit("Both Smart Layer render versions must exist for comparison.")
            return None

        def checksums_by_frame(render: SmartLayerRender) -> dict[int, str | None]:
            return {
                frame.frame_number: render.checksums.get(frame.image_reference)
                for frame in render.frames
            }

        base_checksums = checksums_by_frame(base)
        target_checksums = checksums_by_frame(target)
        base_frames = set(base_checksums)
        target_frames = set(target_checksums)
        shared = base_frames & target_frames
        changed = tuple(
            sorted(frame for frame in shared if base_checksums[frame] != target_checksums[frame])
        )
        added = tuple(sorted(target_frames - base_frames))
        removed = tuple(sorted(base_frames - target_frames))
        report = RenderComparisonReport(
            base_version=base_version,
            target_version=target_version,
            identical=not changed and not added and not removed,
            shared_frames=len(shared),
            added_frames=added,
            removed_frames=removed,
            changed_frames=changed,
        )
        self.render_comparison_ready.emit(report)
        return report

    def inspect_smart_layer_render(self, version: int) -> RenderAuditReport | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            return None
        render = next(
            (item for item in shot.smart_layers[0].renders if item.version == version), None
        )
        if render is None:
            self.error_occurred.emit(f"Smart Layer render v{version} does not exist.")
            return None
        integrity = self.verify_smart_layer_render(version)
        storage_bytes = sum(
            path.stat().st_size
            for frame in render.frames
            if (path := self._package_path / frame.image_reference).is_file()
        )
        return RenderAuditReport(
            version=render.version,
            source_layer_version=render.source_layer_version,
            frame_start=render.frame_start,
            frame_end=render.frame_end,
            frame_count=len(render.frames),
            storage_bytes=storage_bytes,
            protected=render.protected,
            integrity_valid=integrity.valid,
            issues=integrity.issues,
            created_at=render.created_at.isoformat(),
        )

    def delete_smart_layer_render(self, version: int) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            return False
        layer = shot.smart_layers[0]
        render = next((item for item in layer.renders if item.version == version), None)
        if render is None:
            self.error_occurred.emit(f"Smart Layer render v{version} does not exist.")
            return False
        if render.protected:
            self.error_occurred.emit(
                f"Smart Layer render v{version} is protected. Unprotect it before deletion."
            )
            return False
        if not render.frames:
            self.error_occurred.emit(f"Smart Layer render v{version} has no frame assets.")
            return False

        relative_directories = {Path(frame.image_reference).parent for frame in render.frames}
        if len(relative_directories) != 1:
            self.error_occurred.emit("Render assets do not share a safe version directory.")
            return False
        relative_directory = relative_directories.pop()
        render_path = (self._package_path / relative_directory).resolve()
        renders_root = (self._package_path / "renders").resolve()
        if render_path.parent != renders_root or not render_path.is_dir():
            self.error_occurred.emit("Render version directory is missing or unsafe to delete.")
            return False

        quarantine = self._package_path.parent / (
            f".{self._package_path.name}.delete_render_v{version:04d}_{uuid4().hex}"
        )
        render_index = layer.renders.index(render)
        try:
            render_path.replace(quarantine)
        except OSError as exc:
            self.error_occurred.emit(f"Could not stage render deletion: {exc}")
            return False

        layer.renders.pop(render_index)
        if not self._save_current():
            layer.renders.insert(render_index, render)
            try:
                quarantine.replace(render_path)
            except OSError as exc:
                self.error_occurred.emit(f"Could not restore staged render: {exc}")
            return False
        rmtree(quarantine, ignore_errors=True)
        self.render_deleted.emit(version)
        return True

    def export_benchmark_case(
        self, output_directory: Path, case_id: str, *, minimum_iou: float = 0.85
    ) -> DatasetExport | None:
        if self._package_path is None:
            self.error_occurred.emit("Save the project before exporting a benchmark case.")
            return None
        try:
            exported = export_validated_master_case(
                self._package_path,
                output_directory,
                case_id,
                minimum_iou=minimum_iou,
            )
        except (OSError, ValueError, ProjectStoreError) as exc:
            self.error_occurred.emit(f"Could not export benchmark case: {exc}")
            return None
        self.benchmark_case_exported.emit(
            exported.case_id,
            str(exported.manifest_path),
        )
        return exported

    def export_depth_pose_case(
        self, output_directory: Path, case_id: str
    ) -> DepthPoseDatasetExport | None:
        if self._package_path is None:
            self.error_occurred.emit("Save the project before exporting a Pose QA case.")
            return None
        try:
            exported = export_case(self._package_path, output_directory, case_id)
        except (OSError, ValueError, ProjectStoreError) as exc:
            self.error_occurred.emit(f"Could not export Pose QA case: {exc}")
            return None
        self.depth_pose_case_exported.emit(
            exported.case_id,
            str(exported.manifest_path),
            exported.ground_truth_source,
        )
        return exported

    def export_smart_layer_render(
        self,
        destination_directory: Path,
        version: int | None = None,
        *,
        format: ExportFormat | str = ExportFormat.PNG_SEQUENCE,
    ) -> Path | None:
        shot = self.active_shot
        if (
            shot is None
            or not shot.smart_layers
            or self._package_path is None
            or self._project is None
        ):
            self.error_occurred.emit("No Smart Layer render is available for export.")
            return None
        layer = shot.smart_layers[0]
        if not layer.renders:
            self.error_occurred.emit("Render the Smart Layer before exporting.")
            return None
        render = (
            next((item for item in layer.renders if item.version == version), None)
            if version is not None
            else layer.renders[-1]
        )
        if render is None:
            self.error_occurred.emit(f"Smart Layer render v{version} does not exist.")
            return None
        integrity = self.verify_smart_layer_render(render.version)
        if not integrity.valid:
            self.error_occurred.emit(
                "Smart Layer render failed integrity verification and cannot be exported."
            )
            return None
        try:
            export_format = (
                format if isinstance(format, ExportFormat) else ExportFormat(str(format))
            )
        except ValueError:
            self.error_occurred.emit(f"Unsupported Smart Layer export format: {format}")
            return None
        scene_kwargs: dict[str, object] = {}
        if export_format is ExportFormat.SCENE_OPENEXR_SEQUENCE:
            try:
                self._validate_true_scene_export_ready(shot)
            except SmartLayerExportError as exc:
                self.error_occurred.emit(str(exc))
                return None
            assert shot.media.source_path is not None
            diagnostics = self.display_transform_diagnostics
            input_cs = (
                diagnostics.input_color_space
                if diagnostics is not None
                else "scene_linear"
            )
            if self._last_resolved_color_settings is not None:
                input_cs = self._last_resolved_color_settings.input_color_space
            package = self._package_path

            def _mask_loader(reference: str) -> NDArray[np.uint8]:
                assert package is not None
                return self._mask_store.load(package, reference)

            scene_kwargs = {
                "scene_media_path": Path(shot.media.source_path),
                "scene_decoder": self._frame_decoder,
                "mask_loader": _mask_loader,
                "media_fingerprint": shot.media.fingerprint,
                "input_color_space": input_cs,
            }
        safe_layer_name = re.sub(r"[^A-Za-z0-9_-]+", "_", layer.name).strip("_")
        export_stem = (
            f"NOVA_{safe_layer_name or 'Smart_Layer'}_v{render.version:04d}_{export_format.value}"
        )
        try:
            result = export_smart_layer_assets(
                package_path=self._package_path,
                destination_directory=destination_directory,
                export_stem=export_stem,
                render=render,
                format=export_format,
                project={"id": str(self._project.id), "name": self._project.name},
                shot={
                    "id": str(shot.id),
                    "name": shot.name,
                    "range_start": render.frame_start,
                    "range_end": render.frame_end,
                    "frame_rate": shot.media.frame_rate,
                    "width": shot.media.width,
                    "height": shot.media.height,
                },
                smart_layer={"id": str(layer.id), "name": layer.name},
                frame_rate=shot.media.frame_rate,
                color_policy=load_render_color_metadata(self._package_path, render),
                **scene_kwargs,  # type: ignore[arg-type]
            )
        except (OSError, ValueError, SmartLayerExportError, FileNotFoundError, MediaReadError) as exc:
            self.error_occurred.emit(f"Smart Layer export failed: {exc}")
            return None
        self.smart_layer_export_ready.emit(str(result.path))
        return result.path

    def _validate_true_scene_export_ready(self, shot: Shot) -> None:
        """Raise SmartLayerExportError unless EXR sequence + OIIO scene path is available."""
        if shot.media.source_path is None:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        media_path = Path(shot.media.source_path)
        if not isinstance(self._media_reader, ImageSequenceReader):
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        try:
            files = list_sequence_files(media_path)
        except Exception as exc:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            ) from exc
        if not files or files[0].suffix.lower() != ".exr":
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        if _load_openimageio() is None:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        # Probe one scene frame to reject Pillow-only environments early.
        try:
            self._frame_decoder.get_scene_frame(media_path, 0)
        except MediaReadError as exc:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO. "
                f"({exc})"
            ) from exc

    def _job_failed(self, name: str, message: str) -> None:
        if name == "skeleton_fusion_detection":
            if "no semantic labels matching" in message:
                self.error_occurred.emit(
                    "Automatic pose detection found no joints that match the labeled artist "
                    "skeleton. Check joint labels or the Depth/Pose detector configuration."
                )
                return
            self.error_occurred.emit(f"Automatic pose detection failed: {message}")
            return
        self.error_occurred.emit(f"{name} failed: {message}")

    def validation_previews(
        self,
    ) -> list[tuple[FrameResult, NDArray[np.uint8], NDArray[np.uint8]]]:
        shot = self.active_shot
        if (
            shot is None
            or not shot.smart_layers
            or self._package_path is None
            or shot.media.source_path is None
        ):
            return []
        previews: list[tuple[FrameResult, NDArray[np.uint8], NDArray[np.uint8]]] = []
        ordered_results = sorted(
            shot.smart_layers[0].frame_results,
            key=lambda item: item.frame_number,
        )
        for result in ordered_results:
            try:
                frame = self._frame_decoder.get_preview_frame(
                    Path(shot.media.source_path), result.frame_number
                )
                mask = self._mask_store.load(self._package_path, result.mask_reference)
            except (MediaReadError, MaskStoreError, OSError, ValueError) as exc:
                self.error_occurred.emit(str(exc))
                return []
            previews.append((result, frame, mask))
        return previews

    def set_validation_state(self, frame_number: int, state: ValidationState) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            return False
        layer = shot.smart_layers[0]
        result = next(
            (item for item in layer.frame_results if item.frame_number == frame_number),
            None,
        )
        if result is None:
            self.error_occurred.emit(f"No validation result exists for frame {frame_number}.")
            return False

        result.validation_state = state
        decision = (
            "artist_accepted_validation_frame"
            if state == ValidationState.ACCEPTED
            else "artist_requested_frame_correction"
        )
        layer.reasoning_history.append(
            ReasoningRecord(
                evidence_ids=result.evidence_ids,
                decision=decision,
                confidence=result.confidence,
                previous_maturity=layer.object_identity.maturity_state,
                resulting_maturity=layer.object_identity.maturity_state,
                artist_confirmation_required=state != ValidationState.ACCEPTED,
            )
        )

        all_accepted = len(layer.frame_results) >= 3 and all(
            item.validation_state == ValidationState.ACCEPTED for item in layer.frame_results
        )
        generated_previews: list[tuple[int, NDArray[np.uint8], str]] = []
        if all_accepted:
            coverage_ok, coverage_reason = self._full_range_mask_coverage(shot, layer)
            if not coverage_ok:
                self.error_occurred.emit(
                    "Cannot complete validation: " + coverage_reason
                )
                # Do not mark VALIDATED when full-range coverage is incomplete.
            else:
                layer.object_identity.maturity_state = MaturityState.VALIDATED
                layer.reasoning_history[-1].resulting_maturity = MaturityState.VALIDATED
                created = self._create_extraction_previews(shot, layer)
                if created is None:
                    return False
                generated_previews = created

        if not self._save_current():
            return False
        for preview_frame, rgba, reference in generated_previews:
            self.extraction_preview_ready.emit(preview_frame, rgba, reference)
        self.validation_state_changed.emit(layer.frame_results)
        return True

    def _full_range_mask_coverage(
        self, shot: Shot, layer: SmartLayer
    ) -> tuple[bool, str]:
        """Require one on-disk mask source for every frame in the selected range."""
        if self._package_path is None:
            return False, "Project package path is missing."
        by_frame: dict[int, str] = {}
        for item in layer.temporal_observations:
            if item.mask_reference is not None:
                by_frame[item.frame_number] = item.mask_reference
        master = next(
            (item for item in layer.frame_results if item.direction == "master"),
            None,
        )
        if master is not None:
            by_frame.setdefault(master.frame_number, master.mask_reference)
        expected = list(range(shot.range_start, shot.range_end + 1))
        missing = [frame for frame in expected if frame not in by_frame]
        if missing:
            preview = ", ".join(str(frame) for frame in missing[:8])
            more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
            return (
                False,
                "full-range mask coverage is incomplete. Missing frame(s): "
                f"{preview}{more}. Propagate again before marking validation complete.",
            )
        for frame_number in expected:
            reference = by_frame[frame_number]
            if not (self._package_path / reference).is_file():
                return (
                    False,
                    f"mask file missing for frame {frame_number} ({reference}). "
                    "Propagate again before marking validation complete.",
                )
        return True, ""

    def promote_to_production_ready(self) -> bool:
        shot = self.active_shot
        if shot is None or not shot.smart_layers:
            self.error_occurred.emit("No Smart Layer is available for production promotion.")
            return False
        layer = shot.smart_layers[0]
        try:
            promote_to_production_ready(layer)
        except MaturityPromotionError as exc:
            self.error_occurred.emit(str(exc))
            return False
        if not self._save_current():
            return False
        self.production_ready_changed.emit(layer)
        return True

    def _create_extraction_previews(
        self, shot: Shot, layer: SmartLayer
    ) -> list[tuple[int, NDArray[np.uint8], str]] | None:
        if self._package_path is None or shot.media.source_path is None:
            return None
        previews: list[ExtractionPreview] = []
        generated: list[tuple[int, NDArray[np.uint8], str]] = []
        try:
            for result in sorted(layer.frame_results, key=lambda item: item.frame_number):
                frame = self._frame_decoder.get_preview_frame(
                    Path(shot.media.source_path), result.frame_number
                )
                mask = self._mask_store.load(self._package_path, result.mask_reference)
                rgba = compose_rgba(frame, mask)
                reference = f"previews/frame_{result.frame_number:06d}.png"
                self._preview_store.save(self._package_path, reference, rgba)
                previews.append(
                    ExtractionPreview(
                        frame_number=result.frame_number,
                        image_reference=reference,
                        mask_reference=result.mask_reference,
                    )
                )
                generated.append((result.frame_number, rgba, reference))
        except (MediaReadError, MaskStoreError, PreviewStoreError, OSError, ValueError) as exc:
            self.error_occurred.emit(f"Preview extraction failed: {exc}")
            return None
        layer.extraction_previews = previews
        return generated

    def apply_frame_correction(
        self,
        frame_number: int,
        points: list[GuidancePoint],
        bounding_region: BoundingRegion | None,
    ) -> FrameResult | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or self._package_path is None:
            return None
        if frame_number == shot.master_frame:
            self.error_occurred.emit(
                "Master Frame correction requires refining the Object Hypothesis."
            )
            return None
        layer = shot.smart_layers[0]
        existing = next(
            (item for item in layer.frame_results if item.frame_number == frame_number),
            None,
        )
        if existing is None:
            self.error_occurred.emit(f"No propagated result exists for frame {frame_number}.")
            return None
        if not points and bounding_region is None:
            self.error_occurred.emit("Correction requires at least one point or region.")
            return None

        try:
            if shot.media.source_path is None:
                raise ValueError("Source media is not linked.")
            image = self._get_source_processing_frame(
                Path(shot.media.source_path), frame_number
            )
            result = self._segmentation.predict(
                frame_number=frame_number,
                image=image,
                width=shot.media.width,
                height=shot.media.height,
                points=points,
                bounding_region=bounding_region,
            )
        except Exception as exc:
            self.error_occurred.emit(f"Correction segmentation failed: {exc}")
            return None
        correction_reference = f"masks/correction_{frame_number:06d}.png"
        try:
            self._mask_store.save(
                self._package_path,
                correction_reference,
                result.mask,
            )
        except MaskStoreError as exc:
            self.error_occurred.emit(str(exc))
            return None

        artist_evidence = EvidenceRecord(
            source_type="artist",
            frame_number=frame_number,
            payload_reference=correction_reference,
            confidence=1.0,
        )
        capability_evidence = EvidenceRecord(
            source_type="capability",
            frame_number=frame_number,
            payload_reference=correction_reference,
            confidence=result.confidence,
            provenance=result.provenance,
        )
        layer.evidence_history.extend([artist_evidence, capability_evidence])
        existing.mask_reference = correction_reference
        existing.confidence = result.confidence
        existing.evidence_ids = [artist_evidence.id, capability_evidence.id]
        existing.provenance = result.provenance
        existing.validation_state = ValidationState.PENDING
        layer.reasoning_history.append(
            ReasoningRecord(
                evidence_ids=existing.evidence_ids,
                decision=f"artist_correction_recomputed_{existing.direction}_region",
                confidence=result.confidence,
                previous_maturity=layer.object_identity.maturity_state,
                resulting_maturity=MaturityState.CONFIRMED,
                artist_confirmation_required=True,
            )
        )
        layer.object_identity.maturity_state = MaturityState.CONFIRMED
        layer.version += 1
        if not self._save_current():
            return None
        self.correction_applied.emit(frame_number, result.mask, result.confidence)
        self.validation_state_changed.emit(layer.frame_results)
        return existing

    def _hypothesis_layer(self) -> SmartLayer | None:
        shot = self.active_shot
        if shot is None or not shot.smart_layers or not shot.smart_layers[0].frame_results:
            self.error_occurred.emit("Generate an Object Hypothesis first.")
            return None
        return shot.smart_layers[0]

    def save_current_project(self) -> bool:
        """Persist the in-memory project to the open ``.nova`` package."""
        return self._save_current()

    def _save_current(self) -> bool:
        if self._project is None or self._package_path is None:
            return False
        self._project.touch()
        try:
            self._store.save(self._project, self._package_path)
        except ProjectStoreError as exc:
            self.error_occurred.emit(str(exc))
            return False
        return True

    def restore_recovery(self) -> bool:
        if self._package_path is None:
            return False
        try:
            recovered = self._store.load_recovery(self._package_path)
            self._store.save(recovered, self._package_path)
        except ProjectStoreError as exc:
            self.error_occurred.emit(str(exc))
            return False
        self._project = recovered
        self.recovery_resolved.emit("restored")
        self.project_recovered.emit(recovered)
        self.validate_media_link()
        return True

    def discard_recovery(self) -> bool:
        if self._package_path is None:
            return False
        try:
            self._store.discard_recovery(self._package_path)
        except ProjectStoreError as exc:
            self.error_occurred.emit(str(exc))
            return False
        self.recovery_resolved.emit("discarded")
        return True

    def open_project(self, package_path: Path) -> Project | None:
        try:
            project = self._store.load(package_path)
        except ProjectStoreError as exc:
            self.error_occurred.emit(str(exc))
            return None

        self._project = project
        self._package_path = package_path.resolve()
        self.project_changed.emit(project)
        if self._store.last_migration_steps:
            self.project_migrated.emit(list(self._store.last_migration_steps))
        if self._store.has_recovery(self._package_path):
            self.recovery_available.emit(str(self._store.recovery_path(self._package_path)))
        self.validate_media_link()
        return project
