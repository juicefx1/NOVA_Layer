from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from typing import Any
from uuid import uuid4

import av
import numpy as np
from numpy.typing import NDArray

from nova_layer.domain.models import SmartLayerRender


class ExportFormat(StrEnum):
    PNG_SEQUENCE = "png_sequence"
    OPENEXR_SEQUENCE = "openexr_sequence"
    RGBA_MOV = "rgba_mov"


FORMAT_LABELS = {
    ExportFormat.PNG_SEQUENCE: "NOVA Layer RGBA PNG Sequence",
    ExportFormat.OPENEXR_SEQUENCE: "NOVA Layer RGBA OpenEXR Sequence",
    ExportFormat.RGBA_MOV: "NOVA Layer RGBA QuickTime",
}


@dataclass(frozen=True, slots=True)
class SmartLayerExportResult:
    path: Path
    format: ExportFormat
    file_count: int


class SmartLayerExportError(RuntimeError):
    """Raised when a Smart Layer production export cannot be completed."""


def load_rgba_png(path: Path) -> NDArray[np.uint8]:
    with av.open(str(path)) as container:
        frame = next(container.decode(video=0))
        array = frame.to_ndarray(format="rgba")
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 4:
        raise SmartLayerExportError(f"Expected RGBA PNG pixels: {path}")
    return np.ascontiguousarray(array)


def write_openexr_rgba(path: Path, rgba: NDArray[np.uint8]) -> None:
    try:
        import Imath  # type: ignore[import-untyped]
        import OpenEXR  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised when desktop export extras missing
        raise SmartLayerExportError(
            "OpenEXR support requires the optional desktop dependency `OpenEXR`."
        ) from exc
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise SmartLayerExportError("OpenEXR export requires RGBA uint8 frames.")
    height, width, _ = rgba.shape
    header = OpenEXR.Header(width, height)
    header["channels"] = {
        "R": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF)),
        "G": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF)),
        "B": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF)),
        "A": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF)),
    }
    half = (rgba.astype(np.float32) / 255.0).astype(np.float16)
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                "R": half[:, :, 0].tobytes(),
                "G": half[:, :, 1].tobytes(),
                "B": half[:, :, 2].tobytes(),
                "A": half[:, :, 3].tobytes(),
            }
        )
    finally:
        output.close()


def write_rgba_mov(
    path: Path,
    frames: Sequence[NDArray[np.uint8]],
    *,
    frame_rate: float,
) -> None:
    if not frames:
        raise SmartLayerExportError("RGBA movie export requires at least one frame.")
    height, width, channels = frames[0].shape
    if channels != 4:
        raise SmartLayerExportError("RGBA movie export requires four-channel frames.")
    if any(frame.shape != (height, width, 4) or frame.dtype != np.uint8 for frame in frames):
        raise SmartLayerExportError("All movie frames must share RGBA uint8 dimensions.")
    rate = max(1, int(round(frame_rate))) if frame_rate >= 1 else 1
    with av.open(str(path), mode="w", format="mov") as container:
        stream = container.add_stream("qtrle", rate=rate)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "argb"
        for rgba in frames:
            video_frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgba), format="rgba")
            video_frame = video_frame.reformat(format="argb")
            for packet in stream.encode(video_frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_smart_layer_assets(
    *,
    package_path: Path,
    destination_directory: Path,
    export_stem: str,
    render: SmartLayerRender,
    format: ExportFormat,
    project: Mapping[str, Any],
    shot: Mapping[str, Any],
    smart_layer: Mapping[str, Any],
    frame_rate: float,
    color_policy: Mapping[str, Any] | None = None,
) -> SmartLayerExportResult:
    if not destination_directory.is_dir():
        raise SmartLayerExportError("Choose an existing export destination directory.")
    export_path = destination_directory / export_stem
    if export_path.exists():
        raise SmartLayerExportError(f"Export destination already exists: {export_path}")
    staging_path = destination_directory / f".{export_stem}.staging_{uuid4().hex}"
    try:
        staging_path.mkdir()
        exported_files: list[dict[str, Any]] = []
        if format is ExportFormat.PNG_SEQUENCE:
            for frame in render.frames:
                source = package_path / frame.image_reference
                if not source.is_file():
                    raise FileNotFoundError(f"Rendered frame is missing: {source}")
                destination = staging_path / source.name
                copy2(source, destination)
                exported_files.append(
                    {
                        "name": destination.name,
                        "size": destination.stat().st_size,
                        "sha256": _sha256(destination),
                    }
                )
        elif format is ExportFormat.OPENEXR_SEQUENCE:
            for frame in render.frames:
                source = package_path / frame.image_reference
                if not source.is_file():
                    raise FileNotFoundError(f"Rendered frame is missing: {source}")
                rgba = load_rgba_png(source)
                destination = staging_path / f"frame_{frame.frame_number:06d}.exr"
                write_openexr_rgba(destination, rgba)
                exported_files.append(
                    {
                        "name": destination.name,
                        "size": destination.stat().st_size,
                        "sha256": _sha256(destination),
                    }
                )
        elif format is ExportFormat.RGBA_MOV:
            rgba_frames: list[NDArray[np.uint8]] = []
            for frame in render.frames:
                source = package_path / frame.image_reference
                if not source.is_file():
                    raise FileNotFoundError(f"Rendered frame is missing: {source}")
                rgba_frames.append(load_rgba_png(source))
            movie_name = f"{export_stem}.mov"
            destination = staging_path / movie_name
            write_rgba_mov(destination, rgba_frames, frame_rate=frame_rate)
            exported_files.append(
                {
                    "name": destination.name,
                    "size": destination.stat().st_size,
                    "sha256": _sha256(destination),
                    "codec": "qtrle",
                    "pixel_format": "argb",
                }
            )
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise SmartLayerExportError(f"Unsupported export format: {format}")

        resolved_policy = (
            dict(color_policy)
            if color_policy is not None
            else _load_sidecar_color_policy(package_path, render)
        )
        manifest: dict[str, Any] = {
            "format": FORMAT_LABELS[format],
            "format_id": format.value,
            "project": dict(project),
            "shot": dict(shot),
            "smart_layer": dict(smart_layer),
            "render": render.model_dump(mode="json"),
            "files": exported_files,
        }
        if resolved_policy:
            manifest["color_policy"] = resolved_policy
            # Convenience top-level fields used by host tooling / QA.
            if "color_policy" in resolved_policy:
                manifest["color_policy_id"] = resolved_policy.get("color_policy")
            manifest["alpha_mode"] = resolved_policy.get("alpha_mode", "straight")
            manifest["premultiplied"] = resolved_policy.get("premultiplied", False)
            manifest["scene_linear"] = resolved_policy.get("scene_linear", False)
            if resolved_policy.get("pixel_encoding") is not None:
                manifest["pixel_encoding"] = resolved_policy.get("pixel_encoding")
        (staging_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        staging_path.replace(export_path)
    except Exception:
        rmtree(staging_path, ignore_errors=True)
        raise
    return SmartLayerExportResult(
        path=export_path,
        format=format,
        file_count=len(exported_files),
    )


def _load_sidecar_color_policy(
    package_path: Path,
    render: SmartLayerRender,
) -> dict[str, Any] | None:
    if not render.frames:
        return None
    parent = package_path / Path(render.frames[0].image_reference).parent
    path = parent / "color_policy.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None
