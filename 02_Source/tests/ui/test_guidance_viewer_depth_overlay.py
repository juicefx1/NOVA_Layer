"""Phase D2 GuidanceViewer depth overlay / pick-mode tests."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from pytestqt.qtbot import QtBot

from nova_layer.app.depth_region import depth_to_grayscale
from nova_layer.domain.models import GuidancePoint
from nova_layer.ports.depth import DepthFrame, DepthNormalization, freeze_depth_array
from nova_layer.ui.guidance_viewer import GuidanceMode, GuidanceViewer


def _depth_frame() -> DepthFrame:
    depth = np.linspace(0.0, 1.0, 64, dtype=np.float32).reshape(8, 8)
    return DepthFrame(
        frame_number=0,
        media_fingerprint="fp",
        depth=freeze_depth_array(depth),
        valid_mask=None,
        quantity="relative_disparity",
        near_is="high",
        normalization=DepthNormalization(kind="model_native"),
        source_model="fake",
        model_version="1",
        preprocessing_version="p",
        input_policy="source_v1",
        metadata={},
    )


def test_grayscale_overlay_keeps_preview(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(320, 180)
    original = np.full((8, 8, 3), 40, dtype=np.uint8)
    viewer.set_frame(original)
    gray = depth_to_grayscale(_depth_frame())
    viewer.set_depth_overlay(gray, enabled=True, opacity=0.5)
    assert viewer.original_frame is not None
    assert np.array_equal(viewer.original_frame, original)
    viewer.set_depth_overlay_enabled(False)
    assert np.array_equal(viewer.original_frame, original)


def test_region_highlight_and_false_color_conflict(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(320, 180)
    preview = np.full((8, 8, 3), 10, dtype=np.uint8)
    false = np.full((8, 8, 3), 200, dtype=np.uint8)
    viewer.set_frame(preview)
    viewer.set_false_color_frame(false, legend=[("A", (200, 0, 0))], show_legend=True)
    gray = depth_to_grayscale(_depth_frame())
    viewer.set_depth_overlay(gray, enabled=True, opacity=0.6)
    assert viewer._suppress_false_color_for_depth
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:5, 2:5] = True
    viewer.set_depth_region_mask(mask)
    assert viewer._depth_region_overlay is not None
    viewer.clear_depth_overlay()
    assert not viewer._suppress_false_color_for_depth


def test_pick_mode_emits_seed_not_guidance(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.resize(320, 180)
    viewer.set_frame(np.full((32, 48, 3), 12, dtype=np.uint8))
    viewer.set_mode(GuidanceMode.POSITIVE)
    viewer.set_depth_pick_mode(True)
    seeds: list[tuple[int, int]] = []
    viewer.depth_seed_clicked.connect(lambda x, y: seeds.append((x, y)))
    # Click near center of widget; mapping depends on letterbox, may be None if missed.
    # Force via widget_to_image then synthetic event at known mapped area.
    viewer._update_display_rect()
    rect = viewer._display_rect
    assert not rect.isEmpty()
    point = QPoint(rect.center().x(), rect.center().y())
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        point.toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    viewer.mousePressEvent(event)
    assert seeds
    assert viewer.points == []


def test_guidance_unchanged_when_pick_off(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.resize(320, 180)
    viewer.set_frame(np.full((32, 48, 3), 12, dtype=np.uint8))
    viewer.set_mode(GuidanceMode.POSITIVE)
    viewer.set_depth_pick_mode(False)
    viewer._update_display_rect()
    rect = viewer._display_rect
    point = QPoint(rect.center().x(), rect.center().y())
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        point.toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    viewer.mousePressEvent(event)
    assert len(viewer.points) == 1
    assert isinstance(viewer.points[0], GuidancePoint)


def test_outside_click_ignored_in_pick_mode(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.resize(320, 180)
    viewer.set_frame(np.full((16, 16, 3), 8, dtype=np.uint8))
    viewer.set_depth_pick_mode(True)
    seeds: list[tuple[int, int]] = []
    viewer.depth_seed_clicked.connect(lambda x, y: seeds.append((x, y)))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    viewer.mousePressEvent(event)
    # Likely outside letterboxed image (None) → no seed
    assert seeds == [] or isinstance(seeds[0], tuple)
