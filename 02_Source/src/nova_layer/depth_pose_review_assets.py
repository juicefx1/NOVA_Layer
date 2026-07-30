from __future__ import annotations

import argparse
import html
import re
from collections.abc import Sequence
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.depth_pose_benchmark import DepthPoseBenchmarkCase, load_manifest
from nova_layer.domain.models import SkeletonGuidance
from nova_layer.ports.media import MediaReader

Color = tuple[int, int, int]


def _disk(image: NDArray[np.uint8], x: int, y: int, radius: int, color: Color) -> None:
    height, width = image.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    selected = (xx - x) ** 2 + (yy - y) ** 2 <= radius**2
    image[selected] = color


def _line(
    image: NDArray[np.uint8], start: tuple[int, int], end: tuple[int, int], color: Color
) -> None:
    distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
    xs = np.rint(np.linspace(start[0], end[0], distance + 1)).astype(int)
    ys = np.rint(np.linspace(start[1], end[1], distance + 1)).astype(int)
    for x, y in zip(xs, ys, strict=True):
        _disk(image, int(x), int(y), 1, color)


def skeleton_overlay(
    frame: NDArray[np.uint8],
    skeletons: Sequence[tuple[SkeletonGuidance, Color]],
) -> NDArray[np.uint8]:
    output = np.array(frame, copy=True)
    height, width = output.shape[:2]
    for skeleton, color in skeletons:
        joints = {joint.id: joint for joint in skeleton.joints}
        pixels = {
            joint.id: (
                round(joint.x * max(width - 1, 0)),
                round(joint.y * max(height - 1, 0)),
            )
            for joint in skeleton.joints
        }
        for bone in skeleton.bones:
            if bone.start_joint_id in joints and bone.end_joint_id in joints:
                _line(output, pixels[bone.start_joint_id], pixels[bone.end_joint_id], color)
        for position in pixels.values():
            _disk(output, *position, 3, color)
    alpha = np.full((*output.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate((output, alpha), axis=2)


def _joint_rows(case: DepthPoseBenchmarkCase) -> str:
    artist = case.artist_skeleton.semantic_joint_map()
    expected = case.ground_truth_skeleton.semantic_joint_map()
    rows: list[str] = []
    for label in sorted(set(artist) | set(expected)):
        rough = artist.get(label)
        truth = expected.get(label)
        rough_text = f"{rough.x:.4f}, {rough.y:.4f}" if rough else "missing"
        truth_text = f"{truth.x:.4f}, {truth.y:.4f}" if truth else "missing"
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td>{rough_text}</td><td>{truth_text}</td></tr>"
        )
    return "".join(rows)


def generate_review_assets(
    cases: Sequence[DepthPoseBenchmarkCase],
    output_directory: Path,
    *,
    media_reader: MediaReader | None = None,
) -> Path:
    if not cases:
        raise ValueError("Depth/Pose dataset contains no review cases.")
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise ValueError(f"Review output already exists: {output_directory}")
    staging = output_directory.with_name(f".{output_directory.name}.{uuid4().hex}.staging")
    reader = media_reader or PyAvMediaReader()
    store = PngPreviewStore()
    sections: list[str] = []
    try:
        staging.mkdir(parents=True)
        for case in cases:
            media = reader.inspect(case.media_path)
            if (
                case.source_media_fingerprint is not None
                and media.fingerprint != case.source_media_fingerprint
            ):
                raise ValueError(f"Case {case.case_id}: source-media fingerprint mismatch.")
            frame = reader.read_frame(case.media_path, case.frame_number)
            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", case.case_id).strip("-")
            images = {
                "source": skeleton_overlay(frame, ()),
                "artist": skeleton_overlay(frame, ((case.artist_skeleton, (255, 214, 64)),)),
                "truth": skeleton_overlay(frame, ((case.ground_truth_skeleton, (64, 232, 255)),)),
                "compare": skeleton_overlay(
                    frame,
                    (
                        (case.artist_skeleton, (255, 214, 64)),
                        (case.ground_truth_skeleton, (64, 232, 255)),
                    ),
                ),
            }
            for name, image in images.items():
                store.save(staging, f"{safe_id}_{name}.png", image)
            figures = "".join(
                f'<figure><img src="{safe_id}_{name}.png">'
                f"<figcaption>{caption}</figcaption></figure>"
                for name, caption in (
                    ("source", "Source frame"),
                    ("artist", "Artist rough · yellow"),
                    ("truth", "Ground truth · cyan"),
                    ("compare", "Comparison"),
                )
            )
            sections.append(
                f"<section><h2>{html.escape(case.case_id)} · Frame {case.frame_number}</h2>"
                f"<p>Status: <strong>{html.escape(case.annotation_status)}</strong></p>"
                f'<div class="images">{figures}</div><table><thead><tr><th>Label</th>'
                f"<th>Artist x,y</th><th>Ground truth x,y</th></tr></thead>"
                f"<tbody>{_joint_rows(case)}</tbody></table></section>"
            )
        document = (
            '<!doctype html><html><head><meta charset="utf-8"><title>NOVA Depth/Pose QA</title>'
            "<style>body{font-family:system-ui;background:#11151b;color:#eef2f7;margin:32px}"
            "section{margin-bottom:48px;padding:24px;background:#1b2029;border-radius:12px}"
            ".images{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}"
            "img{width:100%;background:#080a0d}figcaption{color:#aeb8c5;margin-top:8px}"
            "table{border-collapse:collapse;width:100%;margin-top:20px}th,td{text-align:left;"
            "padding:8px;border-bottom:1px solid #343b47}</style></head><body>"
            '<h1>NOVA Depth/Pose Ground Truth QA</h1><p><span style="color:#ffd640">Yellow</span> '
            'is artist intent; <span style="color:#40e8ff">cyan</span> is reviewed truth.</p>'
            + "".join(sections)
            + "</body></html>"
        )
        (staging / "index.html").write_text(document, encoding="utf-8")
        staging.replace(output_directory)
    except Exception:
        rmtree(staging, ignore_errors=True)
        raise
    return output_directory / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate visual Depth/Pose QA assets.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _, cases = load_manifest(args.manifest, allow_unreviewed=True)
    print(generate_review_assets(cases, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
