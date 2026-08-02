"""Phase 8D: Smart Layer / BG render color_policy + export metadata."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.preview_extraction import compose_rgba
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.range_decode import decode_frame_range
from nova_layer.app.render_color_metadata import (
    RENDER_COLOR_POLICY_FILENAME,
    build_render_color_metadata,
    load_render_color_metadata,
    validate_render_color_policy,
    write_render_color_metadata,
)
from nova_layer.domain.models import ExtractionPreview, SmartLayerRender
from nova_layer.export.smart_layer import ExportFormat, export_smart_layer_assets
from nova_layer.ports.media import MediaReadError


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


def test_scene_policy_rejected() -> None:
    with pytest.raises(MediaReadError, match="SCENE"):
        validate_render_color_policy(ProcessingColorPolicy.SCENE)


def test_compose_rgba_straight_preserves_rgb_under_zero_alpha() -> None:
    frame = np.full((2, 2, 3), (10, 20, 30), dtype=np.uint8)
    mask = np.zeros((2, 2), dtype=np.uint8)
    rgba = compose_rgba(frame, mask)
    assert rgba.dtype == np.uint8
    assert rgba.shape == (2, 2, 4)
    np.testing.assert_array_equal(rgba[..., :3], frame)
    np.testing.assert_array_equal(rgba[..., 3], mask)


def test_source_metadata_shape() -> None:
    meta = build_render_color_metadata(ProcessingColorPolicy.SOURCE)
    assert meta["color_policy"] == "source"
    assert meta["source_transform_version"] == SOURCE_TRANSFORM_VERSION
    assert meta["display"] is None
    assert meta["view"] is None
    assert meta["exposure"] is None
    assert meta["alpha_mode"] == "straight"
    assert meta["premultiplied"] is False
    assert meta["scene_linear"] is False


def test_preview_metadata_records_exposure() -> None:
    transform = ViewerDisplayTransform(
        exposure=ExposureTransform(1.5),
        display_transform=LegacyDisplayTransform(),
    )
    meta = build_render_color_metadata(
        ProcessingColorPolicy.PREVIEW,
        display_transform=transform,
    )
    assert meta["color_policy"] == "preview"
    assert meta["exposure"] == pytest.approx(1.5)
    assert meta["source_transform_version"] is None
    assert meta["color_backend"] == "legacy"


def test_source_range_does_not_pollute_preview_for_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(
        reader,
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(1.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    before = decoder.preview_cache_stats.count
    decode_frame_range(
        decoder, reader, seq, 0, 1, policy=ProcessingColorPolicy.SOURCE
    )
    assert decoder.preview_cache_stats.count == before
    assert len(counter) == 2
    decode_frame_range(
        decoder, reader, seq, 0, 1, policy=ProcessingColorPolicy.SOURCE
    )
    assert len(counter) == 2


def test_source_rgb_stable_across_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(
        reader,
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    first, _ = decode_frame_range(
        decoder, reader, seq, 0, 0, policy=ProcessingColorPolicy.SOURCE
    )
    mask = np.full((2, 2), 200, dtype=np.uint8)
    rgba_a = compose_rgba(first[0], mask)
    decoder.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    second, stats = decode_frame_range(
        decoder, reader, seq, 0, 0, policy=ProcessingColorPolicy.SOURCE
    )
    assert stats.cache_hits == 1
    rgba_b = compose_rgba(second[0], mask)
    np.testing.assert_array_equal(rgba_a[..., :3], rgba_b[..., :3])
    np.testing.assert_array_equal(rgba_a[..., 3], rgba_b[..., 3])
    assert len(counter) == 1


def test_preview_rgb_changes_with_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(
        reader,
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    a, _ = decode_frame_range(
        decoder, reader, seq, 0, 0, policy=ProcessingColorPolicy.PREVIEW
    )
    decoder.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    b, _ = decode_frame_range(
        decoder, reader, seq, 0, 0, policy=ProcessingColorPolicy.PREVIEW
    )
    assert not np.array_equal(a[0], b[0])
    assert len(counter) == 1


def _source_render_package(tmp_path: Path) -> tuple[Path, SmartLayerRender]:
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    frames: list[ExtractionPreview] = []
    checksums: dict[str, str] = {}
    for index in range(2):
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        rgba[..., :3] = (30, 60, 90)
        rgba[..., 3] = 180
        reference = f"renders/v0001/frame_{index:06d}.png"
        store.save(package, reference, rgba)
        frames.append(
            ExtractionPreview(
                frame_number=index,
                image_reference=reference,
                mask_reference=f"masks/frame_{index:06d}.png",
            )
        )
        checksums[reference] = "x"
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=1,
        frames=frames,
        checksums=checksums,
    )
    write_render_color_metadata(
        package / "renders" / "v0001",
        build_render_color_metadata(ProcessingColorPolicy.SOURCE),
    )
    return package, render


def test_export_manifest_preserves_sidecar_color_policy(tmp_path: Path) -> None:
    package, render = _source_render_package(tmp_path)
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="demo_png",
        render=render,
        format=ExportFormat.PNG_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["color_policy"]["color_policy"] == "source"
    assert manifest["color_policy"]["source_transform_version"] == SOURCE_TRANSFORM_VERSION
    assert manifest["alpha_mode"] == "straight"
    assert manifest["premultiplied"] is False
    assert manifest["scene_linear"] is False
    assert manifest["pixel_encoding"] == "display_or_source_uint8_scaled"


@pytest.mark.parametrize(
    ("export_format", "stem"),
    [
        (ExportFormat.PNG_SEQUENCE, "fmt_png"),
        (ExportFormat.OPENEXR_SEQUENCE, "fmt_exr"),
        (ExportFormat.RGBA_MOV, "fmt_mov"),
    ],
)
def test_export_all_formats_preserve_color_policy(
    tmp_path: Path,
    export_format: ExportFormat,
    stem: str,
) -> None:
    if export_format is ExportFormat.OPENEXR_SEQUENCE:
        pytest.importorskip("OpenEXR")
    package, render = _source_render_package(tmp_path)
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem=stem,
        render=render,
        format=export_format,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["color_policy"]["color_policy"] == "source"
    assert manifest["color_policy"]["source_transform_version"] == SOURCE_TRANSFORM_VERSION
    assert manifest["alpha_mode"] == "straight"
    assert manifest["premultiplied"] is False
    assert manifest["scene_linear"] is False


def test_export_preview_metadata_fields(tmp_path: Path) -> None:
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    reference = "renders/v0002/frame_000000.png"
    store.save(package, reference, rgba)
    render = SmartLayerRender(
        version=2,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference=reference,
                mask_reference="masks/frame_000000.png",
            )
        ],
        checksums={reference: "x"},
    )
    transform = ViewerDisplayTransform(
        exposure=ExposureTransform(0.75),
        display_transform=LegacyDisplayTransform(),
    )
    write_render_color_metadata(
        package / "renders" / "v0002",
        build_render_color_metadata(
            ProcessingColorPolicy.PREVIEW,
            display_transform=transform,
        ),
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="demo_preview",
        render=render,
        format=ExportFormat.PNG_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["color_policy"]["color_policy"] == "preview"
    assert manifest["color_policy"]["exposure"] == pytest.approx(0.75)
    assert manifest["color_policy"]["color_backend"] == "legacy"


def test_bg_preview_still_uses_preview_frame(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    controller = ProjectController()
    assert controller.create_project("BG Prev", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    # Without confirmed mask, preview should fail gracefully — still verifies API.
    assert controller.start_background_removal_preview(0) is False

    # Decoder path identity: get_preview_frame is the BG preview input contract.
    media = Path(shot.media.source_path)
    controller._frame_decoder._prefetch_count = 0
    preview = controller._frame_decoder.get_preview_frame(
        media, 0, schedule_prefetch=False
    )
    assert preview.dtype == np.uint8


def test_controller_rejects_scene_policy(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    assert (
        controller.start_smart_layer_render(color_policy=ProcessingColorPolicy.SCENE)
        is False
    )


def test_load_render_color_metadata_roundtrip(tmp_path: Path) -> None:
    package = tmp_path / "p.nova"
    (package / "renders" / "v0003").mkdir(parents=True)
    render = SmartLayerRender(
        version=3,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference="renders/v0003/frame_000000.png",
                mask_reference="masks/x.png",
            )
        ],
    )
    meta = build_render_color_metadata(ProcessingColorPolicy.SOURCE)
    write_render_color_metadata(package / "renders" / "v0003", meta)
    loaded = load_render_color_metadata(package, render)
    assert loaded is not None
    assert loaded["color_policy"] == "source"
    assert (package / "renders" / "v0003" / RENDER_COLOR_POLICY_FILENAME).is_file()
