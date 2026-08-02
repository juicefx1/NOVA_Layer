from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from numpy.typing import NDArray

from nova_layer.ports.media import MediaInfo, MediaReadError

__all__ = ["MediaReadError", "PyAvMediaReader", "media_fingerprint"]


def media_fingerprint(path: Path, sample_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    stat = path.stat()
    digest.update(str(stat.st_size).encode())
    with path.open("rb") as source:
        digest.update(source.read(sample_size))
        if stat.st_size > sample_size:
            source.seek(max(0, stat.st_size - sample_size))
            digest.update(source.read(sample_size))
    return f"sha256:{digest.hexdigest()}"


class PyAvMediaReader:
    def inspect(self, path: Path) -> MediaInfo:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise MediaReadError(f"Media file does not exist: {resolved}")

        try:
            with av.open(str(resolved)) as container:
                if not container.streams.video:
                    raise MediaReadError("The selected file has no video stream.")
                stream = container.streams.video[0]
                frame_rate = stream.average_rate or stream.base_rate
                if frame_rate is None or float(frame_rate) <= 0:
                    raise MediaReadError("The video stream has no usable frame rate.")
                frame_count = int(stream.frames or 0)
                duration = stream.duration
                time_base = stream.time_base
                if frame_count <= 0 and duration is not None and time_base is not None:
                    duration_seconds = float(duration * time_base)
                    frame_count = max(1, round(duration_seconds * float(frame_rate)))
                if frame_count <= 0:
                    frame_count = sum(1 for _ in container.decode(stream))
                codec_context = stream.codec_context
                pixel_format = codec_context.format.name if codec_context.format else None
                return MediaInfo(
                    path=resolved,
                    fingerprint=media_fingerprint(resolved),
                    frame_count=frame_count,
                    frame_rate=float(frame_rate),
                    width=codec_context.width,
                    height=codec_context.height,
                    time_base=str(stream.time_base or Fraction(1, 1)),
                    pixel_format=pixel_format,
                )
        except MediaReadError:
            raise
        except Exception as exc:
            raise MediaReadError(f"Could not inspect media: {exc}") from exc

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        if frame_number < 0:
            raise MediaReadError("Frame number must be non-negative.")
        resolved = path.expanduser().resolve()
        try:
            with av.open(str(resolved)) as container:
                stream = container.streams.video[0]
                for index, frame in enumerate(container.decode(stream)):
                    if index == frame_number:
                        array = frame.to_ndarray(format="rgb24")
                        return np.asarray(array, dtype=np.uint8)
        except Exception as exc:
            raise MediaReadError(f"Could not decode frame {frame_number}: {exc}") from exc
        raise MediaReadError(f"Frame {frame_number} is outside the media range.")

    def read_frames(
        self,
        path: Path,
        start: int,
        end: int,
    ) -> dict[int, NDArray[np.uint8]]:
        """Decode an inclusive frame range with a single container open (ascending).

        Application helper — not part of the MediaReader Protocol surface.
        """
        if start < 0:
            raise MediaReadError("Frame range start must be non-negative.")
        if end < start:
            raise MediaReadError("Frame range end must be >= start.")
        resolved = path.expanduser().resolve()
        frames: dict[int, NDArray[np.uint8]] = {}
        try:
            with av.open(str(resolved)) as container:
                stream = container.streams.video[0]
                for index, frame in enumerate(container.decode(stream)):
                    if index < start:
                        continue
                    if index > end:
                        break
                    frames[index] = np.asarray(
                        frame.to_ndarray(format="rgb24"),
                        dtype=np.uint8,
                    )
        except MediaReadError:
            raise
        except Exception as exc:
            raise MediaReadError(
                f"Could not decode frames {start}–{end}: {exc}"
            ) from exc
        missing = [index for index in range(start, end + 1) if index not in frames]
        if missing:
            preview = ", ".join(str(item) for item in missing[:8])
            more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
            raise MediaReadError(
                f"Frame(s) missing from media range {start}–{end}: {preview}{more}."
            )
        return frames
