from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class SourceProbeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ProbedSource:
    media_type: str
    width: int
    height: int
    data: bytes


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8\xff"

_EXTENSION_HINTS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def extension_is_supported(path: Path) -> bool:
    return path.suffix.lower() in _EXTENSION_HINTS


def probe_source_bytes(data: bytes, *, original_filename: str) -> ProbedSource:
    if data.startswith(_PNG_SIGNATURE):
        width, height = _png_size(data)
        return ProbedSource(media_type="image/png", width=width, height=height, data=data)
    if data.startswith(_JPEG_SOI):
        width, height = _jpeg_size(data)
        return ProbedSource(media_type="image/jpeg", width=width, height=height, data=data)
    raise SourceProbeError(
        "UNSUPPORTED_MEDIA_TYPE",
        f"file content is not valid PNG or JPEG: {original_filename}",
    )


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24:
        raise SourceProbeError("UNSUPPORTED_MEDIA_TYPE", "PNG header too short")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise SourceProbeError("UNSUPPORTED_MEDIA_TYPE", "invalid PNG dimensions")
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int]:
    offset = 2
    length = len(data)
    while offset + 9 < length:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9):
            continue
        if offset + 2 > length:
            break
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2:
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if offset + 7 > length:
                break
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            if width <= 0 or height <= 0:
                raise SourceProbeError("UNSUPPORTED_MEDIA_TYPE", "invalid JPEG dimensions")
            return width, height
        offset += segment_length
    raise SourceProbeError("UNSUPPORTED_MEDIA_TYPE", "could not read JPEG dimensions")
