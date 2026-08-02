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
from nova_layer.ports.scene_frames import SceneFrame


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


def _sanitize_scene_rgb(rgb: NDArray[np.floating[Any]]) -> NDArray[np.float32]:
    """Normalize EXR RGB for scene cache: float32, NaN/-Inf→0, +Inf→finite max."""
    value = np.array(rgb, dtype=np.float32, copy=True)
    value = np.where(np.isnan(value), np.float32(0.0), value)
    value = np.where(value == -np.inf, np.float32(0.0), value)
    finite_max = np.finfo(np.float32).max
    value = np.where(value == np.inf, np.float32(finite_max), value)
    return value


def _spec_string_attribute(spec: Any, key: str) -> str | None:
    """Best-effort OIIO ImageSpec string attribute read (never raises to caller)."""
    get_string = getattr(spec, "get_string_attribute", None)
    if callable(get_string):
        try:
            value = get_string(key, "")
        except TypeError:
            try:
                value = get_string(key)
            except Exception:
                value = None
        except Exception:
            value = None
        if value is not None:
            text = str(value).strip()
            if text:
                return text

    get_attr = getattr(spec, "getattribute", None)
    if callable(get_attr):
        try:
            value = get_attr(key)
        except Exception:
            value = None
        if value is not None:
            text = str(value).strip()
            if text:
                return text

    extra = getattr(spec, "extra_attribs", None)
    if extra is not None:
        try:
            for item in extra:
                name = getattr(item, "name", None)
                if name == key:
                    raw = getattr(item, "value", None)
                    if raw is None and len(item) >= 2:  # type: ignore[arg-type]
                        raw = item[1]
                    if raw is not None:
                        text = str(raw).strip()
                        if text:
                            return text
        except Exception:
            pass
    return None


def _probe_oiio_color_space(spec: Any) -> tuple[str | None, str]:
    """Read file color-space tag from OIIO spec; never fails the decode path."""
    try:
        for key in ("oiio:ColorSpace", "ColorSpace", "colorspace"):
            value = _spec_string_attribute(spec, key)
            if value:
                return value, "oiio"
    except Exception:
        return None, "unspecified"
    return None, "unspecified"


def _load_exr_float_rgb(
    path: Path, oiio: Any
) -> tuple[NDArray[np.float32], str | None, str]:
    """Decode EXR to float32 HxWx3 RGB via OIIO and probe color-space tags.

    Returns ``(pixels, color_space, color_space_source)``. Probe failures never
    abort pixel decode.
    """
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        raise MediaReadError(f"Could not open EXR: {path}")
    try:
        spec = inp.spec()
        color_space, color_space_source = _probe_oiio_color_space(spec)
        pixels = inp.read_image(oiio.FLOAT)
        if pixels is None:
            raise MediaReadError(f"Could not read EXR pixels: {path}")
        array = np.asarray(pixels)
        if array.ndim == 1:
            channels = int(spec.nchannels)
            array = array.reshape(int(spec.height), int(spec.width), channels)
        elif array.ndim == 2:
            array = array.reshape(int(spec.height), int(spec.width), 1)
        if array.ndim != 3 or array.shape[2] < 3:
            raise MediaReadError(
                f"EXR scene frame requires at least 3 channels: {path} shape={array.shape}"
            )
        return (
            _sanitize_scene_rgb(array[:, :, :3]),
            color_space,
            color_space_source,
        )
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

    @display_transform.setter
    def display_transform(self, value: DisplayTransformProtocol | None) -> None:
        self._display_transform = value or LegacyDisplayTransform()

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

    def read_scene_frame(
        self,
        path: Path,
        frame_number: int,
    ) -> SceneFrame:
        """Decode an EXR sequence frame to file-native float32 RGB.

        Requires OpenImageIO. Pillow fallback and non-EXR formats raise MediaReadError.
        """
        folder = path.expanduser().resolve()
        files = list_sequence_files(folder)

        if frame_number < 0 or frame_number >= len(files):
            raise MediaReadError(
                f"Frame {frame_number} is outside the sequence."
            )

        file_path = files[frame_number]
        if file_path.suffix.lower() != _EXR_SUFFIX:
            raise MediaReadError(
                f"Scene frames are only supported for EXR sequences, got {file_path.suffix!r}"
            )

        oiio = _load_openimageio()
        if oiio is None:
            raise MediaReadError(
                "OpenImageIO is required for EXR scene frames; Pillow fallback is not supported"
            )

        pixels, color_space, color_space_source = _load_exr_float_rgb(file_path, oiio)
        height, width = int(pixels.shape[0]), int(pixels.shape[1])
        return SceneFrame(
            path=folder,
            frame_number=frame_number,
            pixels=pixels,
            width=width,
            height=height,
            channels=3,
            pixel_format="float32_rgb",
            color_space=color_space,
            color_space_source=color_space_source,
        )

    def _read_exr(self, path: Path) -> NDArray[np.uint8]:
        """Decode an OpenEXR frame to preview uint8 RGB via DisplayTransform when float."""
        oiio = _load_openimageio()
        if oiio is not None:
            pixels, _, _ = _load_exr_float_rgb(path, oiio)
            try:
                return self._display_transform.apply(pixels)
            except (TypeError, ValueError) as exc:
                raise MediaReadError(
                    f"Could not display-transform EXR: {path} ({exc})"
                ) from exc
        return _read_exr_pillow(path)

    def _read_raster(self, path: Path) -> NDArray[np.uint8]:
        if path.suffix.lower() == _EXR_SUFFIX:
            return self._read_exr(path)
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)
