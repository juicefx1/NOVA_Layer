"""Phase 8C-1: preview API, range_decode pipeline integration, controller preview paths."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nova_layer.adapters.media.image_sequence_reader import ImageSequenceReader
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.range_decode import decode_frame_range
from nova_layer.domain.models import (
    ArtistIntent,
    CapabilityProvenance,
    FrameResult,
    ObjectIdentity,
    SmartLayer,
    ValidationState,
)
from nova_layer.ports.media import MediaInfo, MediaReadError
from nova_layer.ports.scene_frames import SceneFrame


class CountingUint8Reader:
    def __init__(self, frame_count: int = 10) -> None:
        self.frame_count = frame_count
        self.calls: list[int] = []

    def inspect(self, path: Path) -> MediaInfo:
        return MediaInfo(
            path=path.resolve(),
            fingerprint="sha256:count",
            frame_count=self.frame_count,
            frame_rate=24.0,
            width=8,
            height=6,
            time_base="1/24",
            pixel_format="rgb24",
        )

    def read_frame(self, path: Path, frame_number: int) -> np.ndarray:
        del path
        self.calls.append(frame_number)
        return np.full((6, 8, 3), frame_number % 256, dtype=np.uint8)


def _fake_oiio(monkeypatch: pytest.MonkeyPatch, counter: list[int]) -> None:
    class FakeSpec:
        height = 1
        width = 1
        nchannels = 3

    class FakeInput:
        def spec(self) -> FakeSpec:
            return FakeSpec()

        def read_image(self, _fmt: object) -> np.ndarray:
            counter.append(1)
            return np.array([[[0.25, 0.25, 0.25]]], dtype=np.float32)

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


def _png_seq(tmp_path: Path, frames: int = 3) -> Path:
    seq = tmp_path / "png"
    seq.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        Image.new("RGB", (4, 4), color=(10 * (index + 1), 20, 30)).save(
            seq / f"frame_{index:04d}.png"
        )
    return seq


# --- FrameDecodeService API ---


def test_get_preview_frame_matches_read_frame(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    service = FrameDecodeService(reader, cache_size=4, prefetch_count=0)
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    a = service.get_preview_frame(media, 3)
    service.clear()
    reader.calls.clear()
    b = service.read_frame(media, 3)
    assert a.dtype == b.dtype == np.uint8
    assert a.shape == b.shape
    np.testing.assert_array_equal(a, b)


def test_get_scene_frame_exr_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    scene = service.get_scene_frame(seq, 0)
    assert isinstance(scene, SceneFrame)
    assert scene.pixels.dtype == np.float32
    assert len(counter) == 1
    again = service.get_scene_frame(seq, 0)
    assert len(counter) == 1
    np.testing.assert_array_equal(again.pixels, scene.pixels)


def test_get_scene_frame_non_exr_raises(tmp_path: Path) -> None:
    seq = _png_seq(tmp_path)
    service = FrameDecodeService(ImageSequenceReader(), prefetch_count=0)
    with pytest.raises(MediaReadError, match="EXR"):
        service.get_scene_frame(seq, 0)


def test_get_scene_frame_unsupported_reader(tmp_path: Path) -> None:
    service = FrameDecodeService(CountingUint8Reader(), prefetch_count=0)
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    with pytest.raises(MediaReadError, match="SceneFrameSource"):
        service.get_scene_frame(media, 0)


def test_preview_cache_hit_avoids_reader_call(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    service = FrameDecodeService(reader, cache_size=4, prefetch_count=0)
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    service.get_preview_frame(media, 2)
    assert reader.calls == [2]
    service.get_preview_frame(media, 2)
    assert reader.calls == [2]


# --- range_decode ---


def test_range_decode_image_sequence_uses_decoder(tmp_path: Path) -> None:
    reader = CountingUint8Reader(frame_count=8)
    decoder = FrameDecodeService(reader, cache_size=2, prefetch_count=0)
    path = tmp_path / "clip.mov"
    frames, stats = decode_frame_range(decoder, reader, path, 1, 4)
    assert set(frames) == {1, 2, 3, 4}
    assert reader.calls == [1, 2, 3, 4]
    assert stats.decoded_frames == 4
    # Second pass: preview cache hits (expand_to_fit kept entries).
    frames2, stats2 = decode_frame_range(decoder, reader, path, 1, 4)
    assert stats2.cache_hits == 4
    assert stats2.decoded_frames == 0
    assert reader.calls == [1, 2, 3, 4]
    assert set(frames2) == {1, 2, 3, 4}


def test_range_decode_exr_reuses_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path, frames=3)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    decode_frame_range(decoder, reader, seq, 0, 2)
    assert len(counter) == 3
    decode_frame_range(decoder, reader, seq, 0, 2)
    assert len(counter) == 3
    assert decoder.pipeline.pipeline_stats.raw_decodes == 3


def test_range_decode_tiny_preview_budget_still_completes(tmp_path: Path) -> None:
    reader = CountingUint8Reader(frame_count=6)
    decoder = FrameDecodeService(
        reader,
        cache_size=1,
        prefetch_count=0,
        preview_cache_max_bytes=1,  # force oversized path / eviction
    )
    path = tmp_path / "clip.mov"
    frames, stats = decode_frame_range(decoder, reader, path, 0, 4)
    assert set(frames) == {0, 1, 2, 3, 4}
    assert stats.decoded_frames == 5
    for frame in frames.values():
        assert frame.dtype == np.uint8
        assert frame.shape == (6, 8, 3)


def test_range_decode_png_sequence(tmp_path: Path) -> None:
    seq = _png_seq(tmp_path, frames=3)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    frames, stats = decode_frame_range(decoder, reader, seq, 0, 2)
    assert stats.decoded_frames == 3
    assert tuple(int(v) for v in frames[0][0, 0]) == (10, 20, 30)
    decode_frame_range(decoder, reader, seq, 0, 2)
    assert decoder.preview_cache_stats.hits >= 3


def test_range_decode_cancel(tmp_path: Path) -> None:
    reader = CountingUint8Reader(frame_count=20)
    decoder = FrameDecodeService(reader, prefetch_count=0)
    cancel = {"n": 0}

    def should_cancel() -> bool:
        cancel["n"] += 1
        return cancel["n"] > 3

    frames, stats = decode_frame_range(
        decoder,
        reader,
        tmp_path / "clip.mov",
        0,
        10,
        should_cancel=should_cancel,
    )
    assert len(frames) < 11
    assert stats.decoded_frames + stats.cache_hits == len(frames)


# --- ProjectController preview paths ---


def test_validation_and_extraction_use_decoder_not_direct_reader(
    tmp_path: Path,
    qapp: object,
) -> None:
    del qapp
    seq = _png_seq(tmp_path / "media", frames=4)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    controller = ProjectController()
    assert controller.create_project("Preview Path", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    package = project_root / "Preview_Path.nova"
    assert isinstance(controller._media_reader, ImageSequenceReader)

    # Drain import-time async decode/prefetch so counts stay deterministic.
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5_000)
    controller._frame_decoder.clear()
    controller._frame_decoder._prefetch_count = 0

    read_calls = {"n": 0}
    original = controller._media_reader.read_frame

    def _counting_read(path: Path, frame_number: int) -> np.ndarray:
        read_calls["n"] += 1
        return original(path, frame_number)

    controller._media_reader.read_frame = _counting_read  # type: ignore[method-assign]

    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[1:3, 1:3] = 255
    layer = SmartLayer(
        name="layer",
        object_identity=ObjectIdentity(),
        artist_intent=ArtistIntent(master_frame=0),
        frame_results=[
            FrameResult(
                frame_number=0,
                mask_reference="masks/m0.png",
                confidence=0.9,
                direction="master",
                provenance=CapabilityProvenance(
                    capability="segmentation",
                    adapter="test",
                    adapter_version="1",
                ),
                validation_state=ValidationState.ACCEPTED,
                evidence_ids=[],
            ),
            FrameResult(
                frame_number=2,
                mask_reference="masks/m2.png",
                confidence=0.9,
                direction="forward",
                provenance=CapabilityProvenance(
                    capability="segmentation",
                    adapter="test",
                    adapter_version="1",
                ),
                validation_state=ValidationState.ACCEPTED,
                evidence_ids=[],
            ),
        ],
    )
    shot.smart_layers = [layer]
    controller._mask_store.save(package, "masks/m0.png", mask)
    controller._mask_store.save(package, "masks/m2.png", mask)

    media = Path(shot.media.source_path)
    warm = controller._frame_decoder.get_preview_frame(
        media, 0, schedule_prefetch=False
    )
    warm2 = controller._frame_decoder.get_preview_frame(
        media, 2, schedule_prefetch=False
    )
    assert warm.dtype == np.uint8
    assert warm2.shape == (4, 4, 3)
    assert read_calls["n"] == 2

    previews = controller.validation_previews()
    assert len(previews) == 2
    assert read_calls["n"] == 2  # preview cache hits

    created = controller._create_extraction_previews(shot, layer)
    assert created is not None
    assert len(created) == 2
    assert read_calls["n"] == 2


def test_viewer_validation_share_oiio_decode(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path, frames=2)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    controller = ProjectController()
    assert controller.create_project("OIIO Share", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    package = project_root / "OIIO_Share.nova"
    mask = np.full((1, 1), 255, dtype=np.uint8)
    layer = SmartLayer(
        name="layer",
        object_identity=ObjectIdentity(),
        artist_intent=ArtistIntent(master_frame=0),
        frame_results=[
            FrameResult(
                frame_number=0,
                mask_reference="masks/m0.png",
                confidence=1.0,
                direction="master",
                provenance=CapabilityProvenance(
                    capability="segmentation",
                    adapter="test",
                    adapter_version="1",
                ),
                validation_state=ValidationState.PENDING,
                evidence_ids=[],
            )
        ],
    )
    shot.smart_layers = [layer]
    controller._mask_store.save(package, "masks/m0.png", mask)

    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(5_000)
    media = Path(shot.media.source_path)
    controller._frame_decoder.clear()
    controller._frame_decoder._prefetch_count = 0
    counter.clear()
    frame = controller._frame_decoder.get_preview_frame(
        media, 0, schedule_prefetch=False
    )
    assert frame.dtype == np.uint8
    assert len(counter) == 1

    previews = controller.validation_previews()
    assert len(previews) == 1
    assert previews[0][1].dtype == np.uint8
    assert len(counter) == 1


def test_preview_methods_have_no_direct_media_reader_read_frame() -> None:
    source = inspect.getsource(ProjectController)
    tree = ast.parse(source)
    class_body = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ProjectController"
    )
    targets = {"validation_previews", "_create_extraction_previews", "start_background_removal_preview"}
    for item in class_body.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if item.name not in targets:
            continue
        text = ast.get_source_segment(source, item) or ""
        assert "_media_reader.read_frame" not in text, item.name


def test_viewer_then_range_shares_oiio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path, frames=3)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    decoder.get_preview_frame(seq, 1, schedule_prefetch=False)
    assert len(counter) == 1
    decode_frame_range(decoder, reader, seq, 0, 2)
    # Frame 1 raw/preview already warm; frames 0 and 2 decode once each.
    assert len(counter) == 3
    decode_frame_range(decoder, reader, seq, 0, 2)
    assert len(counter) == 3
