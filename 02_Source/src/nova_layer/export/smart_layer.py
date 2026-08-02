from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
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

from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.domain.models import SmartLayerRender
from nova_layer.export.scene_exr import (
    SCENE_EXR_WRITER_VERSION,
    SceneExrError,
    SceneExrHeaderMetadata,
    build_scene_export_manifest_fields,
    compose_scene_rgba,
    openexr_writer_available,
    write_scene_openexr_rgba,
)
from nova_layer.ports.media import MediaReadError


class ExportFormat(StrEnum):
    PNG_SEQUENCE = "png_sequence"
    OPENEXR_SEQUENCE = "openexr_sequence"
    RGBA_MOV = "rgba_mov"
    SCENE_OPENEXR_SEQUENCE = "scene_openexr_sequence"


FORMAT_LABELS = {
    ExportFormat.PNG_SEQUENCE: "NOVA Layer RGBA PNG Sequence",
    ExportFormat.OPENEXR_SEQUENCE: "NOVA Layer RGBA OpenEXR (Current Render Look)",
    ExportFormat.RGBA_MOV: "NOVA Layer RGBA QuickTime",
    ExportFormat.SCENE_OPENEXR_SEQUENCE: "NOVA Layer RGBA OpenEXR (Scene Linear)",
}

# Workspace / dialog choices: (display label, format id, description).
EXPORT_FORMAT_CHOICES: tuple[tuple[str, str, str], ...] = (
    (
        "PNG Sequence",
        ExportFormat.PNG_SEQUENCE.value,
        "Exports packaged RGBA PNG frames from the current render.",
    ),
    (
        "OpenEXR — Current Render Look",
        ExportFormat.OPENEXR_SEQUENCE.value,
        "Packages PREVIEW/SOURCE render RGB as half EXR. Not scene-linear.",
    ),
    (
        "OpenEXR — Scene Linear",
        ExportFormat.SCENE_OPENEXR_SEQUENCE.value,
        "Exports file-native scene float RGB with the render mask as straight "
        "alpha. Requires an OpenEXR image sequence and OpenImageIO.",
    ),
    (
        "RGBA QuickTime (.mov)",
        ExportFormat.RGBA_MOV.value,
        "Exports a QuickTime movie from packaged RGBA PNG frames.",
    ),
)

SCENE_LINEAR_EXPORT_DESCRIPTION = EXPORT_FORMAT_CHOICES[2][2]


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
    scene_media_path: Path | None = None,
    scene_decoder: FrameDecodeService | None = None,
    mask_loader: Callable[[str], NDArray[np.uint8]] | None = None,
    media_fingerprint: str | None = None,
    input_color_space: str | None = None,
    config_path: str | None = None,
    config_source: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    report_progress: Callable[[int, int, str], None] | None = None,
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
        scene_source_color_space: str | None = None
        scene_source_color_space_source: str | None = None
        header_skipped: list[str] | None = None
        header_warnings: list[str] | None = None
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
        elif format is ExportFormat.SCENE_OPENEXR_SEQUENCE:
            exported_files, scene_tags = _export_scene_openexr_sequence(
                staging_path=staging_path,
                package_path=package_path,
                render=render,
                scene_media_path=scene_media_path,
                scene_decoder=scene_decoder,
                mask_loader=mask_loader,
                input_color_space=input_color_space,
                media_fingerprint=media_fingerprint,
                project_id=(
                    str(project.get("id")) if project.get("id") is not None else None
                ),
                shot_id=str(shot.get("id")) if shot.get("id") is not None else None,
                layer_id=(
                    str(smart_layer.get("id"))
                    if smart_layer.get("id") is not None
                    else None
                ),
                frame_rate=frame_rate,
                should_cancel=should_cancel,
                report_progress=report_progress,
            )
            scene_source_color_space = scene_tags.get("source_color_space")
            scene_source_color_space_source = scene_tags.get(
                "source_color_space_source"
            )
            header_skipped = scene_tags.get("header_metadata_skipped")
            header_warnings = scene_tags.get("header_metadata_warnings")
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise SmartLayerExportError(f"Unsupported export format: {format}")

        manifest: dict[str, Any] = {
            "format": FORMAT_LABELS[format],
            "format_id": format.value,
            "project": dict(project),
            "shot": dict(shot),
            "smart_layer": dict(smart_layer),
            "render": render.model_dump(mode="json"),
            "files": exported_files,
        }
        if format is ExportFormat.SCENE_OPENEXR_SEQUENCE:
            scene_fields = build_scene_export_manifest_fields(
                source_color_space=scene_source_color_space,
                source_color_space_source=scene_source_color_space_source,
                interpretation_color_space=input_color_space,
                media_fingerprint=media_fingerprint,
                project_id=str(project.get("id")) if project.get("id") is not None else None,
                shot_id=str(shot.get("id")) if shot.get("id") is not None else None,
                layer_id=(
                    str(smart_layer.get("id"))
                    if smart_layer.get("id") is not None
                    else None
                ),
                source_render_version=int(render.version),
                frame_start=int(render.frame_start),
                frame_end=int(render.frame_end),
                pixel_type="half",
                config_path=config_path,
                config_source=config_source,
            )
            manifest.update(scene_fields)
            if header_skipped:
                manifest["header_metadata_skipped"] = header_skipped
            if header_warnings:
                manifest["header_metadata_warnings"] = header_warnings
            manifest["header_writer_version"] = SCENE_EXR_WRITER_VERSION
        else:
            resolved_policy = (
                dict(color_policy)
                if color_policy is not None
                else _load_sidecar_color_policy(package_path, render)
            )
            if resolved_policy:
                manifest["color_policy"] = resolved_policy
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


