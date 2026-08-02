"""Phase 10B: Scene Linear EXR header metadata (best-effort convenience attrs)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.export.scene_exr import (
    SCENE_EXR_WRITER_VERSION,
    ExrHeaderWriteResult,
    SceneExrError,
    SceneExrHeaderMetadata,
    apply_openexr_header_attributes,
    build_openexr_header_attributes,
    sanitize_header_text,
    write_scene_openexr_rgba,
)
from nova_layer.export.smart_layer import (
    ExportFormat,
    export_smart_layer_assets,
    write_openexr_rgba,
)

from test_phase_10a_true_scene_export import _scene_package


def _sample_metadata(**overrides: object) -> SceneExrHeaderMetadata:
    base = dict(
        color_policy="scene",
        scene_linear=True,
        source_color_space="ACEScg",
        interpretation_color_space="Linear Rec.709",
        premultiplied=False,
        alpha_mode="straight",
        pixel_encoding="file_native_scene_half",
        source_render_version=1,
        source_fingerprint="fp-abc",
        project_id="project-1",
        shot_id="shot-1",
        layer_id="layer-1",
        frame_number=0,
        writer_version=SCENE_EXR_WRITER_VERSION,
        frames_per_second=24.0,
        software="NOVA Layer",
    )
    base.update(overrides)
    return SceneExrHeaderMetadata(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def test_serializer_string_bool_int_float_and_omit() -> None:
    attrs = build_openexr_header_attributes(_sample_metadata())
    assert attrs["software"] == b"NOVA Layer"
    assert attrs["nova:colorPolicy"] == b"scene"
    assert attrs["nova:sourceColorSpace"] == b"ACEScg"
    assert attrs["nova:interpretationColorSpace"] == b"Linear Rec.709"
    assert attrs["nova:alphaMode"] == b"straight"
    assert attrs["nova:sceneLinear"] == 1
    assert attrs["nova:premultiplied"] == 0
    assert attrs["nova:sourceRenderVersion"] == 1
    assert attrs["nova:frameNumber"] == 0
    assert attrs["framesPerSecond"] == 24.0
    assert isinstance(attrs["software"], bytes)
    assert list(attrs.keys()) == [
        key
        for key in (
            "software",
            "framesPerSecond",
            "nova:colorPolicy",
            "nova:sceneLinear",
            "nova:sourceColorSpace",
            "nova:interpretationColorSpace",
            "nova:premultiplied",
            "nova:alphaMode",
            "nova:pixelEncoding",
            "nova:sourceRenderVersion",
            "nova:sourceFingerprint",
            "nova:projectId",
            "nova:shotId",
            "nova:layerId",
            "nova:frameNumber",
            "nova:writerVersion",
        )
        if key in attrs
    ]


def test_serializer_omits_none_nan_inf_and_empty() -> None:
    attrs = build_openexr_header_attributes(
        _sample_metadata(
            source_color_space=None,
            interpretation_color_space=None,
            source_fingerprint=None,
            project_id=None,
            shot_id=None,
            layer_id=None,
            source_render_version=None,
            frames_per_second=float("nan"),
        )
    )
    assert "nova:sourceColorSpace" not in attrs
    assert "nova:interpretationColorSpace" not in attrs
    assert "nova:sourceFingerprint" not in attrs
    assert "nova:projectId" not in attrs
    assert "nova:sourceRenderVersion" not in attrs
    assert "framesPerSecond" not in attrs
    attrs_inf = build_openexr_header_attributes(
        _sample_metadata(frames_per_second=float("inf"))
    )
    assert "framesPerSecond" not in attrs_inf


def test_serializer_utf8_stable_keys() -> None:
    attrs = build_openexr_header_attributes(
        _sample_metadata(source_color_space="선형-테스트")
    )
    assert attrs["nova:sourceColorSpace"] == "선형-테스트".encode("utf-8")
    again = build_openexr_header_attributes(
        _sample_metadata(source_color_space="선형-테스트")
    )
    assert list(attrs.keys()) == list(again.keys())


def test_sanitize_header_text_paths() -> None:
    assert sanitize_header_text("ACEScg") == "ACEScg"
    assert sanitize_header_text("/Users/juwon/.config/ocio/config.ocio") == "config.ocio"
    assert sanitize_header_text("~/secret/config.ocio") == "config.ocio"
    assert sanitize_header_text("C:\\Users\\x\\a.ocio") == "a.ocio"
    assert sanitize_header_text("") is None
    assert sanitize_header_text(None) is None
    assert sanitize_header_text("/Users/juwon/") is None or sanitize_header_text(
        "/Users/juwon/"
    ) not in {"/Users/juwon/", "~"}


def test_sanitize_drops_abs_into_attributes() -> None:
    attrs = build_openexr_header_attributes(
        _sample_metadata(
            source_fingerprint="/Users/juwon/Desktop/secret_media",
            interpretation_color_space="/opt/ocio/config.ocio",
        )
    )
    # Path-like values become basename tokens (never full home paths).
    assert attrs["nova:sourceFingerprint"] == b"secret_media"
    assert b"/Users/" not in attrs["nova:sourceFingerprint"]
    assert attrs["nova:interpretationColorSpace"] == b"config.ocio"
    assert b"/opt/" not in attrs["nova:interpretationColorSpace"]


# ---------------------------------------------------------------------------
# Header roundtrip
# ---------------------------------------------------------------------------


def _read_header(path: Path) -> dict:
    OpenEXR = pytest.importorskip("OpenEXR")
    inp = OpenEXR.InputFile(str(path))
    try:
        return dict(inp.header())
    finally:
        inp.close()


def test_header_roundtrip_scene_fields(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    rgba = np.zeros((2, 2, 4), dtype=np.float32)
    rgba[..., 0] = -0.25
    rgba[..., 3] = 0.5
    path = tmp_path / "meta.exr"
    result = write_scene_openexr_rgba(
        path,
        rgba,
        metadata=_sample_metadata(frame_number=7, frames_per_second=23.976),
    )
    assert "nova:sceneLinear" in result.written_keys
    header = _read_header(path)
    assert header.get("software") == b"NOVA Layer"
    assert header.get("nova:colorPolicy") == b"scene"
    assert header.get("nova:sceneLinear") == 1
    assert header.get("nova:premultiplied") == 0
    assert header.get("nova:alphaMode") == b"straight"
    assert header.get("nova:sourceColorSpace") == b"ACEScg"
    assert header.get("nova:interpretationColorSpace") == b"Linear Rec.709"
    assert header.get("nova:frameNumber") == 7
    assert header.get("framesPerSecond") == pytest.approx(23.976)
    assert header.get("nova:writerVersion") == SCENE_EXR_WRITER_VERSION.encode("utf-8")
    assert "chromaticities" not in header


def test_header_frame_number_differs_per_file(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    rgba = np.zeros((1, 1, 4), dtype=np.float32)
    rgba[..., 3] = 1.0
    meta = _sample_metadata(frame_number=0)
    path0 = tmp_path / "f0.exr"
    path1 = tmp_path / "f1.exr"
    write_scene_openexr_rgba(path0, rgba, metadata=meta.with_frame_number(10))
    write_scene_openexr_rgba(path1, rgba, metadata=meta.with_frame_number(11))
    assert _read_header(path0)["nova:frameNumber"] == 10
    assert _read_header(path1)["nova:frameNumber"] == 11


def test_header_attr_failure_does_not_block_pixels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("OpenEXR")
    rgba = np.full((2, 2, 4), 0.25, dtype=np.float32)

    real_apply = apply_openexr_header_attributes

    def flaky_apply(header: object, attributes: dict) -> ExrHeaderWriteResult:
        # Force one key to fail assignment while others succeed.
        bad = dict(attributes)
        # Simulate by wrapping header
        class Flaky:
            def __init__(self, inner: object) -> None:
                self._inner = inner

            def __setitem__(self, key: str, value: object) -> None:
                if key == "nova:writerVersion":
                    raise RuntimeError("forced skip")
                self._inner[key] = value  # type: ignore[index]

        return real_apply(Flaky(header), bad)

    monkeypatch.setattr(
        "nova_layer.export.scene_exr.apply_openexr_header_attributes",
        flaky_apply,
    )
    path = tmp_path / "partial.exr"
    result = write_scene_openexr_rgba(path, rgba, metadata=_sample_metadata())
    assert path.is_file()
    assert path.stat().st_size > 0
    assert "nova:writerVersion" in result.skipped_keys
    assert result.warnings
    header = _read_header(path)
    assert header.get("nova:sceneLinear") == 1


def test_missing_openexr_still_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object):
        if name in {"OpenEXR", "Imath"}:
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    rgba = np.zeros((1, 1, 4), dtype=np.float32)
    with pytest.raises(SceneExrError, match="OpenEXR"):
        write_scene_openexr_rgba(tmp_path / "x.exr", rgba, metadata=_sample_metadata())


def test_write_pixels_failure_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("OpenEXR")
    import OpenEXR

    class BoomFile:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def writePixels(self, *_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        def close(self) -> None:
            return None

    monkeypatch.setattr(OpenEXR, "OutputFile", BoomFile)
    rgba = np.zeros((1, 1, 4), dtype=np.float32)
    with pytest.raises(OSError, match="disk full"):
        write_scene_openexr_rgba(tmp_path / "boom.exr", rgba, metadata=_sample_metadata())


# ---------------------------------------------------------------------------
# Export integration / consistency / look-baked regression
# ---------------------------------------------------------------------------


def test_scene_export_writes_headers_consistent_with_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _ = _scene_package(tmp_path, monkeypatch, frames=2)
    destination = tmp_path / "exports"
    destination.mkdir()
    result = export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="hdr_meta",
        render=render,
        format=ExportFormat.SCENE_OPENEXR_SEQUENCE,
        project={"id": "p", "name": "Demo"},
        shot={"id": "s", "name": "Shot", "frame_rate": 24.0, "width": 2, "height": 2},
        smart_layer={"id": "l", "name": "Layer"},
        frame_rate=24.0,
        scene_media_path=media,
        scene_decoder=decoder,
        mask_loader=lambda ref: PngMaskStore().load(package, ref),
        media_fingerprint="fp-export",
        input_color_space="Linear Rec.709",
        config_path="/Users/juwon/.config/ocio/config.ocio",
        config_source="env",
    )
    manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scene_linear"] is True
    assert manifest["source_color_space"] != manifest["interpretation_color_space"]
    assert manifest["interpretation_color_space"] == "Linear Rec.709"
    assert manifest["header_writer_version"] == SCENE_EXR_WRITER_VERSION
    # Absolute config stays in manifest authority only (not required in header).
    assert manifest["config_path"] == "/Users/juwon/.config/ocio/config.ocio"

    header0 = _read_header(result.path / "frame_000000.exr")
    header1 = _read_header(result.path / "frame_000001.exr")
    assert header0["nova:frameNumber"] == 0
    assert header1["nova:frameNumber"] == 1
    assert header0["nova:sceneLinear"] == 1
    assert header0["nova:premultiplied"] == 0
    assert header0["nova:sourceColorSpace"] == manifest["source_color_space"].encode("utf-8")
    assert header0["nova:interpretationColorSpace"] == manifest[
        "interpretation_color_space"
    ].encode("utf-8")
    assert header0["nova:sourceFingerprint"] == b"fp-export"
    assert header0["nova:projectId"] == b"p"
    assert header0["framesPerSecond"] == 24.0
    # No absolute home path leakage in header string/bytes values.
    for value in header0.values():
        if isinstance(value, (bytes, str)):
            text = value.decode("utf-8") if isinstance(value, bytes) else value
            assert "/Users/juwon" not in text
            assert "config.ocio" not in text or text == "config.ocio"


def test_look_baked_exr_unchanged_no_nova_namespace(tmp_path: Path) -> None:
    pytest.importorskip("OpenEXR")
    rgba = np.full((2, 2, 4), 128, dtype=np.uint8)
    path = tmp_path / "look.exr"
    write_openexr_rgba(path, rgba)
    header = _read_header(path)
    assert not any(str(key).startswith("nova:") for key in header)


def test_streaming_export_updates_frame_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("OpenEXR")
    package, media, render, decoder, _ = _scene_package(tmp_path, monkeypatch, frames=3)
    destination = tmp_path / "exports"
    destination.mkdir()
    seen_frames: list[int] = []
    real_write = write_scene_openexr_rgba

    def _tracked(path: Path, rgba: np.ndarray, **kwargs: object) -> ExrHeaderWriteResult:
        meta = kwargs.get("metadata")
        assert isinstance(meta, SceneExrHeaderMetadata)
        seen_frames.append(meta.frame_number)
        return real_write(path, rgba, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "nova_layer.export.smart_layer.write_scene_openexr_rgba",
        _tracked,
    )
    export_smart_layer_assets(
        package_path=package,
        destination_directory=destination,
        export_stem="stream_meta",
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
    assert seen_frames == [0, 1, 2]
