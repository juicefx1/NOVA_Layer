from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.domain.models import ExtractionPreview, SmartLayerRender
from nova_layer.export.smart_layer import (
    ExportFormat,
    export_smart_layer_assets,
    load_rgba_png,
    write_openexr_rgba,
    write_rgba_mov,
)


def _write_rgba_package(tmp_path: Path) -> tuple[Path, SmartLayerRender]:
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    frames: list[ExtractionPreview] = []
    checksums: dict[str, str] = {}
    for index in range(3):
        rgba = np.zeros((12, 16, 4), dtype=np.uint8)
        rgba[..., 0] = 40 + index * 20
        rgba[..., 1] = 80
        rgba[..., 2] = 120
        rgba[..., 3] = 200
        reference = f"renders/v0001/frame_{index:06d}.png"
        store.save(package, reference, rgba)
        frames.append(
            ExtractionPreview(
                frame_number=index,
                image_reference=reference,
                mask_reference=f"masks/frame_{index:06d}.png",
            )
        )
        checksums[reference] = "unused"
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=2,
        frames=frames,
        checksums=checksums,
    )
    return package, render


def test_openexr_round_trip_preserves_normalized_rgba(tmp_path: Path) -> None:
    OpenEXR = pytest.importorskip("OpenEXR")
    Imath = pytest.importorskip("Imath")
    rgba = np.zeros((8, 10, 4), dtype=np.uint8)
    rgba[..., 0] = 64
    rgba[..., 1] = 128
    rgba[..., 2] = 192
    rgba[..., 3] = 255
    path = tmp_path / "frame.exr"
    write_openexr_rgba(path, rgba)
    assert path.is_file()
    inp = OpenEXR.InputFile(str(path))
    red = np.frombuffer(
        inp.channel("R", Imath.PixelType(Imath.PixelType.FLOAT)), dtype=np.float32
    ).reshape(8, 10)
    alpha = np.frombuffer(
        inp.channel("A", Imath.PixelType(Imath.PixelType.FLOAT)), dtype=np.float32
    ).reshape(8, 10)
    assert red[0, 0] == pytest.approx(64 / 255, abs=1e-3)
    assert alpha[0, 0] == pytest.approx(1.0, abs=1e-3)


def test_rgba_mov_writes_quicktime_container(tmp_path: Path) -> None:
    frames = [
        np.full((8, 8, 4), fill_value=(180, 40, 90, 255), dtype=np.uint8),
        np.full((8, 8, 4), fill_value=(20, 200, 40, 128), dtype=np.uint8),
    ]
    path = tmp_path / "layer.mov"
    write_rgba_mov(path, frames, frame_rate=24.0)
    assert path.stat().st_size > 0


def test_export_smart_layer_assets_all_formats(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    package, render = _write_rgba_package(tmp_path)
    destination = tmp_path / "exports"
    destination.mkdir()
    common = {
        "package_path": package,
        "destination_directory": destination,
        "render": render,
        "project": {"id": "p", "name": "Demo"},
        "shot": {"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 16, "height": 12},
        "smart_layer": {"id": "l", "name": "Layer"},
        "frame_rate": 24.0,
    }
    png = export_smart_layer_assets(
        export_stem="demo_png", format=ExportFormat.PNG_SEQUENCE, **common
    )
    exr = export_smart_layer_assets(
        export_stem="demo_exr", format=ExportFormat.OPENEXR_SEQUENCE, **common
    )
    mov = export_smart_layer_assets(
        export_stem="demo_mov", format=ExportFormat.RGBA_MOV, **common
    )
    assert len(list(png.path.glob("frame_*.png"))) == 3
    assert len(list(exr.path.glob("frame_*.exr"))) == 3
    assert list(mov.path.glob("*.mov"))
    png_manifest = json.loads((png.path / "manifest.json").read_text(encoding="utf-8"))
    assert png_manifest["format_id"] == "png_sequence"
    assert exr.path.name.endswith("demo_exr")
    loaded = load_rgba_png(next(png.path.glob("frame_*.png")))
    assert loaded.shape == (12, 16, 4)
