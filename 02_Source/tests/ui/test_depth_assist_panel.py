"""Phase D2 Depth Assist panel UI tests."""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from nova_layer.app.depth_region import DepthRegion
from nova_layer.ui.depth_assist_panel import DepthAssistPanel
import numpy as np


def test_panel_controls_and_empty_state(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.show()
    assert panel.analyze_button.text() == "Analyze Scene"
    assert panel.overlay_check.text() == "Depth Overlay"
    assert panel.pick_button.text() == "Pick Region"
    assert panel.one_click_button.text() == "One-Click Select"
    assert not panel.one_click_button.isChecked()
    assert not panel.one_click_enabled()
    panel.set_empty_state()
    assert not panel.overlay_check.isEnabled()
    assert not panel.pick_button.isEnabled()
    panel.set_depth_available(True)
    assert panel.overlay_check.isEnabled()


def test_analyze_cancel_overlay_opacity_tolerance(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    events: list[str] = []
    panel.analyze_requested.connect(lambda: events.append("analyze"))
    panel.cancel_requested.connect(lambda: events.append("cancel"))
    panel.overlay_toggled.connect(lambda v: events.append(f"overlay:{v}"))
    panel.opacity_changed.connect(lambda v: events.append(f"op:{v:.2f}"))
    panel.tolerance_changed.connect(lambda v: events.append(f"tol:{v:.2f}"))
    panel.clear_region_requested.connect(lambda: events.append("clear"))

    panel.analyze_button.click()
    panel.set_analyzing(True)
    assert panel.cancel_button.isEnabled()
    panel.cancel_button.click()
    panel.set_analyzing(False)
    panel.set_depth_available(True)
    panel.overlay_check.setChecked(True)
    panel.opacity_spin.setValue(0.4)
    panel.tolerance_spin.setValue(0.2)
    panel.clear_region_button.click()
    assert "analyze" in events and "cancel" in events
    assert any(e.startswith("overlay:") for e in events)
    assert any(e.startswith("op:") for e in events)
    assert any(e.startswith("tol:") for e in events)


def test_region_stats_and_pick(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.set_depth_available(True)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    region = DepthRegion(
        frame_number=0,
        seed_x=1,
        seed_y=1,
        seed_depth=0.42,
        tolerance=0.1,
        mask=mask,
        bounding_box=(1, 1, 2, 2),
        pixel_count=4,
        coverage=0.25,
        warning="Depth Region is a spatial prior.",
    )
    panel.apply_region(region)
    assert "0.42" in panel.seed_depth_label.text()
    assert panel.pixel_count_label.text() == "4"
    assert "25.00%" in panel.coverage_label.text()
    assert panel.clear_region_button.isEnabled()
    assert "spatial prior" in panel.status_label.text()
    panel.clear_region_stats()
    assert panel.pixel_count_label.text() == "—"


def test_hidden_panel_safe(qtbot: QtBot) -> None:
    panel = DepthAssistPanel()
    qtbot.addWidget(panel)
    panel.hide()
    panel.set_status("hidden ok")
    panel.set_analyzing(True)
    panel.set_analyzing(False)
    assert panel.status_label.text() == "hidden ok"
