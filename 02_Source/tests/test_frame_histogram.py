"""Phase 9D-1: frame histogram policy / analysis cache / frame-cache hygiene."""

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
from nova_layer.app.histogram_analysis import (
    HistogramAnalysisCache,
    build_histogram_cache_key,
    get_frame_histogram_for_decoder,
    histogram_cache_identity,
)
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.frame_decode_service import FrameDecodeService


def _png_sequence(tmp_path: Path) -> Path:
    seq = tmp_path / "png"
    seq.mkdir()
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    rgb[:, :] = (12, 34, 56)
    Image.fromarray(rgb, mode="RGB").save(seq / "frame_0001.png")
    Image.fromarray(rgb, mode="RGB").save(seq / "frame_0002.png")
    return seq


def test_preview_exposure_changes_histogram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    zero = make_decoder(exposure=0.0)
    plus = make_decoder(exposure=1.0)
    a = zero.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    b = plus.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    assert a.red.mean != b.red.mean


def test_source_and_scene_invariant_to_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    zero = make_decoder(exposure=0.0)
    plus = make_decoder(exposure=2.0)
    s0 = zero.get_frame_histogram(seq, 0, ProcessingColorPolicy.SOURCE)
    s1 = plus.get_frame_histogram(seq, 0, ProcessingColorPolicy.SOURCE)
    c0 = zero.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    c1 = plus.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    assert s0.red.bins.tolist() == s1.red.bins.tolist()
    assert c0.red.bins.tolist() == c1.red.bins.tolist()
    assert c0.red.mean == pytest.approx(c1.red.mean)


def test_cache_keys_separated_by_policy() -> None:
    path = Path("/tmp/media")
    preview = build_histogram_cache_key(
        path, 0, ProcessingColorPolicy.PREVIEW, identity="exp0"
    )
    source = build_histogram_cache_key(
        path, 0, ProcessingColorPolicy.SOURCE, identity=SOURCE_TRANSFORM_VERSION
    )
    scene = build_histogram_cache_key(
        path, 0, ProcessingColorPolicy.SCENE, identity="scene_raw"
    )
    assert len({preview, source, scene}) == 3
    assert histogram_cache_identity(ProcessingColorPolicy.SOURCE) == SOURCE_TRANSFORM_VERSION
    assert histogram_cache_identity(ProcessingColorPolicy.SCENE) == "scene_raw"


def test_analysis_cache_hit_skips_recompute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    cache = decoder.pipeline.histogram_cache
    first = decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    hits_before = cache.hits
    second = decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    assert cache.hits == hits_before + 1
    assert first.red.mean == second.red.mean


def test_histogram_peek_does_not_mutate_frame_cache_stats(
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
    # Warm analysis once then hit
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SOURCE)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    after_warm = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
    )
    # Analysis cache hits — no further frame cache traffic
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SOURCE)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    after = (
        pipeline.preview_cache_stats,
        pipeline.source_cache_stats,
        pipeline.raw_cache_stats,
    )
    for a, b in zip(after_warm, after, strict=True):
        assert a.hits == b.hits
        assert a.misses == b.misses
    # Warming used peeks; compare to before warm — peeks must not bump hits
    for a, b in zip(before, after_warm, strict=True):
        assert a.hits == b.hits
        assert a.misses == b.misses


def test_transform_invalidates_preview_histogram_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.0)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.PREVIEW)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SOURCE)
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    assert len(decoder.pipeline.histogram_cache) == 3
    decoder.set_display_transform(make_decoder(exposure=1.0).pipeline.display_transform)
    # PREVIEW dropped; SOURCE/SCENE remain
    assert len(decoder.pipeline.histogram_cache) == 2


def test_media_change_clears_histogram_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder()
    decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    assert len(decoder.pipeline.histogram_cache) == 1
    decoder.reader = ImageSequenceReader()
    assert len(decoder.pipeline.histogram_cache) == 0


def test_png_scene_unsupported(tmp_path: Path) -> None:
    seq = _png_sequence(tmp_path)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    result = decoder.get_frame_histogram(seq, 0, ProcessingColorPolicy.SCENE)
    assert result.sample_count == 0
    assert result.warning is not None


def test_controller_active_shot_histogram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    controller = ProjectController()
    assert controller.get_frame_histogram(policy=ProcessingColorPolicy.PREVIEW) is None
    controller._frame_decoder = make_decoder()
    seq = make_exr_sequence(tmp_path)
    # No active shot → None
    assert controller.get_frame_histogram(policy=ProcessingColorPolicy.PREVIEW) is None
    # Direct decoder path for coverage
    hist = get_frame_histogram_for_decoder(
        controller._frame_decoder,
        seq,
        0,
        ProcessingColorPolicy.PREVIEW,
    )
    assert hist.sample_count > 0


def test_histogram_analysis_cache_lru_eviction() -> None:
    cache = HistogramAnalysisCache(max_entries=2)
    from nova_layer.app.histogram_analysis import empty_frame_histogram

    a = empty_frame_histogram(policy="preview", warning="a")
    b = empty_frame_histogram(policy="source", warning="b")
    c = empty_frame_histogram(policy="scene", warning="c")
    cache.put(("p", 0, "preview", "i", 256, 0.0, 4.0), a)
    cache.put(("p", 0, "source", "i", 256, 0.0, 4.0), b)
    cache.put(("p", 0, "scene", "i", 256, 0.0, 4.0), c)
    assert len(cache) == 2
