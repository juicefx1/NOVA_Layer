from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    LegacyDisplayTransform,
)
from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.project_controller import ProjectController


class RecordingTransform(LegacyDisplayTransform):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[np.ndarray] = []

    def apply(self, image: np.ndarray) -> np.ndarray:
        array = np.asarray(image)
        self.calls.append(array.copy())
        # Distinct non-legacy preview: constant magenta.
        h, w = array.shape[:2]
        return np.full((h, w, 3), (200, 0, 200), dtype=np.uint8)


def _png_sequence(folder: Path, *, frames: int = 3) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        color = (10 * (index + 1), 20, 30)
        Image.new("RGB", (4, 4), color=color).save(folder / f"frame_{index:04d}.png")
    return folder


def test_controller_default_diagnostics_are_legacy(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    diagnostics = controller.display_transform_diagnostics
    assert diagnostics is not None
    assert diagnostics.backend == "legacy"
    assert diagnostics.fallback_reason is None


def test_set_display_transform_without_active_shot(qapp: object) -> None:
    del qapp
    controller = ProjectController()
    transform = RecordingTransform()
    controller.set_display_transform(transform)
    assert controller._display_transform is transform
    assert controller.display_transform_diagnostics is transform.diagnostics


def test_controller_default_legacy_on_png_sequence(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    sequence = _png_sequence(tmp_path / "seq")
    project_root = tmp_path / "proj"
    project_root.mkdir(parents=True, exist_ok=True)
    controller = ProjectController()
    assert controller.create_project("Color Default", project_root) is not None
    shot = controller.import_media(sequence)
    assert shot is not None
    assert isinstance(controller._media_reader, ImageSequenceReader)
    assert isinstance(controller._media_reader.display_transform, LegacyDisplayTransform)

    media_path = Path(shot.media.source_path)
    frame = controller._frame_decoder.read_frame(media_path, 0)
    assert tuple(int(v) for v in frame[0, 0]) == (10, 20, 30)


def test_custom_transform_applied_on_exr_path(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    sequence = tmp_path / "exr_seq"
    sequence.mkdir()
    (sequence / "frame.exr").write_bytes(b"placeholder")

    class FakeSpec:
        height = 1
        width = 1
        nchannels = 3

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            return np.array([[[0.18, 0.0, 0.0]]], dtype=np.float32)

        def close(self) -> None:
            return None

    class FakeOIIO:
        FLOAT = object()

        class ImageInput:
            @staticmethod
            def open(_path: str) -> FakeInput:
                return FakeInput()

    transform = RecordingTransform()
    monkeypatch.setattr(
        "nova_layer.adapters.media.image_sequence_reader._load_openimageio",
        lambda: FakeOIIO,
    )

    project_root = tmp_path / "proj"
    project_root.mkdir(parents=True, exist_ok=True)
    controller = ProjectController(display_transform=transform)
    assert controller.create_project("EXR Color", project_root) is not None
    shot = controller.import_media(sequence)
    assert shot is not None
    assert isinstance(controller._media_reader, ImageSequenceReader)
    assert controller._media_reader.display_transform is transform

    media_path = Path(shot.media.source_path)
    frame = controller._frame_decoder.read_frame(media_path, 0)
    assert tuple(int(v) for v in frame[0, 0]) == (200, 0, 200)
    assert transform.calls


def test_set_display_transform_rebuilds_reader_and_clears_cache(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    sequence = _png_sequence(tmp_path / "seq", frames=4)
    project_root = tmp_path / "proj"
    project_root.mkdir(parents=True, exist_ok=True)
    controller = ProjectController()
    assert controller.create_project("Cache Color", project_root) is not None
    shot = controller.import_media(sequence)
    assert shot is not None

    media_path = Path(shot.media.source_path)
    decoder = controller._frame_decoder
    decoder.read_frame(media_path, 0)
    decoder.read_frame(media_path, 1)
    assert decoder.cache_count >= 1
    old_reader = controller._media_reader
    old_decoder = controller._frame_decoder

    assert controller.request_frame(0) is True
    assert controller._preview_frame_number == 0

    requested: list[int] = []
    original_request = controller.request_frame

    def _spy_request(frame_number: int) -> bool:
        requested.append(frame_number)
        return original_request(frame_number)

    controller.request_frame = _spy_request  # type: ignore[method-assign]

    transform = RecordingTransform()
    controller.set_display_transform(transform)

    assert controller._media_reader is not old_reader
    assert controller._frame_decoder is not old_decoder
    assert isinstance(controller._media_reader, ImageSequenceReader)
    assert controller._media_reader.display_transform is transform
    assert controller._frame_decoder.cache_count == 0
    assert requested == [0, shot.master_frame]
    assert shot.master_frame != 0


def test_diagnostics_expose_injected_transform(qapp: object) -> None:
    del qapp
    transform = LegacyDisplayTransform(
        diagnostics=DisplayTransformDiagnostics(
            backend="legacy",
            ocio_available=False,
            config_path=None,
            config_source=None,
            display=None,
            view=None,
            input_color_space="scene_linear",
            exposure=0.0,
            fallback_reason="test-injected",
        )
    )
    controller = ProjectController(display_transform=transform)
    assert controller.display_transform_diagnostics is transform.diagnostics
    assert controller.display_transform_diagnostics.fallback_reason == "test-injected"


def test_diagnostics_none_for_transform_without_attribute(qapp: object) -> None:
    del qapp

    class BareTransform:
        def apply(self, image: np.ndarray) -> np.ndarray:
            array = np.asarray(image)
            h, w = array.shape[:2]
            return np.zeros((h, w, 3), dtype=np.uint8)

    controller = ProjectController(display_transform=BareTransform())
    assert controller.display_transform_diagnostics is None
