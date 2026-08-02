"""Phase 9D-2: false-color pipeline / cache / controller behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from color_pipeline_fixtures import (
    install_fake_oiio,
    make_decoder,
    make_exr_sequence,
)
from nova_layer.app.false_color import FalseColorMode
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import ProjectController
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader


def _png_sequence(tmp_path: Path) -> Path:
    seq = tmp_path / "png"
    seq.mkdir()
    rgb = np.full((8, 8, 3), 40, dtype=np.uint8)
    Image.fromarray(rgb, mode="RGB").save(seq / "frame_0001.png")
    Image.fromarray(rgb, mode="RGB").save(seq / "frame_0002.png")
    return seq


def test_cache_hit_and_preview_invalidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.0)
    cache = decoder.pipeline.false_color_cache
    a, _ = decoder.get_false_color_frame(
        seq, 0, mode=FalseColorMode.PREVIEW_LUMA, opacity=1.0
    )
    hits = cache.hits
    b, _ = decoder.get_false_color_frame(
        seq, 0, mode=FalseColorMode.PREVIEW_LUMA, opacity=1.0
    )
    assert cache.hits == hits + 1
    assert a is not None and b is not None
    assert np.array_equal(a, b)

    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.SOURCE_LUMA, opacity=1.0)
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.SCENE_EXPOSURE, opacity=1.0)
    assert len(cache) >= 3
    decoder.set_display_transform(make_decoder(exposure=1.0).pipeline.display_transform)
    # PREVIEW entries gone; SOURCE/SCENE remain
    remaining = {key[2] for key in cache._items}  # noqa: SLF001
    assert FalseColorMode.PREVIEW_LUMA.value not in remaining
    assert FalseColorMode.SOURCE_LUMA.value in remaining
    assert FalseColorMode.SCENE_EXPOSURE.value in remaining


def test_false_color_does_not_pollute_frame_cache_stats(
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
    before = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
    )
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.PREVIEW_LUMA)
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.SOURCE_LUMA)
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.SCENE_CLIPPING)
    # Re-hit false-color cache
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.PREVIEW_LUMA)
    after = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
    )
    for a, b in zip(before, after, strict=True):
        assert a.hits == b.hits
        assert a.misses == b.misses


def test_png_scene_unsupported(tmp_path: Path) -> None:
    seq = _png_sequence(tmp_path)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    rgb, warning = decoder.get_false_color_frame(
        seq, 0, mode=FalseColorMode.SCENE_EXPOSURE
    )
    assert rgb is None
    assert warning is not None


def test_exposure_changes_preview_not_source_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    zero = make_decoder(exposure=0.0)
    plus = make_decoder(exposure=2.0)
    p0, _ = zero.get_false_color_frame(seq, 0, mode=FalseColorMode.PREVIEW_LUMA)
    p1, _ = plus.get_false_color_frame(seq, 0, mode=FalseColorMode.PREVIEW_LUMA)
    s0, _ = zero.get_false_color_frame(seq, 0, mode=FalseColorMode.SOURCE_LUMA)
    s1, _ = plus.get_false_color_frame(seq, 0, mode=FalseColorMode.SOURCE_LUMA)
    c0, _ = zero.get_false_color_frame(seq, 0, mode=FalseColorMode.SCENE_EXPOSURE)
    c1, _ = plus.get_false_color_frame(seq, 0, mode=FalseColorMode.SCENE_EXPOSURE)
    assert p0 is not None and p1 is not None
    assert not np.array_equal(p0, p1)
    assert s0 is not None and s1 is not None
    assert np.array_equal(s0, s1)
    assert c0 is not None and c1 is not None
    assert np.array_equal(c0, c1)


def test_controller_no_media() -> None:
    controller = ProjectController()
    rgb, warning = controller.get_false_color_frame(mode=FalseColorMode.PREVIEW_LUMA)
    assert rgb is None
    assert warning == "No media"


def test_media_change_clears_false_color_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    decoder.get_false_color_frame(seq, 0, mode=FalseColorMode.SCENE_EXPOSURE)
    assert len(decoder.pipeline.false_color_cache) == 1
    decoder.reader = ImageSequenceReader()
    assert len(decoder.pipeline.false_color_cache) == 0
