"""Focused tests: full-range propagation + efficient clip range decode."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest

from nova_layer.adapters.capabilities.mock import MockPropagationCapability
from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.range_decode import decode_frame_range
from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    GuidancePoint,
    MaturityState,
    ValidationState,
)
from nova_layer.ports.capabilities import PropagationResult, VideoFrame
from nova_layer.ports.media import MediaInfo


class CountingMediaReader:
    """Fake reader that counts opens (each read_frame = one open)."""

    def __init__(self, frame_count: int = 8) -> None:
        self.frame_count = frame_count
        self.read_frame_calls = 0
        self.read_order: list[int] = []

    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path.resolve(),
            fingerprint="sha256:count",
            frame_count=self.frame_count,
            frame_rate=24.0,
            width=64,
            height=48,
            time_base="1/12288",
            pixel_format="yuv420p",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        self.read_frame_calls += 1
        self.read_order.append(frame_number)
        return np.full((48, 64, 3), frame_number % 256, dtype=np.uint8)


class DuplicatePropagation:
    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: list[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: list[VideoFrame],
    ) -> list[PropagationResult]:
        del reference_mask, frames
        provenance = CapabilityProvenance(
            capability="temporal_propagation",
            adapter="duplicate_test",
            adapter_version="1.0",
        )
        results: list[PropagationResult] = []
        for frame in target_frames:
            if frame == master_frame:
                continue
            # First candidate (lower confidence) then preferred duplicate.
            results.append(
                PropagationResult(
                    frame_number=frame,
                    mask_reference=f"masks/dup_low_{frame:06d}.png",
                    mask=reference_mask_data.copy(),
                    confidence=0.5,
                    provenance=provenance,
                )
            )
            results.append(
                PropagationResult(
                    frame_number=frame,
                    mask_reference=f"masks/dup_high_{frame:06d}.png",
                    mask=(reference_mask_data.copy() // 2),
                    confidence=0.95,
                    provenance=provenance,
                )
            )
        return results


class SparsePropagation:
    """Intentionally omits intermediate frames (coverage incomplete)."""

    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: list[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: list[VideoFrame],
    ) -> list[PropagationResult]:
        del master_frame, reference_mask, frames
        provenance = CapabilityProvenance(
            capability="temporal_propagation",
            adapter="sparse_test",
            adapter_version="1.0",
        )
        if not target_frames:
            return []
        ends = sorted({min(target_frames), max(target_frames)})
        return [
            PropagationResult(
                frame_number=frame,
                mask_reference=f"masks/sparse_{frame:06d}.png",
                mask=reference_mask_data.copy(),
                confidence=0.9,
                provenance=provenance,
            )
            for frame in ends
        ]


def _confirm_shot(controller: ProjectController, frame_count: int = 8) -> None:
    shot = controller.active_shot
    assert shot is not None
    assert controller.update_shot_selection(0, frame_count - 1, frame_count // 2)
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.5, height=0.5),
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()


def test_propagation_over_n_frames_produces_n_mask_sources(tmp_path: Path) -> None:
    n = 8
    controller = ProjectController(media_reader=CountingMediaReader(frame_count=n))
    controller.create_project("Full Range Prop", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, n)

    validation_cards = controller.propagate_confirmed_identity()
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    sources = controller.smart_layer_frame_sources()

    assert len(sources) == n
    assert {frame for frame, _ in sources} == set(range(n))
    assert len(validation_cards) == 2  # Start + End only
    assert len(layer.temporal_observations) == n - 1
    diagnostics = controller.last_propagation_diagnostics
    assert diagnostics is not None
    assert diagnostics.complete
    assert diagnostics.requested_frames == tuple(i for i in range(n) if i != n // 2)
    assert diagnostics.missing_frames == ()
    assert diagnostics.materialized_file_count == n - 1
    package = tmp_path / "Full_Range_Prop.nova"
    for frame, reference in sources:
        assert (package / reference).is_file(), f"missing mask for frame {frame}"


def test_master_frame_accepted_mask_is_preserved(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=CountingMediaReader(frame_count=6))
    controller.create_project("Master Preserve", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 6)
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    master_ref = layer.object_identity.confirmed_subject_reference
    assert master_ref is not None
    package = tmp_path / "Master_Preserve.nova"
    before = (package / master_ref).read_bytes()

    controller.propagate_confirmed_identity()

    assert layer.object_identity.confirmed_subject_reference == master_ref
    assert (package / master_ref).read_bytes() == before
    master = next(item for item in layer.frame_results if item.direction == "master")
    assert master.mask_reference == master_ref
    sources = dict(controller.smart_layer_frame_sources())
    assert sources[controller.active_shot.master_frame] == master_ref  # type: ignore[union-attr]


def test_duplicate_mask_candidates_collapse_deterministically(tmp_path: Path) -> None:
    controller = ProjectController(
        media_reader=CountingMediaReader(frame_count=5),
        propagation=DuplicatePropagation(),
    )
    controller.create_project("Dup Collapse", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 5)

    controller.propagate_confirmed_identity()
    diagnostics = controller.last_propagation_diagnostics
    assert diagnostics is not None
    assert diagnostics.complete
    assert set(diagnostics.duplicate_frames) == {0, 1, 3, 4}
    sources = dict(controller.smart_layer_frame_sources())
    for frame, reference in sources.items():
        if frame == 2:
            continue
        assert reference.endswith(f"dup_high_{frame:06d}.png")


def test_missing_materialized_files_prevent_validation_completion(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=CountingMediaReader(frame_count=5))
    controller.create_project("Missing Files", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 5)
    assert controller.propagate_confirmed_identity()
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    package = tmp_path / "Missing_Files.nova"
    # Delete an intermediate propagated mask after commit.
    victim = next(
        item
        for item in layer.temporal_observations
        if item.frame_number not in {0, 4}
    )
    assert victim.mask_reference is not None
    (package / victim.mask_reference).unlink()

    assert controller.set_validation_state(0, ValidationState.ACCEPTED)
    # Accept both endpoints; maturity must stay CONFIRMED because coverage files are incomplete.
    assert controller.set_validation_state(4, ValidationState.ACCEPTED)
    assert layer.object_identity.maturity_state == MaturityState.CONFIRMED
    coverage_ok, coverage_reason = controller._full_range_mask_coverage(
        controller.active_shot, layer  # type: ignore[arg-type]
    )
    assert not coverage_ok
    assert "missing" in coverage_reason.lower()
    readiness = controller.background_removal_clip_readiness()
    assert not readiness.ready


def test_mock_propagation_covers_complete_requested_range(tmp_path: Path) -> None:
    mock = MockPropagationCapability()
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[10:40, 10:50] = 255
    targets = list(range(0, 10))
    targets.remove(5)
    results = mock.propagate(
        master_frame=5,
        target_frames=targets,
        reference_mask="masks/master.png",
        reference_mask_data=mask,
        frames=[],
    )
    assert {item.frame_number for item in results} == set(targets)
    assert mock.provenance.settings.get("quality") == "Mock/Test Quality"
    assert mock.provenance.settings.get("mode") == "mock"


def test_readiness_ready_after_successful_full_range_propagation(tmp_path: Path) -> None:
    controller = ProjectController(media_reader=CountingMediaReader(frame_count=6))
    controller.create_project("Ready After Prop", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 6)
    assert not controller.background_removal_clip_readiness().ready

    assert controller.propagate_confirmed_identity()
    assert controller.set_validation_state(0, ValidationState.ACCEPTED)
    assert controller.set_validation_state(5, ValidationState.ACCEPTED)
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    assert layer.object_identity.maturity_state == MaturityState.VALIDATED

    # Provider may still block if BR engine unavailable — coverage/maturity must pass.
    readiness = controller.background_removal_clip_readiness()
    if not readiness.ready:
        assert "Background Removal" in readiness.reason or "provider" in readiness.reason.lower()
        # Force-check coverage portion by ensuring no mask/coverage message.
        assert "Missing frame" not in readiness.reason
        assert "Mask file missing" not in readiness.reason
        assert "validation" not in readiness.reason.lower() or "provider" in readiness.reason.lower()
    else:
        assert readiness.ready


def test_sparse_propagation_does_not_commit_incomplete_coverage(tmp_path: Path) -> None:
    controller = ProjectController(
        media_reader=CountingMediaReader(frame_count=6),
        propagation=SparsePropagation(),
    )
    controller.create_project("Sparse Prop", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 6)
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    results = controller.propagate_confirmed_identity()

    assert results == []
    diagnostics = controller.last_propagation_diagnostics
    assert diagnostics is not None
    assert not diagnostics.complete
    assert diagnostics.missing_frames
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    assert layer.temporal_observations == []
    assert any("full selected range" in message.lower() for message in errors)


def test_range_decode_opens_reader_once_per_job(tmp_path: Path) -> None:
    fixture = Path("/Users/juwon.lee/Desktop/NOVA_Layer/06_Test/fixtures/qa_video/qa_clip_4s.mp4")
    if not fixture.is_file():
        pytest.skip("QA clip fixture not available")
    reader = PyAvMediaReader()
    decoder = FrameDecodeService(reader, cache_size=4)
    info = reader.inspect(fixture)
    end = min(11, info.frame_count - 1)
    frames, stats = decode_frame_range(decoder, reader, fixture, 0, end)
    assert stats.decoder_opens == 1
    assert stats.decoded_frames == end + 1
    assert stats.cache_hits == 0
    assert stats.frame_order == tuple(range(0, end + 1))
    assert set(frames) == set(range(0, end + 1))


def test_frames_decoded_in_ascending_order(tmp_path: Path) -> None:
    reader = CountingMediaReader(frame_count=10)
    decoder = FrameDecodeService(reader, cache_size=2)
    frames, stats = decode_frame_range(decoder, reader, tmp_path / "clip.mov", 2, 7)
    assert list(frames) == sorted(frames)
    assert stats.frame_order == (2, 3, 4, 5, 6, 7)
    assert reader.read_order == [2, 3, 4, 5, 6, 7]


def test_cache_hits_avoid_redundant_decoding(tmp_path: Path) -> None:
    reader = CountingMediaReader(frame_count=10)
    decoder = FrameDecodeService(reader, cache_size=8)
    decode_frame_range(decoder, reader, tmp_path / "clip.mov", 0, 4)
    first_calls = reader.read_frame_calls
    frames, stats = decode_frame_range(decoder, reader, tmp_path / "clip.mov", 0, 4)
    assert stats.cache_hits == 5
    assert stats.decoded_frames == 0
    assert stats.decoder_opens == 0
    assert reader.read_frame_calls == first_calls
    assert set(frames) == {0, 1, 2, 3, 4}


def test_cancellation_creates_no_committed_render(qtbot: object, tmp_path: Path) -> None:
    controller = ProjectController(media_reader=CountingMediaReader(frame_count=6))
    controller.create_project("Cancel Render", tmp_path)
    controller.import_media(tmp_path / "source.mov")
    _confirm_shot(controller, 6)
    assert controller.propagate_confirmed_identity()
    assert controller.set_validation_state(0, ValidationState.ACCEPTED)
    assert controller.set_validation_state(5, ValidationState.ACCEPTED)
    layer = controller.active_shot.smart_layers[0]  # type: ignore[union-attr]
    assert layer.object_identity.maturity_state == MaturityState.VALIDATED
    before = len(layer.renders)

    # If BR provider is unavailable, gate blocks before staging — still no render.
    readiness = controller.background_removal_clip_readiness()
    if not readiness.ready:
        assert controller.start_background_removal_clip() is False
        assert len(layer.renders) == before
        return

    cancel_requested = {"done": False}

    def _cancel_soon() -> None:
        if not cancel_requested["done"]:
            cancel_requested["done"] = True
            controller.cancel_processing()

    controller.processing_progress.connect(lambda *_args: _cancel_soon())
    with qtbot.waitSignal(controller.processing_cancelled, timeout=30_000):  # type: ignore[attr-defined]
        assert controller.start_background_removal_clip()
    assert len(layer.renders) == before
    package = tmp_path / "Cancel_Render.nova"
    staging = list((package / "renders").glob(".staging_*")) if (package / "renders").exists() else []
    assert staging == []
