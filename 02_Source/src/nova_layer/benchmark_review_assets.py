from __future__ import annotations

import argparse
import html
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.media.pyav_reader import PyAvMediaReader
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.ports.media import MediaReader
from nova_layer.real_footage_benchmark import BenchmarkCase, load_manifest


def _load_mask(path: Path) -> NDArray[np.uint8]:
    return PngMaskStore().load(path.parent, path.name)


def _rgba(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate((rgb, alpha), axis=2)


def _mask_rgba(mask: NDArray[np.uint8]) -> NDArray[np.uint8]:
    rgb = np.repeat(mask[:, :, None], 3, axis=2)
    return _rgba(rgb)


def _overlay_rgba(frame: NDArray[np.uint8], mask: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if mask.shape != frame.shape[:2]:
        raise ValueError("Ground Truth mask dimensions do not match the source frame.")
    overlay = frame.astype(np.float32)
    selected = mask > 0
    overlay[selected] = overlay[selected] * 0.55 + np.array([255.0, 48.0, 96.0]) * 0.45
    return _rgba(np.clip(overlay, 0, 255).astype(np.uint8))


def generate_review_assets(
    cases: Sequence[BenchmarkCase],
    output_directory: Path,
    *,
    media_reader: MediaReader | None = None,
    mask_loader: Callable[[Path], NDArray[np.uint8]] = _load_mask,
) -> Path:
    if not cases:
        raise ValueError("Dataset contains no review cases.")
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise ValueError(f"Review output already exists: {output_directory}")
    staging = output_directory.with_name(f".{output_directory.name}.{uuid4().hex}.staging")
    reader = media_reader or PyAvMediaReader()
    store = PngPreviewStore()
    rows: list[str] = []
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
            mask = mask_loader(case.ground_truth_path)
            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", case.case_id).strip("-")
            frame_name = f"{safe_id}_frame.png"
            overlay_name = f"{safe_id}_overlay.png"
            mask_name = f"{safe_id}_mask.png"
            store.save(staging, frame_name, _rgba(frame))
            store.save(staging, overlay_name, _overlay_rgba(frame, mask))
            store.save(staging, mask_name, _mask_rgba(mask))
            escaped_id = html.escape(case.case_id)
            rows.append(
                f"<section><h2>{escaped_id} · Frame {case.frame_number}</h2>"
                f"<p>Status: <strong>{html.escape(case.annotation_status)}</strong></p>"
                '<div class="images"><figure>'
                f'<img src="{frame_name}"><figcaption>Source frame</figcaption>'
                "</figure><figure>"
                f'<img src="{overlay_name}"><figcaption>Ground Truth overlay</figcaption>'
                "</figure><figure>"
                f'<img src="{mask_name}"><figcaption>Ground Truth mask</figcaption>'
                "</figure></div></section>"
            )
        document = (
            '<!doctype html><html><head><meta charset="utf-8"><title>NOVA Dataset QA</title>'
            "<style>body{font-family:system-ui;background:#12151b;color:#eef2f7;margin:32px}"
            "section{margin:0 0 48px;padding:24px;background:#1b2029;border-radius:12px}"
            ".images{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}"
            "img{width:100%;background:#080a0d}figcaption{margin-top:8px;color:#aeb8c5}</style>"
            "</head><body><h1>NOVA Layer Ground Truth QA</h1>" + "".join(rows) + "</body></html>"
        )
        (staging / "index.html").write_text(document, encoding="utf-8")
        staging.replace(output_directory)
    except Exception:
        rmtree(staging, ignore_errors=True)
        raise
    return output_directory / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate visual Ground Truth QA assets.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _, cases = load_manifest(args.manifest, allow_unreviewed=True)
    print(generate_review_assets(cases, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
