"""Phase 8C-2: ProjectController SAM/skeleton use SOURCE processing frames."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.color.display_transform import (
    LegacyDisplayTransform,
    ViewerDisplayTransform,
)
from nova_layer.adapters.color.exposure_transform import ExposureTransform
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    BoundingRegion,
    CapabilityProvenance,
    FrameResult,
    GuidancePoint,
    ValidationState,
)
from nova_layer.ports.capabilities import SegmentationResult


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


def _exr_seq(tmp_path: Path, frames: int = 3) -> Path:
    seq = tmp_path / "exr"
    seq.mkdir()
    for index in range(1, frames + 1):
        (seq / f"frame_{index:04d}.exr").write_bytes(b"x")
    return seq


class CapturingSegmentation:
    def __init__(self) -> None:
        self.images: list[np.ndarray] = []

    def predict(self, **kwargs: object) -> SegmentationResult:
        image = kwargs["image"]
        assert isinstance(image, np.ndarray)
        self.images.append(image.copy())
        height = int(kwargs["height"])  # type: ignore[arg-type]
        width = int(kwargs["width"])  # type: ignore[arg-type]
        return SegmentationResult(
            mask_reference="masks/cap.png",
            mask=np.zeros((height, width), dtype=np.uint8),
            confidence=0.9,
            provenance=CapabilityProvenance(
                capability="interactive_segmentation",
                adapter="capture",
                adapter_version="1",
            ),
        )


def test_predict_hypothesis_uses_source_and_is_exposure_stable(
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
    capture = CapturingSegmentation()
    controller = ProjectController(
        segmentation=capture,
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    assert controller.create_project("Src Pol", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert len(capture.images) == 1
    first = capture.images[0]
    assert first.dtype == np.uint8

    via_api = controller._get_source_processing_frame(
        Path(shot.media.source_path), shot.master_frame
    )
    np.testing.assert_array_equal(first, via_api)

    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    shot2 = controller.active_shot
    assert shot2 is not None
    intent = shot2.smart_layers[0].artist_intent
    controller._predict_hypothesis(shot2, intent)
    assert len(capture.images) == 2
    np.testing.assert_array_equal(capture.images[0], capture.images[1])


def test_apply_frame_correction_uses_source(
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
    capture = CapturingSegmentation()
    controller = ProjectController(segmentation=capture)
    assert controller.create_project("Corr Pol", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()
    layer = shot.smart_layers[0]
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
    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(1.5),
            display_transform=LegacyDisplayTransform(),
        )
    )
    result = controller.apply_frame_correction(
        target,
        [GuidancePoint(x=0.4, y=0.4, polarity="positive")],
        None,
    )
    assert result is not None
    assert len(capture.images) == 1
    assert capture.images[0].dtype == np.uint8
    source = controller._get_source_processing_frame(Path(shot.media.source_path), target)
    np.testing.assert_array_equal(capture.images[0], source)


def test_get_source_processing_frame_helper_policy(tmp_path: Path, qapp: object) -> None:
    del qapp
    controller = ProjectController()
    path = tmp_path / "x.mov"
    path.write_bytes(b"x")

    calls: list[ProcessingColorPolicy] = []

    def _spy(p: Path, frame: int, *, policy: ProcessingColorPolicy) -> np.ndarray:
        del p, frame
        calls.append(policy)
        return np.zeros((2, 2, 3), dtype=np.uint8)

    controller._frame_decoder.get_processing_frame = _spy  # type: ignore[method-assign]
    out = controller._get_source_processing_frame(path, 0)
    assert out.dtype == np.uint8
    assert calls == [ProcessingColorPolicy.SOURCE]


def test_processing_methods_have_no_direct_reader_read_frame() -> None:
    source = inspect.getsource(ProjectController)
    tree = ast.parse(source)
    class_body = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProjectController"
    )
    sam_targets = {
        "_predict_hypothesis",
        "apply_frame_correction",
    }
    skeleton_targets = {
        "start_skeleton_retracking",
        "start_skeleton_fusion_detection",
    }
    for item in class_body.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        text = ast.get_source_segment(source, item) or ""
        if item.name in sam_targets:
            assert "_media_reader.read_frame" not in text, item.name
            assert "_get_sam_processing_frame" in text, item.name
        if item.name in skeleton_targets:
            assert "_media_reader.read_frame" not in text, item.name
            assert "_get_source_processing_frame" in text, item.name
            assert "_get_sam_processing_frame" not in text, item.name


def test_propagation_stays_on_source_v1_helper() -> None:
    """Propagation must not use SAM profile helper."""
    text = inspect.getsource(ProjectController)
    # Propagation path historically uses decode_frame_range / source helper — not SAM.
    assert "_get_sam_processing_frame" in text
    prop_src = inspect.getsource(ProjectController.start_skeleton_retracking)
    assert "_get_sam_processing_frame" not in prop_src
    fusion = inspect.getsource(ProjectController.start_skeleton_fusion_detection)
    assert "_get_sam_processing_frame" not in fusion
    # Range decode helper used by propagation should remain SOURCE without request.
    from nova_layer.app import range_decode as rd

    rd_src = inspect.getsource(rd)
    assert "source_transform_request" not in rd_src



def test_import_uses_image_sequence_reader_for_exr(
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
    assert controller.create_project("EXR Type", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    assert isinstance(controller._media_reader, ImageSequenceReader)


def test_fusion_decode_uses_source_helper_ast() -> None:
    """Nested job callbacks still mention SOURCE helper (static check)."""
    text = inspect.getsource(ProjectController.start_skeleton_fusion_detection)
    assert "_get_source_processing_frame" in text
    assert "_media_reader.read_frame" not in text
