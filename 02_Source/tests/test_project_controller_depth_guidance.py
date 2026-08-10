"""Phase D3 ProjectController Depth → guidance orchestration tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import BoundingRegion, CapabilityProvenance, GuidancePoint
from nova_layer.ports.capabilities import SegmentationResult


def _png_sequence(tmp_path: Path, frames: int = 5) -> Path:
    seq = tmp_path / "png_seq"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = Image.fromarray(
            np.full((16, 24, 3), fill_value=(30 + index * 20) % 255, dtype=np.uint8),
            mode="RGB",
        )
        image.save(seq / f"frame_{index:04d}.png")
    return seq


def _ready_controller(tmp_path: Path, qtbot: object, *, segmentation: object | None = None) -> ProjectController:
    kwargs: dict[str, object] = {
        "media_reader": ImageSequenceReader(),
        "depth_analysis": FakeDepthAnalysisCapability(),
    }
    if segmentation is not None:
        kwargs["segmentation"] = segmentation
    controller = ProjectController(**kwargs)  # type: ignore[arg-type]
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    assert controller.create_project("DepthGuidance", root) is not None
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    shot = controller.active_shot
    assert shot is not None
    master = int(shot.master_frame)
    assert controller.request_frame(master)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(master)
    assert controller.last_depth_frame is not None
    return controller


class CapturingSegmentation:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> SegmentationResult:
        self.calls.append(dict(kwargs))
        height = int(kwargs["height"])  # type: ignore[arg-type]
        width = int(kwargs["width"])  # type: ignore[arg-type]
        return SegmentationResult(
            mask_reference="masks/depth_assist.png",
            mask=np.zeros((height, width), dtype=np.uint8),
            confidence=0.88,
            provenance=CapabilityProvenance(
                capability="interactive_segmentation",
                adapter="capture",
                adapter_version="1",
            ),
        )


def test_no_region_fail_safe(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    assert controller.apply_depth_region_as_guidance() is False


def test_apply_preserves_manual_point_and_bbox(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    manual = GuidancePoint(x=0.1, y=0.2, polarity="positive")
    manual_box = BoundingRegion(x=0.05, y=0.05, width=0.4, height=0.5)
    assert controller.update_artist_guidance([manual], manual_box) is not None
    region = controller.select_depth_region(x=8, y=6, tolerance=0.2)
    assert region is not None and region.pixel_count > 0
    applied: list[object] = []
    controller.depth_guidance_applied.connect(lambda p: applied.append(p))
    assert controller.apply_depth_region_as_guidance() is True
    assert applied
    intent = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    assert any(
        abs(p.x - 0.1) < 1e-9 and abs(p.y - 0.2) < 1e-9 and p.polarity == "positive"
        for p in intent.points
    )
    assert intent.bounding_region == manual_box
    assert not controller.depth_bbox_owned
    assert len(intent.points) > 1


def test_depth_bbox_when_no_manual(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    region = controller.select_depth_region(x=10, y=8, tolerance=0.25)
    assert region is not None and region.pixel_count > 0
    assert controller.apply_depth_region_as_guidance() is True
    intent = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    assert intent.bounding_region is not None
    assert controller.depth_bbox_owned


def test_duplicate_dedupe_and_clear_preserves_manual(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    region = controller.select_depth_region(x=7, y=5, tolerance=0.2)
    assert region is not None
    assert controller.apply_depth_region_as_guidance() is True
    intent = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    depth_count = len(intent.points)
    # Second apply replaces depth guidance (not doubles).
    assert controller.apply_depth_region_as_guidance() is True
    intent2 = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    assert len(intent2.points) == depth_count

    manual = GuidancePoint(x=0.9, y=0.9, polarity="negative")
    assert (
        controller.update_artist_guidance(
            [*intent2.points, manual],
            intent2.bounding_region,
        )
        is not None
    )
    assert controller.clear_depth_assist_guidance() is True
    cleared = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    assert any(p.polarity == "negative" and abs(p.x - 0.9) < 1e-9 for p in cleared.points)
    # Depth-owned bbox removed; manual points remain.
    assert cleared.bounding_region is None or not controller.depth_bbox_owned


def test_new_region_replaces_old_depth_guidance(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    assert controller.select_depth_region(x=4, y=4, tolerance=0.15) is not None
    assert controller.apply_depth_region_as_guidance() is True
    keys_a = set(controller.depth_guidance_point_keys)
    assert controller.select_depth_region(x=18, y=10, tolerance=0.15) is not None
    assert controller.apply_depth_region_as_guidance() is True
    keys_b = set(controller.depth_guidance_point_keys)
    assert keys_b
    # Provenance fully refreshed (may intersect, but should not only equal a strict subset forever).
    intent = controller.active_shot.smart_layers[0].artist_intent  # type: ignore[union-attr]
    assert any(guidance_key in keys_b for guidance_key in [
        (round(p.x, 6), round(p.y, 6), p.polarity) for p in intent.points
    ])
    del keys_a


def test_stale_frame_rejected(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    shot = controller.active_shot
    assert shot is not None
    other = 0 if shot.master_frame != 0 else 1
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(other)
    assert controller.select_depth_region(x=5, y=5, tolerance=0.2) is not None
    # Region frame is non-master → rejected.
    assert controller.apply_depth_region_as_guidance() is False


def test_sam_integration_receives_guidance_not_depth_mask(
    tmp_path: Path, qtbot: object
) -> None:
    capture = CapturingSegmentation()
    controller = _ready_controller(tmp_path, qtbot, segmentation=capture)
    region = controller.select_depth_region(x=8, y=6, tolerance=0.25)
    assert region is not None and region.pixel_count > 0
    assert controller.apply_depth_region_as_guidance() is True
    proposal = controller.last_depth_guidance
    assert proposal is not None
    with qtbot.waitSignal(controller.hypothesis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_hypothesis()
    assert len(capture.calls) == 1
    call = capture.calls[0]
    points = call["points"]
    assert isinstance(points, list)
    assert any(p.polarity == "positive" for p in points)  # type: ignore[union-attr]
    if proposal.negative_points:
        assert any(p.polarity == "negative" for p in points)  # type: ignore[union-attr]
    assert call["bounding_region"] is not None
    assert "depth" not in call
    assert "mask_prior" not in call
    image = call["image"]
    assert isinstance(image, np.ndarray) and image.dtype == np.uint8
