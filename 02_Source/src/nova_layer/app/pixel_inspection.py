"""Pixel inspection: PREVIEW / SOURCE / SCENE samples at an image coordinate.

Phase 9C-1 — read-only sampling for the Viewer Pixel Inspector. Prefers cache
peeks (no hit/miss/LRU mutation); falls back to normal decode only on miss.
Shared EXR raw decode: ``get_preview_frame`` / ``get_processing_frame`` /
``get_scene_frame`` reuse the raw cache so one hover does not triple-decode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.ports.media import MediaReadError

if TYPE_CHECKING:
    from nova_layer.app.frame_decode_service import FrameDecodeService


@dataclass(frozen=True, slots=True)
class PixelSample:
    x: int
    y: int
    rgb: tuple[float, float, float]
    alpha: float | None
    dtype: str
    value_range: str
    policy: str


@dataclass(frozen=True, slots=True)
class PixelInspection:
    image_x: int
    image_y: int
    preview: PixelSample | None
    source: PixelSample | None
    scene: PixelSample | None
    media_path: Path | None
    frame_number: int | None
    warning: str | None = None


def empty_pixel_inspection(
    *,
    image_x: int = -1,
    image_y: int = -1,
    media_path: Path | None = None,
    frame_number: int | None = None,
    warning: str | None = None,
) -> PixelInspection:
    return PixelInspection(
        image_x=image_x,
        image_y=image_y,
        preview=None,
        source=None,
        scene=None,
        media_path=media_path,
        frame_number=frame_number,
        warning=warning,
    )


def _format_float_component(value: float) -> float:
    if np.isnan(value):
        return float("nan")
    if np.isinf(value):
        return float(value)
    return float(value)


def _sample_from_array(
    image: NDArray[np.floating | np.integer],
    x: int,
    y: int,
    *,
    policy: str,
    value_range: str,
) -> PixelSample | None:
    if image.ndim < 2:
        return None
    height, width = int(image.shape[0]), int(image.shape[1])
    if x < 0 or y < 0 or x >= width or y >= height:
        return None
    pixel = image[y, x]
    channels = 1 if np.ndim(pixel) == 0 else int(np.shape(pixel)[0])
    if channels < 3:
        value = float(np.asarray(pixel).reshape(-1)[0])
        rgb = (value, value, value)
        alpha = None
    else:
        values = np.asarray(pixel, dtype=np.float64).reshape(-1)
        rgb = (
            _format_float_component(float(values[0])),
            _format_float_component(float(values[1])),
            _format_float_component(float(values[2])),
        )
        alpha = (
            _format_float_component(float(values[3]))
            if channels >= 4
            else None
        )
    return PixelSample(
        x=x,
        y=y,
        rgb=rgb,
        alpha=alpha,
        dtype=str(image.dtype),
        value_range=value_range,
        policy=policy,
    )


def format_sample_component(value: float, *, policy: str) -> str:
    """Human-readable channel string for UI."""
    if np.isnan(value):
        return "NaN"
    if np.isposinf(value):
        return "+Inf"
    if np.isneginf(value):
        return "-Inf"
    if policy in {
        ProcessingColorPolicy.PREVIEW.value,
        ProcessingColorPolicy.SOURCE.value,
        "preview",
        "source",
    }:
        return str(int(round(value)))
    return f"{value:.4f}"


def _array_shape(
    image: NDArray[np.floating | np.integer] | None,
) -> tuple[int, int] | None:
    if image is None or image.ndim < 2:
        return None
    return int(image.shape[0]), int(image.shape[1])


def inspect_pixel(
    decoder: FrameDecodeService,
    path: Path,
    frame_number: int,
    x: int,
    y: int,
    *,
    allow_decode: bool = True,
) -> PixelInspection:
    """Sample PREVIEW / SOURCE / SCENE at ``(x, y)`` for ``path``/``frame``.

    Prefer peek APIs (no cache stats mutation). On miss, optionally decode
    through normal APIs (shared raw for EXR). Invalid / out-of-bounds
    coordinates return an empty result without raising.
    """
    resolved = path.expanduser().resolve()
    if x < 0 or y < 0:
        return empty_pixel_inspection(
            image_x=x,
            image_y=y,
            media_path=resolved,
            frame_number=frame_number,
            warning="Invalid coordinates",
        )

    pipeline = decoder.pipeline
    warnings: list[str] = []

    preview_img = pipeline.peek_preview(resolved, frame_number)
    source_img = pipeline.peek_source(resolved, frame_number)
    scene = pipeline.peek_scene(resolved, frame_number)

    if allow_decode:
        # Warm PREVIEW first so EXR raw is shared with SOURCE / SCENE.
        if preview_img is None:
            try:
                preview_img = decoder.get_preview_frame(
                    resolved,
                    frame_number,
                    schedule_prefetch=False,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"PREVIEW unavailable: {exc}")
        if source_img is None:
            try:
                source_frame = decoder.get_processing_frame(
                    resolved,
                    frame_number,
                    policy=ProcessingColorPolicy.SOURCE,
                )
                if isinstance(source_frame, np.ndarray):
                    source_img = source_frame
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"SOURCE unavailable: {exc}")
        if scene is None:
            try:
                scene = decoder.get_scene_frame(resolved, frame_number)
            except MediaReadError as exc:
                warnings.append(str(exc) or "SCENE unsupported")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"SCENE unavailable: {exc}")

    height_width: tuple[int, int] | None = None
    for candidate in (
        preview_img,
        source_img,
        None if scene is None else scene.pixels,
    ):
        height_width = _array_shape(candidate)
        if height_width is not None:
            break
    if height_width is not None:
        height, width = height_width
        if x >= width or y >= height:
            return empty_pixel_inspection(
                image_x=x,
                image_y=y,
                media_path=resolved,
                frame_number=frame_number,
                warning="Outside image",
            )

    preview = (
        _sample_from_array(
            preview_img,
            x,
            y,
            policy=ProcessingColorPolicy.PREVIEW.value,
            value_range="uint8 0–255",
        )
        if preview_img is not None
        else None
    )
    source = (
        _sample_from_array(
            source_img,
            x,
            y,
            policy=ProcessingColorPolicy.SOURCE.value,
            value_range="uint8 0–255",
        )
        if source_img is not None
        else None
    )
    scene_sample = (
        _sample_from_array(
            scene.pixels,
            x,
            y,
            policy=ProcessingColorPolicy.SCENE.value,
            value_range="float32 file-native",
        )
        if scene is not None
        else None
    )

    warning = "; ".join(warnings) if warnings else None
    if preview is None and source is None and scene_sample is None and warning is None:
        warning = "No pixel data available"

    return PixelInspection(
        image_x=x,
        image_y=y,
        preview=preview,
        source=source,
        scene=scene_sample,
        media_path=resolved,
        frame_number=frame_number,
        warning=warning,
    )
