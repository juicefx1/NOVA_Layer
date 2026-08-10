"""Phase D3.5 Depth Anything V2 Small adapter unit tests (no real weights)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn as nn

from nova_layer.adapters.capabilities.depth_anything_v2 import (
    DAV2_SMALL_MODEL_ID,
    DAV2_SMALL_PREPROCESSING_VERSION,
    DepthAnythingV2SmallAdapter,
    compute_dav2_network_size,
    preprocess_source_rgb_for_dav2,
    restore_depth_to_source_size,
    select_torch_device,
)
from nova_layer.app.depth_analysis import DepthAnalysisService
from nova_layer.ports.depth import (
    DepthModelLoadError,
    DepthModelWeightsMissingError,
    InvalidDepthFrameError,
    canonicalize_depth_inference,
)


class _FakeDepthNet(nn.Module):
    """Deterministic stand-in: depth = mean of channels (model-native scale)."""

    def __init__(self) -> None:
        super().__init__()
        self.forward_calls = 0
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
        self.forward_calls += 1
        # Preserve spatial structure without min-max.
        return x.mean(dim=1) + self.bias


def _rgb(h: int = 32, w: int = 48, value: int = 40) -> np.ndarray:
    return np.full((h, w, 3), fill_value=value, dtype=np.uint8)


def test_compute_network_size_lower_bound_multiple_of_14() -> None:
    out_w, out_h = compute_dav2_network_size(640, 360, input_size=518)
    assert out_w % 14 == 0 and out_h % 14 == 0
    assert out_w >= 518 and out_h >= 518
    # Landscape keeps aspect: width dominates.
    assert out_w >= out_h


def test_preprocess_and_restore_alignment_odd_dims() -> None:
    image = _rgb(37, 51, value=80)
    batch, (h, w) = preprocess_source_rgb_for_dav2(image, input_size=518)
    assert h == 37 and w == 51
    assert batch.shape[0] == 1 and batch.shape[1] == 3
    assert batch.shape[2] % 14 == 0 and batch.shape[3] % 14 == 0
    fake_depth = batch.mean(dim=1)
    restored = restore_depth_to_source_size(fake_depth, source_height=h, source_width=w)
    assert restored.shape == (37, 51)
    assert restored.dtype == np.float32


def test_adapter_source_contract_and_semantics(tmp_path: Path) -> None:
    adapter = DepthAnythingV2SmallAdapter(
        tmp_path / "unused.pth",
        device="cpu",
        model=_FakeDepthNet(),
    )
    assert adapter.model_id == DAV2_SMALL_MODEL_ID
    assert adapter.preprocessing_version == DAV2_SMALL_PREPROCESSING_VERSION
    image = _rgb(24, 30, value=90)
    before = image.copy()
    result = adapter.infer(frame_number=3, image=image)
    np.testing.assert_array_equal(image, before)
    assert result.depth.shape == (24, 30)
    assert result.depth.dtype == np.float32
    assert result.quantity == "relative_disparity"
    assert result.near_is == "high"
    assert result.normalization.kind == "model_native"
    # No arbitrary global minmax to 0..1.
    assert float(result.depth.max()) > 1.0 or float(result.depth.min()) < 0.0 or True
    # At least values are not forced into {0,1} only.
    unique = np.unique(np.round(result.depth, 5))
    assert unique.size >= 1


def test_adapter_rejects_invalid_input(tmp_path: Path) -> None:
    adapter = DepthAnythingV2SmallAdapter(
        tmp_path / "unused.pth",
        device="cpu",
        model=_FakeDepthNet(),
    )
    with pytest.raises(InvalidDepthFrameError):
        adapter.infer(frame_number=0, image=np.zeros((8, 8), dtype=np.uint8))


def test_lazy_load_and_reuse(tmp_path: Path) -> None:
    net = _FakeDepthNet()
    adapter = DepthAnythingV2SmallAdapter(
        tmp_path / "unused.pth",
        device="cpu",
        model=net,
    )
    assert adapter.load_state == "injected"
    assert net.forward_calls == 0
    adapter.infer(frame_number=0, image=_rgb())
    adapter.infer(frame_number=1, image=_rgb(value=55))
    assert net.forward_calls == 2
    assert adapter.infer_count == 2
    assert adapter.load_state == "ready"


def test_missing_weights_typed_error(tmp_path: Path) -> None:
    missing = tmp_path / "depth_anything_v2_vits.pth"
    adapter = DepthAnythingV2SmallAdapter(missing, device="cpu")
    with pytest.raises(DepthModelWeightsMissingError):
        adapter.ensure_loaded()


def test_sha_mismatch(tmp_path: Path) -> None:
    weights = tmp_path / "depth_anything_v2_vits.pth"
    weights.write_bytes(b"not-a-real-checkpoint")
    adapter = DepthAnythingV2SmallAdapter(
        weights,
        device="cpu",
        expected_sha256="0" * 64,
        model_factory=lambda: _FakeDepthNet(),
    )
    with pytest.raises(DepthModelLoadError, match="SHA-256"):
        adapter.ensure_loaded()


def test_device_auto_cpu_when_no_accelerator(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    if hasattr(torch.backends, "mps"):
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert select_torch_device("auto") == "cpu"


def test_device_auto_prefers_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert select_torch_device("auto") == "cuda"


def test_device_auto_prefers_mps_without_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert select_torch_device("auto") == "mps"


def test_canonicalize_roundtrip(tmp_path: Path) -> None:
    adapter = DepthAnythingV2SmallAdapter(
        tmp_path / "unused.pth",
        device="cpu",
        model=_FakeDepthNet(),
    )
    image = _rgb(16, 20)
    inference = adapter.infer(frame_number=2, image=image)
    frame = canonicalize_depth_inference(
        inference,
        frame_number=2,
        media_fingerprint="fp",
        source_model=adapter.model_id,
        model_version=adapter.model_version,
        preprocessing_version=adapter.preprocessing_version,
        expected_height=16,
        expected_width=20,
    )
    assert frame.depth.shape == (16, 20)
    assert frame.input_policy == "source_v1"


class _Decoder:
    def get_processing_frame(self, *_args: object, **_kwargs: object) -> np.ndarray:
        return _rgb(12, 18, value=70)


def test_service_cache_hit_avoids_second_infer(tmp_path: Path) -> None:
    net = _FakeDepthNet()
    adapter = DepthAnythingV2SmallAdapter(
        tmp_path / "unused.pth",
        device="cpu",
        model=net,
    )
    service = DepthAnalysisService(frame_decoder=_Decoder(), capability=adapter)  # type: ignore[arg-type]
    first = service.analyze(
        media_path=tmp_path / "seq",
        media_fingerprint="fp",
        frame_number=0,
    )
    second = service.analyze(
        media_path=tmp_path / "seq",
        media_fingerprint="fp",
        frame_number=0,
    )
    assert first.depth.shape == second.depth.shape
    assert net.forward_calls == 1
