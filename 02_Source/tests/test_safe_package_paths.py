"""Phase H1: package / export path containment."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from nova_layer.adapters.persistence.mask_store import MaskStoreError, PngMaskStore
from nova_layer.adapters.persistence.safe_paths import (
    UnsafePackagePathError,
    assert_path_within_root,
    resolve_within_root,
    sanitize_export_stem,
    sanitize_path_segment,
)
from nova_layer.app.project_controller import ProjectController
from nova_layer.domain.models import (
    ArtistIntent,
    ExtractionPreview,
    MediaReference,
    Sequence,
    Shot,
    SmartLayer,
    SmartLayerRender,
)
from nova_layer.export.smart_layer import (
    ExportFormat,
    SmartLayerExportError,
    export_smart_layer_assets,
)


def test_resolve_within_root_accepts_nested_relative(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    nested = package / "renders" / "v0001"
    nested.mkdir(parents=True)
    target = nested / "frame_000001.png"
    target.write_bytes(b"png")
    resolved = resolve_within_root(
        package, "renders/v0001/frame_000001.png", must_exist=True, expect="file"
    )
    assert resolved == target.resolve()


def test_resolve_rejects_absolute_parent_home_and_dot(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    for unsafe in (
        "/etc/passwd",
        "../outside",
        "../../etc/passwd",
        "~/file",
        r"C:\absolute\file",
        r"\\server\share\file",
        "",
        ".",
        "./",
        "renders/../outside.png",
        "renders/./frame.png",
    ):
        with pytest.raises(UnsafePackagePathError):
            resolve_within_root(package, unsafe)


def test_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.bin"
    secret.write_bytes(b"secret")
    link = package / "link_out"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(UnsafePackagePathError):
        resolve_within_root(package, "link_out/secret.bin", must_exist=True)


def test_resolve_allows_root_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real_pkg"
    real.mkdir()
    (real / "masks").mkdir()
    mask = real / "masks" / "a.png"
    mask.write_bytes(b"m")
    linked_root = tmp_path / "linked_pkg"
    try:
        linked_root.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    resolved = resolve_within_root(
        linked_root, "masks/a.png", must_exist=True, expect="file"
    )
    assert resolved.resolve() == mask.resolve()


def test_sanitize_export_stem_and_segments() -> None:
    assert sanitize_export_stem("NOVA_Smart_Layer_v0001_png_sequence")
    for bad in ("", ".", "..", "a/b", "a\\b", "has space", "bad\nname"):
        with pytest.raises(UnsafePackagePathError):
            sanitize_path_segment(bad)


def test_mask_store_rejects_traversal(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    store = PngMaskStore()
    mask = np.zeros((2, 2), dtype=np.uint8)
    with pytest.raises(MaskStoreError, match="escape|Absolute|\\.\\."):
        store.save(package, "../escape.png", mask)
    with pytest.raises(MaskStoreError):
        store.load(package, "../escape.png")


def test_export_rejects_unsafe_render_reference(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    dest = tmp_path / "out"
    dest.mkdir()
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference="../escape.png",
                mask_reference="masks/ok.png",
            )
        ],
        checksums={},
    )
    with pytest.raises(SmartLayerExportError, match="Unsafe"):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=dest,
            export_stem="safe_stem",
            render=render,
            format=ExportFormat.PNG_SEQUENCE,
            project={"id": "p", "name": "P"},
            shot={"id": "s", "name": "S"},
            smart_layer={"id": "l", "name": "L"},
            frame_rate=24.0,
        )
    assert list(dest.iterdir()) == []


def test_export_rejects_malicious_export_stem(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    (package / "renders" / "v0001").mkdir(parents=True)
    frame = package / "renders" / "v0001" / "frame_000000.png"
    # Minimal readable placeholder — PNG path read may fail later; stem check is first.
    frame.write_bytes(b"x")
    dest = tmp_path / "out"
    dest.mkdir()
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=0,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference="renders/v0001/frame_000000.png",
                mask_reference="masks/x.png",
            )
        ],
        checksums={},
    )
    with pytest.raises(SmartLayerExportError, match="export name|Invalid"):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=dest,
            export_stem="../evil",
            render=render,
            format=ExportFormat.PNG_SEQUENCE,
            project={"id": "p", "name": "P"},
            shot={"id": "s", "name": "S"},
            smart_layer={"id": "l", "name": "L"},
            frame_rate=24.0,
        )
    assert not (tmp_path / "evil").exists()
    assert list(dest.iterdir()) == []


def test_export_failure_cleanup_stays_inside_destination(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    (package / "renders" / "v0001").mkdir(parents=True)
    outside = tmp_path / "must_keep.txt"
    outside.write_text("keep", encoding="utf-8")
    dest = tmp_path / "out"
    dest.mkdir()
    render = SmartLayerRender(
        version=1,
        frame_start=0,
        frame_end=1,
        frames=[
            ExtractionPreview(
                frame_number=0,
                image_reference="renders/v0001/frame_000000.png",
                mask_reference="masks/0.png",
            ),
            ExtractionPreview(
                frame_number=1,
                image_reference="renders/v0001/frame_000001.png",
                mask_reference="masks/1.png",
            ),
        ],
        checksums={},
    )
    (package / "renders" / "v0001" / "frame_000000.png").write_bytes(b"x")
    # Second frame intentionally missing → fail after staging exists.
    with pytest.raises(SmartLayerExportError):
        export_smart_layer_assets(
            package_path=package,
            destination_directory=dest,
            export_stem="fail_stem",
            render=render,
            format=ExportFormat.PNG_SEQUENCE,
            project={"id": "p", "name": "P"},
            shot={"id": "s", "name": "S"},
            smart_layer={"id": "l", "name": "L"},
            frame_rate=24.0,
        )
    assert outside.read_text(encoding="utf-8") == "keep"
    assert not (dest / "fail_stem").exists()
    assert not list(dest.glob(".fail_stem.staging_*"))


def _attach_render(controller: ProjectController, *, image_reference: str) -> None:
    assert controller._project is not None
    package = controller.package_path
    assert package is not None
    path = Path(image_reference)
    if not path.is_absolute():
        (package / path).parent.mkdir(parents=True, exist_ok=True)
        try:
            (package / path).write_bytes(b"png")
        except OSError:
            pass
    layer = SmartLayer(
        artist_intent=ArtistIntent(master_frame=0),
        renders=[
            SmartLayerRender(
                version=1,
                frame_start=0,
                frame_end=0,
                frames=[
                    ExtractionPreview(
                        frame_number=0,
                        image_reference=image_reference,
                        mask_reference="masks/x.png",
                    )
                ],
                checksums={image_reference: "x"},
            )
        ],
        render_version_counter=1,
    )
    shot = Shot(
        name="Shot",
        media=MediaReference(
            relative_path="media/x",
            source_path=str(package),
            fingerprint="fp",
            frame_count=1,
            frame_rate=24.0,
            width=2,
            height=2,
        ),
        range_start=0,
        range_end=0,
        master_frame=0,
        smart_layers=[layer],
    )
    controller._project.sequences = [Sequence(name="Seq", shots=[shot])]


def test_async_unsafe_path_emits_processing_failed(
    tmp_path: Path,
    qtbot: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = ProjectController()
    assert (
        controller.create_project("UnsafeExport", (tmp_path / "proj").mkdir() or tmp_path / "proj")
        is not None
    )
    _attach_render(controller, image_reference="../escape.png")
    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(
        controller,
        "verify_smart_layer_render",
        lambda version=None: type("R", (), {"valid": True})(),
    )
    with qtbot.waitSignal(controller.processing_failed, timeout=5000) as failed:  # type: ignore[attr-defined]
        assert controller.start_smart_layer_export(dest, version=1, format="png_sequence")
    assert failed.args[0] == "smart_layer_export"
    assert "Unsafe" in failed.args[1] or "escape" in failed.args[1].casefold()
    assert not (dest / "NOVA_Smart_Layer_v0001_png_sequence").exists()
    assert not controller._jobs.is_running
    QCoreApplication.processEvents()


def test_assert_path_within_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    child = root / "a" / "b.txt"
    child.parent.mkdir()
    child.write_text("ok", encoding="utf-8")
    assert assert_path_within_root(root, child) == child.resolve()
    with pytest.raises(UnsafePackagePathError):
        assert_path_within_root(root, tmp_path / "other")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
def test_expect_file_vs_directory(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    (package / "renders" / "v0001").mkdir(parents=True)
    with pytest.raises(UnsafePackagePathError, match="file"):
        resolve_within_root(package, "renders/v0001", must_exist=True, expect="file")
    resolve_within_root(package, "renders/v0001", must_exist=True, expect="dir")
