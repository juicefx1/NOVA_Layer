"""Phase D3.9 Artist Study aggregate report helpers (local, privacy-safe).

Aggregates paired Manual vs Depth Assist D3.8 sessions into D39 reports.
Does not implement D4 or change Depth Assist production behavior.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nova_layer.app.depth_assist_telemetry import (
    DepthAssistSessionComparison,
    DepthAssistStudySession,
    compare_sessions,
    session_to_json_dict,
    summarize_depth_assist_session,
)

STUDY_CASES: tuple[dict[str, str], ...] = (
    {
        "case_id": "case01_person_fg",
        "scenario": "1_single_person_fg",
        "frame_stem": "case01_person_fg",
    },
    {
        "case_id": "case02_person_chair_proxy",
        "scenario": "2_person_chair_same_depth",
        "frame_stem": "case02_person_chair_proxy",
    },
    {
        "case_id": "case03_prop_object",
        "scenario": "3_foreground_prop",
        "frame_stem": "case03_prop_object",
    },
    {
        "case_id": "case04_overlap_proxy",
        "scenario": "4_overlapping_subjects",
        "frame_stem": "case04_overlap_proxy",
    },
    {
        "case_id": "case05_limbs_proxy",
        "scenario": "5_hair_limbs_thin",
        "frame_stem": "case05_limbs_proxy",
    },
    {
        "case_id": "case06_reflective_proxy",
        "scenario": "6_reflective",
        "frame_stem": "case06_reflective_proxy",
    },
    {
        "case_id": "case07_low_contrast_proxy",
        "scenario": "7_low_contrast",
        "frame_stem": "case07_low_contrast_proxy",
    },
    {
        "case_id": "case08_depth_scene_proxy",
        "scenario": "8_wide_deep_scene",
        "frame_stem": "case08_depth_scene_proxy",
    },
    {
        "case_id": "case09_shallow_dof_proxy",
        "scenario": "9_shallow_dof",
        "frame_stem": "case09_shallow_dof_proxy",
    },
    {
        "case_id": "case10_vfx_plate",
        "scenario": "10_vfx_greenscreen_like",
        "frame_stem": "case10_vfx_plate",
    },
)


@dataclass(frozen=True, slots=True)
class PairedStudyResult:
    case_id: str
    scenario: str
    media_fingerprint: str | None
    frame_number: int
    manual: dict[str, Any]
    depth_assist: dict[str, Any]
    comparison: dict[str, Any]
    notes: str
    cliff_warnings: int
    soft_guard_warnings: int
    depth_won: bool


def load_exported_session(path: Path) -> DepthAssistStudySession:
    """Load a D3.8 export JSON (``{session, summary}``) into a session object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("session", payload)
    events = tuple(
        __import__("nova_layer.app.depth_assist_telemetry", fromlist=["DepthAssistInteractionEvent"])
        .DepthAssistInteractionEvent(**event)
        for event in raw.get("events", ())
    )
    return DepthAssistStudySession(
        session_id=str(raw["session_id"]),
        workflow=raw.get("workflow", "unknown"),
        media_fingerprint=raw.get("media_fingerprint"),
        started_at_monotonic=float(raw["started_at_monotonic"]),
        events=events,
        accepted=raw.get("accepted"),
        refine_rounds=int(raw.get("refine_rounds", 0)),
        notes=raw.get("notes"),
        finished_at_monotonic=raw.get("finished_at_monotonic"),
        backend_model_id=raw.get("backend_model_id"),
    )


def pair_result(
    *,
    case_id: str,
    scenario: str,
    frame_number: int,
    manual: DepthAssistStudySession,
    depth_assist: DepthAssistStudySession,
    notes: str = "",
) -> PairedStudyResult:
    man = summarize_depth_assist_session(manual)
    dep = summarize_depth_assist_session(depth_assist)
    cmp = compare_sessions(manual, depth_assist)
    cliff = sum(
        1
        for e in depth_assist.events
        if e.warning and "expanded sharply" in e.warning.lower()
    )
    soft = sum(
        1
        for e in depth_assist.events
        if e.warning and "reduced negative" in e.warning.lower()
    )
    depth_won = cmp.interaction_delta > 0
    return PairedStudyResult(
        case_id=case_id,
        scenario=scenario,
        media_fingerprint=manual.media_fingerprint or depth_assist.media_fingerprint,
        frame_number=frame_number,
        manual=asdict(man),
        depth_assist=asdict(dep),
        comparison=asdict(cmp),
        notes=notes,
        cliff_warnings=cliff,
        soft_guard_warnings=soft,
        depth_won=depth_won,
    )


def aggregate_pairs(pairs: list[PairedStudyResult]) -> dict[str, Any]:
    reductions = [
        p.comparison["interaction_reduction_percent"]
        for p in pairs
        if p.comparison.get("interaction_reduction_percent") is not None
    ]
    refine_deltas = [p.comparison["refine_round_delta"] for p in pairs]
    duration_deltas = [
        p.comparison["duration_delta_seconds"]
        for p in pairs
        if p.comparison.get("duration_delta_seconds") is not None
    ]
    man_fp = [p.manual.get("first_pass_accept") for p in pairs]
    dep_fp = [p.depth_assist.get("first_pass_accept") for p in pairs]
    man_fp_rate = sum(1 for v in man_fp if v is True) / max(1, len(pairs))
    dep_fp_rate = sum(1 for v in dep_fp if v is True) / max(1, len(pairs))
    wins = sum(1 for p in pairs if p.depth_won)
    tol_freq = sum(1 for p in pairs if int(p.depth_assist.get("tolerance_changes") or 0) > 0)
    return {
        "n_pairs": len(pairs),
        "median_interaction_reduction_pct": float(np.median(reductions)) if reductions else None,
        "mean_interaction_reduction_pct": float(np.mean(reductions)) if reductions else None,
        "depth_assist_win_rate": wins / max(1, len(pairs)),
        "cases_depth_won": wins,
        "median_refine_round_delta": float(np.median(refine_deltas)) if refine_deltas else None,
        "manual_first_pass_rate": man_fp_rate,
        "depth_first_pass_rate": dep_fp_rate,
        "first_pass_regression_pp": (man_fp_rate - dep_fp_rate) * 100.0,
        "median_duration_delta_seconds": float(np.median(duration_deltas))
        if duration_deltas
        else None,
        "tolerance_adjust_case_frequency": tol_freq / max(1, len(pairs)),
        "cliff_warning_cases": sum(1 for p in pairs if p.cliff_warnings > 0),
        "soft_guard_cases": sum(1 for p in pairs if p.soft_guard_warnings > 0),
    }


