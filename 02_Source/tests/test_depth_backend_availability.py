"""Phase D3.5 depth backend factory / diagnostics tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from nova_layer.adapters.capabilities.depth_anything_v2 import DAV2_SMALL_CHECKPOINT_NAME
from nova_layer.app.depth_backend import (
    ENV_DEPTH_MODEL_PATH,
    create_default_depth_capability,
    create_depth_anything_v2_small_adapter,
    depth_backend_diagnostics,
    is_depth_backend_available,
    resolve_depth_model_path,
)
from nova_layer.ports.depth import DepthModelWeightsMissingError


def test_resolve_explicit_and_env(tmp_path: Path) -> None:
    weights = tmp_path / DAV2_SMALL_CHECKPOINT_NAME
    weights.write_bytes(b"abc")
    assert resolve_depth_model_path(explicit=weights) == weights.resolve()
    assert (
        resolve_depth_model_path(environ={ENV_DEPTH_MODEL_PATH: str(weights)})
        == weights.resolve()
    )


def test_resolve_env_directory(tmp_path: Path) -> None:
    directory = tmp_path / "models"
    directory.mkdir()
    weights = directory / DAV2_SMALL_CHECKPOINT_NAME
    weights.write_bytes(b"abc")
    assert (
        resolve_depth_model_path(environ={ENV_DEPTH_MODEL_PATH: str(directory)})
        == weights.resolve()
    )


def test_missing_model_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DEPTH_MODEL_PATH, raising=False)
    monkeypatch.setattr(
        "nova_layer.app.depth_backend.default_depth_model_directories",
        lambda: (tmp_path / "empty",),
    )
    assert resolve_depth_model_path() is None
    assert is_depth_backend_available(environ={}) is False
    assert create_default_depth_capability(environ={}) is None
    with pytest.raises(DepthModelWeightsMissingError):
        create_depth_anything_v2_small_adapter(environ={})


def test_diagnostics_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nova_layer.app.depth_backend.default_depth_model_directories",
        lambda: (tmp_path / "empty",),
    )
    diag = depth_backend_diagnostics(None, environ={})
    assert diag.available is False
    assert diag.backend == "depth_anything_v2_small"
    assert diag.last_error


def test_create_adapter_from_explicit_path(tmp_path: Path) -> None:
    weights = tmp_path / DAV2_SMALL_CHECKPOINT_NAME
    weights.write_bytes(b"placeholder")
    adapter = create_depth_anything_v2_small_adapter(
        model_path=weights,
        device="cpu",
        environ={},
    )
    assert adapter.model_path == weights.resolve()
    diag = depth_backend_diagnostics(adapter)
    assert diag.available is True
    assert diag.weights_path == str(weights.resolve())
