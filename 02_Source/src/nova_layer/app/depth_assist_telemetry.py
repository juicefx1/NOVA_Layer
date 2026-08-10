"""Phase D3.8 Depth Assist artist-study telemetry (session-local, privacy-safe).

In-memory interaction logging for Manual vs Depth Assist comparison.
No network, no schema persistence, no source/path payloads.
"""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from time import monotonic
from typing import Any, Literal

WorkflowKind = Literal["manual", "depth_assist", "unknown"]

# Canonical event vocabulary (instrumentation should use these strings).
EVENT_STUDY_STARTED = "study_started"
EVENT_ANALYZE_SCENE = "analyze_scene"
EVENT_DEPTH_REGION_PICKED = "depth_region_picked"
EVENT_TOLERANCE_CHANGED = "tolerance_changed"
EVENT_DEPTH_ASSIST_APPLIED = "depth_assist_applied"
EVENT_DEPTH_GUIDANCE_CLEARED = "depth_guidance_cleared"
EVENT_MANUAL_POSITIVE = "manual_positive"
EVENT_MANUAL_NEGATIVE = "manual_negative"
EVENT_BBOX_CHANGED = "bbox_changed"
EVENT_GENERATE_HYPOTHESIS = "generate_hypothesis"
EVENT_HYPOTHESIS_REJECTED = "hypothesis_rejected"
EVENT_HYPOTHESIS_ACCEPTED = "hypothesis_accepted"
EVENT_REFINE_ROUND_STARTED = "refine_round_started"
EVENT_STUDY_FINISHED = "study_finished"

PRIMARY_EVENT_TYPES = frozenset(
    {
        EVENT_MANUAL_POSITIVE,
        EVENT_MANUAL_NEGATIVE,
        EVENT_BBOX_CHANGED,
        EVENT_TOLERANCE_CHANGED,
        EVENT_DEPTH_REGION_PICKED,
        EVENT_DEPTH_ASSIST_APPLIED,
        EVENT_REFINE_ROUND_STARTED,
        # Refine clicks after reject are modeled as refine_round_started + manual_* .
    }
)
SETUP_EVENT_TYPES = frozenset({EVENT_ANALYZE_SCENE})
ACTION_EVENT_TYPES = frozenset({EVENT_GENERATE_HYPOTHESIS})


@dataclass(frozen=True, slots=True)
class DepthAssistInteractionEvent:
    """One privacy-safe artist interaction sample."""

    timestamp_monotonic: float
    event_type: str
    frame_number: int | None = None
    workflow: WorkflowKind = "unknown"
    tolerance: float | None = None
    region_coverage: float | None = None
    positive_count: int | None = None
    negative_count: int | None = None
    bbox_present: bool | None = None
    warning: str | None = None
    backend_model_id: str | None = None


@dataclass(frozen=True, slots=True)
class DepthAssistStudySession:
    """Finished or in-progress study snapshot (in-memory / export only)."""

    session_id: str
    workflow: WorkflowKind
    media_fingerprint: str | None
    started_at_monotonic: float
    events: tuple[DepthAssistInteractionEvent, ...]
    accepted: bool | None = None
    refine_rounds: int = 0
    notes: str | None = None
    finished_at_monotonic: float | None = None
    backend_model_id: str | None = None


@dataclass(frozen=True, slots=True)
class DepthAssistSessionSummary:
    session_id: str
    workflow: WorkflowKind
    primary_interactions: int
    setup_interactions: int
    action_interactions: int
    total_interactions: int
    refine_rounds: int
    accepted: bool | None
    first_pass_accept: bool | None
    tolerance_changes: int
    assist_count: int
    positive_clicks: int
    negative_clicks: int
    pick_count: int
    bbox_changes: int
    generate_count: int
    duration_seconds: float | None
    media_fingerprint: str | None
    event_count: int


@dataclass(frozen=True, slots=True)
class DepthAssistSessionComparison:
    manual_primary: int
    depth_assist_primary: int
    interaction_delta: int
    interaction_reduction_percent: float | None
    refine_round_delta: int
    manual_first_pass_accept: bool | None
    depth_assist_first_pass_accept: bool | None
    duration_delta_seconds: float | None


def _sanitize_warning(warning: str | None) -> str | None:
    """Drop path-like fragments from free-text warnings before storage."""
    if warning is None:
        return None
    text = str(warning).strip()
    if not text:
        return None
    # Strip absolute / home-style path segments without inventing replacements.
    parts = []
    for token in text.replace("\\", "/").split():
        if token.startswith("/") or token.startswith("~") or ":/" in token:
            continue
        if len(token) > 2 and token[1] == ":" and token[2] == "/":
            continue
        parts.append(token)
    cleaned = " ".join(parts).strip()
    return cleaned or None


