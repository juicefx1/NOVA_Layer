"""Phase 10C-1: Working-space contracts, identity, cache skeleton, diagnostics."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from nova_layer.app.color_pipeline_diagnostics import (
    build_color_pipeline_diagnostics,
    format_color_pipeline_diagnostics,
)
from nova_layer.app.preview_pipeline import PreviewPipeline
from nova_layer.app.processing_frames import SOURCE_TRANSFORM_VERSION
from nova_layer.app.raw_frame_cache import RawFrameCache
from nova_layer.app.working_scene_cache import (
    DEFAULT_WORKING_CACHE_MAX_BYTES,
    DEFAULT_WORKING_SCENE_CACHE_SIZE,
    WorkingSceneCache,
)
from nova_layer.app.working_space import (
    WORKING_CONVERTER_VERSION,
    WorkingSpaceSettings,
    WorkingTransformIdentity,
    resolve_working_space_intent,
)
from nova_layer.ports.scene_frames import SceneFrame, WorkingSceneFrame


def _identity(**overrides: str) -> WorkingTransformIdentity:
    base = {
        "source_color_space": "ACEScg",
        "working_color_space": "scene_linear",
        "ocio_config_identity": "/tmp/config.ocio|env",
        "converter_version": WORKING_CONVERTER_VERSION,
    }
    base.update(overrides)
    return WorkingTransformIdentity(**base)


def _working_frame(
    path: Path,
    frame_number: int = 0,
    *,
    pixels: np.ndarray | None = None,
    identity: WorkingTransformIdentity | None = None,
) -> WorkingSceneFrame:
    tid = identity or _identity()
    arr = (
        pixels
        if pixels is not None
        else np.full((2, 2, 3), 0.25, dtype=np.float32)
    )
    return WorkingSceneFrame(
        path=path.resolve(),
        frame_number=frame_number,
        pixels=arr,
        width=int(arr.shape[1]),
        height=int(arr.shape[0]),
        source_color_space=tid.source_color_space,
        working_color_space=tid.working_color_space,
        ocio_config_identity=tid.ocio_config_identity,
        converter_version=tid.converter_version,
    )


# ---------------------------------------------------------------------------
# WorkingSpaceSettings / intent
# ---------------------------------------------------------------------------


def test_working_space_settings_default_disabled() -> None:
    settings = WorkingSpaceSettings()
    assert settings.enabled is False
    assert settings.working_color_space is None
    assert settings.use_scene_linear_role is True
    assert settings.converter_version == WORKING_CONVERTER_VERSION
    intent = resolve_working_space_intent(settings)
    assert intent.enabled is False
    assert intent.resolution_source == "disabled"
    assert intent.warnings == ()


def test_working_space_explicit_setting() -> None:
    settings = WorkingSpaceSettings(
        enabled=True,
        working_color_space="ACEScg",
        use_scene_linear_role=True,
    )
    intent = resolve_working_space_intent(settings)
    assert intent.enabled is True
    assert intent.requested_color_space == "ACEScg"
    assert intent.resolution_source == "explicit"
    assert intent.warnings == ()


def test_working_space_scene_linear_role_intent() -> None:
    settings = WorkingSpaceSettings(enabled=True, working_color_space=None)
    intent = resolve_working_space_intent(settings)
    assert intent.enabled is True
    assert intent.requested_color_space == "scene_linear"
    assert intent.resolution_source == "scene_linear_role"
    assert intent.warnings
    assert "scene_linear" in intent.warnings[0]


def test_working_space_empty_normalization() -> None:
    settings = WorkingSpaceSettings(
        enabled=True,
        working_color_space="  ",
        use_scene_linear_role=False,
        converter_version="  ",
    )
    assert settings.working_color_space is None
    assert settings.converter_version == WORKING_CONVERTER_VERSION
    intent = resolve_working_space_intent(settings)
    assert intent.resolution_source == "unspecified"
    assert intent.warnings
    assert intent.requested_color_space is None


def test_working_space_intent_none_settings() -> None:
    intent = resolve_working_space_intent(None)
    assert intent.enabled is False
    assert intent.resolution_source == "disabled"


# ---------------------------------------------------------------------------
# WorkingTransformIdentity
# ---------------------------------------------------------------------------


def test_working_transform_identity_equality_hash() -> None:
    a = _identity()
    b = _identity()
    c = _identity(working_color_space="ACEScg")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    assert {a, b, c} == {a, c}


def test_working_transform_identity_field_normalization() -> None:
    identity = WorkingTransformIdentity(
        source_color_space="  ACEScg  ",
        working_color_space=" scene_linear ",
        ocio_config_identity=" /tmp/x.ocio ",
        converter_version=f"  {WORKING_CONVERTER_VERSION}  ",
    )
    assert identity.source_color_space == "ACEScg"
    assert identity.working_color_space == "scene_linear"
    assert identity.ocio_config_identity == "/tmp/x.ocio"
    assert identity.converter_version == WORKING_CONVERTER_VERSION


def test_working_transform_identity_missing_required() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        WorkingTransformIdentity(
            source_color_space="",
            working_color_space="scene_linear",
            ocio_config_identity="/tmp/x.ocio",
            converter_version=WORKING_CONVERTER_VERSION,
        )
    assert (
        WorkingTransformIdentity.try_create(
            source_color_space="ACEScg",
            working_color_space=None,
            ocio_config_identity="/tmp/x.ocio",
        )
        is None
    )


# ---------------------------------------------------------------------------
# WorkingSceneFrame
# ---------------------------------------------------------------------------


def test_working_scene_frame_metadata() -> None:
    path = Path("/tmp/seq").resolve()
    pixels = np.full((3, 4, 3), -0.5, dtype=np.float32)
    frame = _working_frame(path, pixels=pixels)
    assert frame.pixels.dtype == np.float32
    assert frame.pixels.shape == (3, 4, 3)
    assert frame.width == 4
    assert frame.height == 3
    assert frame.channels == 3
    assert frame.pixel_format == "float32_rgb"
    assert frame.source_color_space == "ACEScg"
    assert frame.working_color_space == "scene_linear"


def test_working_scene_frame_immutable_and_mutation_policy() -> None:
    frame = _working_frame(Path("/tmp/a"))
    with pytest.raises(Exception):
        frame.width = 99  # type: ignore[misc]
    # Dataclass is frozen but ndarray buffer may still be writable; caches copy.
    assert frame.pixels.flags.writeable
    original = float(frame.pixels[0, 0, 0])
    frame.pixels[0, 0, 0] = 9.0
    assert float(frame.pixels[0, 0, 0]) != original


# ---------------------------------------------------------------------------
# WorkingSceneCache
# ---------------------------------------------------------------------------


def test_working_scene_cache_put_get_and_identity() -> None:
    cache = WorkingSceneCache(max_entries=4, max_bytes=10_000)
    path = Path("/tmp/ws").resolve()
    identity = _identity()
    frame = _working_frame(path, identity=identity)
    assert cache.put(frame) is True
    got = cache.get(path, 0, identity)
    assert got is not None
    assert got.source_color_space == "ACEScg"
    assert got.working_color_space == "scene_linear"
    assert got.converter_version == WORKING_CONVERTER_VERSION
    assert np.array_equal(got.pixels, frame.pixels)
    other = _identity(working_color_space="ACEScg")
    assert cache.get(path, 0, other) is None
    assert cache.stats().hits == 1
    assert cache.stats().misses == 1


def test_working_scene_cache_copy_on_get() -> None:
    cache = WorkingSceneCache(max_entries=2, max_bytes=10_000)
    path = Path("/tmp/copy").resolve()
    identity = _identity()
    frame = _working_frame(path, identity=identity)
    cache.put(frame)
    got = cache.get(path, 0, identity)
    assert got is not None
    got.pixels[0, 0, 0] = 1.0
    again = cache.get(path, 0, identity)
    assert again is not None
    assert float(again.pixels[0, 0, 0]) == pytest.approx(0.25)


def test_working_scene_cache_byte_accounting_and_lru() -> None:
    # 2x2x3 float32 = 48 bytes
    cache = WorkingSceneCache(max_entries=2, max_bytes=100)
    path = Path("/tmp/lru").resolve()
    identity = _identity()
    assert cache.put(_working_frame(path, 0, identity=identity)) is True
    assert cache.put(_working_frame(path, 1, identity=identity)) is True
    assert cache.count == 2
    assert cache.current_bytes == 96
    assert cache.put(_working_frame(path, 2, identity=identity)) is True
    assert cache.count == 2
    assert cache.stats().evictions >= 1
    assert cache.get(path, 0, identity) is None
    assert cache.get(path, 2, identity) is not None


def test_working_scene_cache_clear() -> None:
    cache = WorkingSceneCache(max_entries=2, max_bytes=10_000)
    path = Path("/tmp/clear").resolve()
    identity = _identity()
    cache.put(_working_frame(path, identity=identity))
    cache.clear()
    assert cache.count == 0
    assert cache.current_bytes == 0
    assert cache.get(path, 0, identity) is None


def test_working_scene_cache_env_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_WORKING_CACHE_MB", "3")
    cache = WorkingSceneCache()
    assert cache.max_bytes == 3 * 1024 * 1024
    assert cache.max_entries == DEFAULT_WORKING_SCENE_CACHE_SIZE
    monkeypatch.delenv("NOVA_WORKING_CACHE_MB", raising=False)
    cache2 = WorkingSceneCache()
    assert cache2.max_bytes == DEFAULT_WORKING_CACHE_MAX_BYTES


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_default_working_disabled() -> None:
    snap = build_color_pipeline_diagnostics()
    assert snap.working_enabled is False
    assert snap.requested_working_color_space is None
    assert snap.resolved_working_color_space is None
    assert snap.working_resolution_source == "disabled"
    assert snap.working_converter_version == WORKING_CONVERTER_VERSION
    assert snap.working_cache.count == 0
    assert snap.working_warnings == ()
    text = format_color_pipeline_diagnostics(snap)
    assert "Working Space:" in text
    assert "Enabled: False" in text


def test_diagnostics_working_intent_warnings() -> None:
    settings = WorkingSpaceSettings(enabled=True, working_color_space=None)
    snap = build_color_pipeline_diagnostics(working_settings=settings)
    assert snap.working_enabled is True
    assert snap.requested_working_color_space == "scene_linear"
    assert snap.working_resolution_source == "scene_linear_role"
    assert snap.resolved_working_color_space is None
    assert snap.working_warnings
    text = format_color_pipeline_diagnostics(snap)
    assert "Working warnings:" in text
    assert "scene_linear" in text


def test_diagnostics_with_working_cache_stats() -> None:
    cache = WorkingSceneCache(max_entries=2, max_bytes=10_000)
    path = Path("/tmp/diag").resolve()
    cache.put(_working_frame(path))
    snap = build_color_pipeline_diagnostics(
        working_settings=WorkingSpaceSettings(enabled=True, working_color_space="ACEScg"),
        working_cache_stats=cache.stats(),
    )
    assert snap.working_cache.count == 1
    assert snap.requested_working_color_space == "ACEScg"
    assert snap.working_resolution_source == "explicit"


# ---------------------------------------------------------------------------
# Static contracts — no silent behaviour change
# ---------------------------------------------------------------------------


def test_static_scene_frame_and_raw_key_unchanged() -> None:
    frame = SceneFrame(
        path=Path("/tmp"),
        frame_number=0,
        pixels=np.zeros((1, 1, 3), dtype=np.float32),
        width=1,
        height=1,
    )
    assert frame.color_space is None
    assert frame.color_space_source == "unspecified"
    cache = RawFrameCache(max_entries=2, max_bytes=10_000)
    assert cache.put(frame) is True
    assert cache.contains(Path("/tmp"), 0) is True


def test_static_source_transform_version_locked() -> None:
    assert SOURCE_TRANSFORM_VERSION == "source_legacy_srgb_v1"
    assert WORKING_CONVERTER_VERSION == "working_scene_v1"


def test_static_preview_pipeline_has_no_working_wiring() -> None:
    source = inspect.getsource(PreviewPipeline)
    assert "WorkingSceneCache" not in source
    assert "WorkingSceneFrame" not in source
    assert "resolve_working_space_intent" not in source
    assert "WorkingTransformIdentity" not in source
    assert "working_space" not in source
