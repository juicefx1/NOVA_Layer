"""Phase 10A: True Scene Linear EXR export."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.adapters.persistence.preview_store import PngPreviewStore
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.render_color_metadata import (
    build_render_color_metadata,
    validate_render_color_policy,
    write_render_color_metadata,
)
from nova_layer.app.scene_range_decode import decode_scene_frame_range
from nova_layer.domain.models import ArtistIntent, ExtractionPreview, SmartLayer, SmartLayerRender
from nova_layer.export.scene_exr import (
    compose_scene_rgba,
    write_scene_openexr_rgba,
)
from nova_layer.export.smart_layer import (
    ExportFormat,
    SmartLayerExportError,
    export_smart_layer_assets,
    write_openexr_rgba,
)
from nova_layer.ports.media import MediaReadError


def _fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    *,
    counter: list[int] | None = None,
    pixels: np.ndarray | None = None,
) -> list[int]:
    calls = counter if counter is not None else []
    rgb = (
        np.asarray(pixels, dtype=np.float32)
        if pixels is not None
        else np.array(
            [
                [[-0.25, 0.0, 0.5], [1.5, 2.0, 0.75]],
                [[0.1, 0.2, 0.3], [3.0, -1.0, 1.0]],
            ],
            dtype=np.float32,
        )
    )
    height, width = int(rgb.shape[0]), int(rgb.shape[1])

    class FakeSpec:
        def __init__(self) -> None:
            self.height = height
            self.width = width
            self.nchannels = 3

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


def _exr_seq(tmp_path: Path, frames: int = 2) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


# ---------------------------------------------------------------------------
# compose_scene_rgba
# ---------------------------------------------------------------------------


def test_compose_scene_preserves_negative_and_overrange() -> None:
    rgb = np.array([[[-0.5, 0.0, 1.25]]], dtype=np.float32)
    mask = np.array([[128]], dtype=np.uint8)
    rgba = compose_scene_rgba(rgb, mask)
    assert rgba.dtype == np.float32
    assert rgba.shape == (1, 1, 4)
    np.testing.assert_allclose(rgba[0, 0, :3], [-0.5, 0.0, 1.25])
    assert float(rgba[0, 0, 3]) == pytest.approx(128 / 255)


def test_compose_scene_zero_alpha_keeps_rgb() -> None:
    rgb = np.full((2, 2, 3), 1.7, dtype=np.float32)
    mask = np.zeros((2, 2), dtype=np.uint8)
    rgba = compose_scene_rgba(rgb, mask)
    np.testing.assert_array_equal(rgba[..., :3], rgb)
    np.testing.assert_array_equal(rgba[..., 3], 0.0)


def test_compose_scene_does_not_mutate_inputs() -> None:
    rgb = np.ones((2, 2, 3), dtype=np.float32)
    mask = np.full((2, 2), 200, dtype=np.uint8)
    rgb_copy = rgb.copy()
    mask_copy = mask.copy()
    compose_scene_rgba(rgb, mask)
    np.testing.assert_array_equal(rgb, rgb_copy)
    np.testing.assert_array_equal(mask, mask_copy)


def test_compose_scene_shape_mismatch() -> None:
    rgb = np.zeros((2, 2, 3), dtype=np.float32)
    mask = np.zeros((3, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="shape"):
        compose_scene_rgba(rgb, mask)


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------


def test_scene_exr_writer_preserves_values(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    Imath = pytest.importorskip("Imath")
    OpenEXR = pytest.importorskip("OpenEXR")
    rgba = np.zeros((2, 2, 4), dtype=np.float32)
    rgba[..., 0] = -0.25
    rgba[..., 1] = 1.5
    rgba[..., 2] = 0.0
    rgba[..., 3] = 0.5
    path = tmp_path / "scene.exr"
    write_scene_openexr_rgba(path, rgba, metadata={"novaSceneLinear": "true"})
    inp = OpenEXR.InputFile(str(path))
    try:
        red = np.frombuffer(
            inp.channel("R", Imath.PixelType(Imath.PixelType.HALF)), dtype=np.float16
        ).astype(np.float32).reshape(2, 2)
        green = np.frombuffer(
            inp.channel("G", Imath.PixelType(Imath.PixelType.HALF)), dtype=np.float16
        ).astype(np.float32).reshape(2, 2)
        alpha = np.frombuffer(
            inp.channel("A", Imath.PixelType(Imath.PixelType.HALF)), dtype=np.float16
        ).astype(np.float32).reshape(2, 2)
    finally:
        inp.close()
    assert float(red[0, 0]) == pytest.approx(-0.25, abs=1e-3)
    assert float(green[0, 0]) == pytest.approx(1.5, abs=1e-2)
    assert float(alpha[0, 0]) == pytest.approx(0.5, abs=1e-3)


def test_uint8_exr_writer_still_remaps(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    Imath = pytest.importorskip("Imath")
    OpenEXR = pytest.importorskip("OpenEXR")
    rgba = np.full((1, 1, 4), 128, dtype=np.uint8)
    path = tmp_path / "u8.exr"
    write_openexr_rgba(path, rgba)
    inp = OpenEXR.InputFile(str(path))
    try:
        red = np.frombuffer(
            inp.channel("R", Imath.PixelType(Imath.PixelType.FLOAT)), dtype=np.float32
        ).reshape(1, 1)
    finally:
        inp.close()
    assert float(red[0, 0]) == pytest.approx(128 / 255, abs=1e-3)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _scene_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    frames: int = 2,
) -> tuple[Path, Path, SmartLayerRender, FrameDecodeService, list[int]]:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter=counter)
    media = _exr_seq(tmp_path, frames=frames)
    package = tmp_path / "project.nova"
    package.mkdir()
    (package / "masks").mkdir()
    (package / "renders" / "v0001").mkdir(parents=True)
    store = PngPreviewStore()
    mask_store = PngMaskStore()
    preview_frames: list[ExtractionPreview] = []
    for index in range(frames):
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        rgba[..., :3] = 40
        rgba[..., 3] = 200
        reference = f"renders/v0001/frame_{index:06d}.png"
        store.save(package, reference, rgba)
        mask = np.full((2, 2), 180, dtype=np.uint8)
        mask_ref = f"masks/frame_{index:06d}.png"
        mask_store.save(package, mask_ref, mask)
        preview_frames.append(
            ExtractionPreview(
                frame_number=index,
                image_reference=reference,
                mask_reference=mask_ref,
            )
        )
    write_render_color_metadata(
        package / "renders" / "v0001",
        build_render_color_metadata(ProcessingColorPolicy.PREVIEW),
    )
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=frames - 1,
        frames=preview_frames,
        checksums={item.image_reference: "x" for item in preview_frames},
    )
    decoder = FrameDecodeService(
        ImageSequenceReader(),
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
        prefetch_count=0,
    )
    return package, media, render, decoder, counter


def test_scene_export_creates_exr_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, counter = _scene_package(tmp_path, monkeypatch)
    destination = tmp_path / "exports"
    destination.mkdir()
    before_preview = decoder.preview_cache_stats.count
    before_source = decoder.source_cache_stats.count
    render_png = package / render.frames[0].image_reference
    png_before = render_png.read_bytes()

    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="scene_out",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        media_fingerprint="fp",
        input_color_space="scene_linear",
    )
    assert (result.path / "frame_000000.exr").is_file()
    assert (result.path / "frame_000001.exr").is_file()
    assert render_png.read_bytes() == png_before
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format_id"] == "scene_openexr_sequence"
    assert manifest["export_mode"] == "compose_scene"
    assert manifest["scene_linear"] is True
    assert manifest["pixel_encoding"] == "scene_linear_half"
    assert manifest["alpha_mode"] == "straight"
    assert manifest["premultiplied"] is False
    assert manifest["color_policy"]["color_policy"] == "scene"
    assert manifest["color_policy"]["source_transform_version"] is None
    assert manifest["color_policy"]["display"] is None
    assert manifest["media_fingerprint"] == "fp"
    assert manifest["files"][0]["sha256"]
    assert decoder.preview_cache_stats.count == before_preview
    assert decoder.source_cache_stats.count == before_source
    assert len(counter) == 2


def test_scene_export_stable_across_exposure_and_raw_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, counter = _scene_package(
        tmp_path, monkeypatch, frames=1
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    common = dict(
        package_path=package,
        destination_directory=destination,
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        media_fingerprint="fp",
        input_color_space="scene_linear",
    )
    first = export_smart_layer_assets(export_stem="a", **common)  # type: ignore[arg-type]
    decoder.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    second = export_smart_layer_assets(export_stem="b", **common)  # type: ignore[arg-type]
    assert (first.path / "frame_000000.exr").read_bytes() == (
        second.path / "frame_000000.exr"
    ).read_bytes()
    assert len(counter) == 1
    assert decoder.preview_cache_stats.count == 0


def test_scene_export_errors_without_context(tmp_path: Path) -> None:
    package = tmp_path / "p.nova"
    package.mkdir()
    render = SmartLayerRender(
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
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(SmartLayerExportError, match="OpenImageIO"):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=destination,
            export_stem="bad",
            render=render,
            format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
            project={"id": "p", "name": "Demo"},
            shot={"id": "s", "name": "Shot", "frame_rate": 24.0},
            smart_layer={"id": "l", "name": "Layer"},
            frame_rate=24.0,
        )


def test_scene_range_helper_uses_raw_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _fake_oiio(monkeypatch)
    media = _exr_seq(tmp_path, frames=2)
    decoder = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    before_preview = decoder.preview_cache_stats.count
    before_source = decoder.source_cache_stats.count
    frames = decode_scene_frame_range(decoder, media, 0, 1)
    assert set(frames) == {0, 1}
    assert frames[0].pixels.dtype == np.float32
    assert decoder.preview_cache_stats.count == before_preview
    assert decoder.source_cache_stats.count == before_source
    assert len(counter) == 2
    decode_scene_frame_range(decoder, media, 0, 1)
    assert len(counter) == 2


def test_scene_render_policy_still_rejected(qapp: object) -> None:
    del qapp
    with pytest.raises(MediaReadError, match="SCENE"):
        validate_render_color_policy(ProcessingColorPolicy.SCENE)
    controller = ProjectController()
    assert (
        controller.start_smart_layer_render(color_policy=ProcessingColorPolicy.SCENE)
        is False
    )


def test_controller_rejects_non_exr_scene_export(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    from PIL import Image

    root = tmp_path / "proj"
    root.mkdir()
    controller = ProjectController()
    assert controller.create_project("SceneEx", root) is not None
    seq = tmp_path / "png"
    seq.mkdir()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(seq / "frame_0001.png")
    shot = controller.import_media(seq)
    assert shot is not None
    package = controller.package_path
    assert package is not None
    (package / "renders" / "v0001").mkdir(parents=True)
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    PngPreviewStore().save(package, "renders/v0001/frame_000000.png", rgba)
    layer = SmartLayer(
        artist_intent=ArtistIntent(master_frame=0),
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
                checksums={"renders/v0001/frame_000000.png": "x"},
            )
        ],
        render_version_counter=1,
    )
    shot.smart_layers.append(layer)
    # Bypass integrity for this rejection test by stubbing verify.
    controller.verify_smart_layer_render = (  # type: ignore[method-assign]
        lambda version=None: type(
            "R",
            (),
            {"valid": True, "version": 1, "checked_files": 1, "issues": ()},
        )()
    )
    out = tmp_path / "exports"
    out.mkdir()
    assert (
        controller.export_smart_layer_render(
            out, format=ExportFormat.SCENE_OPENEXR_SEQUENCE
        )
        is None
    )


def test_legacy_openexr_sequence_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    pytest.importorskip("OpenEXR")
    package = tmp_path / "project.nova"
    package.mkdir()
    store = PngPreviewStore()
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., :3] = 64
    rgba[..., 3] = 255
    reference = "renders/v0001/frame_000000.png"
    store.save(package, reference, rgba)
    write_render_color_metadata(
        package / "renders" / "v0001",
        build_render_color_metadata(ProcessingColorPolicy.SOURCE),
    )
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference=reference,
                mask_reference="masks/x.png",
            )
        ],
        checksums={reference: "x"},
    )
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="u8_exr",
        render=render,
        format=ExportFormat.OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 4, "height": 4},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format_id"] == "openexr_sequence"
    assert manifest["scene_linear"] is False
    assert manifest["pixel_encoding"] == "display_or_source_uint8_scaled"
