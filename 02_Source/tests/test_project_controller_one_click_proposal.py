"""Phase D3.10 One-Click Object Proposal orchestration tests."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import (
    ONE_CLICK_STATUS_FAILED,
    ONE_CLICK_STATUS_IN_PROGRESS,
    ONE_CLICK_STATUS_INVALID,
    ONE_CLICK_STATUS_READY_FOR_REVIEW,
    ProjectController,
)
from nova_layer.domain.models import (
    CapabilityProvenance,
    GuidancePoint,
    MaturityState,
)
from nova_layer.ports.capabilities import SegmentationResult
from nova_layer.ports.depth import DepthFrame


def _png_sequence(tmp_path: Path, frames: int = 5) -> Path:
    seq = tmp_path / "png_seq"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        Image.fromarray(
            np.full((16, 24, 3), fill_value=(index * 40) % 255, dtype=np.uint8),
            mode="RGB",
        ).save(seq / f"frame_{index:04d}.png")
    return seq


class CapturingSegmentation:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> SegmentationResult:
        self.calls.append(dict(kwargs))
        height = int(kwargs["height"])  # type: ignore[arg-type]
        width = int(kwargs["width"])  # type: ignore[arg-type]
        return SegmentationResult(
            mask_reference="masks/one_click.png",
            mask=np.zeros((height, width), dtype=np.uint8),
            confidence=0.81,
            provenance=CapabilityProvenance(
                capability="interactive_segmentation",
                adapter="capture",
                adapter_version="1",
            ),
        )


def _controller(
    tmp_path: Path,
    *,
    fake: FakeDepthAnalysisCapability | None = None,
    segmentation: object | None = None,
) -> ProjectController:
    kwargs: dict[str, object] = {
        "media_reader": ImageSequenceReader(),
        "depth_analysis": fake if fake is not None else FakeDepthAnalysisCapability(),
    }
    if segmentation is not None:
        kwargs["segmentation"] = segmentation
    controller = ProjectController(**kwargs)  # type: ignore[arg-type]
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    assert controller.create_project("OneClickD310", root) is not None
    return controller


def _on_master(controller: ProjectController) -> int:
    shot = controller.active_shot
    assert shot is not None
    master = int(shot.master_frame)
    assert controller.request_frame(master)
    return master


def test_click_snapshots_frame_and_seed(tmp_path: Path, qtbot: object) -> None:
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(master)
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_one_click_proposal(8, 6)
    request = controller.one_click_request
    assert request is None
    assert controller.last_one_click_status == ONE_CLICK_STATUS_READY_FOR_REVIEW
    region = controller.last_depth_region
    assert region is not None
    assert region.seed_x == 8 and region.seed_y == 6
    assert region.frame_number == master


def test_duplicate_request_rejected_while_in_flight(tmp_path: Path, qtbot: object) -> None:
    fake = FakeDepthAnalysisCapability()
    controller = _controller(tmp_path, fake=fake)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow_analyze(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original(**kwargs)

    controller._depth_service.analyze = slow_analyze  # type: ignore[union-attr]
    assert controller.start_one_click_proposal(8, 6) is True
    assert controller.one_click_in_progress is True
    statuses: list[str] = []
    controller.one_click_status_changed.connect(statuses.append)
    assert controller.start_one_click_proposal(4, 4) is False
    assert ONE_CLICK_STATUS_IN_PROGRESS in statuses
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        gate.set()


def test_invalid_click_rejected(tmp_path: Path, qapp: object) -> None:
    del qapp
    controller = _controller(tmp_path)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    assert controller.start_one_click_proposal(-1, 0) is False
    assert controller.last_one_click_status == ONE_CLICK_STATUS_INVALID
    assert controller.start_one_click_proposal(8, 99) is False
    assert controller.one_click_in_progress is False


def test_cache_fast_path_does_not_infer_again(tmp_path: Path, qtbot: object) -> None:
    fake = FakeDepthAnalysisCapability()
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, fake=fake, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(master)
    infer_count = fake.call_count
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_one_click_proposal(8, 6)
    assert fake.call_count == infer_count
    assert len(capture.calls) == 1
    assert "depth" not in capture.calls[0]
    assert "mask_prior" not in capture.calls[0]
    assert "mask_input" not in capture.calls[0]


def test_slow_path_keeps_original_seed(tmp_path: Path, qtbot: object) -> None:
    fake = FakeDepthAnalysisCapability()
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, fake=fake, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow_analyze(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original(**kwargs)

    controller._depth_service.analyze = slow_analyze  # type: ignore[union-attr]
    assert controller.start_one_click_proposal(8, 6) is True
    snapshot = controller.one_click_request
    assert snapshot is not None
    assert snapshot.seed_x == 8 and snapshot.seed_y == 6
    assert snapshot.frame_number == master
    assert snapshot.used_depth_cache is False
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        gate.set()
    region = controller.last_depth_region
    assert region is not None
    assert region.seed_x == 8 and region.seed_y == 6
    assert len(capture.calls) == 1
    assert fake.call_count == 1


def test_scrub_does_not_contaminate_current_frame(tmp_path: Path, qtbot: object) -> None:
    fake = FakeDepthAnalysisCapability()
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, fake=fake, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    shot = controller.active_shot
    assert shot is not None
    master = _on_master(controller)
    other = int(shot.range_end)
    assert other != master
    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow_analyze(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original(**kwargs)

    controller._depth_service.analyze = slow_analyze  # type: ignore[union-attr]
    assert controller.start_one_click_proposal(8, 6) is True
    assert controller.request_frame(other)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        gate.set()
    assert capture.calls == []
    assert controller.one_click_in_progress is False
    assert f"Proposal completed for frame {master}" in controller.last_one_click_status
    active = controller.active_shot
    assert active is not None
    if active.smart_layers:
        intent = active.smart_layers[0].artist_intent
        assert intent.points == []
        assert intent.bounding_region is None


def test_source_policy_for_depth_and_sam(tmp_path: Path, qtbot: object) -> None:
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    policies: list[object] = []
    preview_calls = {"count": 0}
    decoder = controller._frame_decoder
    original = decoder.get_processing_frame
    original_preview = decoder.get_preview_frame

    def wrapped_processing(*args: object, **kwargs: object) -> object:
        policies.append(kwargs.get("policy") or (args[3] if len(args) > 3 else None))
        return original(*args, **kwargs)

    def wrapped_preview(*args: object, **kwargs: object) -> object:
        preview_calls["count"] += 1
        return original_preview(*args, **kwargs)

    decoder.get_processing_frame = wrapped_processing  # type: ignore[method-assign]
    decoder.get_preview_frame = wrapped_preview  # type: ignore[method-assign]
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_one_click_proposal(8, 6)
    assert preview_calls["count"] == 0
    assert policies
    assert all(policy is ProcessingColorPolicy.SOURCE for policy in policies if policy is not None)
    image = capture.calls[0]["image"]
    assert isinstance(image, np.ndarray) and image.dtype == np.uint8


def test_no_auto_accept(tmp_path: Path, qtbot: object) -> None:
    controller = _controller(tmp_path)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_one_click_proposal(8, 6)
    shot = controller.active_shot
    assert shot is not None
    assert shot.smart_layers[0].object_identity.maturity_state == MaturityState.HYPOTHESIS


def test_cancel_clears_pending_and_skips_sam(tmp_path: Path, qtbot: object) -> None:
    capture = CapturingSegmentation()
    controller = _controller(tmp_path, segmentation=capture)
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    gate = Event()
    original = controller._depth_service.analyze  # type: ignore[union-attr]

    def slow_analyze(**kwargs: object) -> DepthFrame:
        gate.wait(timeout=2)
        return original(**kwargs)

    controller._depth_service.analyze = slow_analyze  # type: ignore[union-attr]
    assert controller.start_one_click_proposal(8, 6) is True
    with qtbot.waitSignal(controller.depth_analysis_cancelled, timeout=5000):  # type: ignore[attr-defined]
        assert controller.cancel_one_click_proposal()
        gate.set()
    assert capture.calls == []
    assert controller.one_click_in_progress is False
    assert controller.last_one_click_status == "Cancelled"


def test_failure_leaves_manual_workflow_usable(tmp_path: Path, qtbot: object) -> None:
    controller = ProjectController(media_reader=ImageSequenceReader(), depth_analysis=None)
    root = tmp_path / "proj"
    root.mkdir()
    assert controller.create_project("NoDepthOneClick", root) is not None
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    master = _on_master(controller)
    assert controller.start_one_click_proposal(8, 6) is False
    assert controller.last_one_click_status == ONE_CLICK_STATUS_FAILED
    from nova_layer.domain.models import GuidancePoint

    assert (
        controller.update_artist_guidance(
            [GuidancePoint(x=0.4, y=0.5, polarity="positive")],
            None,
        )
        is not None
    )
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_hypothesis()
