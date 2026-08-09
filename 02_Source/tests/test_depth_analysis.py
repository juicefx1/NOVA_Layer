"""Phase D1 DepthAnalysisService tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.capabilities.fake_depth import FakeDepthAnalysisCapability
from nova_layer.app.depth_analysis import DepthAnalysisService
from nova_layer.app.depth_frame_cache import DepthFrameCache
from nova_layer.app.processing_frames import ProcessingColorPolicy
from nova_layer.ports.depth import (
    DepthAnalysisCancelled,
    DepthInferenceResult,
    DepthNormalization,
    InvalidDepthFrameError,
)


class RecordingDecoder:
    def __init__(self, image: np.ndarray) -> None:
        self.image = image
        self.calls: list[tuple[object, ...]] = []
        self.preview_calls = 0
        self.scene_calls = 0

    def get_processing_frame(
        self,
        path: Path,
        frame_number: int,
        *,
        policy: ProcessingColorPolicy,
        source_transform_request: object | None = None,
    ) -> np.ndarray:
        del source_transform_request
        self.calls.append((path, frame_number, policy))
        assert policy is ProcessingColorPolicy.SOURCE
        return self.image

    def get_preview_frame(self, *_a: object, **_k: object) -> np.ndarray:
        self.preview_calls += 1
        raise AssertionError("preview must not be used for depth")

    def get_scene_frame(self, *_a: object, **_k: object) -> object:
        self.scene_calls += 1
        raise AssertionError("scene must not be used for depth")


def _rgb(height: int = 4, width: int = 6) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)
    image[..., 1] = 40
    image[..., 2] = 80
    return image


def test_source_path_only_and_deterministic(tmp_path: Path) -> None:
    image = _rgb()
    decoder = RecordingDecoder(image)
    fake = FakeDepthAnalysisCapability()
    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=fake,
        cache=DepthFrameCache(max_entries=4, max_bytes=10_000_000),
    )
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    a = service.analyze(
        media_path=media,
        media_fingerprint="fp-a",
        frame_number=2,
    )
    b = service.analyze(
        media_path=media,
        media_fingerprint="fp-a",
        frame_number=2,
    )
    assert fake.call_count == 1  # second is cache hit
    assert np.allclose(a.depth, b.depth)
    assert decoder.preview_calls == 0
    assert decoder.scene_calls == 0
    assert all(call[2] is ProcessingColorPolicy.SOURCE for call in decoder.calls)


def test_wrong_output_shape_rejected(tmp_path: Path) -> None:
    image = _rgb(4, 6)
    decoder = RecordingDecoder(image)

    class BadShape:
        model_id = "bad"
        model_version = "1"
        preprocessing_version = "p"

        def infer(self, *, frame_number: int, image: np.ndarray) -> DepthInferenceResult:
            del frame_number, image
            return DepthInferenceResult(
                depth=np.linspace(0, 1, 4, dtype=np.float32).reshape(2, 2),
                valid_mask=None,
                quantity="relative_disparity",
                near_is="high",
                normalization=DepthNormalization(kind="model_native"),
                metadata={},
            )

    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=BadShape(),  # type: ignore[arg-type]
    )
    with pytest.raises(InvalidDepthFrameError, match="shape"):
        service.analyze(
            media_path=tmp_path / "m.mov",
            media_fingerprint="fp",
            frame_number=0,
        )


def test_cancel_before_source_decode(tmp_path: Path) -> None:
    decoder = RecordingDecoder(_rgb())
    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=FakeDepthAnalysisCapability(),
    )
    with pytest.raises(DepthAnalysisCancelled):
        service.analyze(
            media_path=tmp_path / "m.mov",
            media_fingerprint="fp",
            frame_number=0,
            should_cancel=lambda: True,
        )
    assert decoder.calls == []


def test_cancel_before_inference(tmp_path: Path) -> None:
    decoder = RecordingDecoder(_rgb())
    fake = FakeDepthAnalysisCapability()
    flags = {"n": 0}

    def should_cancel() -> bool:
        flags["n"] += 1
        # After cache miss: first check before decode (False), second before infer (True)
        return flags["n"] >= 2

    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=fake,
    )
    with pytest.raises(DepthAnalysisCancelled):
        service.analyze(
            media_path=tmp_path / "m.mov",
            media_fingerprint="fp",
            frame_number=0,
            should_cancel=should_cancel,
        )
    assert fake.call_count == 0
    assert len(decoder.calls) == 1


def test_cancel_before_cache_put(tmp_path: Path) -> None:
    decoder = RecordingDecoder(_rgb())
    fake = FakeDepthAnalysisCapability()
    flags = {"n": 0}

    def should_cancel() -> bool:
        flags["n"] += 1
        # 1 before decode, 2 before infer, 3 after canonicalize before put
        return flags["n"] >= 3

    cache = DepthFrameCache(max_entries=4, max_bytes=10_000_000)
    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=fake,
        cache=cache,
    )
    with pytest.raises(DepthAnalysisCancelled):
        service.analyze(
            media_path=tmp_path / "m.mov",
            media_fingerprint="fp",
            frame_number=0,
            should_cancel=should_cancel,
        )
    assert fake.call_count == 1
    assert cache.stats().count == 0


@pytest.mark.parametrize("label", ["png", "video", "exr"])
def test_source_contract_mock_media_kinds(tmp_path: Path, label: str) -> None:
    decoder = RecordingDecoder(_rgb(8, 8))
    service = DepthAnalysisService(
        frame_decoder=decoder,  # type: ignore[arg-type]
        capability=FakeDepthAnalysisCapability(),
    )
    frame = service.analyze(
        media_path=tmp_path / "media.bin",
        media_fingerprint=f"fp-{label}",
        frame_number=1,
    )
    assert frame.input_policy == "source_v1"
    assert frame.depth.shape == (8, 8)
    assert frame.depth.dtype == np.float32
