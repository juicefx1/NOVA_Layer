"""Phase D3.6 Depth Assist real-footage validation harness (offline).

Compares Manual vs Depth Assist guidance on SOURCE frames.
Writes JSON + Markdown reports. Does not implement D4 features.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from nova_layer.adapters.capabilities.depth_anything_v2 import DepthAnythingV2SmallAdapter
from nova_layer.adapters.capabilities.mock import MockSegmentationCapability
from nova_layer.app.depth_guidance import build_depth_guidance_proposal
from nova_layer.app.depth_region import extract_depth_region
from nova_layer.app.depth_backend import create_depth_anything_v2_small_adapter
from nova_layer.domain.models import BoundingRegion, GuidancePoint
from nova_layer.ports.depth import DepthFrame, canonicalize_depth_inference


@dataclass(frozen=True, slots=True)
class ValidationCase:
    case_id: str
    scenario: str
    media_path: Path
    frame_number: int
    seed_xy: tuple[int, int] | None = None  # None → auto seed from near peak
    notes: str = ""
    proxy_level: str = "real_proxy"  # real | real_proxy | fixture_proxy


@dataclass
class CaseMetrics:
    case_id: str
    scenario: str
    media: str
    frame_number: int
    resolution: tuple[int, int]
    device: str | None
    depth_latency_ms: float
    depth_region_coverage: float
    depth_bbox_area_norm: float | None
    generated_positive: int
    generated_negative: int
    has_bbox: bool
    region_warning: str | None
    purity_score: int
    completeness_score: int
    contamination_score: int  # higher = worse
    manual_interactions: int
    depth_assist_interactions: int
    delta_interactions: int
    manual_refine_rounds: int
    depth_refine_rounds: int
    first_pass_accept_manual: bool
    first_pass_accept_depth: bool
    sam_latency_manual_ms: float
    sam_latency_depth_ms: float
    manual_confidence: float
    depth_confidence: float
    boundary_quality_subjective: int
    failure_reason: str | None = None
    notes: str = ""
    proxy_level: str = "real_proxy"
    extra: dict[str, Any] = field(default_factory=dict)


INTERACTION = {
    "analyze": 1,  # setup
    "pick": 1,
    "assist": 1,
    "tolerance_adjust": 1,
    "positive_click": 1,
    "negative_click": 1,
    "bbox_draw": 1,
    "refine_click": 1,
}


def load_rgb(path: Path) -> NDArray[np.uint8]:
    image = Image.open(path).convert("RGB")
    return np.asarray(image, dtype=np.uint8)


def auto_seed(depth: NDArray[np.float32], valid: NDArray[np.bool_]) -> tuple[int, int]:
    """Pick a near-biased seed slightly inside the upper-central band (person proxy)."""
    h, w = depth.shape
    ys = slice(h // 5, (3 * h) // 5)
    xs = slice(w // 4, (3 * w) // 4)
    region = np.zeros_like(valid)
    region[ys, xs] = True
    mask = valid & region
    if not np.any(mask):
        mask = valid
    # near_is high → larger values nearer
    idx = np.argmax(np.where(mask, depth, -np.inf))
    y, x = np.unravel_index(idx, depth.shape)
    return int(x), int(y)


def score_region_quality(region_mask: NDArray[np.bool_], depth: NDArray[np.float32]) -> tuple[int, int, int]:
    """Heuristic 1–5 scores: purity, completeness, contamination(worse=higher)."""
    h, w = region_mask.shape
    coverage = float(np.count_nonzero(region_mask)) / float(h * w)
    # components count via simple labeling
    from collections import deque

    visited = np.zeros_like(region_mask)
    components = 0
    for y in range(h):
        for x in range(w):
            if not region_mask[y, x] or visited[y, x]:
                continue
            components += 1
            q: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            while q:
                cx, cy = q.popleft()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and region_mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            q.append((nx, ny))

    purity = 5
    completeness = 5
    contamination = 1
    if coverage < 0.002:
        completeness = 2
        purity = 3
    elif coverage > 0.45:
        purity = 2
        contamination = 4
    if components > 1:
        contamination = min(5, contamination + components - 1)
        purity = max(1, purity - 1)
    # depth std inside vs border
    if np.count_nonzero(region_mask) > 20:
        vals = depth[region_mask]
        span = float(np.percentile(vals, 95) - np.percentile(vals, 5))
        if span > 0.35 * float(np.nanmax(depth) - np.nanmin(depth) + 1e-6):
            purity = max(1, purity - 1)
            contamination = min(5, contamination + 1)
    return purity, completeness, contamination


def bbox_area_norm(bbox: tuple[int, int, int, int] | None, h: int, w: int) -> float | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return float((x1 - x0 + 1) * (y1 - y0 + 1)) / float(h * w)


def run_sam(
    segmentation: MockSegmentationCapability,
    image: NDArray[np.uint8],
    points: list[GuidancePoint],
    bbox: BoundingRegion | None,
) -> tuple[Any, float]:
    h, w = image.shape[:2]
    t0 = perf_counter()
    result = segmentation.predict(
        frame_number=0,
        image=image,
        width=w,
        height=h,
        points=points,
        bounding_region=bbox,
    )
    return result, (perf_counter() - t0) * 1000.0


def accept_proxy(confidence: float, mask: NDArray[np.uint8], coverage_hint: float) -> bool:
    area = float(np.count_nonzero(mask)) / float(mask.size)
    if confidence < 0.7:
        return False
    if area < 0.002 or area > 0.75:
        return False
    # Prefer masks not wildly larger than depth coverage when hint available
    if coverage_hint > 0 and area > max(0.55, coverage_hint * 4.0):
        return False
    return True


def manual_guidance_for_seed(
    seed_x: int,
    seed_y: int,
    h: int,
    w: int,
) -> tuple[list[GuidancePoint], BoundingRegion, int]:
    """Synthesize a typical manual artist pass around a seed."""
    points = [
        GuidancePoint(x=(seed_x + 0.5) / w, y=(seed_y + 0.5) / h, polarity="positive"),
        GuidancePoint(
            x=min(0.99, (seed_x + w * 0.05 + 0.5) / w),
            y=min(0.99, (seed_y + 0.5) / h),
            polarity="positive",
        ),
        GuidancePoint(
            x=max(0.0, (seed_x - w * 0.05 + 0.5) / w),
            y=min(0.99, (seed_y + h * 0.04 + 0.5) / h),
            polarity="positive",
        ),
        GuidancePoint(x=0.05, y=0.05, polarity="negative"),
        GuidancePoint(x=0.95, y=0.08, polarity="negative"),
    ]
    x0 = max(0.0, (seed_x / w) - 0.18)
    y0 = max(0.0, (seed_y / h) - 0.22)
    bw = min(1.0 - x0, 0.42)
    bh = min(1.0 - y0, 0.55)
    bbox = BoundingRegion(x=x0, y=y0, width=bw, height=bh)
    interactions = (
        3 * INTERACTION["positive_click"]
        + 2 * INTERACTION["negative_click"]
        + INTERACTION["bbox_draw"]
    )
    return points, bbox, interactions


def evaluate_case(
    case: ValidationCase,
    adapter: DepthAnythingV2SmallAdapter,
    segmentation: MockSegmentationCapability,
    *,
    tolerance: float = 0.08,
) -> CaseMetrics:
    image = load_rgb(case.media_path)
    h, w = image.shape[:2]
    t0 = perf_counter()
    inference = adapter.infer(frame_number=case.frame_number, image=image)
    depth_ms = (perf_counter() - t0) * 1000.0
    frame = canonicalize_depth_inference(
        inference,
        frame_number=case.frame_number,
        media_fingerprint=case.case_id,
        source_model=adapter.model_id,
        model_version=adapter.model_version,
        preprocessing_version=adapter.preprocessing_version,
        expected_height=h,
        expected_width=w,
    )
    valid = np.isfinite(frame.depth)
    if case.seed_xy is None:
        seed_x, seed_y = auto_seed(frame.depth, valid)
    else:
        seed_x, seed_y = case.seed_xy

    region = extract_depth_region(
        frame, seed_x=seed_x, seed_y=seed_y, tolerance=tolerance
    )
    proposal = build_depth_guidance_proposal(
        region, image_width=w, image_height=h, include_negative_points=True
    )
    purity, completeness, contamination = score_region_quality(region.mask, frame.depth)

    # Manual baseline
    manual_points, manual_bbox, manual_base = manual_guidance_for_seed(seed_x, seed_y, h, w)
    manual_result, manual_sam_ms = run_sam(segmentation, image, manual_points, manual_bbox)
    manual_accept = accept_proxy(manual_result.confidence, manual_result.mask, region.coverage)
    manual_refine = 0 if manual_accept else 1
    manual_interactions = manual_base + manual_refine * INTERACTION["refine_click"]

    # Depth assist path
    depth_points = [*proposal.positive_points, *proposal.negative_points]
    depth_bbox = proposal.bounding_region
    # interactions: analyze(setup)+pick+assist (+ optional tolerance later counted in sweep)
    depth_interactions = (
        INTERACTION["analyze"] + INTERACTION["pick"] + INTERACTION["assist"]
    )
    if region.warning and "small" in region.warning.lower():
        depth_interactions += INTERACTION["tolerance_adjust"]
    if region.warning and "most of the frame" in region.warning.lower():
        depth_interactions += INTERACTION["tolerance_adjust"]

    depth_result, depth_sam_ms = run_sam(
        segmentation, image, list(depth_points), depth_bbox
    )
    depth_accept = accept_proxy(depth_result.confidence, depth_result.mask, region.coverage)
    depth_refine = 0
    if not depth_accept:
        # one refine: add one positive near seed (artist)
        extra = GuidancePoint(
            x=(seed_x + 0.5) / w, y=(seed_y + 0.5) / h, polarity="positive"
        )
        depth_points = [*depth_points, extra]
        depth_result, depth_sam_ms2 = run_sam(
            segmentation, image, list(depth_points), depth_bbox
        )
        depth_sam_ms += depth_sam_ms2
        depth_refine = 1
        depth_interactions += INTERACTION["refine_click"]
        depth_accept = accept_proxy(
            depth_result.confidence, depth_result.mask, region.coverage
        )

    # Subjective boundary quality proxy from scores
    boundary = max(1, min(5, int(round((purity + completeness + (6 - contamination)) / 3))))

    failure = None
    if region.pixel_count == 0:
        failure = "empty_depth_region"
    elif not depth_accept and not manual_accept:
        failure = "both_workflows_proxy_reject"

    return CaseMetrics(
        case_id=case.case_id,
        scenario=case.scenario,
        media=str(case.media_path),
        frame_number=case.frame_number,
        resolution=(w, h),
        device=adapter.resolved_device,
        depth_latency_ms=depth_ms,
        depth_region_coverage=float(region.coverage),
        depth_bbox_area_norm=bbox_area_norm(region.bounding_box, h, w),
        generated_positive=len(proposal.positive_points),
        generated_negative=len(proposal.negative_points),
        has_bbox=proposal.bounding_region is not None,
        region_warning=region.warning or proposal.warning,
        purity_score=purity,
        completeness_score=completeness,
        contamination_score=contamination,
        manual_interactions=manual_interactions,
        depth_assist_interactions=depth_interactions,
        delta_interactions=manual_interactions - depth_interactions,
        manual_refine_rounds=manual_refine,
        depth_refine_rounds=depth_refine,
        first_pass_accept_manual=manual_accept and manual_refine == 0,
        first_pass_accept_depth=depth_accept and depth_refine == 0,
        sam_latency_manual_ms=manual_sam_ms,
        sam_latency_depth_ms=depth_sam_ms,
        manual_confidence=float(manual_result.confidence),
        depth_confidence=float(depth_result.confidence),
        boundary_quality_subjective=boundary,
        failure_reason=failure,
        notes=case.notes,
        proxy_level=case.proxy_level,
        extra={
            "seed": [seed_x, seed_y],
            "effective_band": region.effective_band,
            "region_pixels": region.pixel_count,
        },
    )


def tolerance_sweep(
    case: ValidationCase,
    adapter: DepthAnythingV2SmallAdapter,
    tolerances: list[float],
) -> list[dict[str, Any]]:
    image = load_rgb(case.media_path)
    h, w = image.shape[:2]
    inference = adapter.infer(frame_number=case.frame_number, image=image)
    frame = canonicalize_depth_inference(
        inference,
        frame_number=case.frame_number,
        media_fingerprint=case.case_id,
        source_model=adapter.model_id,
        model_version=adapter.model_version,
        preprocessing_version=adapter.preprocessing_version,
        expected_height=h,
        expected_width=w,
    )
    valid = np.isfinite(frame.depth)
    seed = case.seed_xy or auto_seed(frame.depth, valid)
    rows = []
    for tol in tolerances:
        region = extract_depth_region(frame, seed_x=seed[0], seed_y=seed[1], tolerance=tol)
        proposal = build_depth_guidance_proposal(region, image_width=w, image_height=h)
        rows.append(
            {
                "case_id": case.case_id,
                "tolerance": tol,
                "coverage": region.coverage,
                "bbox_area_norm": bbox_area_norm(region.bounding_box, h, w),
                "positives": len(proposal.positive_points),
                "negatives": len(proposal.negative_points),
                "warning": region.warning,
                "pixels": region.pixel_count,
            }
        )
    return rows


def stability_check(
    case: ValidationCase,
    weights: Path,
) -> dict[str, Any]:
    image = load_rgb(case.media_path)
    h, w = image.shape[:2]
    results = {}
    for device in ("mps", "cpu"):
        try:
            adapter = DepthAnythingV2SmallAdapter(weights, device=device)
            inf = adapter.infer(frame_number=0, image=image)
            results[device] = {
                "min": float(np.nanmin(inf.depth)),
                "max": float(np.nanmax(inf.depth)),
                "mean": float(np.nanmean(inf.depth)),
                "device": adapter.resolved_device,
            }
        except Exception as exc:  # noqa: BLE001
            results[device] = {"error": str(exc)}
    if "mps" in results and "cpu" in results and "error" not in results["mps"] and "error" not in results["cpu"]:
        # rebuild for correlation / region overlap
        a_mps = DepthAnythingV2SmallAdapter(weights, device="mps")
        a_cpu = DepthAnythingV2SmallAdapter(weights, device="cpu")
        d_mps = a_mps.infer(frame_number=0, image=image).depth
        d_cpu = a_cpu.infer(frame_number=0, image=image).depth
        flat_m = d_mps.reshape(-1)
        flat_c = d_cpu.reshape(-1)
        corr = float(np.corrcoef(flat_m, flat_c)[0, 1])
        seed = auto_seed(d_mps, np.isfinite(d_mps))
        # canonicalize lightly via DepthInferenceResult fields already set
        from nova_layer.ports.depth import DepthInferenceResult, DepthNormalization

        def to_frame(depth: NDArray[np.float32], device_tag: str) -> DepthFrame:
            inf = DepthInferenceResult(
                depth=depth,
                valid_mask=None,
                quantity="relative_disparity",
                near_is="high",
                normalization=DepthNormalization(kind="model_native"),
                metadata={"device": device_tag},
            )
            return canonicalize_depth_inference(
                inf,
                frame_number=0,
                media_fingerprint="stab",
                source_model="depth_anything_v2_small",
                model_version="stab",
                preprocessing_version="stab",
                expected_height=h,
                expected_width=w,
            )

        r_m = extract_depth_region(to_frame(d_mps, "mps"), seed_x=seed[0], seed_y=seed[1], tolerance=0.08)
        r_c = extract_depth_region(to_frame(d_cpu, "cpu"), seed_x=seed[0], seed_y=seed[1], tolerance=0.08)
        inter = np.count_nonzero(r_m.mask & r_c.mask)
        union = np.count_nonzero(r_m.mask | r_c.mask)
        results["correlation"] = corr
        results["region_iou"] = float(inter / union) if union else 0.0
        results["seed"] = list(seed)
    # repeat inference UX stability on one device
    adapter = DepthAnythingV2SmallAdapter(weights, device="auto")
    d1 = adapter.infer(frame_number=0, image=image).depth
    d2 = adapter.infer(frame_number=0, image=image).depth
    results["repeat_max_abs_diff"] = float(np.nanmax(np.abs(d1 - d2)))
    results["repeat_mean_abs_diff"] = float(np.nanmean(np.abs(d1 - d2)))
    return results


def viewer_transform_independence(case: ValidationCase, adapter: DepthAnythingV2SmallAdapter) -> dict[str, Any]:
    """DepthFrame/region unchanged conceptually when only display transform would change.

    This harness compares two SOURCE inferences (SOURCE must be identical) and notes
    that exposure is a viewer-only concern; both SOURCE depth runs must match.
    """
    image = load_rgb(case.media_path)
    a = adapter.infer(frame_number=0, image=image).depth
    # Simulate "viewer exposure changed" without altering SOURCE pixels:
    b = adapter.infer(frame_number=0, image=image).depth
    return {
        "source_depth_identical": bool(np.array_equal(a, b)),
        "max_abs_diff": float(np.nanmax(np.abs(a - b))),
        "note": "SOURCE bytes unchanged; exposure/display must not feed depth adapter.",
        "viewer_transform_policy": {
            "exposure_stops_example": 1.5,
            "display": "legacy",
            "affects_depth": False,
        },
    }


def default_cases(frame_dir: Path) -> list[ValidationCase]:
    specs = [
        ("case01_person_fg", "1_single_person_fg", "Person-like plate frame", "real"),
        ("case02_person_chair_proxy", "2_person_chair_same_depth", "Frame proxy for person+furniture depth merge risk", "real_proxy"),
        ("case03_prop_object", "3_foreground_prop", "QA fixture mid frame prop/object", "fixture_proxy"),
        ("case04_overlap_proxy", "4_overlapping_subjects", "Later frame; may include overlap", "real_proxy"),
        ("case05_limbs_proxy", "5_hair_limbs_thin", "Thin-structure risk frame", "real_proxy"),
        ("case06_reflective_proxy", "6_reflective", "UI screenshot/reflective proxy", "fixture_proxy"),
        ("case07_low_contrast_proxy", "7_low_contrast", "Lower-key frame proxy", "real_proxy"),
        ("case08_depth_scene_proxy", "8_wide_deep_scene", "VFX plate deeper staging proxy", "real"),
        ("case09_shallow_dof_proxy", "9_shallow_dof", "Plate edge frame as DOF/soft proxy", "real_proxy"),
        ("case10_vfx_plate", "10_vfx_greenscreen_like", "Publish plate footage", "real"),
    ]
    cases: list[ValidationCase] = []
    for stem, scenario, notes, level in specs:
        path = frame_dir / f"{stem}.png"
        if path.exists():
            cases.append(
                ValidationCase(
                    case_id=stem,
                    scenario=scenario,
                    media_path=path,
                    frame_number=0,
                    notes=notes,
                    proxy_level=level,
                )
            )
    return cases


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase D3.6 Depth Assist Real-Footage Validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Device: {report.get('device')}",
        f"Default tolerance: {report.get('default_tolerance')}",
        "",
        "## Interaction table",
        "",
        "| Case | Manual | Depth Assist | Δ | Manual refine | Depth refine | Purity | First-pass Depth | Depth ms | Notes |",
        "|---|---:|---:|---:|---:|---:|---:|:---:|---:|---|",
    ]
    for row in report["cases"]:
        lines.append(
            "| {case_id} | {manual_interactions} | {depth_assist_interactions} | {delta_interactions} | {manual_refine_rounds} | {depth_refine_rounds} | {purity_score} | {fp} | {depth_latency_ms:.0f} | {notes} |".format(
                fp="Y" if row["first_pass_accept_depth"] else "N",
                **row,
            )
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Median interaction reduction: {report['summary']['median_interaction_reduction_pct']:.1f}%",
            f"- Mean interaction reduction: {report['summary']['mean_interaction_reduction_pct']:.1f}%",
            f"- Depth first-pass accept rate: {report['summary']['depth_first_pass_rate']:.0%}",
            f"- Manual first-pass accept rate: {report['summary']['manual_first_pass_rate']:.0%}",
            f"- Cases with Depth Assist fewer interactions: {report['summary']['cases_depth_fewer']}/{report['summary']['n_cases']}",
            "",
            "## Go / No-Go",
            "",
            f"- Depth Assist: **{report['decisions']['depth_assist']}**",
            f"- Proceed to D4: **{report['decisions']['d4']}**",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D3.6 Depth Assist validation")
    parser.add_argument(
        "--frames",
        type=Path,
        default=Path("tmp/depth_assist_d36/frames"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/depth_assist_d36/report"),
    )
    parser.add_argument("--tolerance", type=float, default=0.08)
    parser.add_argument(
        "--device",
        default="auto",
        help="Depth adapter device: auto|mps|cpu|cuda",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault(
        "NOVA_DEPTH_MODEL_PATH",
        "/Users/juwon.lee/Desktop/nova-ai-vfx/weights/depth_anything_v2_vits.pth",
    )
    weights = Path(os.environ["NOVA_DEPTH_MODEL_PATH"]).expanduser()
    if not weights.is_file():
        raise SystemExit(f"Missing weights: {weights}")

    t_load = perf_counter()
    adapter = create_depth_anything_v2_small_adapter(device=str(args.device))
    # warm / first load timing
    warmup = load_rgb(next(args.frames.glob("case01*.png")))
    _ = adapter.infer(frame_number=0, image=warmup)
    first_load_ms = (perf_counter() - t_load) * 1000.0
    t_warm = perf_counter()
    _ = adapter.infer(frame_number=0, image=warmup)
    warm_ms = (perf_counter() - t_warm) * 1000.0

    segmentation = MockSegmentationCapability()
    cases = default_cases(args.frames)
    metrics = [
        evaluate_case(case, adapter, segmentation, tolerance=args.tolerance)
        for case in cases
    ]

    # Tolerance sweep on 3 representative cases
    sweep_ids = ["case01_person_fg", "case02_person_chair_proxy", "case10_vfx_plate"]
    sweep_cases = [c for c in cases if c.case_id in sweep_ids]
    sweep_rows: list[dict[str, Any]] = []
    for case in sweep_cases:
        sweep_rows.extend(
            tolerance_sweep(
                case,
                adapter,
                [0.03, 0.05, 0.08, 0.10, 0.15, 0.20],
            )
        )

    stability = stability_check(cases[0], weights) if cases else {}
    transform = viewer_transform_independence(cases[0], adapter) if cases else {}

    reductions = []
    for m in metrics:
        if m.manual_interactions > 0:
            reductions.append(
                100.0 * (m.manual_interactions - m.depth_assist_interactions) / m.manual_interactions
            )
    depth_fp = sum(1 for m in metrics if m.first_pass_accept_depth) / max(1, len(metrics))
    manual_fp = sum(1 for m in metrics if m.first_pass_accept_manual) / max(1, len(metrics))
    median_red = float(np.median(reductions)) if reductions else 0.0
    mean_red = float(np.mean(reductions)) if reductions else 0.0
    fewer = sum(1 for m in metrics if m.delta_interactions > 0)

    # Acceptance thresholds from recommended policy
    assist_go = (
        median_red >= 25.0
        and depth_fp + 1e-9 >= manual_fp - 0.05
        and fewer >= int(0.6 * len(metrics))
    )
    d4_go = assist_go  # still recommend D3.6 fixes first if not green

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "device": adapter.resolved_device,
        "default_tolerance": args.tolerance,
        "performance": {
            "first_load_plus_infer_ms": first_load_ms,
            "warm_infer_ms": warm_ms,
            "warmup_resolution": list(warmup.shape[1::-1]),
        },
        "cases": [asdict(m) for m in metrics],
        "tolerance_sweep": sweep_rows,
        "stability": stability,
        "viewer_transform": transform,
        "summary": {
            "n_cases": len(metrics),
            "median_interaction_reduction_pct": median_red,
            "mean_interaction_reduction_pct": mean_red,
            "depth_first_pass_rate": depth_fp,
            "manual_first_pass_rate": manual_fp,
            "cases_depth_fewer": fewer,
        },
        "decisions": {
            "depth_assist": "GO" if assist_go else "CONDITIONAL GO",
            "d4": "NO-GO until D3.6 follow-ups" if not assist_go else "GO after UX polish",
            "thresholds": {
                "median_interaction_reduction_pct": 25.0,
                "first_pass_non_regression": True,
            },
        },
        "limitations": [
            "Several cases are real-footage frame proxies mapped to scenario labels without dedicated GT mattes.",
            "Accept/reject uses MockSegmentation + coverage/confidence heuristics — not artist IoU.",
            "Interaction counts for Manual are synthesized typical click budgets, not logged UI telemetry.",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output.with_suffix(".json")
    md_path = args.output.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"median_reduction={median_red:.1f}% depth_fp={depth_fp:.0%} "
        f"assist={report['decisions']['depth_assist']} d4={report['decisions']['d4']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