def new_session_id() -> str:
    return str(uuid.uuid4())


@dataclass
class _MutableSession:
    session_id: str
    workflow: WorkflowKind
    media_fingerprint: str | None
    started_at_monotonic: float
    events: list[DepthAssistInteractionEvent] = field(default_factory=list)
    accepted: bool | None = None
    notes: str | None = None
    finished_at_monotonic: float | None = None
    backend_model_id: str | None = None

    def freeze(self) -> DepthAssistStudySession:
        refine = sum(
            1 for e in self.events if e.event_type == EVENT_REFINE_ROUND_STARTED
        )
        return DepthAssistStudySession(
            session_id=self.session_id,
            workflow=self.workflow,
            media_fingerprint=self.media_fingerprint,
            started_at_monotonic=self.started_at_monotonic,
            events=tuple(self.events),
            accepted=self.accepted,
            refine_rounds=refine,
            notes=self.notes,
            finished_at_monotonic=self.finished_at_monotonic,
            backend_model_id=self.backend_model_id,
        )


class DepthAssistTelemetryRecorder:
    """In-memory study recorder. Disabled → every mutation is a no-op."""

    def __init__(self) -> None:
        self._enabled = False
        self._active: _MutableSession | None = None
        self._last_finished: DepthAssistStudySession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    @property
    def is_recording(self) -> bool:
        return self._enabled and self._active is not None and self._active.finished_at_monotonic is None

    @property
    def current_session(self) -> DepthAssistStudySession | None:
        if self._active is None:
            return None
        return self._active.freeze()

    @property
    def last_finished_session(self) -> DepthAssistStudySession | None:
        return self._last_finished

    def clear(self) -> None:
        self._active = None
        self._last_finished = None

    def start_session(
        self,
        *,
        workflow: WorkflowKind,
        media_fingerprint: str | None = None,
        backend_model_id: str | None = None,
        frame_number: int | None = None,
    ) -> DepthAssistStudySession | None:
        if not self._enabled:
            return None
        if workflow not in ("manual", "depth_assist", "unknown"):
            raise ValueError(f"Unsupported workflow: {workflow!r}")
        started = monotonic()
        self._active = _MutableSession(
            session_id=new_session_id(),
            workflow=workflow,  # type: ignore[arg-type]
            media_fingerprint=media_fingerprint,
            started_at_monotonic=started,
            backend_model_id=backend_model_id,
        )
        self.record_event(
            EVENT_STUDY_STARTED,
            frame_number=frame_number,
            workflow=workflow,  # type: ignore[arg-type]
            backend_model_id=backend_model_id,
        )
        return self.current_session

    def record_event(
        self,
        event_type: str,
        *,
        frame_number: int | None = None,
        workflow: WorkflowKind | None = None,
        tolerance: float | None = None,
        region_coverage: float | None = None,
        positive_count: int | None = None,
        negative_count: int | None = None,
        bbox_present: bool | None = None,
        warning: str | None = None,
        backend_model_id: str | None = None,
        timestamp_monotonic: float | None = None,
    ) -> DepthAssistInteractionEvent | None:
        if not self.is_recording or self._active is None:
            return None
        assert self._active is not None
        wf: WorkflowKind = workflow or self._active.workflow
        event = DepthAssistInteractionEvent(
            timestamp_monotonic=float(
                monotonic() if timestamp_monotonic is None else timestamp_monotonic
            ),
            event_type=str(event_type),
            frame_number=None if frame_number is None else int(frame_number),
            workflow=wf,
            tolerance=None if tolerance is None else float(tolerance),
            region_coverage=None if region_coverage is None else float(region_coverage),
            positive_count=None if positive_count is None else int(positive_count),
            negative_count=None if negative_count is None else int(negative_count),
            bbox_present=None if bbox_present is None else bool(bbox_present),
            warning=_sanitize_warning(warning),
            backend_model_id=backend_model_id or self._active.backend_model_id,
        )
        self._active.events.append(event)
        return event

    def finish_session(
        self,
        *,
        accepted: bool | None = None,
        notes: str | None = None,
    ) -> DepthAssistStudySession | None:
        if not self._enabled or self._active is None:
            return None
        if self._active.finished_at_monotonic is not None:
            return self._active.freeze()
        if accepted is not None:
            self._active.accepted = bool(accepted)
        elif self._active.accepted is None:
            for event in reversed(self._active.events):
                if event.event_type == EVENT_HYPOTHESIS_ACCEPTED:
                    self._active.accepted = True
                    break
                if event.event_type == EVENT_HYPOTHESIS_REJECTED:
                    self._active.accepted = False
                    break
        self._active.notes = _sanitize_warning(notes)
        self.record_event(EVENT_STUDY_FINISHED)
        self._active.finished_at_monotonic = monotonic()
        finished = self._active.freeze()
        self._last_finished = finished
        self._active = None
        return finished


