"""Phase D3.8 Depth Assist artist-study telemetry unit tests."""

from __future__ import annotations

import json
from pathlib import Path

from nova_layer.app.depth_assist_telemetry import (
    EVENT_ANALYZE_SCENE,
    EVENT_DEPTH_ASSIST_APPLIED,
    EVENT_GENERATE_HYPOTHESIS,
    EVENT_HYPOTHESIS_ACCEPTED,
    EVENT_HYPOTHESIS_REJECTED,
    EVENT_MANUAL_NEGATIVE,
    EVENT_MANUAL_POSITIVE,
    EVENT_REFINE_ROUND_STARTED,
    EVENT_STUDY_FINISHED,
    EVENT_STUDY_STARTED,
    EVENT_TOLERANCE_CHANGED,
    DepthAssistTelemetryRecorder,
    compare_sessions,
    export_session_csv_summary,
    export_session_json,
    session_to_json_dict,
    summarize_depth_assist_session,
)


def test_disabled_recorder_is_noop() -> None:
    recorder = DepthAssistTelemetryRecorder()
    assert recorder.enabled is False
    assert recorder.start_session(workflow="manual") is None
    assert recorder.record_event(EVENT_MANUAL_POSITIVE) is None
    assert recorder.finish_session() is None


def test_start_finish_event_order_and_duration(tmp_path: Path) -> None:
    recorder = DepthAssistTelemetryRecorder()
    recorder.set_enabled(True)
    started = recorder.start_session(
        workflow="depth_assist",
        media_fingerprint="fp-abc",
        backend_model_id="fake_depth_v1",
        frame_number=3,
    )
    assert started is not None
    assert started.events[0].event_type == EVENT_STUDY_STARTED
    recorder.record_event(EVENT_ANALYZE_SCENE, frame_number=3)
    recorder.record_event(EVENT_MANUAL_POSITIVE)
    recorder.record_event(EVENT_GENERATE_HYPOTHESIS)
    recorder.record_event(EVENT_HYPOTHESIS_ACCEPTED)
    finished = recorder.finish_session(accepted=True)
    assert finished is not None
    types = [e.event_type for e in finished.events]
    assert types[0] == EVENT_STUDY_STARTED
    assert types[-1] == EVENT_STUDY_FINISHED
    assert finished.accepted is True
    summary = summarize_depth_assist_session(finished)
    assert summary.duration_seconds is not None and summary.duration_seconds >= 0.0
    assert summary.first_pass_accept is True
    assert summary.setup_interactions == 1
    assert summary.action_interactions == 1
    assert summary.primary_interactions == 1
    assert "/Users" not in json.dumps(session_to_json_dict(finished))
    path = export_session_json(finished, tmp_path / "study.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session"]["media_fingerprint"] == "fp-abc"
    assert "source_path" not in json.dumps(payload)
    csv_path = export_session_csv_summary(finished, tmp_path / "study.csv")
    assert csv_path.is_file()


def test_manual_vs_depth_interaction_counting_and_compare() -> None:
    manual_rec = DepthAssistTelemetryRecorder()
    manual_rec.set_enabled(True)
    manual_rec.start_session(workflow="manual", media_fingerprint="fp")
    for _ in range(3):
        manual_rec.record_event(EVENT_MANUAL_POSITIVE)
    for _ in range(2):
        manual_rec.record_event(EVENT_MANUAL_NEGATIVE)
    manual_rec.record_event(EVENT_GENERATE_HYPOTHESIS)
    manual_rec.record_event(EVENT_HYPOTHESIS_ACCEPTED)
    manual = manual_rec.finish_session(accepted=True)
    assert manual is not None

    depth_rec = DepthAssistTelemetryRecorder()
    depth_rec.set_enabled(True)
    depth_rec.start_session(workflow="depth_assist", media_fingerprint="fp")
    depth_rec.record_event(EVENT_ANALYZE_SCENE)
    depth_rec.record_event(EVENT_DEPTH_ASSIST_APPLIED)
    depth_rec.record_event(EVENT_TOLERANCE_CHANGED, tolerance=0.08)
    depth_rec.record_event(EVENT_GENERATE_HYPOTHESIS)
    depth_rec.record_event(EVENT_HYPOTHESIS_ACCEPTED)
    depth = depth_rec.finish_session(accepted=True)
    assert depth is not None

    comparison = compare_sessions(manual, depth)
    assert comparison.manual_primary == 5
    assert comparison.depth_assist_primary == 2  # assist + tolerance
    assert comparison.interaction_delta == 3
    assert comparison.interaction_reduction_percent == 60.0
    assert comparison.manual_first_pass_accept is True
    assert comparison.depth_assist_first_pass_accept is True


def test_refine_rounds_and_first_pass_false() -> None:
    recorder = DepthAssistTelemetryRecorder()
    recorder.set_enabled(True)
    recorder.start_session(workflow="manual")
    recorder.record_event(EVENT_MANUAL_POSITIVE)
    recorder.record_event(EVENT_GENERATE_HYPOTHESIS)
    recorder.record_event(EVENT_HYPOTHESIS_REJECTED)
    recorder.record_event(EVENT_REFINE_ROUND_STARTED)
    recorder.record_event(EVENT_MANUAL_NEGATIVE)
    recorder.record_event(EVENT_GENERATE_HYPOTHESIS)
    recorder.record_event(EVENT_HYPOTHESIS_ACCEPTED)
    finished = recorder.finish_session(accepted=True)
    assert finished is not None
    summary = summarize_depth_assist_session(finished)
    assert summary.refine_rounds == 1
    assert summary.first_pass_accept is False
    assert summary.generate_count == 2


def test_warning_path_sanitized() -> None:
    recorder = DepthAssistTelemetryRecorder()
    recorder.set_enabled(True)
    recorder.start_session(workflow="manual")
    recorder.record_event(
        EVENT_TOLERANCE_CHANGED,
        warning="failed under /Users/secret/project/foo.mov please lower tolerance",
    )
    finished = recorder.finish_session()
    assert finished is not None
    warning = finished.events[1].warning or ""
    assert "/Users" not in warning
    assert "tolerance" in warning.lower() or "lower" in warning.lower()
