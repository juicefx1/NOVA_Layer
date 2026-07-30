from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from nova_layer.adapters.capabilities.mock import MockSkeletonDetectionCapability
from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.depth_pose_benchmark import (
    DepthPoseBenchmarkCase,
    DepthPoseSuiteGates,
    evaluate_suite,
    run_benchmark,
    write_report,
)
from nova_layer.depth_pose_comparison import compare_depth_pose_reports, write_comparison
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint


@dataclass(frozen=True, slots=True)
class DepthPoseSmokeResult:
    passed: bool
    report_path: Path
    comparison_path: Path | None
    case_count: int
    mean_joint_error: float
    mean_pck: float
    temporal_transition_count: int
    message: str


def _skeleton(*, x_offset: float = 0.0, y_offset: float = 0.0) -> SkeletonGuidance:
    shoulder = SkeletonJoint(x=0.40 + x_offset, y=0.30 + y_offset, label="left_shoulder")
    elbow = SkeletonJoint(x=0.34 + x_offset, y=0.46 + y_offset, label="left_elbow")
    wrist = SkeletonJoint(x=0.30 + x_offset, y=0.62 + y_offset, label="left_wrist")
    return SkeletonGuidance(
        joints=[shoulder, elbow, wrist],
        bones=[
            SkeletonBone(start_joint_id=shoulder.id, end_joint_id=elbow.id),
            SkeletonBone(start_joint_id=elbow.id, end_joint_id=wrist.id),
        ],
    )


def write_smoke_video(path: Path, *, frame_count: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=12)
        stream.width = 96
        stream.height = 72
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 12)
        for index in range(frame_count):
            pixels = np.full((72, 96, 3), 24 + index * 8, dtype=np.uint8)
            pixels[18:54, 30 + index * 4 : 58 + index * 4] = (210, 96, 48)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def build_smoke_cases(media_path: Path, fingerprint: str) -> tuple[DepthPoseBenchmarkCase, ...]:
    artist = _skeleton()
    # Deterministic mock shifts joints by (+0.012, +0.008); lock ground truth to that envelope.
    truth = _skeleton(x_offset=0.012, y_offset=0.008)
    return (
        DepthPoseBenchmarkCase(
            case_id="smoke-frame-0",
            media_path=media_path,
            frame_number=0,
            artist_skeleton=artist,
            ground_truth_skeleton=truth,
            pck_threshold=0.05,
            minimum_pck=0.8,
            minimum_joint_coverage=0.8,
            minimum_depth_coverage=0.8,
            minimum_sampled_depth_coverage=0.8,
            maximum_duration_seconds=5.0,
            annotation_status="approved",
            source_media_fingerprint=fingerprint,
            depth_sequence="depth-pose-smoke",
        ),
        DepthPoseBenchmarkCase(
            case_id="smoke-frame-2",
            media_path=media_path,
            frame_number=2,
            artist_skeleton=artist,
            ground_truth_skeleton=truth,
            pck_threshold=0.05,
            minimum_pck=0.8,
            minimum_joint_coverage=0.8,
            minimum_depth_coverage=0.8,
            minimum_sampled_depth_coverage=0.8,
            maximum_duration_seconds=5.0,
            annotation_status="approved",
            source_media_fingerprint=fingerprint,
            depth_sequence="depth-pose-smoke",
        ),
    )


def run_depth_pose_smoke(output_dir: Path) -> DepthPoseSmokeResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_path = output_dir / "depth_pose_smoke.mp4"
    write_smoke_video(media_path)
    reader = PyAvMediaReader()
    info = reader.inspect(media_path)
    cases = build_smoke_cases(media_path, info.fingerprint)
    results = run_benchmark(cases, MockSkeletonDetectionCapability(), media_reader=reader)
    gates = DepthPoseSuiteGates(
        maximum_mean_temporal_relative_depth_delta=0.25,
        minimum_temporal_transition_coverage=1.0,
    )
    report_path = write_report(
        output_dir / "depth_pose_smoke_latest.json",
        "NOVA Depth Pose Deterministic Smoke",
        results,
        gates=gates,
    )
    evaluation = evaluate_suite(results, gates)
    comparison_path: Path | None = None
    if evaluation.passed:
        # Self-compare locks the regression path against the same deterministic evidence.
        comparison = compare_depth_pose_reports(report_path, report_path)
        comparison_json, _ = write_comparison(output_dir / "regression", comparison)
        comparison_path = comparison_json
        if not comparison.passed:
            evaluation_passed = False
            message = "Smoke suite passed gates but failed self-comparison."
        else:
            evaluation_passed = True
            message = "Deterministic Depth/Pose smoke passed benchmark and regression gates."
    else:
        evaluation_passed = False
        message = "Deterministic Depth/Pose smoke failed one or more suite gates."
    summary = json.loads(report_path.read_text(encoding="utf-8"))["summary"]
    sidecar = {
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": evaluation_passed,
        "report": str(report_path),
        "comparison": str(comparison_path) if comparison_path is not None else None,
        "message": message,
    }
    (output_dir / "depth_pose_smoke_summary.json").write_text(
        json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
    )
    return DepthPoseSmokeResult(
        passed=evaluation_passed,
        report_path=report_path,
        comparison_path=comparison_path,
        case_count=int(summary["case_total"]),
        mean_joint_error=float(summary["mean_joint_error"]),
        mean_pck=float(summary["mean_pck"]),
        temporal_transition_count=int(summary["temporal_depth_transition_count"]),
        message=message,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a deterministic Depth/Pose smoke suite without real footage."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../06_Test/reports/depth_pose_smoke"),
        help="Directory for smoke media, JSON/Markdown reports, and self-comparison",
    )
    args = parser.parse_args()
    result = run_depth_pose_smoke(args.output)
    print(result.message)
    print(result.report_path)
    if result.comparison_path is not None:
        print(result.comparison_path)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
