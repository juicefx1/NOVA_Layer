"""Phase 9C-1: GuidanceViewer widget → image coordinate mapping."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QSize
from pytestqt.qtbot import QtBot

from nova_layer.ui.guidance_viewer import GuidanceViewer


def _solid_frame(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 40, dtype=np.uint8)


def test_fit_mode_letterbox_center_maps(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(QSize(640, 360))
    viewer.set_frame(_solid_frame(100, 100))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    rect = viewer._display_rect
    assert not rect.isEmpty()
    # Center of display rect → near image center
    cx = rect.left() + rect.width() / 2.0
    cy = rect.top() + rect.height() / 2.0
    coords = viewer.widget_to_image_coordinates(QPointF(cx, cy))
    assert coords is not None
    assert abs(coords[0] - 50) <= 1
    assert abs(coords[1] - 50) <= 1


def test_letterbox_margins_are_outside(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(QSize(800, 200))
    viewer.set_frame(_solid_frame(100, 100))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    rect = viewer._display_rect
    # Point left of the letterboxed image
    assert viewer.widget_to_image_coordinates(QPointF(rect.left() - 2, rect.center().y())) is None
    assert viewer.widget_to_image_coordinates(QPointF(rect.right() + 2, rect.center().y())) is None


def test_boundary_pixels(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(QSize(400, 400))
    viewer.set_frame(_solid_frame(10, 10))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    rect = viewer._display_rect
    # Slightly inside top-left of display → pixel (0, 0)
    top_left = viewer.widget_to_image_coordinates(
        QPointF(rect.left() + 0.5, rect.top() + 0.5)
    )
    assert top_left == (0, 0)
    # Exactly at right/bottom edge (≥1.0) → outside (no clamp)
    assert viewer.widget_to_image_coordinates(
        QPointF(rect.left() + rect.width(), rect.top() + 1)
    ) is None
    # Near bottom-right interior → last pixel
    near_br = viewer.widget_to_image_coordinates(
        QPointF(
            rect.left() + rect.width() * 0.999,
            rect.top() + rect.height() * 0.999,
        )
    )
    assert near_br == (9, 9)


def test_one_to_one_when_sizes_match(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.setMinimumSize(0, 0)
    viewer.resize(QSize(64, 48))
    viewer.set_frame(_solid_frame(64, 48))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    assert viewer.widget_to_image_coordinates(QPointF(0.5, 0.5)) == (0, 0)
    assert viewer.widget_to_image_coordinates(QPointF(63.5, 47.5)) == (63, 47)
    assert viewer.widget_to_image_coordinates(QPointF(100, 100)) is None


def test_zoom_via_larger_widget_still_maps(qtbot: QtBot) -> None:
    """Larger widget than image scales up (fit); coords stay image-space."""
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(QSize(400, 400))
    viewer.set_frame(_solid_frame(40, 40))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    rect = viewer._display_rect
    assert rect.width() > 40
    coords = viewer.widget_to_image_coordinates(
        QPointF(rect.left() + rect.width() * 0.25, rect.top() + rect.height() * 0.25)
    )
    assert coords is not None
    assert coords == (10, 10)


def test_pixel_hover_signals(qtbot: QtBot) -> None:
    viewer = GuidanceViewer()
    qtbot.addWidget(viewer)
    viewer.resize(QSize(200, 200))
    viewer.set_frame(_solid_frame(20, 20))
    viewer.show()
    qtbot.waitExposed(viewer)
    viewer._update_display_rect()
    rect = viewer._display_rect
    with qtbot.waitSignal(viewer.pixel_hovered, timeout=1000) as blocker:
        viewer._emit_pixel_hover(
            QPointF(rect.left() + rect.width() * 0.5, rect.top() + rect.height() * 0.5)
        )
    assert blocker.args == [10, 10]
    with qtbot.waitSignal(viewer.pixel_hover_cleared, timeout=1000):
        viewer._emit_pixel_hover(QPointF(0, 0))
