"""Phase D2 ProjectController Depth Region orchestration tests."""

from __future__ import annotations

from pathlib import Path

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
from nova_layer.app.depth_region import DepthRegion
from nova_layer.app.project_controller import ProjectController


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


def _ready_controller(tmp_path: Path, qtbot: object) -> ProjectController:
    controller = ProjectController(
        media_reader=ImageSequenceReader(),
        depth_analysis=FakeDepthAnalysisCapability(),
    )
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    assert controller.create_project("DepthRegion", root) is not None
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    assert controller.request_frame(1)
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(1)
    assert controller.last_depth_frame is not None
    return controller


def test_no_depth_frame_returns_none(tmp_path: Path, qapp: object) -> None:
    del qapp
    controller = ProjectController(
        media_reader=ImageSequenceReader(),
        depth_analysis=FakeDepthAnalysisCapability(),
    )
    root = tmp_path / "proj"
    root.mkdir()
    assert controller.create_project("NoDepth", root) is not None
    assert controller.import_media(_png_sequence(tmp_path)) is not None
    assert controller.select_depth_region(x=1, y=1) is None
    assert controller.last_depth_region is None


def test_valid_region_and_signal(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    ready: list[DepthRegion] = []
    controller.depth_region_ready.connect(lambda r: ready.append(r))
    region = controller.select_depth_region(x=8, y=6, tolerance=0.15)
    assert region is not None
    assert ready and ready[-1].pixel_count == region.pixel_count
    assert controller.last_depth_region is region
    assert region.frame_number == 1


def test_out_of_bounds_and_invalid_seed(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    oob = controller.select_depth_region(x=999, y=0, tolerance=0.1)
    assert oob is not None and oob.pixel_count == 0
    assert oob.warning


def test_new_analysis_and_clear_region(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    assert controller.select_depth_region(x=4, y=4, tolerance=0.2) is not None
    assert controller.last_depth_region is not None
    cleared: list[int] = []
    controller.depth_region_cleared.connect(lambda: cleared.append(1))
    with qtbot.waitSignal(controller.depth_analysis_ready, timeout=5000):  # type: ignore[attr-defined]
        assert controller.start_depth_analysis(1)
    assert cleared
    assert controller.last_depth_region is None

    assert controller.select_depth_region(x=3, y=3, tolerance=0.1) is not None
    controller.clear_depth_region()
    assert controller.last_depth_region is None
    assert cleared


def test_scrub_clears_region_keeps_depth_frame(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    assert controller.select_depth_region(x=5, y=5, tolerance=0.12) is not None
    assert controller.request_frame(3)
    assert controller.last_depth_region is None
    assert controller.last_depth_frame is not None


def test_display_exposure_keeps_depth_and_region(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    region = controller.select_depth_region(x=7, y=5, tolerance=0.1)
    assert region is not None
    before = region.pixel_count
    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.5),
            display_transform=LegacyDisplayTransform(),
        )
    )
    assert controller.last_depth_frame is not None
    assert controller.last_depth_region is not None
    assert controller.last_depth_region.pixel_count == before


def test_media_change_clears(tmp_path: Path, qtbot: object) -> None:
    controller = _ready_controller(tmp_path, qtbot)
    assert controller.select_depth_region(x=2, y=2, tolerance=0.2) is not None
    assert controller.relink_media(_png_sequence(tmp_path / "b"), accept_changed=True)
    assert controller.last_depth_frame is None
    assert controller.last_depth_region is None
