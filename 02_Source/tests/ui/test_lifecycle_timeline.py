from uuid import uuid4

from PySide6.QtCore import QPoint, Qt

from nova_layer.domain.models import (
    CapabilityProvenance,
    LifecycleState,
    SkeletonCorrection,
    SkeletonGuidance,
    TemporalIdentityObservation,
)
from nova_layer.ui.lifecycle_timeline import LifecycleTimeline


def make_observation(frame: int, state: LifecycleState) -> TemporalIdentityObservation:
    return TemporalIdentityObservation(
        frame_number=frame,
        lifecycle_state=state,
        confidence=0.8,
        visible=state != LifecycleState.TEMPORARILY_LOST,
        area_ratio=1.0,
        mask_reference=f"masks/{frame}.png",
        provenance=CapabilityProvenance(
            capability="temporal_propagation",
            adapter="timeline_test",
            adapter_version="1.0",
        ),
    )


def test_lifecycle_timeline_summarizes_and_navigates_markers(qtbot: object) -> None:
    timeline = LifecycleTimeline()
    timeline.resize(600, 36)
    timeline.setRange(0, 100)
    timeline.set_observations(
        [
            make_observation(20, LifecycleState.TRACKED),
            make_observation(40, LifecycleState.TEMPORARILY_LOST),
            make_observation(60, LifecycleState.RECOVERED),
        ]
    )
    qtbot.addWidget(timeline)  # type: ignore[attr-defined]
    timeline.show()

    assert timeline.marker_frames(LifecycleState.TEMPORARILY_LOST) == [40]
    assert timeline.lifecycle_summary() == "Tracked 1  ·  Lost 1  ·  Recovered 1"

    click = QPoint(timeline.marker_x(40), timeline.height() // 2)
    qtbot.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=click)  # type: ignore[attr-defined]

    assert timeline.value() == 40


def test_shot_range_handles_preview_constrained_values(qtbot: object) -> None:
    timeline = LifecycleTimeline()
    timeline.resize(600, 36)
    timeline.setRange(0, 100)
    timeline.set_shot_range(10, 90, 50)
    qtbot.addWidget(timeline)  # type: ignore[attr-defined]
    timeline.show()
    qtbot.waitExposed(timeline)  # type: ignore[attr-defined]

    start = QPoint(timeline.marker_x(10), 4)
    target = QPoint(timeline.marker_x(25), 4)
    with qtbot.waitSignal(timeline.shot_range_previewed, timeout=2000) as preview:  # type: ignore[attr-defined]
        qtbot.mousePress(timeline, Qt.MouseButton.LeftButton, pos=start)  # type: ignore[attr-defined]
        qtbot.mouseMove(timeline, pos=target)  # type: ignore[attr-defined]
        qtbot.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=target)  # type: ignore[attr-defined]

    assert preview.args == [25, 90, 50]
    assert timeline.shot_range == (25, 90, 50)


def test_skeleton_corrections_are_summarized_and_clickable(qtbot: object) -> None:
    timeline = LifecycleTimeline()
    timeline.resize(600, 36)
    timeline.setRange(0, 100)
    timeline.set_observations([make_observation(30, LifecycleState.TRACKED)])
    timeline.set_skeleton_corrections(
        [
            SkeletonCorrection(
                frame_number=30,
                skeleton=SkeletonGuidance(),
                evidence_id=uuid4(),
            )
        ]
    )
    qtbot.addWidget(timeline)  # type: ignore[attr-defined]
    timeline.show()

    assert timeline.correction_frames() == [30]
    assert timeline.lifecycle_summary().endswith("Corrected 1")
    click = QPoint(timeline.marker_x(30), timeline.height() // 2)
    qtbot.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=click)  # type: ignore[attr-defined]

    assert timeline.value() == 30
