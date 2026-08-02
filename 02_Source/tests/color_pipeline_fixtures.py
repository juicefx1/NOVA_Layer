"""Shared synthetic fixtures for Phase 9A color-pipeline golden tests.

CI-safe: no real OpenImageIO/OCIO required. Fake OIIO returns a fixed float RGB.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.preview_pipeline import PreviewPipeline

# 4×4 scene-linear float RGB: dark / mid / 1.0 / over-range corners.
GOLDEN_SCENE_RGB: NDArray[np.float32] = np.array(
    [
        [
            [0.0, 0.0, 0.0],
            [0.01, 0.01, 0.01],
            [0.18, 0.18, 0.18],
            [0.5, 0.25, 0.1],
        ],
        [
            [1.0, 1.0, 1.0],
            [1.5, 1.2, 0.8],
            [0.0, 0.5, 1.0],
            [2.0, 0.0, 0.0],
        ],
        [
            [0.0031308, 0.0031308, 0.0031308],
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
            [0.7, 0.8, 0.9],
        ],
        [
            [0.05, 0.0, 0.05],
            [0.0, 0.05, 0.0],
            [0.25, 0.25, 0.25],
            [3.0, 3.0, 3.0],
        ],
    ],
    dtype=np.float32,
)

GOLDEN_MASK: NDArray[np.uint8] = np.array(
    [
        [0, 64, 128, 255],
        [255, 200, 100, 0],
        [32, 0, 255, 180],
        [0, 0, 0, 255],
    ],
    dtype=np.uint8,
)


def install_fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    *,
    counter: list[int] | None = None,
    pixels: NDArray[np.floating] | None = None,
) -> list[int]:
    """Patch ImageSequenceReader OIIO loader; return decode counter."""
    calls = counter if counter is not None else []
    rgb = np.asarray(
        pixels if pixels is not None else GOLDEN_SCENE_RGB,
        dtype=np.float32,
    )
    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    channels = int(rgb.shape[2]) if rgb.ndim == 3 else 3

    class FakeSpec:
        def __init__(self) -> None:
            self.height = height
            self.width = width
            self.nchannels = channels

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            calls.append(1)
            return rgb.copy()

        def close(self) -> None:
            return None

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(_path: str) -> FakeInput:
                return FakeInput()

    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )
    return calls


def make_exr_sequence(tmp_path: Path, *, frames: int = 2, name: str = "exr") -> Path:
    seq = tmp_path / name
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


def make_viewer_transform(*, exposure: float = 0.0) -> ViewerDisplayTransform:
    return ViewerDisplayTransform(
        exposure=ExposureTransform(exposure),
        display_transform=LegacyDisplayTransform(),
    )


def make_pipeline(*, exposure: float = 0.0) -> PreviewPipeline:
    return PreviewPipeline(
        ImageSequenceReader(),
        make_viewer_transform(exposure=exposure),
    )


def make_decoder(*, exposure: float = 0.0) -> FrameDecodeService:
    return FrameDecodeService(
        ImageSequenceReader(),
        display_transform=make_viewer_transform(exposure=exposure),
        prefetch_count=0,
    )
