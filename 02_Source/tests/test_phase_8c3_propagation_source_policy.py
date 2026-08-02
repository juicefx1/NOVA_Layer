"""Phase 8C-3: Propagation range decode uses SOURCE (not PREVIEW)."""

from __future__ import annotations

import ast
import inspect
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
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.app.project_controller import ProjectController
from nova_layer.app.range_decode import decode_frame_range
from nova_layer.domain.models import BoundingRegion, GuidancePoint
from nova_layer.ports.capabilities import PropagationResult, VideoFrame
from nova_layer.ports.media import MediaInfo, MediaReadError


class CountingUint8Reader:
    def __init__(self, frame_count: int = 8) -> None:
        self.frame_count = frame_count
        self.read_frame_calls = 0
        self.read_order: list[int] = []

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
        self.read_frame_calls += 1
        self.read_order.append(frame_number)
        return np.full((6, 8, 3), frame_number % 256, dtype=np.uint8)


class CapturingPropagation:
    def __init__(self) -> None:
        self.frames: list[VideoFrame] = []

    def propagate(
        self,
        *,
        master_frame: int,
        target_frames: list[int],
        reference_mask: str,
        reference_mask_data: np.ndarray,
        frames: list[VideoFrame],
    ) -> list[PropagationResult]:
        del reference_mask
        self.frames = [
            VideoFrame(frame_number=item.frame_number, image=item.image.copy())
            for item in frames
        ]
        from nova_layer.domain.models import CapabilityProvenance

        provenance = CapabilityProvenance(
            capability="temporal_propagation",
            adapter="capture",
            adapter_version="1",
        )
        return [
            PropagationResult(
                frame_number=frame,
                mask_reference=f"masks/cap_{frame:06d}.png",
                mask=reference_mask_data.copy(),
                confidence=0.9,
                provenance=provenance,
            )
            for frame in target_frames
            if frame != master_frame
        ]


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
            return np.full((2, 2, 3), 0.18, dtype=np.float32)

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


# --- Policy API ---