def _export_scene_openexr_sequence(
    *,
    staging_path: Path,
    package_path: Path,
    render: SmartLayerRender,
    scene_media_path: Path | None,
    scene_decoder: FrameDecodeService | None,
    mask_loader: Callable[[str], NDArray[np.uint8]] | None,
    input_color_space: str | None,
    media_fingerprint: str | None = None,
    project_id: str | None = None,
    shot_id: str | None = None,
    layer_id: str | None = None,
    frame_rate: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    report_progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Frame-at-a-time True Scene EXR export (Phase 10A-2 / 10B header metadata).

    Holds at most one ``SceneFrame`` in locals per loop iteration. Does not call
    ``decode_scene_frame_range`` (no full-range dict). Staging cleanup on failure
    is handled by the caller. Header metadata is best-effort convenience; the
    export manifest remains authoritative.
    """
    _ = package_path  # Scene pixels come from media+mask, not packaged render PNGs.
    if scene_media_path is None or scene_decoder is None or mask_loader is None:
        raise SmartLayerExportError(
            "True Scene export requires an EXR image sequence and OpenImageIO "
            "(scene media path, decoder, and mask loader)."
        )
    if not openexr_writer_available():
        raise SmartLayerExportError(
            "True Scene export requires the optional desktop dependency `OpenEXR` "
            "(writer)."
        )
    if not render.frames:
        raise SmartLayerExportError("True Scene export requires render frames with masks.")

    cancel = should_cancel or (lambda: False)
    report = report_progress or (lambda *_args: None)
    total = len(render.frames)

    source_color_space: str | None = None
    source_color_space_source: str | None = None
    header_template: SceneExrHeaderMetadata | None = None
    exported_files: list[dict[str, Any]] = []
    skipped_keys: set[str] = set()
    warning_messages: list[str] = []

    report(0, total, "Exporting scene-linear OpenEXR sequence")
    for index, frame in enumerate(render.frames, start=1):
        if cancel():
            raise SmartLayerExportError("True Scene export cancelled.")
        report(index - 1, total, f"Scene export frame {frame.frame_number}")
        try:
            scene = scene_decoder.get_scene_frame(
                scene_media_path,
                frame.frame_number,
            )
        except MediaReadError as exc:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO. "
                f"(frame {frame.frame_number}: {exc})"
            ) from exc
        except Exception as exc:
            raise SmartLayerExportError(
                "True Scene export failed decoding scene frame "
                f"{frame.frame_number}: {exc}"
            ) from exc

        if header_template is None:
            source_color_space = scene.color_space
            source_color_space_source = scene.color_space_source
            source_tag = (
                str(source_color_space).strip()
                if source_color_space is not None and str(source_color_space).strip()
                else "unspecified"
            )
            interpretation = (
                str(input_color_space).strip()
                if input_color_space is not None and str(input_color_space).strip()
                else None
            )
            header_template = SceneExrHeaderMetadata(
                color_policy="scene",
                scene_linear=True,
                source_color_space=source_tag,
                interpretation_color_space=interpretation,
                premultiplied=False,
                alpha_mode="straight",
                pixel_encoding="file_native_scene_half",
                source_render_version=int(render.version),
                source_fingerprint=media_fingerprint,
                project_id=project_id,
                shot_id=shot_id,
                layer_id=layer_id,
                frame_number=int(frame.frame_number),
                writer_version=SCENE_EXR_WRITER_VERSION,
                frames_per_second=float(frame_rate) if frame_rate is not None else None,
            )

        if not frame.mask_reference:
            raise SmartLayerExportError(
                f"True Scene export missing mask for frame {frame.frame_number}."
            )
        try:
            mask = mask_loader(frame.mask_reference)
        except Exception as exc:
            raise SmartLayerExportError(
                f"True Scene export could not load mask for frame {frame.frame_number}: {exc}"
            ) from exc
        try:
            rgba = compose_scene_rgba(scene.pixels, mask)
        except ValueError as exc:
            raise SmartLayerExportError(str(exc)) from exc
        # Drop scene reference before next decode so only RGBA + mask live briefly.
        del scene
        destination = staging_path / f"frame_{frame.frame_number:06d}.exr"
        assert header_template is not None
        frame_metadata = header_template.with_frame_number(frame.frame_number)
        try:
            header_result = write_scene_openexr_rgba(
                destination,
                rgba,
                pixel_type="half",
                compression="zip",
                metadata=frame_metadata,
            )
        except SceneExrError as exc:
            raise SmartLayerExportError(str(exc)) from exc
        del rgba
        if header_result is not None:
            skipped_keys.update(header_result.skipped_keys)
            warning_messages.extend(header_result.warnings)
        exported_files.append(
            {
                "name": destination.name,
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
        report(index, total, f"Scene export frame {frame.frame_number} done")

    tags: dict[str, Any] = {
        "source_color_space": source_color_space,
        "source_color_space_source": source_color_space_source,
    }
    if skipped_keys:
        tags["header_metadata_skipped"] = sorted(skipped_keys)
    if warning_messages:
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique_warnings: list[str] = []
        for message in warning_messages:
            if message in seen:
                continue
            seen.add(message)
            unique_warnings.append(message)
        tags["header_metadata_warnings"] = unique_warnings
    return exported_files, tags


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
