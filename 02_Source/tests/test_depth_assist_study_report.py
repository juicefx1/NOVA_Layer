"""Unit tests for D3.9 artist-study aggregate helpers."""

from __future__ import annotations

from nova_layer.app.depth_assist_study_report import STUDY_CASES, aggregate_pairs, decide_d4, pair_result
from nova_layer.app.depth_assist_telemetry import (
    EVENT_DEPTH_ASSIST_APPLIED,
    EVENT_GENERATE_HYPOTHESIS,
    EVENT_HYPOTHESIS_ACCEPTED,
    EVENT_MANUAL_POSITIVE,
    DepthAssistTelemetryRecorder,
)


def _finished(workflow: str, *, primary_events: list[str]):
    rec = DepthAssistTelemetryRecorder()
    rec.set_enabled(True)
    rec.start_session(workflow=workflow, media_fingerprint="fp")  # type: ignore[arg-type]
    for name in primary_events:
        rec.record_event(name)
    rec.record_event(EVENT_GENERATE_HYPOTHESIS)
    rec.record_event(EVENT_HYPOTHESIS_ACCEPTED)
    return rec.finish_session(accepted=True)


def test_study_matrix_has_ten_cases() -> None:
    assert len(STUDY_CASES) == 10


def test_aggregate_and_d4_go_on_clear_win() -> None:
    pairs = []
    for i, spec in enumerate(STUDY_CASES):
        manual = _finished(
            "manual",
            primary_events=[EVENT_MANUAL_POSITIVE] * 5,
        )
        depth = _finished(
            "depth_assist",
            primary_events=[EVENT_DEPTH_ASSIST_APPLIED, EVENT_MANUAL_POSITIVE],
        )
        assert manual is not None and depth is not None
        pairs.append(
            pair_result(
                case_id=spec["case_id"],
                scenario=spec["scenario"],
                frame_number=i,
                manual=manual,
                depth_assist=depth,
            )
        )
    agg = aggregate_pairs(pairs)
    assert agg["n_pairs"] == 10
    assert agg["median_interaction_reduction_pct"] >= 25.0
    assert agg["depth_assist_win_rate"] == 1.0
    decision = decide_d4(agg)
    assert decision["decision"] == "GO"
