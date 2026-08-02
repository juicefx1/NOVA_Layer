from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np
from numpy.typing import NDArray

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
    LegacyDisplayTransform,
)
from nova_layer.app.raw_frame_cache import DEFAULT_RAW_FRAME_CACHE_SIZE, RawFrameCache
from nova_layer.ports.media import MediaReader
from nova_layer.ports.scene_frames import SceneFrame

# Preview cache holds uint8 RGB. 32×1080p ≈ 190 MB; prefer smaller raw cache instead.
DEFAULT_PREVIEW_CACHE_SIZE = 32


@dataclass(frozen=True, slots=True)
class TransformIdentity:
    """Identity for preview-cache keys (color path + exposure)."""

    backend: str
    config_path: str | None
    config_source: str | None
    input_color_space: str
    display: str | None
    view: str | None
    exposure: float

    @classmethod
    def from_transform(cls, transform: DisplayTransformProtocol) -> TransformIdentity:
        diagnostics = getattr(transform, "diagnostics", None)
        if isinstance(diagnostics, DisplayTransformDiagnostics):
            return cls(
                backend=str(diagnostics.backend),
                config_path=diagnostics.config_path,
                config_source=diagnostics.config_source,
                input_color_space=str(diagnostics.input_color_space),
                display=diagnostics.display,
                view=diagnostics.view,
                exposure=round(float(diagnostics.exposure), 6),
            )
        return cls(
            backend="unknown",
            config_path=None,
            config_source=None,
            input_color_space="scene_linear",
            display=None,
            view=None,
            exposure=0.0,
        )


PreviewKey = tuple[Path, int, TransformIdentity]


