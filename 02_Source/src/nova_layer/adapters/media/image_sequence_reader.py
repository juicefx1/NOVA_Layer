from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from nova_layer.adapters.color.display_transform import (
    DisplayTransformProtocol,
    LegacyDisplayTransform,
)
from nova_layer.ports.media import MediaInfo, MediaReadError


SUPPORTED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".exr",
}

_NATURAL_SORT_CHUNK = re.compile(r"(\d+)")
_EXR_SUFFIX = ".exr"


def _load_openimageio() -> Any | None:
    try:
        import OpenImageIO as oiio
    except ImportError:
        return None
    return oiio


def natural_sort_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Sort key that compares digit runs as integers (natural order)."""
    chunks: list[tuple[int, int | str]] = []
    for token in _NATURAL_SORT_CHUNK.split(path.name):
        if not token:
            continue
        if token.isdigit():
            chunks.append((0, int(token)))
        else:
            chunks.append((1, token.casefold()))
    return tuple(chunks)


def list_sequence_files(folder: Path) -> list[Path]:
    return sorted(
        (
            entry
            for entry in folder.iterdir()
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=natural_sort_key,
    )


def sequence_fingerprint(files: list[Path]) -> str:
    digest = hashlib.sha256()

    for path in files:
        stat = path.stat()
        digest.update(path.name.encode())
        digest.update(str(stat.st_size).encode())

    return f"sha256:{digest.hexdigest()}"


def _read_exr_pillow(path: Path) -> NDArray[np.uint8]:
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)
    except Exception as exc:
        raise MediaReadError(
            f"Could not decode EXR without OpenImageIO: {path} ({exc})"
        ) from exc


def _read_exr_openimageio(
    path: Path,
    oiio: Any,
    display_transform: DisplayTransformProtocol,
) -> NDArray[np.uint8]:
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        raise MediaReadError(f"Could not open EXR: {path}")
    try:
        spec = inp.spec()
        # FLOAT read accepts half and float EXR sources.
        pixels = inp.read_image(oiio.FLOAT)
        if pixels is None:
            raise MediaReadError(f"Could not read EXR pixels: {path}")
        array = np.asarray(pixels)
        if array.ndim == 1:
            channels = int(spec.nchannels)
            array = array.reshape(int(spec.height), int(spec.width), channels)
        elif array.ndim == 2:
            array = array.reshape(int(spec.height), int(spec.width), 1)
        try:
            return display_transform.apply(array)
        except (TypeError, ValueError) as exc:
            raise MediaReadError(f"Could not display-transform EXR: {path} ({exc})") from exc
    except MediaReadError:
        raise
    except Exception as exc:
        raise MediaReadError(f"Could not decode EXR: {path} ({exc})") from exc
    finally:
        inp.close()


def _probe_image(path: Path) -> tuple[int, int, str]:
    if path.suffix.lower() == _EXR_SUFFIX:
        oiio = _load_openimageio()
        if oiio is not None:
            inp = oiio.ImageInput.open(str(path))
            if inp is None:
                raise MediaReadError(f"Could not open EXR: {path}")
            try:
                spec = inp.spec()
                format_name = str(getattr(spec, "format", "exr"))
                return int(spec.width), int(spec.height), f"exr/{format_name}"
            finally:
                inp.close()
        try:
            with Image.open(path) as img:
                width, height = img.size
                return int(width), int(height), str(img.mode)
        except Exception as exc:
            raise MediaReadError(
                f"Could not inspect EXR without OpenImageIO: {path} ({exc})"
            ) from exc

    with Image.open(path) as img:
        width, height = img.size
        return int(width), int(height), str(img.mode)


class ImageSequenceReader:
    def __init__(
        self,
        display_transform: DisplayTransformProtocol | None = None,
    ) -> None:
        # Default remains LegacyDisplayTransform (no automatic OCIO selection).
        self._display_transform = display_transform or LegacyDisplayTransform()

    @property
    def display_transform(self) -> DisplayTransformProtocol:
        return self._display_transform

    def inspect(self, path: Path) -> MediaInfo:
        folder = path.expanduser().resolve()

        if not folder.is_dir():
            raise MediaReadError(f"Sequence folder does not exist: {folder}")

        files = list_sequence_files(folder)

        if not files:
            raise MediaReadError("No supported image files found.")

        width, height, pixel_format = _probe_image(files[0])

        return MediaInfo(
            path=folder,
            fingerprint=sequence_fingerprint(files),
            frame_count=len(files),
            frame_rate=24.0,
            width=width,
            height=height,
            time_base="1/24",
            pixel_format=pixel_format,
        )

    def read_frame(
        self,
        path: Path,
        frame_number: int,
    ) -> NDArray[np.uint8]:

        folder = path.expanduser().resolve()

        files = list_sequence_files(folder)

        if frame_number < 0 or frame_number >= len(files):
            raise MediaReadError(
                f"Frame {frame_number} is outside the sequence."
            )

        return self._read_raster(files[frame_number])

    def _read_exr(self, path: Path) -> NDArray[np.uint8]:
        """Decode an OpenEXR frame to preview uint8 RGB via DisplayTransform when float."""
        oiio = _load_openimageio()
        if oiio is not None:
            return _read_exr_openimageio(path, oiio, self._display_transform)
        return _read_exr_pillow(path)

    def _read_raster(self, path: Path) -> NDArray[np.uint8]:
        if path.suffix.lower() == _EXR_SUFFIX:
            return self._read_exr(path)
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)
