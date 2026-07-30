from __future__ import annotations

import struct
import zlib
from pathlib import Path


class MaskIoError(RuntimeError):
    pass


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_binary_mask_png(path: Path, width: int, height: int, data: bytes) -> None:
    if len(data) != width * height:
        raise MaskIoError("mask data length mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter none
        start = row * width
        raw.extend(data[start : start + width])
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    path.write_bytes(
        PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")
    )


def read_binary_mask_png(path: Path) -> tuple[int, int, bytes]:
    return read_binary_mask_png_bytes(path.read_bytes())


def read_binary_mask_png_bytes(payload: bytes) -> tuple[int, int, bytes]:
    if not payload.startswith(PNG_SIGNATURE):
        raise MaskIoError("not a PNG mask")
    offset = len(PNG_SIGNATURE)
    width = height = None
    idat = bytearray()
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        offset += 4
        chunk_type = payload[offset : offset + 4]
        offset += 4
        chunk_data = payload[offset : offset + length]
        offset += length
        offset += 4  # crc
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, *_rest = struct.unpack(">IIBBBBB", chunk_data)
            if bit_depth != 8 or color_type != 0:
                raise MaskIoError("mask PNG must be 8-bit grayscale")
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None:
        raise MaskIoError("missing IHDR")
    decompressed = zlib.decompress(bytes(idat))
    expected_stride = width + 1
    if len(decompressed) != expected_stride * height:
        raise MaskIoError("unexpected PNG raster size")
    pixels = bytearray()
    for row in range(height):
        start = row * expected_stride
        if decompressed[start] != 0:
            raise MaskIoError("unsupported PNG filter")
        pixels.extend(decompressed[start + 1 : start + 1 + width])
    return width, height, bytes(pixels)


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)
