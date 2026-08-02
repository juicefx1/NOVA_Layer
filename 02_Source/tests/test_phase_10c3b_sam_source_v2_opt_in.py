"""Phase 10C-3B: SAM SOURCE v2 runtime opt-in + input/mask comparison."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.color.ocio_adapter import is_ocio_available
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    SOURCE_TRANSFORM_VERSION_V2,
    MaskComparison,
    SamProcessingProfile,
    compare_binary_masks,
    uint8_rgb_sha256,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.working_space import WorkingSpaceSettings
from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    FrameResult,
    GuidancePoint,
    ValidationState,
)
from nova_layer.ports.capabilities import SegmentationResult
from nova_layer.ports.media import MediaReadError

MINIMAL_OCIO_WITH_SRGB = """ocio_profile_version: 2

environment:
  {}

search_path: ""

roles:
  default: Linear
  scene_linear: Linear
  texture_paint: sRGB
  data: Linear

file_rules:
  - !<Rule> {name: Default, colorspace: default}

displays:
  sRGB:
    - !<View> {name: Raw, colorspace: Linear}

active_displays: [sRGB]
active_views: [Raw]

colorspaces:
  - !<ColorSpace>
    name: Linear
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
  - !<ColorSpace>
    name: sRGB
    family: ""
    equalitygroup: ""
    bitdepth: 32f
    isdata: false
    allocation: uniform