def test_default_policy_is_preview(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    path = tmp_path / "clip.mov"
    decode_frame_range(decoder, reader, path, 0, 2)
    # Default warms preview via get_preview_frame path for non-PyAv.
    assert decoder.get_cached(path, 0) is not None


def test_scene_policy_raises(tmp_path: Path) -> None:
    reader = CountingUint8Reader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    with pytest.raises(MediaReadError, match="SCENE"):
        decode_frame_range(
            decoder,
            reader,
            tmp_path / "clip.mov",
            0,
            1,
            policy=ProcessingColorPolicy.SCENE,
        )


def test_source_range_does_not_pollute_preview(
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
    preview_before = decoder.preview_cache_stats.count
    decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    assert decoder.preview_cache_stats.count == preview_before
    assert decoder.source_cache_stats.count >= 1


def test_source_range_reuses_raw_and_source_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    assert len(counter) == 3
    _, stats = decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    assert stats.cache_hits == 3
    assert stats.decoded_frames == 0
    assert len(counter) == 3


def test_viewer_preview_then_source_prop_shares_oiio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    decoder.get_preview_frame(seq, 1, schedule_prefetch=False)
    assert len(counter) == 1
    decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    # Frame 1 raw warm; 0 and 2 decode once each.
    assert len(counter) == 3


def test_source_stable_after_exposure(
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
        decoder, reader, seq, 0, 1, policy=ProcessingColorPolicy.SOURCE
    )
    decoder.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    second, stats = decode_frame_range(
        decoder, reader, seq, 0, 1, policy=ProcessingColorPolicy.SOURCE
    )
    assert stats.cache_hits == 2
    np.testing.assert_array_equal(first[0], second[0])
    assert len(counter) == 2


def test_png_source_range(tmp_path: Path) -> None:
    seq = _png_seq(tmp_path)
    reader = ImageSequenceReader()
    decoder = FrameDecodeService(reader, prefetch_count=0)
    frames, stats = decode_frame_range(
        decoder, reader, seq, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    assert stats.decoded_frames == 3
    assert tuple(int(v) for v in frames[0][0, 0]) == (10, 20, 30)


def test_source_preview_video_like_bit_identical(tmp_path: Path) -> None:
    reader = CountingUint8Reader(frame_count=4)
    decoder = FrameDecodeService(reader, prefetch_count=0)
    path = tmp_path / "clip.mov"
    preview, _ = decode_frame_range(
        decoder, reader, path, 0, 2, policy=ProcessingColorPolicy.PREVIEW
    )
    decoder.clear()
    reader.read_frame_calls = 0
    source, _ = decode_frame_range(
        decoder, reader, path, 0, 2, policy=ProcessingColorPolicy.SOURCE
    )
    for frame in (0, 1, 2):
        np.testing.assert_array_equal(preview[frame], source[frame])


def test_source_cancel_partial(tmp_path: Path) -> None:
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
        policy=ProcessingColorPolicy.SOURCE,
        should_cancel=should_cancel,
    )
    assert len(frames) < 11
    assert stats.decoded_frames + stats.cache_hits == len(frames)


def test_source_tiny_budget_completes(tmp_path: Path) -> None:
    reader = CountingUint8Reader(frame_count=5)
    decoder = FrameDecodeService(
        reader,
        prefetch_count=0,
        cache_size=1,
        preview_cache_max_bytes=1,
    )
    frames, stats = decode_frame_range(
        decoder, reader, tmp_path / "clip.mov", 0, 4, policy=ProcessingColorPolicy.SOURCE
    )
    assert set(frames) == {0, 1, 2, 3, 4}
    assert stats.decoded_frames == 5


# --- ProjectController ---


def test_propagation_uses_source_matching_hypothesis(
    tmp_path: Path,
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    counter: list[int] = []
    _fake_oiio(monkeypatch, counter)
    seq = _exr_seq(tmp_path, frames=4)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    capture = CapturingPropagation()
    controller = ProjectController(
        propagation=capture,
        display_transform=ViewerDisplayTransform(
            exposure=ExposureTransform(0.0),
            display_transform=LegacyDisplayTransform(),
        ),
    )
    assert controller.create_project("Prop Src", project_root) is not None
    shot = controller.import_media(seq)
    assert shot is not None
    controller.update_artist_guidance(
        [GuidancePoint(x=0.5, y=0.5, polarity="positive")],
        BoundingRegion(x=0.2, y=0.2, width=0.4, height=0.4),
    )
    assert controller.generate_hypothesis() is not None
    assert controller.accept_hypothesis()

    master = shot.master_frame
    master_source = controller._get_source_processing_frame(
        Path(shot.media.source_path), master
    )
    assert controller.propagate_confirmed_identity()
    assert capture.frames
    by_frame = {item.frame_number: item.image for item in capture.frames}
    assert master in by_frame
    np.testing.assert_array_equal(by_frame[master], master_source)

    # Exposure change must not alter SOURCE adapter inputs on re-decode path.
    controller.set_display_transform(
        ViewerDisplayTransform(
            exposure=ExposureTransform(2.0),
            display_transform=LegacyDisplayTransform(),
        )
    )
    before = {n: img.copy() for n, img in by_frame.items()}
    capture.frames = []
    frames = controller._decode_shot_frames(shot)
    for item in frames:
        np.testing.assert_array_equal(item.image, before[item.frame_number])


def test_decode_shot_frames_default_source_is_source() -> None:
    text = inspect.getsource(ProjectController._decode_shot_frames)
    assert "policy: ProcessingColorPolicy = ProcessingColorPolicy.SOURCE" in text


def test_static_propagation_source_and_export_preview() -> None:
    source = inspect.getsource(ProjectController)
    tree = ast.parse(source)
    class_body = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProjectController"
    )

    def _fn_text(name: str) -> str:
        for item in class_body.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                return ast.get_source_segment(source, item) or ""
        raise AssertionError(name)

    assert "ProcessingColorPolicy.SOURCE" in _fn_text("_decode_shot_frames")
    assert "policy=ProcessingColorPolicy.SOURCE" in _fn_text("start_propagation")

    for item in class_body.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        text = ast.get_source_segment(source, item) or ""
        if "decode_frame_range" not in text:
            continue
        if item.name in {"start_propagation", "_decode_shot_frames"}:
            continue
        assert "policy=ProcessingColorPolicy.SOURCE" not in text, item.name
