"""Phase 9A: Golden regression for color pipeline contracts and caches."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from color_pipeline_fixtures import (
    GOLDEN_MASK,
    GOLDEN_SCENE_RGB,
    install_fake_oiio,
    make_decoder,
    make_exr_sequence,
    make_pipeline,
    make_viewer_transform,
)
from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.app.preview_extraction import compose_rgba
from nova_layer.app.preview_pipeline import PreviewFrameCache, TransformIdentity
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.range_decode import decode_frame_range
from nova_layer.app.raw_frame_cache import RawFrameCache
from nova_layer.app.render_color_metadata import (
    build_render_color_metadata,
    validate_render_color_policy,
    write_render_color_metadata,
)
from nova_layer.domain.models import ExtractionPreview, SmartLayerRender
from nova_layer.export.smart_layer import (
    ExportFormat,
    export_smart_layer_assets,
    load_rgba_png,
)
from nova_layer.ports.media import MediaReadError
from nova_layer.ports.scene_frames import SceneFrame



# ---------------------------------------------------------------------------
# Document / constant lock
# ---------------------------------------------------------------------------


def test_source_transform_version_locked() -> None:
    assert SOURCE_TRANSFORM_VERSION == "source_legacy_srgb_v1"


def test_color_pipeline_doc_mentions_source_transform_version() -> None:
    doc_path: Path | None = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "00_Project" / "01_Implementation" / "COLOR_PIPELINE.md"
        if candidate.is_file():
            doc_path = candidate
            break
    assert doc_path is not None, "COLOR_PIPELINE.md not found"
    text = doc_path.read_text(encoding="utf-8")
    assert SOURCE_TRANSFORM_VERSION in text
    assert "scene_linear=false" in text
    assert "premultiplied=false" in text
    assert "straight alpha" in text.lower() or 'alpha_mode`="straight"' in text or "straight" in text



def test_source_metadata_version_matches_constant() -> None:
    meta = build_render_color_metadata(ProcessingColorPolicy.SOURCE)
    assert meta["source_transform_version"] == SOURCE_TRANSFORM_VERSION
    assert meta["color_policy"] == "source"


# ---------------------------------------------------------------------------
# PREVIEW / SOURCE / SCENE golden pixels
# ---------------------------------------------------------------------------


def test_preview_exposure_changes_rgb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    zero = make_decoder(exposure=0.0)
    plus = make_decoder(exposure=1.0)
    a = zero.get_preview_frame(seq, 0, schedule_prefetch=False)
    b = plus.get_preview_frame(seq, 0, schedule_prefetch=False)
    assert a.dtype == np.uint8
    assert not np.array_equal(a, b)


def test_preview_same_transform_bit_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.5)
    a = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    b = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    np.testing.assert_array_equal(a, b)
    assert decoder.preview_cache_stats.hits >= 1


def test_preview_transform_change_misses_preview_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    pipeline = make_pipeline(exposure=0.0)
    pipeline.read_frame(seq, 0)
    assert pipeline.preview_cache_stats.count == 1
    before_raw = pipeline.raw_cache_stats.count
    before_source = pipeline.source_cache_stats.count
    before_decodes = pipeline.pipeline_stats.raw_decodes
    pipeline.set_display_transform(make_viewer_transform(exposure=1.0))
    assert pipeline.preview_cache_stats.count == 0
    assert pipeline.preview_cache_stats.current_bytes == 0
    assert pipeline.raw_cache_stats.count == before_raw
    assert pipeline.source_cache_stats.count == before_source
    pipeline.read_frame(seq, 0)
    assert pipeline.pipeline_stats.raw_decodes == before_decodes
    assert len(counter) == 1
    assert pipeline.pipeline_stats.preview_generations >= 2


def test_source_stable_across_exposure_and_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    pipeline = make_pipeline(exposure=0.0)
    source_a = pipeline.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source_a, np.ndarray)

    class Tagged(LegacyDisplayTransform):
        def __init__(self, tag: str) -> None:
            super().__init__()
            self.diagnostics = DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=None,
                config_source=None,
                display=tag,
                view=f"{tag}_view",
                input_color_space="scene_linear",
                exposure=0.0,
            )

    pipeline.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=Tagged("B"),
        )
    )
    source_b = pipeline.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source_b, np.ndarray)
    np.testing.assert_array_equal(source_a, source_b)
    assert pipeline.source_cache_stats.hits >= 1
    assert len(counter) == 1


def test_scene_raw_independent_of_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    pipeline = make_pipeline(exposure=0.0)
    scene_a = pipeline.get_scene_frame(seq, 0)
    np.testing.assert_allclose(scene_a.pixels[..., :3], GOLDEN_SCENE_RGB, rtol=0, atol=0)
    # Mutate viewer look and regenerate previews/source; raw must stay identical.
    pipeline.read_frame(seq, 0)
    pipeline.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    pipeline.set_display_transform(make_viewer_transform(exposure=2.0))
    scene_b = pipeline.get_scene_frame(seq, 0)
    np.testing.assert_array_equal(scene_a.pixels, scene_b.pixels)
    cached = pipeline.raw_cache.get(seq.resolve(), 0)
    assert cached is not None
    np.testing.assert_array_equal(cached.pixels, scene_a.pixels)


def test_preview_and_source_caches_do_not_pollute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    pipeline = make_pipeline(exposure=0.0)
    preview = pipeline.read_frame(seq, 0)
    source = pipeline.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source, np.ndarray)
    # Policies may produce different uint8 on EXR when exposure≠0 or bake differs;
    # isolation is about cache populations, not pixel equality.
    assert pipeline.preview_cache_stats.count >= 1
    assert pipeline.source_cache_stats.count >= 1
    raw_count = pipeline.raw_cache_stats.count
    source_count = pipeline.source_cache_stats.count
    source_bytes = pipeline.source_cache_stats.current_bytes
    pipeline.set_display_transform(make_viewer_transform(exposure=1.5))
    assert pipeline.preview_cache_stats.count == 0
    assert pipeline.preview_cache_stats.current_bytes == 0
    assert pipeline.raw_cache_stats.count == raw_count
    assert pipeline.source_cache_stats.count == source_count
    assert pipeline.source_cache_stats.current_bytes == source_bytes
    # Preview regenerate must not clear source.
    pipeline.read_frame(seq, 0)
    assert pipeline.source_cache_stats.count == source_count
    del preview


# ---------------------------------------------------------------------------
# Cache stats (end-to-end; detailed oversized left to Phase 8B unit tests)
# ---------------------------------------------------------------------------


def test_cache_stats_exposure_change_increments_preview_not_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path, frames=1)
    pipeline = make_pipeline(exposure=0.0)
    pipeline.read_frame(seq, 0)
    assert pipeline.raw_cache_stats.hits + pipeline.raw_cache_stats.misses >= 1
    raw_decodes = pipeline.pipeline_stats.raw_decodes
    gens = pipeline.pipeline_stats.preview_generations
    pipeline.set_display_transform(make_viewer_transform(exposure=1.0))
    pipeline.read_frame(seq, 0)
    assert pipeline.pipeline_stats.raw_decodes == raw_decodes
    assert pipeline.pipeline_stats.preview_generations == gens + 1
    assert len(counter) == 1


def test_raw_oversized_policy_still_admits_foreground() -> None:
    """Smoke: oversized foreground admission remains (Phase 8B contract)."""
    cache = RawFrameCache(max_entries=2, max_bytes=64)
    path = Path("/synthetic/seq")
    frame = SceneFrame(
        path=path,
        frame_number=0,
        pixels=np.zeros((8, 8, 3), dtype=np.float32),
        width=8,
        height=8,
    )
    assert frame.pixels.nbytes > 64
    assert cache.put(frame, allow_eviction=True) is True
    assert cache.stats().oversized_admissions == 1
    assert cache.current_bytes == frame.pixels.nbytes


def test_preview_byte_accounting_after_clear() -> None:
    cache = PreviewFrameCache(max_entries=4, max_bytes=10_000)
    key = (
        Path("/x"),
        0,
        TransformIdentity(
            backend="legacy",
            config_path=None,
            config_source=None,
            input_color_space="scene_linear",
            display=None,
            view=None,
            exposure=0.0,
        ),
    )
    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    assert cache.put(key, rgb) is True
    assert cache.stats().current_bytes == rgb.nbytes
    cache.clear()
    assert cache.stats().count == 0
    assert cache.stats().current_bytes == 0


# ---------------------------------------------------------------------------
# Processing golden
# ---------------------------------------------------------------------------


def test_sam_input_stable_across_exposure(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path, frames=3)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Golden SAM", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    media = Path(shot.media.source_path)
    frame0 = controller._get_source_processing_frame(media, 0)
    controller.set_display_transform(make_viewer_transform(exposure=2.0))
    frame1 = controller._get_source_processing_frame(media, 0)
    np.testing.assert_array_equal(frame0, frame1)

    controller.set_display_transform(make_viewer_transform(exposure=0.0))
    preview_lo = controller._frame_decoder.get_preview_frame(
        media, 0, schedule_prefetch=False
    )
    controller.set_display_transform(make_viewer_transform(exposure=2.0))
    preview_hi = controller._frame_decoder.get_preview_frame(
        media, 0, schedule_prefetch=False
    )
    assert not np.array_equal(preview_lo, preview_hi)


def test_propagation_range_source_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path, frames=3)
    decoder = make_decoder(exposure=0.0)
    reader = decoder.reader
    first, _ = decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    decoder.set_display_transform(make_viewer_transform(exposure=1.5))
    second, stats = decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    for frame_number in range(3):
        np.testing.assert_array_equal(first[frame_number], second[frame_number])
    assert stats.cache_hits == 3
    assert decoder.preview_cache_stats.count == 0


def test_preview_validation_may_change_with_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.0)
    a = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    decoder.set_display_transform(make_viewer_transform(exposure=1.0))
    b = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    assert not np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Render / export golden
# ---------------------------------------------------------------------------


def test_preview_vs_source_compose_rgba_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_oiio(monkeypatch)
    seq = make_exr_sequence(tmp_path)
    decoder = make_decoder(exposure=0.0)
    preview = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    source = decoder.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source, np.ndarray)
    rgba_preview = compose_rgba(preview, GOLDEN_MASK)
    rgba_source = compose_rgba(source, GOLDEN_MASK)
    np.testing.assert_array_equal(rgba_preview[..., 3], GOLDEN_MASK)
    np.testing.assert_array_equal(rgba_source[..., 3], GOLDEN_MASK)
    # A=0 pixels keep RGB
    zero = GOLDEN_MASK == 0
    np.testing.assert_array_equal(rgba_preview[zero, :3], preview[zero])

    decoder.set_display_transform(make_viewer_transform(exposure=1.0))
    preview2 = decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    source2 = decoder.get_processing_frame(
        seq, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert isinstance(source2, np.ndarray)
    assert not np.array_equal(preview, preview2)
    np.testing.assert_array_equal(source, source2)
    np.testing.assert_array_equal(
        compose_rgba(source2, GOLDEN_MASK)[..., 3], GOLDEN_MASK
    )


def test_export_preserves_png_pixels_and_metadata(tmp_path: Path) -> None:
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., :3] = (11, 22, 33)
    rgba[..., 3] = GOLDEN_MASK
    reference = "renders/v0009/frame_000000.png"
    store.save(package, reference, rgba)
    render = SmartLayerRender(
        version=9,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference=reference,
                mask_reference="masks/m.png",
            )
        ],
        checksums={reference: "x"},
    )
    write_render_color_metadata(
        package / "renders" / "v0009",
        build_render_color_metadata(ProcessingColorPolicy.SOURCE),
    )
    destination = tmp_path / "out"
    destination.mkdir()
    # Guard: export must not touch media readers — no fake OIIO needed.
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="golden_export",
        render=render,
        format=ExportFormat.PNG_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    exported = result.path / "frame_000000.png"
    assert exported.is_file()
    np.testing.assert_array_equal(load_rgba_png(exported), rgba)
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["color_policy"]["color_policy"] == "source"
    assert manifest["color_policy"]["source_transform_version"] == SOURCE_TRANSFORM_VERSION
    assert manifest["alpha_mode"] == "straight"
    assert manifest["premultiplied"] is False
    assert manifest["scene_linear"] is False


def test_scene_rejected_for_range_and_render_validation() -> None:
    with pytest.raises(MediaReadError):
        validate_render_color_policy(ProcessingColorPolicy.SCENE)


# ---------------------------------------------------------------------------
# Static policy guards (lightweight AST / source checks)
# ---------------------------------------------------------------------------


def test_static_processing_paths_use_source() -> None:
    source = inspect.getsource(ProjectController)
    tree = ast.parse(source)
    class_body = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProjectController"
    )
    targets = {
        "_predict_hypothesis",
        "apply_frame_correction",
        "start_skeleton_retracking",
        "start_skeleton_fusion_detection",
        "_decode_shot_frames",
    }
    for item in class_body.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if item.name not in targets:
            continue
        text = ast.get_source_segment(source, item) or ""
        if item.name == "_decode_shot_frames":
            assert "ProcessingColorPolicy.SOURCE" in text
            continue
        if item.name in {"_predict_hypothesis", "apply_frame_correction"}:
            assert "_get_sam_processing_frame" in text, item.name
            continue
        assert "_get_source_processing_frame" in text or (
            "ProcessingColorPolicy.SOURCE" in text
        ), item.name


def test_static_preview_paths_use_get_preview_frame() -> None:
    text_bg = inspect.getsource(ProjectController.start_background_removal_preview)
    assert "get_preview_frame" in text_bg
    assert "color_policy" not in text_bg
    text_val = inspect.getsource(ProjectController.validation_previews)
    assert "get_preview_frame" in text_val


def test_static_render_defaults_preview() -> None:
    for name in ("start_smart_layer_render", "start_background_removal_clip"):
        text = inspect.getsource(getattr(ProjectController, name))
        assert "ProcessingColorPolicy.PREVIEW" in text
        assert "color_policy" in text
        assert "ProcessingColorPolicy.SCENE" not in text or "validate" in text.lower()


def test_static_export_does_not_decode_policy() -> None:
    text = inspect.getsource(export_smart_layer_assets)
    assert "decode_frame_range" not in text
    assert "get_preview_frame" not in text
    assert "get_processing_frame" not in text
    assert "color_policy" in text