def count_event_types(session: DepthAssistStudySession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in session.events:
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return counts


def summarize_depth_assist_session(
    session: DepthAssistStudySession,
) -> DepthAssistSessionSummary:
    counts = count_event_types(session)
    primary = sum(counts.get(name, 0) for name in PRIMARY_EVENT_TYPES)
    setup = sum(counts.get(name, 0) for name in SETUP_EVENT_TYPES)
    action = sum(counts.get(name, 0) for name in ACTION_EVENT_TYPES)
    refine = int(session.refine_rounds)
    if refine == 0:
        refine = int(counts.get(EVENT_REFINE_ROUND_STARTED, 0))
    accepted = session.accepted
    generate_count = int(counts.get(EVENT_GENERATE_HYPOTHESIS, 0))
    first_pass: bool | None
    if accepted is True:
        first_pass = refine == 0 and generate_count >= 1
    elif accepted is False:
        first_pass = False
    else:
        first_pass = None
    duration = None
    if session.finished_at_monotonic is not None:
        duration = float(session.finished_at_monotonic - session.started_at_monotonic)
    return DepthAssistSessionSummary(
        session_id=session.session_id,
        workflow=session.workflow,
        primary_interactions=primary,
        setup_interactions=setup,
        action_interactions=action,
        total_interactions=primary + setup + action,
        refine_rounds=refine,
        accepted=accepted,
        first_pass_accept=first_pass,
        tolerance_changes=int(counts.get(EVENT_TOLERANCE_CHANGED, 0)),
        assist_count=int(counts.get(EVENT_DEPTH_ASSIST_APPLIED, 0)),
        positive_clicks=int(counts.get(EVENT_MANUAL_POSITIVE, 0)),
        negative_clicks=int(counts.get(EVENT_MANUAL_NEGATIVE, 0)),
        pick_count=int(counts.get(EVENT_DEPTH_REGION_PICKED, 0)),
        bbox_changes=int(counts.get(EVENT_BBOX_CHANGED, 0)),
        generate_count=generate_count,
        duration_seconds=duration,
        media_fingerprint=session.media_fingerprint,
        event_count=len(session.events),
    )


def compare_sessions(
    manual: DepthAssistStudySession,
    depth_assist: DepthAssistStudySession,
) -> DepthAssistSessionComparison:
    """Compare a Manual vs Depth Assist finished study pair (D3.6-compatible)."""
    man = summarize_depth_assist_session(manual)
    dep = summarize_depth_assist_session(depth_assist)
    delta = man.primary_interactions - dep.primary_interactions
    reduction: float | None
    if man.primary_interactions > 0:
        reduction = 100.0 * float(delta) / float(man.primary_interactions)
    else:
        reduction = None
    duration_delta = None
    if man.duration_seconds is not None and dep.duration_seconds is not None:
        duration_delta = float(man.duration_seconds - dep.duration_seconds)
    return DepthAssistSessionComparison(
        manual_primary=man.primary_interactions,
        depth_assist_primary=dep.primary_interactions,
        interaction_delta=delta,
        interaction_reduction_percent=reduction,
        refine_round_delta=man.refine_rounds - dep.refine_rounds,
        manual_first_pass_accept=man.first_pass_accept,
        depth_assist_first_pass_accept=dep.first_pass_accept,
        duration_delta_seconds=duration_delta,
    )


def session_to_json_dict(session: DepthAssistStudySession) -> dict[str, Any]:
    summary = summarize_depth_assist_session(session)
    payload = {
        "session": asdict(session),
        "summary": asdict(summary),
    }
    # Hard guarantee: never include keys that look like filesystem paths.
    text = json.dumps(payload)
    if "\"/" in text or "~/" in text:
        # Strip accidental path-like warning tokens already handled; re-check notes only.
        session = replace(session, notes=_sanitize_warning(session.notes))
        payload = {
            "session": asdict(session),
            "summary": asdict(summarize_depth_assist_session(session)),
        }
    return payload


def export_session_json(session: DepthAssistStudySession, path: Path | str) -> Path:
    """Write a local JSON study artifact. Caller chooses the path explicitly."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = session_to_json_dict(session)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def export_session_csv_summary(session: DepthAssistStudySession, path: Path | str) -> Path:
    """Optional one-row CSV summary for spreadsheet comparison."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize_depth_assist_session(session)
    row = asdict(summary)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)
    return out
