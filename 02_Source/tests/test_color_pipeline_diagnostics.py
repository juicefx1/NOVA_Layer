"""Phase 9B: ColorPipelineDiagnostics model + controller snapshots."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.settings import ResolvedColorSettings
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.color_pipeline_diagnostics import (
    CacheDiagnostics,
    ColorSettingProvenance,
    build_color_pipeline_diagnostics,
    bytes_to_mib,
    format_color_pipeline_diagnostics,
    format_transform_identity,
    hit_rate,
)
from nova_layer.app.frame_cache_stats import FrameCacheStats
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.preview_pipeline import PreviewPipeline, TransformIdentity
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.render_color_metadata import (
    build_render_color_metadata,
    write_render_color_metadata,
)
from nova_layer.domain.models import ExtractionPreview, SmartLayerRender
from dataclasses import FrozenInstanceError


def _fake_oiio(monkeypatch: pytest.MonkeyPatch, counter: list[int]) -> None:
    class FakeSpec:
        height = 2
        width = 2
        nchannels = 3

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            counter.append(1)
            return np.full((2, 2, 3), 0.2, dtype=np.float32)

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


def _exr_seq(tmp_path: Path, frames: int = 2) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


def test_hit_rate_empty_is_none() -> None:
    assert hit_rate(0, 0) is None


def test_hit_rate_computation() -> None:
    assert hit_rate(5, 5) == pytest.approx(0.5)
    assert hit_rate(3, 1) == pytest.approx(0.75)


def test_bytes_to_mib() -> None:
    assert bytes_to_mib(0) == 0.0
    assert bytes_to_mib(1024 * 1024) == pytest.approx(1.0)


def test_empty_stats_diagnostics() -> None:
    snap = build_color_pipeline_diagnostics()
    assert snap.active_backend == "unknown"
    assert snap.raw_cache.count == 0
    assert snap.raw_hit_rate is None
    assert snap.raw_cache_mib == 0.0
    assert snap.last_render_color_policy is None
    assert snap.warnings == ()


def test_warnings_from_resolved_and_fallback() -> None:
    resolved = ResolvedColorSettings(
        backend="legacy",
        config_path=None,
        config_source=None,
        input_color_space="scene_linear",
        display=None,
        view=None,
        exposure=0.0,
        source_backend="default",
        source_config="none",
        source_input_color_space="default",
        source_display="none",
        source_view="none",
        source_exposure="default",
        warnings=("workspace preference ignored",),
    )
    transform = DisplayTransformDiagnostics(
        backend="legacy",
        ocio_available=False,
        config_path=None,
        config_source=None,
        display=None,
        view=None,
        input_color_space="scene_linear",
        exposure=0.0,
        fallback_reason="OCIO config missing",
    )
    snap = build_color_pipeline_diagnostics(
        resolved=resolved,
        transform_diagnostics=transform,
    )
    assert any("workspace preference ignored" in w for w in snap.warnings)
    assert any("OCIO config missing" in w for w in snap.warnings)
    assert snap.fallback_reason == "OCIO config missing"


def test_controller_snapshot_without_project(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    snap = controller.color_pipeline_diagnostics
    assert snap.active_backend == "legacy"
    assert snap.media_path is None
    assert snap.shot_name is None
    assert snap.last_render_color_policy is None
    text = format_color_pipeline_diagnostics(snap)
    assert "NOVA Layer Color Pipeline Diagnostics" in text
    assert "Backend: legacy" in text


def test_controller_legacy_and_media_path(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Diag", root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    snap = controller.color_pipeline_diagnostics
    assert snap.active_backend == "legacy"
    assert snap.media_path is not None
    assert shot.media.source_path in snap.media_path
    assert snap.shot_name == shot.name


def test_controller_fallback_diagnostics(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    diag = DisplayTransformDiagnostics(
        backend="legacy",
        ocio_available=True,
        config_path="/missing.ocio",
        config_source="absolute",
        display="sRGB",
        view="A",
        input_color_space="scene_linear",
        exposure=1.0,
        fallback_reason="Could not load OCIO config",
    )
    controller.set_display_transform(LegacyDisplayTransform(diagnostics=diag))
    snap = controller.color_pipeline_diagnostics
    assert snap.fallback_reason == "Could not load OCIO config"
    assert any("Could not load OCIO config" in w for w in snap.warnings)
    assert snap.exposure == pytest.approx(1.0)


def test_last_render_policy_memory_and_sidecar(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    from PIL import Image

    from nova_layer.domain.models import ArtistIntent, SmartLayer

    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("RenderDiag", root) is not None
    seq = tmp_path / "png"
    seq.mkdir()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(seq / "frame_0001.png")
    shot = controller.import_media(seq)
    assert shot is not None
    package = controller.package_path
    assert package is not None
    render_dir = package / "renders" / "v0001"
    render_dir.mkdir(parents=True)
    write_render_color_metadata(
        render_dir,
        build_render_color_metadata(ProcessingColorPolicy.SOURCE),
    )
    intent = ArtistIntent(master_frame=0)
    layer = SmartLayer(
        artist_intent=intent,
        renders=[
            SmartLayerRender(
                version=1,
                frame_start=0,
                frame_end=0,
                frames=[
                    ExtractionPreview(
                        frame_number=0,
                        image_reference="renders/v0001/frame_000000.png",
                        mask_reference="masks/x.png",
                    )
                ],
            )
        ],
        render_version_counter=1,
    )
    shot.smart_layers.append(layer)
    assert controller.last_render_color_policy is None
    snap = controller.color_pipeline_diagnostics
    assert snap.last_render_color_policy == "source"

    controller._last_render_color_policy = "preview"
    assert controller.color_pipeline_diagnostics.last_render_color_policy == "preview"


def test_decoder_diagnostics_cache_and_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    decoder = FrameDecodeService(
        ImageSequenceReader(),
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    decoder.get_processing_frame(seq, 0, policy=ProcessingColorPolicy.SOURCE)
    before = decoder.color_pipeline_diagnostics
    assert before.raw_cache.count >= 1
    assert before.preview_cache.count >= 1
    assert before.source_cache.count >= 1
    assert before.raw_decode_count >= 1
    assert before.preview_generation_count >= 1
    raw_count = before.raw_cache.count
    source_count = before.source_cache.count
    raw_decodes = before.raw_decode_count

    decoder.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    after_clear = decoder.color_pipeline_diagnostics
    assert after_clear.preview_cache.count == 0
    assert after_clear.preview_cache.current_bytes == 0
    assert after_clear.raw_cache.count == raw_count
    assert after_clear.source_cache.count == source_count

    decoder.get_preview_frame(seq, 0, schedule_prefetch=False)
    after = decoder.color_pipeline_diagnostics
    assert after.raw_decode_count == raw_decodes
    assert after.preview_generation_count > before.preview_generation_count
    assert len(counter) == 1


def test_pipeline_property_matches_decoder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    pipeline.read_frame(seq, 0)
    snap = build_color_pipeline_diagnostics(pipeline=pipeline)
    assert isinstance(snap.raw_cache, FrameCacheStats)
    assert snap.preview_hit_rate is None or snap.preview_hit_rate >= 0.0
    via_api = pipeline.diagnostics_snapshot()
    assert via_api.raw_cache.count == snap.raw_cache.count
    assert via_api.transform_identity == snap.transform_identity


def test_cache_diagnostics_hit_rate_property() -> None:
    empty = CacheDiagnostics.from_stats(
        "raw",
        FrameCacheStats(0, 0, 1, 1, 0, 0, 0, 0, 0),
    )
    assert empty.hit_rate is None
    filled = CacheDiagnostics.from_stats(
        "preview",
        FrameCacheStats(1, 12, 100, 8, 3, 1, 0, 0, 0),
    )
    assert filled.hit_rate == pytest.approx(0.75)
    assert filled.current_mib == pytest.approx(12 / (1024 * 1024))


def test_policy_defaults_and_source_version_constant() -> None:
    snap = build_color_pipeline_diagnostics()
    assert snap.processing_default_policy == ProcessingColorPolicy.SOURCE.value
    assert snap.render_default_policy == ProcessingColorPolicy.PREVIEW.value
    assert snap.source_transform_version == SOURCE_TRANSFORM_VERSION
    assert snap.source_transform_version == "source_legacy_srgb_v1"
    assert snap.active_frame is None
    assert isinstance(snap.provenance, ColorSettingProvenance)
    assert snap.provenance.backend == "none"


def test_provenance_from_resolved() -> None:
    resolved = ResolvedColorSettings(
        backend="ocio",
        config_path="/tmp/a.ocio",
        config_source="explicit",
        input_color_space="ACEScg",
        display="sRGB",
        view="ACES 1.0",
        exposure=0.5,
        source_backend="project",
        source_config="workspace",
        source_input_color_space="session",
        source_display="project",
        source_view="default",
        source_exposure="environment",
        warnings=("note",),
    )
    snap = build_color_pipeline_diagnostics(resolved=resolved)
    assert snap.provenance.backend == "project"
    assert snap.provenance.config == "workspace"
    assert snap.provenance.input_color_space == "session"
    assert snap.resolve_warnings == ("note",)


def test_transform_identity_stable_and_display_safe() -> None:
    identity = TransformIdentity(
        backend="ocio",
        config_path=str(Path.home() / "configs" / "studio.ocio"),
        config_source="explicit",
        input_color_space="ACEScg",
        display="sRGB",
        view="ACES 1.0",
        exposure=0.0,
    )
    full = format_transform_identity(identity)
    safe = format_transform_identity(identity, display_safe=True)
    assert full.startswith("backend=ocio|config=")
    assert "|input=ACEScg|" in full
    assert full.endswith("|exposure=0") or "|exposure=0|" in full or full.endswith("|exposure=0.0")
    assert "~/" in safe or safe.startswith("backend=ocio|config=~")
    assert Path.home().as_posix() not in safe.replace("\\", "/")
    snap = build_color_pipeline_diagnostics(transform_identity=identity)
    assert snap.transform_identity == full
    assert snap.transform_identity_display == safe


def test_snapshot_does_not_mutate_cache_hits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    pipeline = PreviewPipeline(
        ImageSequenceReader(),
        LegacyDisplayTransform(),
    )
    pipeline.read_frame(seq, 0)
    before = pipeline.raw_cache_stats
    # Warm path so peek can find frame 0 tags.
    _ = build_color_pipeline_diagnostics(
        pipeline=pipeline,
        media_path=seq,
    )
    mid = pipeline.raw_cache_stats
    assert mid.hits == before.hits
    assert mid.misses == before.misses
    snap2 = pipeline.diagnostics_snapshot()
    after = pipeline.raw_cache_stats
    assert after.hits == before.hits
    assert after.misses == before.misses
    assert snap2.raw_cache.hits == before.hits


def test_snapshot_immutable() -> None:
    snap = build_color_pipeline_diagnostics()
    with pytest.raises(FrozenInstanceError):
        snap.active_backend = "hacked"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snap.provenance.backend = "x"  # type: ignore[misc]


def test_controller_active_frame_and_format(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("FrameDiag", root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    controller.request_frame(1)
    snap = controller.color_pipeline_diagnostics
    assert snap.active_frame == 1
    assert snap.processing_default_policy == "source"
    assert snap.render_default_policy == "preview"
    text = format_color_pipeline_diagnostics(snap)
    assert "Processing default: source" in text
    assert "Render default: preview" in text
    assert "SOURCE transform version:" in text
    assert "Active frame: 1" in text
    assert "Provenance:" in text


def test_format_helper_empty_state() -> None:
    text = format_color_pipeline_diagnostics(build_color_pipeline_diagnostics())
    assert "NOVA Layer Color Pipeline Diagnostics" in text
    assert "Active frame: —" in text
    assert "Raw Cache:" in text
