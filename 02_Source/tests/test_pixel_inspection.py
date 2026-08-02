"""Phase 9C-1: pixel inspection sampling and cache peek behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from color_pipeline_fixtures import (
    GOLDEN_SCENE_RGB,
    install_fake_oiio,
    make_decoder,
    make_exr_sequence,
)
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.pixel_inspection import format_sample_component, inspect_pixel
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader


def _make_png_sequence(tmp_path: Path) -> Path:
    seq = tmp_path / "png_seq"
    seq.mkdir()
    for index in range(1, 3):
        rgb = np.zeros((8, 10, 3), dtype=np.uint8)
        rgb[:, :] = (10 * index, 20 * index, 30 * index)
        rgb[3, 4] = (11, 22, 33)
        Image.fromarray(rgb, mode="RGB").save(seq / f"frame_{index:04d}.png")
    return seq


def test_preview_source_scene_samples_accurate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.0)
    x, y = 1, 1
    inspection = decoder.inspect_pixel(seq, 0, x, y)
    assert inspection.preview is not None
    assert inspection.source is not None
    assert inspection.scene is not None
    assert inspection.preview.dtype.startswith("uint8")
    assert inspection.source.dtype.startswith("uint8")
    assert inspection.scene.dtype.startswith("float32")
    expected_scene = GOLDEN_SCENE_RGB[y, x]
    np.testing.assert_allclose(inspection.scene.rgb, expected_scene, rtol=0, atol=1e-5)
    preview_frame = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    source_frame = decoder.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source_frame, np.ndarray)
    assert inspection.preview.rgb == (
        float(preview_frame[y, x, 0]),
        float(preview_frame[y, x, 1]),
        float(preview_frame[y, x, 2]),
    )
    assert inspection.source.rgb == (
        float(source_frame[y, x, 0]),
        float(source_frame[y, x, 1]),
        float(source_frame[y, x, 2]),
    )
    assert format_sample_component(inspection.scene.rgb[0], policy="scene") == (
        f"{expected_scene[0]:.4f}"
    )


def test_invalid_coordinate_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    inspection = decoder.inspect_pixel(seq, 0, -1, 0)
    assert inspection.preview is None
    assert inspection.source is None
    assert inspection.scene is None
    assert inspection.warning == "Invalid coordinates"
    outside = decoder.inspect_pixel(seq, 0, 99, 99)
    assert outside.preview is None
    assert outside.warning == "Outside image"


def test_png_scene_unsupported(tmp_path: Path) -> None:
    seq = _make_png_sequence(tmp_path)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    inspection = decoder.inspect_pixel(seq, 0, 4, 3)
    assert inspection.preview is not None
    assert inspection.source is not None
    assert inspection.scene is None
    assert inspection.warning is not None
    assert "SCENE" in inspection.warning.upper() or "EXR" in inspection.warning.upper()
    assert inspection.preview.rgb == (11.0, 22.0, 33.0)


def test_exr_shared_decode_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    decoder.inspect_pixel(seq, 0, 0, 0)
    assert len(calls) == 1


def test_exposure_changes_preview_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    zero = make_decoder(exposure=0.0)
    plus = make_decoder(exposure=1.0)
    a = zero.inspect_pixel(seq, 0, 1, 1)
    b = plus.inspect_pixel(seq, 0, 1, 1)
    assert a.preview is not None and b.preview is not None
    assert a.source is not None and b.source is not None
    assert a.scene is not None and b.scene is not None
    assert a.preview.rgb != b.preview.rgb
    assert a.source.rgb == b.source.rgb
    assert a.scene.rgb == b.scene.rgb


def test_cached_inspect_does_not_increase_decode_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    decoder.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    decoder.get_scene_frame(seq, 0)
    assert len(calls) == 1
    before = len(calls)
    inspection = decoder.inspect_pixel(seq, 0, 2, 2)
    assert inspection.preview is not None
    assert len(calls) == before


def test_peek_sampling_does_not_mutate_cache_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    decoder.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    decoder.get_scene_frame(seq, 0)
    pipeline = decoder.pipeline
    preview_before = pipeline.preview_cache_stats
    source_before = pipeline.source_cache_stats
    raw_before = pipeline.raw_cache_stats
    peeked = inspect_pixel(decoder, seq, 0, 1, 1, allow_decode=False)
    assert peeked.preview is not None
    assert peeked.source is not None
    assert peeked.scene is not None
    preview_after = pipeline.preview_cache_stats
    source_after = pipeline.source_cache_stats
    raw_after = pipeline.raw_cache_stats
    assert preview_after.hits == preview_before.hits
    assert preview_after.misses == preview_before.misses
    assert source_after.hits == source_before.hits
    assert source_after.misses == source_before.misses
    assert raw_after.hits == raw_before.hits
    assert raw_after.misses == raw_before.misses


def test_format_nan_inf() -> None:
    assert format_sample_component(float("nan"), policy="scene") == "NaN"
    assert format_sample_component(float("inf"), policy="scene") == "+Inf"
    assert format_sample_component(float("-inf"), policy="scene") == "-Inf"
    assert format_sample_component(128.4, policy="preview") == "128"


def test_controller_inspect_pixel_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nova_layer.app.project_controller import ProjectController

    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    controller = ProjectController()
    controller._frame_decoder = make_decoder()
    inspection = controller.inspect_pixel(seq, 0, 0, 0)
    assert inspection.scene is not None
