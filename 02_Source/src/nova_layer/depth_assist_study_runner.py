"""Execute Phase D3.9 paired Artist Study sessions via D3.8 telemetry.

Runs Manual vs Depth Assist on the D3.6 frame matrix using the same event
vocabulary and summarize/compare helpers. Depth uses real DA-V2 Small when
weights are available; SAM accept uses MockSegmentation heuristics for fairness.

This is an automated operator study through production APIs/telemetry —
not a live human GUI clickstream. Reports disclose that limitation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from time import perf_counter, sleep

import numpy as np
from PIL import Image

from nova_layer.adapters.capabilities.mock import MockSegmentationCapability
from nova_layer.app.depth_assist_study_report import (
    STUDY_CASES,
    aggregate_pairs,
    decide_d4,
    pair_result,
    write_d39_reports,
)
from nova_layer.app.depth_assist_telemetry import (
    EVENT_ANALYZE_SCENE,
    EVENT_BBOX_CHANGED,
    EVENT_DEPTH_ASSIST_APPLIED,
    EVENT_DEPTH_REGION_PICKED,
    EVENT_GENERATE_HYPOTHESIS,
    EVENT_HYPOTHESIS_ACCEPTED,
    EVENT_HYPOTHESIS_REJECTED,
    EVENT_MANUAL_NEGATIVE,
    EVENT_MANUAL_POSITIVE,
    EVENT_REFINE_ROUND_STARTED,
    EVENT_TOLERANCE_CHANGED,
    DepthAssistTelemetryRecorder,
    export_session_json,
)
from nova_layer.app.depth_backend import create_depth_anything_v2_small_adapter
from nova_layer.app.depth_guidance import (
    NEGATIVE_FULL_MIN_COVERAGE,
    REDUCED_NEGATIVE_STATUS,
    build_depth_guidance_proposal,
)
from nova_layer.app.depth_region import (
    DEFAULT_DEPTH_TOLERANCE,
    TOLERANCE_CLIFF_WARNING,
    annotate_tolerance_cliff,
    extract_depth_region,
)
from nova_layer.domain.models import BoundingRegion, GuidancePoint
from nova_layer.ports.depth import canonicalize_depth_inference


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _fingerprint(path: Path) -> str:
    data = path.read_bytes()[: 1024 * 1024]
    return hashlib.sha256(data).hexdigest()[:16]


def _auto_seed(depth: np.ndarray, valid: np.ndarray) -> tuple[int, int]:
    h, w = depth.shape
    region = np.zeros_like(valid)
    region[h // 5 : (3 * h) // 5, w // 4 : (3 * w) // 4] = True
    mask = valid & region
    if not np.any(mask):
        mask = valid
    idx = int(np.argmax(np.where(mask, depth, -np.inf)))
    y, x = np.unravel_index(idx, depth.shape)
    return int(x), int(y)


def _accept_proxy(confidence: float, mask: np.ndarray, coverage_hint: float) -> bool:
    area = float(np.count_nonzero(mask)) / float(mask.size)
    if confidence < 0.7:
        return False
    if area < 0.002 or area > 0.75:
        return False
    if coverage_hint > 0 and area > max(0.55, coverage_hint * 4.0):
        return False
    return True


def _run_sam(
    seg: MockSegmentationCapability,
    image: np.ndarray,
    points: list[GuidancePoint],
    bbox: BoundingRegion | None,
) -> tuple[object, float]:
    h, w = image.shape[:2]
    t0 = perf_counter()
    result = seg.predict(
        frame_number=0,
        image=image,
        width=w,
        height=h,
        points=points,
        bounding_region=bbox,
    )
    return result, (perf_counter() - t0) * 1000.0


def _manual_session(
    *,
    case_id: str,
    fingerprint: str,
    frame_number: int,
    image: np.ndarray,
    seed: tuple[int, int],
    seg: MockSegmentationCapability,
    out_dir: Path,
) -> object:
    h, w = image.shape[:2]
    sx, sy = seed
    recorder = DepthAssistTelemetryRecorder()
    recorder.set_enabled(True)
    recorder.start_session(
        workflow="manual",
        media_fingerprint=fingerprint,
        backend_model_id="n/a",
        frame_number=frame_number,
    )
    sleep(0.01)
    # Fair baseline: 3+/2-/bbox around seed (same accept bar as Depth Assist).
    points = [
        GuidancePoint(x=(sx + 0.5) / w, y=(sy + 0.5) / h, polarity="positive"),
        GuidancePoint(
            x=min(0.99, (sx + w * 0.05 + 0.5) / w),
            y=min(0.99, (sy + 0.5) / h),
            polarity="positive",
        ),
        GuidancePoint(
            x=max(0.0, (sx - w * 0.05 + 0.5) / w),
            y=min(0.99, (sy + h * 0.04 + 0.5) / h),
            polarity="positive",
        ),
        GuidancePoint(x=0.05, y=0.05, polarity="negative"),
        GuidancePoint(x=0.95, y=0.08, polarity="negative"),
    ]
    for _ in range(3):
        recorder.record_event(EVENT_MANUAL_POSITIVE, frame_number=frame_number)
    for _ in range(2):
        recorder.record_event(EVENT_MANUAL_NEGATIVE, frame_number=frame_number)
    x0 = max(0.0, (sx / w) - 0.18)
    y0 = max(0.0, (sy / h) - 0.22)
    bbox = BoundingRegion(
        x=x0,
        y=y0,
        width=min(1.0 - x0, 0.42),
        height=min(1.0 - y0, 0.55),
    )
    recorder.record_event(EVENT_BBOX_CHANGED, frame_number=frame_number, bbox_present=True)
    recorder.record_event(EVENT_GENERATE_HYPOTHESIS, frame_number=frame_number)
    result, _ = _run_sam(seg, image, points, bbox)
    accepted = _accept_proxy(float(result.confidence), result.mask, 0.05)
    if not accepted:
        recorder.record_event(EVENT_HYPOTHESIS_REJECTED, frame_number=frame_number)
        recorder.record_event(EVENT_REFINE_ROUND_STARTED, frame_number=frame_number)
        recorder.record_event(EVENT_MANUAL_POSITIVE, frame_number=frame_number)
        points = [
            *points,
            GuidancePoint(x=(sx + 0.5) / w, y=(sy + 0.5) / h, polarity="positive"),
        ]
        recorder.record_event(EVENT_GENERATE_HYPOTHESIS, frame_number=frame_number)
        result, _ = _run_sam(seg, image, points, bbox)
        accepted = _accept_proxy(float(result.confidence), result.mask, 0.05)
    if accepted:
        recorder.record_event(EVENT_HYPOTHESIS_ACCEPTED, frame_number=frame_number)
    else:
        recorder.record_event(EVENT_HYPOTHESIS_REJECTED, frame_number=frame_number)
    finished = recorder.finish_session(accepted=accepted, notes=f"manual:{case_id}")
    assert finished is not None
    export_session_json(finished, out_dir / f"{case_id}_manual.json")
    return finished


def _depth_session(
    *,
    case_id: str,
    fingerprint: str,
    frame_number: int,
    image: np.ndarray,
    adapter: object,
    seg: MockSegmentationCapability,
    out_dir: Path,
) -> tuple[object, dict]:
    h, w = image.shape[:2]
    recorder = DepthAssistTelemetryRecorder()
    recorder.set_enabled(True)
    model_id = getattr(adapter, "model_id", "depth_anything_v2_small")
    recorder.start_session(
        workflow="depth_assist",
        media_fingerprint=fingerprint,
        backend_model_id=str(model_id),
        frame_number=frame_number,
    )
    meta: dict = {
        "cliff_warning": False,
        "soft_guard": False,
        "tolerance_adjusts": 0,
        "coverage": 0.0,
        "negatives": 0,
    }

    # Analyze Scene (setup)
    t0 = perf_counter()
    inference = adapter.infer(frame_number=frame_number, image=image)
    depth_ms = (perf_counter() - t0) * 1000.0
    frame = canonicalize_depth_inference(
        inference,
        frame_number=frame_number,
        media_fingerprint=fingerprint,
        source_model=str(getattr(adapter, "model_id", "dav2")),
        model_version=str(getattr(adapter, "model_version", "v")),
        preprocessing_version=str(getattr(adapter, "preprocessing_version", "p")),
        expected_height=h,
        expected_width=w,
    )
    recorder.record_event(
        EVENT_ANALYZE_SCENE,
        frame_number=frame_number,
        backend_model_id=str(model_id),
    )
    meta["depth_latency_ms"] = depth_ms

    seed = _auto_seed(frame.depth, np.isfinite(frame.depth))
    tolerance = float(DEFAULT_DEPTH_TOLERANCE)
    region = extract_depth_region(
        frame, seed_x=seed[0], seed_y=seed[1], tolerance=tolerance
    )
    recorder.record_event(
        EVENT_DEPTH_REGION_PICKED,
        frame_number=frame_number,
        tolerance=tolerance,
        region_coverage=float(region.coverage),
        warning=region.warning,
        bbox_present=region.bounding_box is not None,
    )

    # Soften path / grow once if region is uselessly tiny (fair, countable cost).
    if region.coverage < 0.005 and region.pixel_count > 0:
        previous = region
        tolerance = min(0.12, tolerance + 0.04)
        region = extract_depth_region(
            frame, seed_x=seed[0], seed_y=seed[1], tolerance=tolerance
        )
        region = annotate_tolerance_cliff(region, previous)
        cliff = bool(region.warning and TOLERANCE_CLIFF_WARNING in region.warning)
        recorder.record_event(
            EVENT_TOLERANCE_CHANGED,
            frame_number=frame_number,
            tolerance=tolerance,
            region_coverage=float(region.coverage),
            warning=region.warning,
        )
        meta["tolerance_adjusts"] = 1
        meta["cliff_warning"] = cliff

    proposal = build_depth_guidance_proposal(
        region, image_width=w, image_height=h, include_negative_points=True
    )
    soft = float(region.coverage) < NEGATIVE_FULL_MIN_COVERAGE
    meta["soft_guard"] = soft
    meta["coverage"] = float(region.coverage)
    meta["negatives"] = len(proposal.negative_points)
    soft_warning = REDUCED_NEGATIVE_STATUS if soft else proposal.warning
    recorder.record_event(
        EVENT_DEPTH_ASSIST_APPLIED,
        frame_number=frame_number,
        tolerance=tolerance,
        region_coverage=float(region.coverage),
        positive_count=len(proposal.positive_points),
        negative_count=len(proposal.negative_points),
        bbox_present=proposal.bounding_region is not None,
        warning=soft_warning or region.warning,
    )

    points = [*proposal.positive_points, *proposal.negative_points]
    bbox = proposal.bounding_region
    recorder.record_event(EVENT_GENERATE_HYPOTHESIS, frame_number=frame_number)
    result, _ = _run_sam(seg, image, list(points), bbox)
    accepted = _accept_proxy(float(result.confidence), result.mask, region.coverage)
    if not accepted:
        recorder.record_event(EVENT_HYPOTHESIS_REJECTED, frame_number=frame_number)
        recorder.record_event(EVENT_REFINE_ROUND_STARTED, frame_number=frame_number)
        recorder.record_event(EVENT_MANUAL_POSITIVE, frame_number=frame_number)
        points = [
            *points,
            GuidancePoint(
                x=(seed[0] + 0.5) / w, y=(seed[1] + 0.5) / h, polarity="positive"
            ),
        ]
        recorder.record_event(EVENT_GENERATE_HYPOTHESIS, frame_number=frame_number)
        result, _ = _run_sam(seg, image, list(points), bbox)
        accepted = _accept_proxy(float(result.confidence), result.mask, region.coverage)
    if accepted:
        recorder.record_event(EVENT_HYPOTHESIS_ACCEPTED, frame_number=frame_number)
    else:
        recorder.record_event(EVENT_HYPOTHESIS_REJECTED, frame_number=frame_number)

    finished = recorder.finish_session(
        accepted=accepted, notes=f"depth_assist:{case_id}"
    )
    assert finished is not None
    export_session_json(finished, out_dir / f"{case_id}_depth_assist.json")
    return finished, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D3.9 paired artist study runner")
    parser.add_argument(
        "--frames",
        type=Path,
        default=Path("tmp/depth_assist_d36/frames"),
    )
    parser.add_argument(
        "--sessions-out",
        type=Path,
        default=Path("tmp/depth_assist_d39/sessions"),
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../06_Test/reports/D39_ARTIST_STUDY.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../06_Test/reports/D39_ARTIST_STUDY.json"),
    )
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)

    os.environ.setdefault(
        "NOVA_DEPTH_MODEL_PATH",
        "/Users/juwon.lee/Desktop/nova-ai-vfx/weights/depth_anything_v2_vits.pth",
    )
    args.sessions_out.mkdir(parents=True, exist_ok=True)

    adapter = create_depth_anything_v2_small_adapter(device=str(args.device))
    seg = MockSegmentationCapability()
    pairs = []
    notes_global = [
        "Execution mode: automated operator study via D3.8 telemetry + production depth APIs.",
        "Not a live human GUI clickstream; same event vocabulary and fairness accept bar.",
        "Absolute media paths were not stored — media_fingerprint only.",
        f"Depth device: {getattr(adapter, 'resolved_device', None)}",
        f"Default tolerance: {DEFAULT_DEPTH_TOLERANCE}",
    ]

    for spec in STUDY_CASES:
        stem = spec["frame_stem"]
        path = args.frames / f"{stem}.png"
        if not path.is_file():
            print(f"SKIP missing frame {path}")
            continue
        image = _load_rgb(path)
        fingerprint = _fingerprint(path)
        # Precompute seed from a quick depth infer for Manual target alignment.
        inference = adapter.infer(frame_number=0, image=image)
        h, w = image.shape[:2]
        frame = canonicalize_depth_inference(
            inference,
            frame_number=0,
            media_fingerprint=fingerprint,
            source_model=str(adapter.model_id),
            model_version=str(adapter.model_version),
            preprocessing_version=str(adapter.preprocessing_version),
            expected_height=h,
            expected_width=w,
        )
        seed = _auto_seed(frame.depth, np.isfinite(frame.depth))
        manual = _manual_session(
            case_id=spec["case_id"],
            fingerprint=fingerprint,
            frame_number=0,
            image=image,
            seed=seed,
            seg=seg,
            out_dir=args.sessions_out,
        )
        depth, meta = _depth_session(
            case_id=spec["case_id"],
            fingerprint=fingerprint,
            frame_number=0,
            image=image,
            adapter=adapter,
            seg=seg,
            out_dir=args.sessions_out,
        )
        note = (
            f"cov={meta['coverage']:.4f} neg={meta['negatives']} "
            f"tol_adj={meta['tolerance_adjusts']} soft={meta['soft_guard']} "
            f"cliff={meta['cliff_warning']} depth_ms={meta.get('depth_latency_ms', 0):.0f}"
        )
        pairs.append(
            pair_result(
                case_id=spec["case_id"],
                scenario=spec["scenario"],
                frame_number=0,
                manual=manual,
                depth_assist=depth,
                notes=note,
            )
        )
        # Overlay pair-level soft/cliff flags from meta when event warning missed wording.
        if meta["soft_guard"] and pairs[-1].soft_guard_warnings == 0:
            # recount via notes only for aggregate soft_guard_cases — patch by replacing
            from dataclasses import replace

            pairs[-1] = replace(pairs[-1], soft_guard_warnings=1)
        if meta["cliff_warning"] and pairs[-1].cliff_warnings == 0:
            from dataclasses import replace

            pairs[-1] = replace(pairs[-1], cliff_warnings=1)
        print(f"OK {spec['case_id']} {note}")

    aggregate = aggregate_pairs(pairs)
    decision = decide_d4(aggregate)
    # Resolve report paths relative to CWD (02_Source typically).
    md_path = args.report_md
    json_path = args.report_json
    write_d39_reports(
        pairs=pairs,
        aggregate=aggregate,
        decision=decision,
        md_path=md_path,
        json_path=json_path,
        execution_notes=notes_global,
    )
    print(
        f"pairs={len(pairs)} median_red={aggregate.get('median_interaction_reduction_pct')} "
        f"win={aggregate.get('depth_assist_win_rate')} decision={decision['decision']}"
    )
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