def decide_d4(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Apply recommended D3.9 → D4 thresholds with rationale."""
    median_red = aggregate.get("median_interaction_reduction_pct")
    win_rate = aggregate.get("depth_assist_win_rate") or 0.0
    regression_pp = aggregate.get("first_pass_regression_pp") or 0.0
    checks = {
        "median_reduction_ge_25": bool(median_red is not None and median_red >= 25.0),
        "win_rate_ge_70": bool(win_rate >= 0.70),
        "first_pass_regression_le_10pp": bool(regression_pp <= 10.0),
    }
    if all(checks.values()):
        decision = "GO"
        reason = "Paired study meets recommended D4 entry thresholds."
    elif checks["median_reduction_ge_25"] and win_rate >= 0.5:
        decision = "HOLD"
        reason = (
            "Interaction benefit present but win-rate/first-pass conditions need UX polish."
        )
    else:
        decision = "NO-GO"
        reason = "Measured Depth Assist benefit is insufficient for D4 entry."
    return {"decision": decision, "reason": reason, "checks": checks}


def write_d39_reports(
    *,
    pairs: list[PairedStudyResult],
    aggregate: dict[str, Any],
    decision: dict[str, Any],
    md_path: Path,
    json_path: Path,
    execution_notes: list[str],
) -> None:
    payload = {
        "phase": "D3.9",
        "pairs": [asdict(p) for p in pairs],
        "aggregate": aggregate,
        "d4_decision": decision,
        "execution_notes": execution_notes,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Phase D3.9 — Artist Study Execution Report",
        "",
        "## 1. Study Matrix",
        "",
        "| Case | Scenario | Frame |",
        "|---|---|---|",
    ]
    for p in pairs:
        lines.append(f"| {p.case_id} | {p.scenario} | {p.frame_number} |")
    lines.extend(
        [
            "",
            f"## 2. Paired Session Count",
            "",
            f"**{len(pairs)}** Manual / Depth Assist pairs",
            "",
            "## 3–5. Pairwise results",
            "",
            "| Case | Manual primary | Depth primary | Δ | Reduction % | Depth won | Manual FP | Depth FP |",
            "|---|---:|---:|---:|---:|:---:|:---:|:---:|",
        ]
    )
    for p in pairs:
        c = p.comparison
        red = c.get("interaction_reduction_percent")
        red_s = "—" if red is None else f"{red:.1f}"
        lines.append(
            "| {case} | {mp} | {dp} | {delta} | {red} | {won} | {mfp} | {dfp} |".format(
                case=p.case_id,
                mp=p.manual.get("primary_interactions"),
                dp=p.depth_assist.get("primary_interactions"),
                delta=c.get("interaction_delta"),
                red=red_s,
                won="Y" if p.depth_won else "N",
                mfp="Y" if p.manual.get("first_pass_accept") else "N",
                dfp="Y" if p.depth_assist.get("first_pass_accept") else "N",
            )
        )
    lines.extend(
        [
            "",
            "## 12. Aggregate Metrics",
            "",
            f"- Median interaction reduction: **{aggregate.get('median_interaction_reduction_pct')}%**",
            f"- Mean interaction reduction: **{aggregate.get('mean_interaction_reduction_pct')}%**",
            f"- Depth Assist win rate: **{100.0 * (aggregate.get('depth_assist_win_rate') or 0):.0f}%** "
            f"({aggregate.get('cases_depth_won')}/{aggregate.get('n_pairs')})",
            f"- Median refine-round Δ (Manual−Depth): **{aggregate.get('median_refine_round_delta')}**",
            f"- Manual first-pass: **{100.0 * (aggregate.get('manual_first_pass_rate') or 0):.0f}%**",
            f"- Depth first-pass: **{100.0 * (aggregate.get('depth_first_pass_rate') or 0):.0f}%**",
            f"- First-pass regression: **{aggregate.get('first_pass_regression_pp'):.1f} pp**",
            f"- Median duration Δ (Manual−Depth): **{aggregate.get('median_duration_delta_seconds')} s**",
            f"- Tolerance-adjust case frequency: **{100.0 * (aggregate.get('tolerance_adjust_case_frequency') or 0):.0f}%**",
            f"- Cliff-warning cases: **{aggregate.get('cliff_warning_cases')}**",
            f"- Soft-guard cases: **{aggregate.get('soft_guard_cases')}**",
            "",
            "## 14. D4 Decision",
            "",
            f"**{decision['decision']}** — {decision['reason']}",
            "",
            "Checks:",
        ]
    )
    for key, value in decision.get("checks", {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Execution notes", ""])
    for note in execution_notes:
        lines.append(f"- {note}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
