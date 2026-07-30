from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.capabilities.sam2_video import Sam2VideoPropagationCapability
from nova_layer.app.capability_selection import default_checkpoint
from nova_layer.ports.capabilities import VideoFrame


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    name: str
    frames: tuple[VideoFrame, ...]
    master_frame: int
    master_mask: NDArray[np.uint8]
    ground_truth: dict[int, NDArray[np.uint8]]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    status: str
    duration_seconds: float
    start_iou: float
    end_iou: float
    minimum_iou: float
    start_confidence: float
    end_confidence: float
    maximum_calibration_gap: float


def _rectangle_mask(height: int, width: int, x: int, y: int, w: int, h: int) -> NDArray[np.uint8]:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[y : y + h, x : x + w] = 255
    return mask


def make_scenario(name: str, *, height: int = 180, width: int = 320) -> BenchmarkScenario:
    if name not in {
        "translation",
        "occlusion_recovery",
        "similar_distractor",
        "motion_blur",
        "full_occlusion_recovery",
        "frame_exit",
    }:
        raise ValueError(f"Unknown benchmark scenario: {name}")
    frames: list[VideoFrame] = []
    ground_truth: dict[int, NDArray[np.uint8]] = {}
    for number in range(7):
        image = np.full((height, width, 3), 18, dtype=np.uint8)
        x = 48 + number * 20
        mask = _rectangle_mask(height, width, x, 55, 72, 70)
        image[mask > 0] = (220, 72, 42)
        if name == "occlusion_recovery" and number in {1, 5}:
            image[45:135, x + 24 : x + 54] = (30, 120, 205)
        if name == "similar_distractor":
            image[20:72, 220:278] = (210, 68, 40)
        if name == "motion_blur" and number in {1, 5}:
            image[55:125, x - 24 : x] = (95, 40, 30)
            image[55:125, x + 72 : x + 96] = (95, 40, 30)
        if name == "full_occlusion_recovery" and number in {1, 2, 4, 5}:
            image[45:135, x - 4 : x + 78] = (30, 120, 205)
        if name == "frame_exit" and number in {0, 1, 5, 6}:
            image[mask > 0] = (18, 18, 18)
            mask = np.zeros_like(mask)
        frames.append(VideoFrame(frame_number=number, image=image))
        ground_truth[number] = mask
    return BenchmarkScenario(
        name=name,
        frames=tuple(frames),
        master_frame=3,
        master_mask=ground_truth[3],
        ground_truth={0: ground_truth[0], 6: ground_truth[6]},
    )


def intersection_over_union(prediction: NDArray[np.uint8], truth: NDArray[np.uint8]) -> float:
    predicted = prediction > 0
    expected = truth > 0
    union = np.logical_or(predicted, expected).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(predicted, expected).sum() / union)


def run_benchmark(checkpoint: Path) -> list[ScenarioResult]:
    adapter = Sam2VideoPropagationCapability(checkpoint, device="mps")
    results: list[ScenarioResult] = []
    for name in (
        "translation",
        "occlusion_recovery",
        "similar_distractor",
        "motion_blur",
        "full_occlusion_recovery",
        "frame_exit",
    ):
        scenario = make_scenario(name)
        started = monotonic()
        propagated = adapter.propagate(
            master_frame=scenario.master_frame,
            target_frames=[0, 6],
            reference_mask="benchmark_master.png",
            reference_mask_data=scenario.master_mask,
            frames=scenario.frames,
        )
        duration = monotonic() - started
        by_frame = {item.frame_number: item for item in propagated}
        start_iou = intersection_over_union(by_frame[0].mask, scenario.ground_truth[0])
        end_iou = intersection_over_union(by_frame[6].mask, scenario.ground_truth[6])
        minimum = min(start_iou, end_iou)
        start_confidence = by_frame[0].confidence
        end_confidence = by_frame[6].confidence
        calibration_gap = max(abs(start_confidence - start_iou), abs(end_confidence - end_iou))
        results.append(
            ScenarioResult(
                name=name,
                status="passed" if minimum >= 0.80 else "review",
                duration_seconds=round(duration, 3),
                start_iou=round(start_iou, 4),
                end_iou=round(end_iou, 4),
                minimum_iou=round(minimum, 4),
                start_confidence=round(start_confidence, 4),
                end_confidence=round(end_confidence, 4),
                maximum_calibration_gap=round(calibration_gap, 4),
            )
        )
    return results


def write_reports(results: list[ScenarioResult], output_dir: Path) -> tuple[Path, Path]:
    generated_at = datetime.now(UTC).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sam2_video_scenario_benchmark_latest.json"
    markdown_path = output_dir / "sam2_video_scenario_benchmark_latest.md"
    payload = {
        "suite": "NOVA Layer SAM 2.1 Video Scenario Benchmark",
        "generated_at": generated_at,
        "model": "SAM 2.1 Hiera Tiny",
        "device": "mps",
        "pass_threshold_iou": 0.80,
        "results": [asdict(result) for result in results],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# NOVA Layer SAM 2.1 Video Scenario Benchmark",
        "",
        f"Generated: {generated_at}",
        "",
        "Model: SAM 2.1 Hiera Tiny  ",
        "Device: Apple MPS  ",
        "Review threshold: minimum endpoint IoU 0.80",
        "",
        "| Scenario | Status | Start IoU / confidence | End IoU / confidence | "
        "Max gap | Duration |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.name} | {item.status.upper()} | {item.start_iou:.4f} / "
        f"{item.start_confidence:.4f} | {item.end_iou:.4f} / {item.end_confidence:.4f} | "
        f"{item.maximum_calibration_gap:.4f} | {item.duration_seconds:.3f}s |"
        for item in results
    )
    lines.extend(
        [
            "",
            "This procedural suite is a deterministic capability benchmark. It does not replace",
            "licensed real-footage evaluation or artist review.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SAM 2.1 video tracking scenarios.")
    parser.add_argument("--checkpoint", type=Path, default=default_checkpoint())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "06_Test" / "reports",
    )
    args = parser.parse_args()
    results = run_benchmark(args.checkpoint)
    json_path, markdown_path = write_reports(results, args.output)
    print(json_path)
    print(markdown_path)
    return 0 if all(item.status == "passed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
