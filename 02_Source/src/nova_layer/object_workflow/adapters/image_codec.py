from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from nova_layer.object_workflow.application.errors import ApplicationError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageCodecError(RuntimeError):
    pass


def decode_rgb_image_bytes(data: bytes) -> tuple[int, int, bytes]:
    """Decode PNG/JPEG bytes to contiguous RGB8 (width, height, rgb_bytes)."""
    image = QImage.fromData(data)
    if image.isNull():
        raise ApplicationError("IMAGE_DECODE_FAILED", "could not decode source image")
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    width = image.width()
    height = image.height()
    bytes_per_line = image.bytesPerLine()
    ptr = image.constBits()
    buffer = np.frombuffer(ptr, dtype=np.uint8, count=bytes_per_line * height).reshape(
        (height, bytes_per_line)
    )
    rgb = np.ascontiguousarray(buffer[:, : width * 3]).reshape((height, width, 3))
    return width, height, rgb.tobytes()


def write_rgba_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    if len(rgba) != width * height * 4:
        raise ImageCodecError("RGBA data length mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)
        start = row * stride
        raw.extend(rgba[start : start + stride])
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")
    )


def decode_rgba_png_bytes(payload: bytes) -> tuple[int, int, bytes]:
    if not payload.startswith(PNG_SIGNATURE):
        raise ImageCodecError("not a PNG")
    offset = len(PNG_SIGNATURE)
    width = height = None
    idat = bytearray()
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        offset += 4
        chunk_type = payload[offset : offset + 4]
        offset += 4
        chunk_data = payload[offset : offset + length]
        offset += length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, *_rest = struct.unpack(">IIBBBBB", chunk_data)
            if bit_depth != 8 or color_type != 6:
                raise ImageCodecError("extraction PNG must be 8-bit RGBA")
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None:
        raise ImageCodecError("missing IHDR")
    decompressed = zlib.decompress(bytes(idat))
    stride = width * 4 + 1
    if len(decompressed) != stride * height:
        raise ImageCodecError("unexpected PNG raster size")
    pixels = bytearray()
    for row in range(height):
        start = row * stride
        if decompressed[start] != 0:
            raise ImageCodecError("unsupported PNG filter")
        pixels.extend(decompressed[start + 1 : start + stride])
    return width, height, bytes(pixels)


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)