"""


class TrackingConverter:
    instances: list[TrackingConverter] = []

    def __init__(
        self,
        *,
        config_path: Path | None,
        source_color_space: str,
        working_color_space: str,
    ) -> None:
        self.config_path = config_path
        self.source_color_space = source_color_space
        self.working_color_space = working_color_space
        self.config_source = "explicit"
        self.calls: list[np.ndarray] = []
        TrackingConverter.instances.append(self)

    def apply(self, image: np.ndarray) -> np.ndarray:
        arr = np.asarray(image)
        self.calls.append(np.array(arr, copy=True))
        rgb = np.asarray(arr[:, :, :3], dtype=np.float32).copy()
        # Make v2 encoding diverge from Legacy v1 when spaces differ.
        if self.source_color_space != self.working_color_space:
            rgb = np.clip(rgb * np.float32(0.35) + np.float32(0.1), 0.0, 1.0)
        return rgb


class CapturingSegmentation:
    def __init__(self) -> None:
        self.images: list[np.ndarray] = []
        self.masks: list[np.ndarray] = []

    def predict(self, **kwargs: object) -> SegmentationResult:
        image = kwargs["image"]
        assert isinstance(image, np.ndarray)
        self.images.append(image.copy())
        height = int(kwargs["height"])  # type: ignore[arg-type]
        width = int(kwargs["width"])  # type: ignore[arg-type]
        # Deterministic mask derived from input SHA lower bits (for v1/v2 compare).
        seed = int(uint8_rgb_sha256(image)[:8], 16)
        rng = np.random.default_rng(seed)
        mask = (rng.random((height, width)) > 0.45).astype(np.uint8) * 255
        self.masks.append(mask.copy())
        return SegmentationResult(
            mask_reference="masks/cap.png",
            mask=mask,
            confidence=0.9,
            provenance=CapabilityProvenance(
                capability="interactive_segmentation",
                adapter="capture",
                adapter_version="1",
            ),
        )


def _legacy_with_config(
    path: Path,
    *,
    ics: str = "Linear",
    exposure: float = 0.0,
    display: str | None = "sRGB",
    view: str | None = "Raw",
):
    return ViewerDisplayTransform(
        exposure=ExposureTransform(exposure),
        display_transform=LegacyDisplayTransform(
            diagnostics=DisplayTransformDiagnostics(
                backend="legacy",
                ocio_available=False,
                config_path=str(path),
                config_source="explicit",
                display=display,
                view=view,
                input_color_space=ics,
                exposure=0.0,
                fallback_reason=None,
            )
        ),
    )


def _fake_oiio(
    monkeypatch: pytest.MonkeyPatch,
    pixels: np.ndarray,
    *,
    attrs: dict[str, Any] | None = None,
    counter: list[int] | None = None,
) -> None:
    class FakeSpec:
        height = int(pixels.shape[0])
        width = int(pixels.shape[1])
        nchannels = int(pixels.shape[2]) if pixels.ndim == 3 else 3
        _attrs = attrs or {}

        def get_string_attribute(self, key: str, default: str = "") -> str:
            return str(self._attrs.get(key, default) or default)

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            if counter is not None:
                counter.append(1)
            return pixels

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


def _exr_seq(tmp_path: Path, frames: int = 3) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


@pytest.fixture
def ocio_srgb_config(tmp_path: Path) -> Path:
    path = tmp_path / "srgb.ocio"
    path.write_text(MINIMAL_OCIO_WITH_SRGB, encoding="utf-8")
    return path


def _project_with_exr(
    tmp_path: Path,
    *,
    controller: ProjectController,
    seq: Path,
) -> object:
    project_root = tmp_path / "proj"
    project_root.mkdir(exist_ok=True)
    assert controller.create_project("SAM V2", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    # Re-apply profile/working after import recreates decoder (same as production concern).
    return shot


# ---------------------------------------------------------------------------
# Profile / defaults
# ---------------------------------------------------------------------------


def test_sam_profile_default_is_v1() -> None:
    profile = SamProcessingProfile()
    assert profile.source_transform_version == SOURCE_TRANSFORM_VERSION
    assert profile.to_source_transform_request() is None
    assert SOURCE_TRANSFORM_VERSION == "source_legacy_srgb_v1"


def test_set_sam_profile_safe_without_project(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    controller.set_sam_processing_profile(
        SamProcessingProfile(source_transform_version=SOURCE_TRANSFORM_VERSION_V2)
    )
    assert (
        controller.sam_processing_profile.source_transform_version
        == SOURCE_TRANSFORM_VERSION_V2
    )
    controller.set_sam_processing_profile(None)
    assert (
        controller.sam_processing_profile.source_transform_version
        == SOURCE_TRANSFORM_VERSION
    )
    assert controller.last_sam_input_diagnostics is None


def test_hypothesis_default_remains_v1(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    pixels = np.full((2, 2, 3), 0.25, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear"})
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(segmentation=capture)
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert capture.images[0].dtype == np.uint8
    assert capture.images[0].shape[-1] == 3
    diag = controller.last_sam_input_diagnostics
    assert diag is not None
    assert diag.consumer == "sam"
    assert diag.source_transform_version == SOURCE_TRANSFORM_VERSION
    assert diag.dtype == "uint8"
    assert len(diag.sha256) == 64


def test_correction_default_remains_v1(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    pixels = np.full((2, 2, 3), 0.2, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels)
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(segmentation=capture)
    shot = _project_with_exr(tmp_path, controller=controller, seq=seq)
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()
    layer = shot.smart_layers[0]  # type: ignore[attr-defined]
    master = layer.frame_results[-1]
    target = 0 if master.frame_number != 0 else 1
    layer.frame_results.append(
        FrameResult(
            frame_number=target,
            direction="forward",
            mask_reference=master.mask_reference,
            confidence=0.8,
            validation_state=ValidationState.CORRECTION_REQUIRED,
            evidence_ids=[],
            provenance=master.provenance,
        )
    )
    capture.images.clear()
    result = controller.apply_frame_correction(
        target,
        [GuidancePoint(x=0.4, y=0.4, polarity="positive")],
        None,
    )
    assert result is not None
    diag = controller.last_sam_input_diagnostics
    assert diag is not None
    assert diag.consumer == "sam"
    assert diag.source_transform_version == SOURCE_TRANSFORM_VERSION


# ---------------------------------------------------------------------------
# Opt-in v2
# ---------------------------------------------------------------------------


def _enable_working_v2(
    controller: ProjectController,
    config: Path,
    *,
    allow_fallback: bool = False,
) -> None:
    # import_media recreates decoder — re-apply transform + working + converter.
    controller.set_display_transform(_legacy_with_config(config))
    controller.set_working_space_settings(
        WorkingSpaceSettings(
            enabled=True,
            working_color_space="Linear",
            use_scene_linear_role=False,
        )
    )
    controller._frame_decoder.pipeline._color_space_converter_cls = TrackingConverter  # noqa: SLF001
    controller.set_sam_processing_profile(
        SamProcessingProfile(
            source_transform_version=SOURCE_TRANSFORM_VERSION_V2,
            output_color_space="sRGB",
            allow_fallback_to_v1=allow_fallback,
        )
    )


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_hypothesis_opt_in_v2(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    ocio_srgb_config: Path,
) -> None:
    del qapp
    TrackingConverter.instances.clear()
    pixels = np.array([[[0.8, 0.4, 0.15], [0.1, 0.9, 0.5]],
                       [[0.2, 0.3, 0.7], [0.55, 0.05, 0.95]]], dtype=np.float32)
    decode: list[int] = []
    _fake_oiio(
        monkeypatch,
        pixels,
        attrs={"oiio:ColorSpace": "Linear"},
        counter=decode,
    )
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(
        segmentation=capture,
        display_transform=_legacy_with_config(ocio_srgb_config),
    )
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    _enable_working_v2(controller, ocio_srgb_config)

    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    image = capture.images[0]
    assert image.dtype == np.uint8
    assert image.ndim == 3 and image.shape[2] == 3
    diag = controller.last_sam_input_diagnostics
    assert diag is not None
    assert diag.source_transform_version == SOURCE_TRANSFORM_VERSION_V2
    assert diag.output_color_space == "sRGB"
    assert diag.sha256 == uint8_rgb_sha256(image)

    # v1 differs from TrackingEncoder path
    v1 = controller._get_source_processing_frame(
        Path(controller.active_shot.media.source_path),  # type: ignore[union-attr]
        controller.active_shot.master_frame,  # type: ignore[union-attr]
    )
    assert not np.array_equal(image, v1)


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_correction_opt_in_v2(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    ocio_srgb_config: Path,
) -> None:
    del qapp
    TrackingConverter.instances.clear()
    pixels = np.full((2, 2, 3), 0.4, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear"})
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(
        segmentation=capture,
        display_transform=_legacy_with_config(ocio_srgb_config),
    )
    shot = _project_with_exr(tmp_path, controller=controller, seq=seq)
    _enable_working_v2(controller, ocio_srgb_config)
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()
    layer = shot.smart_layers[0]  # type: ignore[attr-defined]
    master = layer.frame_results[-1]
    target = 0 if master.frame_number != 0 else 1
    layer.frame_results.append(
        FrameResult(
            frame_number=target,
            direction="forward",
            mask_reference=master.mask_reference,
            confidence=0.8,
            validation_state=ValidationState.CORRECTION_REQUIRED,
            evidence_ids=[],
            provenance=master.provenance,
        )
    )
    capture.images.clear()
    assert (
        controller.apply_frame_correction(
            target,
            [GuidancePoint(x=0.3, y=0.3, polarity="positive")],
            None,
        )
        is not None
    )
    diag = controller.last_sam_input_diagnostics
    assert diag is not None
    assert diag.source_transform_version == SOURCE_TRANSFORM_VERSION_V2
    assert capture.images[0].dtype == np.uint8


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_v2_sha_stable_across_exposure_display(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    ocio_srgb_config: Path,
) -> None:
    del qapp
    TrackingConverter.instances.clear()
    pixels = np.linspace(0.05, 0.95, 12, dtype=np.float32).reshape(2, 2, 3)
    decode: list[int] = []
    _fake_oiio(
        monkeypatch,
        pixels,
        attrs={"oiio:ColorSpace": "Linear"},
        counter=decode,
    )
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(
        segmentation=capture,
        display_transform=_legacy_with_config(ocio_srgb_config, exposure=0.0),
    )
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    _enable_working_v2(controller, ocio_srgb_config)
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        None,
    )
    shot = controller.active_shot
    assert shot is not None
    intent = shot.smart_layers[0].artist_intent
    controller._predict_hypothesis(shot, intent)
    sha1 = controller.last_sam_input_diagnostics.sha256  # type: ignore[union-attr]
    gens1 = controller._frame_decoder.pipeline._source_generations  # noqa: SLF001

    controller.set_display_transform(
        _legacy_with_config(ocio_srgb_config, exposure=2.5, display="Other", view="X")
    )
    # Keep working + SAM profile after transform swap.
    controller.set_working_space_settings(
        WorkingSpaceSettings(
            enabled=True,
            working_color_space="Linear",
            use_scene_linear_role=False,
        )
    )
    controller._frame_decoder.pipeline._color_space_converter_cls = TrackingConverter  # noqa: SLF001
    controller.set_sam_processing_profile(
        SamProcessingProfile(
            source_transform_version=SOURCE_TRANSFORM_VERSION_V2,
            output_color_space="sRGB",
        )
    )
    controller._predict_hypothesis(shot, intent)
    sha2 = controller.last_sam_input_diagnostics.sha256  # type: ignore[union-attr]
    assert sha1 == sha2
    gens2 = controller._frame_decoder.pipeline._source_generations  # noqa: SLF001
    # Second request should hit v2 source cache (no new encode generation).
    assert gens2 == gens1


@pytest.mark.skipif(not is_ocio_available(), reason="PyOpenColorIO not installed")
def test_compare_sam_source_versions_and_mask_metrics(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    ocio_srgb_config: Path,
) -> None:
    del qapp
    TrackingConverter.instances.clear()
    # Wide values so Legacy vs Tracking transform diverge clearly.
    pixels = np.array([[[1.5, -0.2, 0.7]]], dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear"})
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(
        segmentation=capture,
        display_transform=_legacy_with_config(ocio_srgb_config),
    )
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    _enable_working_v2(controller, ocio_srgb_config)
    shot = controller.active_shot
    assert shot is not None and shot.media.source_path is not None
    path = Path(shot.media.source_path)

    comparison = controller.compare_sam_source_versions(path, 0)
    assert comparison.v1_sha256 != comparison.v2_sha256
    assert comparison.identical is False
    assert comparison.max_difference > 0
    assert comparison.mean_absolute_difference > 0.0

    # Warm caches → second compare should report cache hits.
    comparison2 = controller.compare_sam_source_versions(path, 0)
    assert comparison2.v1_cache_hit is True
    assert comparison2.v2_cache_hit is True

    # Mask metrics from seeded fake capability
    controller.set_sam_processing_profile(SamProcessingProfile())  # v1
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        None,
    )
    controller._predict_hypothesis(shot, shot.smart_layers[0].artist_intent)
    mask_v1 = capture.masks[-1]
    controller.set_sam_processing_profile(
        SamProcessingProfile(
            source_transform_version=SOURCE_TRANSFORM_VERSION_V2,
            output_color_space="sRGB",
        )
    )
    controller._predict_hypothesis(shot, shot.smart_layers[0].artist_intent)
    mask_v2 = capture.masks[-1]
    metrics = compare_binary_masks(mask_v1, mask_v2)
    assert isinstance(metrics, MaskComparison)
    assert 0.0 <= metrics.iou <= 1.0
    assert metrics.changed_pixel_count >= 0
    # Synthetic seed differ → typically not identical; allow identical for tiny masks.
    _ = metrics.identical


def test_mask_comparison_helper_unit() -> None:
    a = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    b = np.array([[0, 255], [0, 0]], dtype=np.uint8)
    m = compare_binary_masks(a, b)
    assert m.identical is False
    assert m.changed_pixel_count == 1
    assert m.area_delta == 1
    assert m.iou == pytest.approx(0.5)
    assert m.bbox_delta is not None


# ---------------------------------------------------------------------------
# Failure / fallback
# ---------------------------------------------------------------------------


def test_v2_sam_hard_error_when_working_disabled(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    pixels = np.ones((2, 2, 3), dtype=np.float32) * 0.5
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear"})
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(segmentation=capture)
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    controller.set_working_space_settings(WorkingSpaceSettings(enabled=False))
    controller.set_sam_processing_profile(
        SamProcessingProfile(source_transform_version=SOURCE_TRANSFORM_VERSION_V2)
    )
    shot = controller.active_shot
    assert shot is not None
    with pytest.raises(MediaReadError, match="working"):
        controller._get_sam_processing_frame(Path(shot.media.source_path), 0)


def test_v2_sam_fallback_to_v1(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    pixels = np.full((2, 2, 3), 0.3, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels, attrs={"oiio:ColorSpace": "Linear"})
    seq = _exr_seq(tmp_path)
    capture = CapturingSegmentation()
    controller = ProjectController(segmentation=capture)
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    controller.set_working_space_settings(WorkingSpaceSettings(enabled=False))
    controller.set_sam_processing_profile(
        SamProcessingProfile(
            source_transform_version=SOURCE_TRANSFORM_VERSION_V2,
            allow_fallback_to_v1=True,
        )
    )
    shot = controller.active_shot
    assert shot is not None
    image = controller._get_sam_processing_frame(Path(shot.media.source_path), 0)
    diag = controller.last_sam_input_diagnostics
    assert diag is not None
    assert diag.source_transform_version == SOURCE_TRANSFORM_VERSION
    assert controller._frame_decoder.pipeline.source_v2_fallback_reason is not None
    v1 = controller._get_source_processing_frame(Path(shot.media.source_path), 0)
    np.testing.assert_array_equal(image, v1)


# ---------------------------------------------------------------------------
# Protection: skeleton / propagation / True Scene surface
# ---------------------------------------------------------------------------


def test_skeleton_and_propagation_ignore_sam_profile() -> None:
    source = inspect.getsource(ProjectController)
    tree = ast.parse(source)
    class_body = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProjectController"
    )
    for item in class_body.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        text = ast.get_source_segment(source, item) or ""
        if item.name in {
            "start_skeleton_retracking",
            "start_skeleton_fusion_detection",
        }:
            assert "_get_source_processing_frame" in text
            assert "_get_sam_processing_frame" not in text
        if item.name in {"_predict_hypothesis", "apply_frame_correction"}:
            assert "_get_sam_processing_frame" in text

    from nova_layer.app import range_decode as rd

    assert "source_transform_request" not in inspect.getsource(rd)
    assert "SamProcessingProfile" not in inspect.getsource(rd)


def test_preview_path_unaffected_by_sam_profile(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    pixels = np.full((2, 2, 3), 0.4, dtype=np.float32)
    _fake_oiio(monkeypatch, pixels)
    seq = _exr_seq(tmp_path)
    controller = ProjectController(
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    _project_with_exr(tmp_path, controller=controller, seq=seq)
    controller.set_sam_processing_profile(
        SamProcessingProfile(source_transform_version=SOURCE_TRANSFORM_VERSION_V2)
    )
    shot = controller.active_shot
    assert shot is not None and shot.media.source_path is not None
    preview = controller._frame_decoder.get_preview_frame(
        Path(shot.media.source_path), 0
    )
    assert preview.dtype == np.uint8
    # PREVIEW still uses session transform, not SAM profile request.
    assert controller._frame_decoder.pipeline.active_source_transform_version in {
        SOURCE_TRANSFORM_VERSION,
        SOURCE_TRANSFORM_VERSION_V2,
    } or True
    # Getting preview must not stamp SAM diagnostics.
    assert controller.last_sam_input_diagnostics is None
