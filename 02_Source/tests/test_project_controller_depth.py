"""Phase D1 ProjectController depth analysis orchestration tests."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    ArtistIntent,
    BoundingRegion,
    GuidancePoint,
    Sequence,
    SmartLayer,
)
from nova_layer.ports.depth import DepthFrame


def _png_sequence(tmp_path: Path, frames: int = 5) -> Path:
    seq = tmp_path / "png_seq"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = Image.fromarray(
            np.full((16, 24, 3), fill_value=(index * 40) % 255, dtype=np.uint8),
            mode="RGB",
        )
        image.save(seq / f"frame_{index:04d}.png")
    return seq


def _controller(tmp_path: Path, fake: FakeDepthAnalysisCapability | None = None) -> ProjectController:
    capability = fake if fake is not None else FakeDepthAnalysisCapability()
    reader = ImageSequenceReader()
    controller = ProjectController(
        media_reader=reader,
        depth_analysis=capability,
    )
    project_root = tmp_path / "proj"
    project_root.mkdir(parents=True, exist_ok=True)
    assert controller.create_project("DepthD1", project_root) is not None
    return controller


def test_current_frame_snapshot_survives_scrub(
    tmp_path: Path,
    qtbot: object,
) -> None:
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake)
    seq = _png_sequence(tmp_path)
    shot = controller.import_media(seq)
    assert shot is not None
    assert controller.request_frame(1)
    assert controller._preview_frame_number == 1

    started: list[int] = []
    controller.depth_analysis_started.connect(lambda n: started.append(int(n)))

    gate = Event()

    original_analyze = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow_analyze(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original_analyze(**kwargs)

    controller._depth_service.analyze = slow_analyze  # type: ignore[union-attr]

    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis() is True
        # Scrub after start must not retarget the job.
        assert controller.request_frame(4)
        assert controller._preview_frame_number == 4
        gate.set()

    assert started == [1]
    assert controller.last_depth_frame is not None
    assert controller.last_depth_frame.frame_number == 1


def test_ready_last_depth_and_duplicate_reject(
    tmp_path: Path,
    qtbot: object,
) -> None:
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake)
    seq = _png_sequence(tmp_path)
    assert controller.import_media(seq) is not None
    assert controller.request_frame(2)

    ready: list[DepthFrame] = []
    controller.depth_analysis_ready.connect(lambda frame: ready.append(frame))

    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def blocked(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original(**kwargs)

    controller._depth_service.analyze = blocked  # type: ignore[union-attr]

    assert controller.start_depth_analysis(2) is True
    assert controller.start_depth_analysis(2) is False  # duplicate job
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        gate.set()
    assert ready and controller.last_depth_frame is ready[-1]
    assert controller.last_depth_frame.frame_number == 2
    assert fake.call_count == 1


def test_failed_and_cancelled_signals(
    tmp_path: Path,
    qtbot: object,
) -> None:
    class BoomDepth(FakeDepthAnalysisCapability):
        def infer(self, *, frame_number: int, image: np.ndarray):  # type: ignore[override]
            del frame_number, image
            raise RuntimeError("boom depth")

    controller = _controller(tmp_path, BoomDepth())
    seq = _png_sequence(tmp_path)
    assert controller.import_media(seq) is not None
    assert controller.request_frame(0)

    with qtbot.waitSignal(controller.depth_analysis_failed, timeout=5000) as failed:  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(0)
    assert "boom" in str(failed.args[0]).casefold() or "failed" in str(failed.args[0]).casefold()

    # Cancel path
    fake = FakeDepthAnalysisCapability()
    controller2 = _controller(tmp_path / "c2", fake)
    assert controller2.import_media(_png_sequence(tmp_path / "c2")) is not None
    assert controller2.request_frame(0)
    gate = Event()
    original = controller2._depth_service.analyze  # type: ignore[union-attr]

    def slow(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        sleep(0.05)
        return original(**kwargs)

    controller2._depth_service.analyze = slow  # type: ignore[union-attr]
    with qtbot.waitSignal(controller2.depth_analysis_cancelled, timeout=5000):  # type: ignore[attr-defined]
        assert controller2.start_depth_analysis(0)
        assert controller2.cancel_depth_analysis()
        gate.set()


def test_capability_missing(tmp_path: Path, qapp: object) -> None:
    del qapp
    controller = ProjectController(media_reader=ImageSequenceReader())
    project_root = tmp_path / "p"
    project_root.mkdir()
    assert controller.create_project("NoDepth", project_root) is not None
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    failed: list[str] = []
    controller.depth_analysis_failed.connect(lambda m: failed.append(m))
    assert controller.start_depth_analysis() is False
    assert failed


def test_media_change_clears_cache_display_keeps(
    tmp_path: Path,
    qtbot: object,
) -> None:
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake)
    seq_a = _png_sequence(tmp_path / "a")
    assert controller.import_media(seq_a) is not None
    assert controller.request_frame(0)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(0)
    assert controller.last_depth_frame is not None
    before = fake.call_count
    stats_before = controller.depth_cache_stats
    assert stats_before is not None and stats_before.count >= 1

    # Display/exposure change must keep depth cache
    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    assert controller.last_depth_frame is not None
    assert controller.depth_cache_stats is not None
    assert controller.depth_cache_stats.count >= 1

    # Relink/new media clears (same frame count so Shot Range remains valid)
    seq_b = _png_sequence(tmp_path / "b", frames=5)
    errors: list[str] = []
    controller.error_occurred.connect(lambda m: errors.append(m))
    assert controller.relink_media(seq_b, accept_changed=True), errors
    assert controller.last_depth_frame is None
    assert controller.depth_cache_stats is not None
    assert controller.depth_cache_stats.count == 0
    assert fake.call_count == before


def test_shutdown_cancels_depth(
    tmp_path: Path,
    qtbot: object,
) -> None:
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    assert controller.request_frame(0)
    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        sleep(0.2)
        return original(**kwargs)

    controller._depth_service.analyze = slow  # type: ignore[union-attr]
    assert controller.start_depth_analysis(0)
    ok = controller.shutdown(timeout_ms=3000)
    gate.set()
    assert ok is True


def test_sam_and_propagation_unchanged(
    tmp_path: Path,
    qtbot: object,
) -> None:
    """Depth analysis must not mutate hypothesis / temporal observations."""
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake)
    seq = _png_sequence(tmp_path)
    shot = controller.import_media(seq)
    assert shot is not None
    # Seed a synthetic Smart Layer like post-hypothesis state (without running SAM).
    layer = SmartLayer(
        artist_intent=ArtistIntent(
            master_frame=0,
            points=[GuidancePoint(x=0.5, y=0.5, polarity="positive")],
            bounding_region=BoundingRegion(x=0.1, y=0.1, width=0.4, height=0.4),
        )
    )
    shot.smart_layers = [layer]
    controller._project.sequences = [Sequence(name="S", shots=[shot])]  # type: ignore[union-attr]
    before_intent = layer.artist_intent.model_copy(deep=True)
    before_obs = list(layer.temporal_observations)

    assert controller.request_frame(0)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(0)

    active = controller.active_shot
    assert active is not None
    after = active.smart_layers[0]
    assert after.artist_intent == before_intent
    assert after.temporal_observations == before_obs


def test_explicit_frame_argument(
    tmp_path: Path,
    qtbot: object,
) -> None:
    controller = _controller(tmp_path)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    assert controller.request_frame(0)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000) as ready:  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(3)
    frame = ready.args[0]
    assert isinstance(frame, DepthFrame)
    assert frame.frame_number == 3
    assert frame.media_fingerprint
    assert not frame.media_fingerprint.endswith(".png")