class PreviewFrameCache:
    """Thread-unsafe LRU for uint8 preview frames keyed by path/frame/transform."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("preview_cache_size must be positive")
        self._capacity = capacity
        self._items: OrderedDict[PreviewKey, NDArray[np.uint8]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity

    def clear(self) -> None:
        self._items.clear()

    def contains(self, key: PreviewKey) -> bool:
        return key in self._items

    def get(self, key: PreviewKey) -> NDArray[np.uint8] | None:
        cached = self._items.get(key)
        if cached is None:
            return None
        self._items.move_to_end(key)
        return cached

    def put(
        self,
        key: PreviewKey,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
    ) -> None:
        self._items[key] = np.ascontiguousarray(image).copy()
        self._items.move_to_end(key)
        if expand_to_fit and len(self._items) > self._capacity:
            self._capacity = len(self._items)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)


def _is_scene_frame_source(reader: object) -> bool:
    return callable(getattr(reader, "read_scene_frame", None))


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


class PreviewPipeline:
    """EXR raw cache → display transform → uint8 preview cache.

    Non-scene media (video, PNG, …) falls through to ``MediaReader.read_frame``.
    Changing the display transform clears preview entries but keeps raw EXR frames.
    """

    def __init__(
        self,
        reader: MediaReader,
        display_transform: DisplayTransformProtocol | None = None,
        *,
        raw_cache_size: int = DEFAULT_RAW_FRAME_CACHE_SIZE,
        preview_cache_size: int = DEFAULT_PREVIEW_CACHE_SIZE,
        raw_cache: RawFrameCache | None = None,
    ) -> None:
        self._reader = reader
        self._display_transform = display_transform or LegacyDisplayTransform()
        self._transform_id = TransformIdentity.from_transform(self._display_transform)
        self._raw_cache = raw_cache or RawFrameCache(raw_cache_size)
        self._preview_cache = PreviewFrameCache(preview_cache_size)
        self._lock = Lock()
        self._oiio_decode_count = 0

    @property
    def reader(self) -> MediaReader:
        return self._reader

    @property
    def display_transform(self) -> DisplayTransformProtocol:
        return self._display_transform

    @property
    def transform_identity(self) -> TransformIdentity:
        return self._transform_id

    @property
    def raw_cache(self) -> RawFrameCache:
        return self._raw_cache

    @property
    def preview_cache_count(self) -> int:
        with self._lock:
            return len(self._preview_cache)

    @property
    def oiio_decode_count(self) -> int:
        """Test/diagnostics: number of scene-frame OIIO loads performed by this pipeline."""
        return self._oiio_decode_count

    def set_reader(self, reader: MediaReader, *, keep_raw_cache: bool = False) -> None:
        with self._lock:
            self._reader = reader
            self._preview_cache.clear()
            if not keep_raw_cache:
                self._raw_cache.clear()

    def set_display_transform(self, transform: DisplayTransformProtocol | None) -> None:
        """Swap exposure/display path; keep EXR raw cache, drop preview cache."""
        with self._lock:
            self._display_transform = transform or LegacyDisplayTransform()
            self._transform_id = TransformIdentity.from_transform(self._display_transform)
            self._preview_cache.clear()

    def clear_preview_cache(self) -> None:
        with self._lock:
            self._preview_cache.clear()

    def clear_all(self) -> None:
        with self._lock:
            self._preview_cache.clear()
            self._raw_cache.clear()

    def read_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        resolved = _resolve_path(path)
        with self._lock:
            tid = self._transform_id
            key: PreviewKey = (resolved, frame_number, tid)
            cached = self._preview_cache.get(key)
            if cached is not None:
                return cached.copy()
            transform = self._display_transform
            reader = self._reader

        if _is_scene_frame_source(reader) and self._frame_is_exr_candidate(reader, resolved, frame_number):
            scene = self._get_or_load_scene(reader, resolved, frame_number)
            try:
                preview = transform.apply(scene.pixels)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Could not display-transform scene frame: {exc}") from exc
        else:
            preview = reader.read_frame(resolved, frame_number)

        preview_u8 = np.ascontiguousarray(preview, dtype=np.uint8)
        with self._lock:
            # Identity may have changed while decoding; store under current id if match.
            if self._transform_id == tid:
                self._preview_cache.put(key, preview_u8)
        return preview_u8.copy()

    def put_preview(
        self,
        path: Path,
        frame_number: int,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
    ) -> None:
        key: PreviewKey = (_resolve_path(path), frame_number, self._transform_id)
        with self._lock:
            self._preview_cache.put(key, image, expand_to_fit=expand_to_fit)

    def get_preview(
        self,
        path: Path,
        frame_number: int,
    ) -> NDArray[np.uint8] | None:
        key: PreviewKey = (_resolve_path(path), frame_number, self._transform_id)
        with self._lock:
            cached = self._preview_cache.get(key)
            if cached is None:
                return None
            return cached.copy()

    def prefetch_raw(
        self,
        path: Path,
        anchor_frame: int,
        count: int,
        *,
        is_current: Callable[[], bool],
    ) -> None:
        """Warm upcoming EXR scene frames into the raw cache. Swallows failures."""
        if count < 1 or not _is_scene_frame_source(self._reader):
            return
        resolved = _resolve_path(path)
        reader = self._reader
        for offset in range(1, count + 1):
            if not is_current():
                return
            frame_number = anchor_frame + offset
            if self._raw_cache.contains(resolved, frame_number):
                continue
            if not self._frame_is_exr_candidate(reader, resolved, frame_number):
                continue
            try:
                self._get_or_load_scene(reader, resolved, frame_number)
            except Exception:
                continue

    def _get_or_load_scene(
        self,
        reader: MediaReader,
        resolved: Path,
        frame_number: int,
    ) -> SceneFrame:
        cached = self._raw_cache.get(resolved, frame_number)
        if cached is not None:
            return cached
        # Serialize miss→load so concurrent preview/prefetch workers share one OIIO read.
        with self._lock:
            cached = self._raw_cache.get(resolved, frame_number)
            if cached is not None:
                return cached
            scene = reader.read_scene_frame(resolved, frame_number)  # type: ignore[attr-defined]
            self._oiio_decode_count += 1
            self._raw_cache.put(scene)
            return self._raw_cache.get(resolved, frame_number) or scene

    def _frame_is_exr_candidate(
        self,
        reader: MediaReader,
        resolved: Path,
        frame_number: int,
    ) -> bool:
        """Cheap probe: sequence dir + inspect pixel_format, or try frame path suffix via listing.

        Avoids raising when frame is PNG mixed into a folder; relies on read_scene_frame
        for definitive unsupported errors when we already believe the slot is EXR.
        """
        del reader
        try:
            # Single file path is video-like — no scene frames.
            if resolved.is_file():
                return resolved.suffix.lower() == ".exr"
            if not resolved.is_dir():
                return False
            from nova_layer.adapters.media.image_sequence_reader import list_sequence_files

            files = list_sequence_files(resolved)
            if frame_number < 0 or frame_number >= len(files):
                return False
            return files[frame_number].suffix.lower() == ".exr"
        except Exception:
            return False
