from __future__ import annotations

import argparse
import json
from pathlib import Path

from nova_layer.adapters.media.image_sequence_reader import (
    ImageSequenceReader,
    _load_openimageio,
    list_sequence_files,
)
from nova_layer.adapters.media.media_reader_factory import MediaReaderFactory
from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.adapters.persistence.mask_store import PngMaskStore
from nova_layer.adapters.persistence.safe_paths import (
    UnsafePackagePathError,
    resolve_within_root,
)
from nova_layer.app.frame_decode_service import FrameDecodeService
from nova_layer.export.smart_layer import (
    FORMAT_LABELS,
    ExportFormat,
    SmartLayerExportError,
    export_smart_layer_assets,
)


def export_render_from_project(
    package_path: Path,
    destination_directory: Path,
    *,
    version: int | None = None,
    format: ExportFormat = ExportFormat.PNG_SEQUENCE,
    layer_index: int = 0,
) -> Path:
    store = JsonProjectStore()
    project = store.load(package_path)
    if not project.sequences or not project.sequences[0].shots:
        raise SmartLayerExportError("Project does not contain a Shot.")
    shot = project.sequences[0].shots[0]
    if not shot.smart_layers:
        raise SmartLayerExportError("Project does not contain a Smart Layer.")
    if layer_index < 0 or layer_index >= len(shot.smart_layers):
        raise SmartLayerExportError(f"Smart Layer index is out of range: {layer_index}")
    layer = shot.smart_layers[layer_index]
    if not layer.renders:
        raise SmartLayerExportError("Smart Layer has no render versions to export.")
    render = (
        next((item for item in layer.renders if item.version == version), None)
        if version is not None
        else layer.renders[-1]
    )
    if render is None:
        raise SmartLayerExportError(f"Smart Layer render v{version} does not exist.")
    for frame in render.frames:
        expected = render.checksums.get(frame.image_reference)
        try:
            source = resolve_within_root(
                package_path,
                frame.image_reference,
                must_exist=True,
                expect="file",
            )
        except UnsafePackagePathError as exc:
            raise SmartLayerExportError(f"Unsafe render reference: {exc}") from exc
        if expected is not None:
            from hashlib import sha256

            digest = sha256(source.read_bytes()).hexdigest()
            if digest != expected:
                raise SmartLayerExportError(
                    f"Render integrity failed for {frame.image_reference}."
                )
    safe_layer_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in layer.name
    ).strip("_")
    export_stem = (
        f"NOVA_{safe_layer_name or 'Smart_Layer'}_v{render.version:04d}_{format.value}"
    )
    scene_kwargs: dict[str, object] = {}
    if format is ExportFormat.SCENE_OPENEXR_SEQUENCE:
        if shot.media.source_path is None:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        media_path = Path(shot.media.source_path)
        reader = MediaReaderFactory.create(media_path)
        if not isinstance(reader, ImageSequenceReader):
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        files = list_sequence_files(media_path)
        if not files or files[0].suffix.lower() != ".exr" or _load_openimageio() is None:
            raise SmartLayerExportError(
                "True Scene export requires an EXR image sequence and OpenImageIO."
            )
        decoder = FrameDecodeService(reader, prefetch_count=0)
        mask_store = PngMaskStore()

        def _mask_loader(reference: str) -> object:
            return mask_store.load(package_path, reference)

        scene_kwargs = {
            "scene_media_path": media_path,
            "scene_decoder": decoder,
            "mask_loader": _mask_loader,
            "media_fingerprint": shot.media.fingerprint,
            "input_color_space": "scene_linear",
        }
    result = export_smart_layer_assets(
        package_path=package_path,
        destination_directory=destination_directory,
        export_stem=export_stem,
        render=render,
        format=format,
        project={"id": str(project.id), "name": project.name},
        shot={
            "id": str(shot.id),
            "name": shot.name,
            "range_start": render.frame_start,
            "range_end": render.frame_end,
            "frame_rate": shot.media.frame_rate,
            "width": shot.media.width,
            "height": shot.media.height,
        },
        smart_layer={"id": str(layer.id), "name": layer.name},
        frame_rate=shot.media.frame_rate,
        **scene_kwargs,  # type: ignore[arg-type]
    )
    return result.path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a Smart Layer render as PNG, OpenEXR, or RGBA QuickTime."
    )
    parser.add_argument("project", type=Path, help="Path to a .nova project package")
    parser.add_argument("--output", type=Path, required=True, help="Destination directory")
    parser.add_argument("--version", type=int, default=None, help="Render version number")
    parser.add_argument(
        "--format",
        choices=[item.value for item in ExportFormat],
        default=ExportFormat.PNG_SEQUENCE.value,
        help="Production export format",
    )
    parser.add_argument("--layer-index", type=int, default=0)
    args = parser.parse_args()
    export_format = ExportFormat(args.format)
    path = export_render_from_project(
        args.project,
        args.output,
        version=args.version,
        format=export_format,
        layer_index=args.layer_index,
    )
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    print(path)
    print(manifest.get("format", FORMAT_LABELS[export_format]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
