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
from nova_layer.app.frame_cache_stats import (
    FrameCacheStats,
    PreviewPipelineStats,
    bytes_from_env_mb,
)
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.app.raw_frame_cache import (
    DEFAULT_RAW_CACHE_MAX_BYTES,
    DEFAULT_RAW_FRAME_CACHE_SIZE,
    RawFrameCache,
)
from nova_layer.ports.media import MediaReadError, MediaReader
from nova_layer.ports.scene_frames import SceneFrame

# Entry-count soft cap (legacy ``preview_cache_size`` / ``cache_size``).
DEFAULT_PREVIEW_CACHE_SIZE = 32

# ~256 MiB hard RAM budget for uint8 RGB previews (override: NOVA_PREVIEW_CACHE_MB).
DEFAULT_PREVIEW_CACHE_MAX_BYTES = 256 * 1024 * 1024


def _default_preview_max_bytes() -> int:
    return bytes_from_env_mb("NOVA_PREVIEW_CACHE_MB", DEFAULT_PREVIEW_CACHE_MAX_BYTES)


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

# Fixed Legacy linear→sRGB bake identity for SOURCE EXR cache keys.
SOURCE_TRANSFORM_IDENTITY = TransformIdentity(
    backend=SOURCE_TRANSFORM_VERSION,
    config_path=None,
    config_source=None,
    input_color_space="scene_linear",
    display=None,
    view=None,
    exposure=0.0,
)


class PreviewFrameCache:
    """Thread-safe LRU for uint8 preview frames with byte budget + entry cap.

    ``expand_to_fit`` may raise ``max_entries`` but never raises ``max_bytes``.
    """

    def __init__(
        self,
        capacity: int | None = None,
        *,
        max_bytes: int | None = None,
        max_entries: int | None = None,
    ) -> None:
        if capacity is not None and max_entries is None:
            max_entries = capacity
        if max_entries is None:
            max_entries = DEFAULT_PREVIEW_CACHE_SIZE
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_bytes is None:
            max_bytes = _default_preview_max_bytes()
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")

        self._max_bytes = int(max_bytes)
        self._max_entries = int(max_entries)
        self._base_max_entries = int(max_entries)
        self._items: OrderedDict[PreviewKey, NDArray[np.uint8]] = OrderedDict()
        self._entry_bytes: dict[PreviewKey, int] = {}
        self._current_bytes = 0
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._oversized_rejections = 0
        self._oversized_admissions = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def capacity(self) -> int:
        return self._max_entries

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    def stats(self) -> FrameCacheStats:
        with self._lock:
            return FrameCacheStats(
                count=len(self._items),
                current_bytes=self._current_bytes,
                max_bytes=self._max_bytes,
                max_entries=self._max_entries,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                oversized_rejections=self._oversized_rejections,
                oversized_admissions=self._oversized_admissions,
            )

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._entry_bytes.clear()
            self._current_bytes = 0
            self._max_entries = self._base_max_entries

    def contains(self, key: PreviewKey) -> bool:
        with self._lock:
            return key in self._items

    def get(self, key: PreviewKey) -> NDArray[np.uint8] | None:
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return np.ascontiguousarray(cached).copy()

    def put(
        self,
        key: PreviewKey,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
        allow_eviction: bool = True,
    ) -> bool:
        stored = np.ascontiguousarray(image, dtype=np.uint8).copy()
        nbytes = int(stored.nbytes)

        with self._lock:
            if expand_to_fit and len(self._items) >= self._max_entries and key not in self._items:
                # Raise entry cap only — never the byte budget.
                self._max_entries = len(self._items) + 1

            if nbytes > self._max_bytes:
                if not allow_eviction:
                    self._oversized_rejections += 1
                    return False
                self._items.clear()
                self._entry_bytes.clear()
                self._items[key] = stored
                self._entry_bytes[key] = nbytes
                self._current_bytes = nbytes
                self._items.move_to_end(key)
                self._oversized_admissions += 1
                return True

            old_nbytes = self._entry_bytes.get(key)
            replacing = old_nbytes is not None
            next_bytes = self._current_bytes - (old_nbytes or 0) + nbytes
            next_count = len(self._items) if replacing else len(self._items) + 1

            if not allow_eviction:
                if next_bytes > self._max_bytes or next_count > self._max_entries:
                    return False
                if replacing:
                    self._current_bytes -= old_nbytes or 0
                self._items[key] = stored
                self._entry_bytes[key] = nbytes
                self._current_bytes += nbytes
                self._items.move_to_end(key)
                return True

            if replacing:
                self._current_bytes -= old_nbytes or 0
            self._items[key] = stored
            self._entry_bytes[key] = nbytes
            self._current_bytes += nbytes
            self._items.move_to_end(key)
            self._evict_until_fit_unlocked(protect_key=key)
            return True

    def _evict_until_fit_unlocked(self, *, protect_key: PreviewKey | None = None) -> None:
        while self._items and (
            self._current_bytes > self._max_bytes or len(self._items) > self._max_entries
        ):
            victim_key = None
            for candidate in self._items:
                if candidate != protect_key:
                    victim_key = candidate
                    break
            if victim_key is None:
                break
            self._items.pop(victim_key)
            removed = self._entry_bytes.pop(victim_key, 0)
            self._current_bytes -= removed
            self._evictions += 1
        if self._current_bytes < 0:
            self._current_bytes = 0


def _is_scene_frame_source(reader: object) -> bool:
    return callable(getattr(reader, "read_scene_frame", None))


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


class PreviewPipeline:
    """EXR raw cache → display transform → uint8 preview cache.

    Lock order (never invert): ``PreviewPipeline._lock`` → cache locks
    (RawFrameCache / PreviewFrameCache). OIIO decode runs **without** holding
    ``_lock``; miss paths re-check under lock after decode.
    """

    def __init__(
        self,
        reader: MediaReader,
        display_transform: DisplayTransformProtocol | None = None,
        *,
        raw_cache_size: int = DEFAULT_RAW_FRAME_CACHE_SIZE,
        preview_cache_size: int = DEFAULT_PREVIEW_CACHE_SIZE,
        raw_cache_max_bytes: int | None = None,
        preview_cache_max_bytes: int | None = None,
        raw_cache: RawFrameCache | None = None,
    ) -> None:
        self._reader = reader
        self._display_transform = display_transform or LegacyDisplayTransform()
        self._transform_id = TransformIdentity.from_transform(self._display_transform)
        if raw_cache is not None:
            self._raw_cache = raw_cache
        else:
            raw_bytes = (
                raw_cache_max_bytes
                if raw_cache_max_bytes is not None
                else bytes_from_env_mb("NOVA_RAW_CACHE_MB", DEFAULT_RAW_CACHE_MAX_BYTES)
            )
            self._raw_cache = RawFrameCache(
                max_entries=raw_cache_size,
                max_bytes=raw_bytes,
            )
        preview_bytes = (
            preview_cache_max_bytes
            if preview_cache_max_bytes is not None
            else _default_preview_max_bytes()
        )
        self._preview_cache = PreviewFrameCache(
            max_entries=preview_cache_size,
            max_bytes=preview_bytes,
        )
        # Separate LRU so SOURCE bytes are not evicted by scrubbing previews.
        self._source_cache = PreviewFrameCache(
            max_entries=preview_cache_size,
            max_bytes=preview_bytes,
        )
        self._source_display = LegacyDisplayTransform()
        self._lock = Lock()
        self._scene_load_lock = Lock()
        self._raw_decodes = 0
        self._preview_generations = 0
        self._source_generations = 0
        self._raw_prefetch_skips = 0
        self._preview_prefetch_skips = 0

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
        return self._preview_cache.stats().count

    @property
    def oiio_decode_count(self) -> int:
        """Backward-compatible alias for ``pipeline_stats.raw_decodes``."""
        return self._raw_decodes

    @property
    def raw_cache_stats(self) -> FrameCacheStats:
        return self._raw_cache.stats()

    @property
    def preview_cache_stats(self) -> FrameCacheStats:
        return self._preview_cache.stats()

    @property
    def source_cache_stats(self) -> FrameCacheStats:
        return self._source_cache.stats()

    @property
    def pipeline_stats(self) -> PreviewPipelineStats:
        return PreviewPipelineStats(
            raw_decodes=self._raw_decodes,
            preview_generations=self._preview_generations,
            raw_prefetch_skips=self._raw_prefetch_skips,
            preview_prefetch_skips=self._preview_prefetch_skips,
        )

    def set_reader(self, reader: MediaReader, *, keep_raw_cache: bool = False) -> None:
        with self._lock:
            self._reader = reader
            self._preview_cache.clear()
            self._source_cache.clear()
            if not keep_raw_cache:
                self._raw_cache.clear()

    def set_display_transform(self, transform: DisplayTransformProtocol | None) -> None:
        """Swap exposure/display path; keep EXR raw + SOURCE caches, drop preview.

        Lifetime counters (hits/misses/…) on caches are retained; preview
        ``count`` / ``current_bytes`` go to 0 via ``clear()``. SOURCE stable
        uint8 bake is independent of session viewer transform.
        """
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
            self._source_cache.clear()
            self._raw_cache.clear()

    def read_frame(
        self,
        path: Path,
        frame_number: int,
        *,
        expand_to_fit: bool = False,
    ) -> NDArray[np.uint8]:
        resolved = _resolve_path(path)
        with self._lock:
            tid = self._transform_id
            key: PreviewKey = (resolved, frame_number, tid)
            cached = self._preview_cache.get(key)
            if cached is not None:
                return cached
            transform = self._display_transform
            reader = self._reader

        if _is_scene_frame_source(reader) and self._frame_is_exr_candidate(
            reader, resolved, frame_number
        ):
            scene = self._get_or_load_scene(reader, resolved, frame_number)
            try:
                preview = transform.apply(scene.pixels)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Could not display-transform scene frame: {exc}") from exc
            self._preview_generations += 1
        else:
            preview = reader.read_frame(resolved, frame_number)
            self._preview_generations += 1

        preview_u8 = np.ascontiguousarray(preview, dtype=np.uint8)
        with self._lock:
            if self._transform_id == tid:
                self._preview_cache.put(
                    key,
                    preview_u8,
                    expand_to_fit=expand_to_fit,
                    allow_eviction=True,
                )
        return preview_u8.copy()

    def get_scene_frame(self, path: Path, frame_number: int) -> SceneFrame:
        """Return scene-linear EXR pixels via the raw cache (no display transform)."""
        resolved = _resolve_path(path)
        with self._lock:
            reader = self._reader
        if not _is_scene_frame_source(reader):
            raise MediaReadError(
                "Scene frames require a SceneFrameSource media reader (EXR via OIIO)."
            )
        if not self._frame_is_exr_candidate(reader, resolved, frame_number):
            raise MediaReadError(
                f"Scene frames are only supported for EXR media; "
                f"frame {frame_number} is not an EXR candidate."
            )
        scene = self._get_or_load_scene(reader, resolved, frame_number)
        if scene is None:
            raise MediaReadError(
                f"Could not load scene frame {frame_number} from {resolved}."
            )
        return scene

    def get_processing_frame(
        self,
        path: Path,
        frame_number: int,
        *,
        policy: ProcessingColorPolicy,
    ) -> NDArray[np.uint8] | SceneFrame:
        """Return pixels for a processing path according to ``policy``."""
        if policy is ProcessingColorPolicy.PREVIEW:
            return self.read_frame(path, frame_number)
        if policy is ProcessingColorPolicy.SCENE:
            return self.get_scene_frame(path, frame_number)
        if policy is ProcessingColorPolicy.SOURCE:
            return self._get_source_frame(path, frame_number)
        raise ValueError(f"Unsupported processing color policy: {policy!r}")

    def _get_source_frame(self, path: Path, frame_number: int) -> NDArray[np.uint8]:
        """Stable uint8 RGB independent of session viewer Exposure/Display/View."""
        resolved = _resolve_path(path)
        key: PreviewKey = (resolved, frame_number, SOURCE_TRANSFORM_IDENTITY)
        with self._lock:
            cached = self._source_cache.get(key)
            if cached is not None:
                return cached
            reader = self._reader
            source_display = self._source_display

        if _is_scene_frame_source(reader) and self._frame_is_exr_candidate(
            reader, resolved, frame_number
        ):
            try:
                scene = self._get_or_load_scene(reader, resolved, frame_number)
            except MediaReadError:
                scene = None
            if scene is not None:
                try:
                    baked = source_display.apply(scene.pixels)
                except (TypeError, ValueError) as exc:
                    raise MediaReadError(
                        f"Could not bake SOURCE frame {frame_number}: {exc}"
                    ) from exc
                self._source_generations += 1
                source_u8 = np.ascontiguousarray(baked, dtype=np.uint8)
            else:
                # EXR without usable OIIO scene decode — Pillow path (no viewer TF).
                source_u8 = self._read_exr_pillow_source(resolved, frame_number)
                self._source_generations += 1
        else:
            # PNG / video / stubs: raster uint8 without applying viewer transform.
            # ImageSequenceReader non-EXR and PyAv never apply display_transform.
            raster = reader.read_frame(resolved, frame_number)
            self._source_generations += 1
            source_u8 = np.ascontiguousarray(raster, dtype=np.uint8)

        if source_u8.ndim != 3 or source_u8.shape[2] != 3:
            raise MediaReadError(
                f"SOURCE frame must be HxWx3 RGB, got shape {source_u8.shape}"
            )
        with self._lock:
            self._source_cache.put(key, source_u8, allow_eviction=True)
        return source_u8.copy()

    def _read_exr_pillow_source(self, resolved: Path, frame_number: int) -> NDArray[np.uint8]:
        from nova_layer.adapters.media.image_sequence_reader import (
            _read_exr_pillow,
            list_sequence_files,
        )

        if resolved.is_file() and resolved.suffix.lower() == ".exr":
            return np.ascontiguousarray(_read_exr_pillow(resolved), dtype=np.uint8)
        files = list_sequence_files(resolved)
        if frame_number < 0 or frame_number >= len(files):
            raise MediaReadError(f"Frame {frame_number} is outside the sequence.")
        file_path = files[frame_number]
        if file_path.suffix.lower() != ".exr":
            raise MediaReadError(
                f"SOURCE Pillow EXR fallback requires .exr, got {file_path.suffix!r}"
            )
        return np.ascontiguousarray(_read_exr_pillow(file_path), dtype=np.uint8)

    def put_preview(
        self,
        path: Path,
        frame_number: int,
        image: NDArray[np.uint8],
        *,
        expand_to_fit: bool = False,
        allow_eviction: bool = True,
    ) -> bool:
        key: PreviewKey = (_resolve_path(path), frame_number, self._transform_id)
        return self._preview_cache.put(
            key,
            image,
            expand_to_fit=expand_to_fit,
            allow_eviction=allow_eviction,
        )

    def get_preview(
        self,
        path: Path,
        frame_number: int,
    ) -> NDArray[np.uint8] | None:
        key: PreviewKey = (_resolve_path(path), frame_number, self._transform_id)
        return self._preview_cache.get(key)

    def prefetch_raw(
        self,
        path: Path,
        anchor_frame: int,
        count: int,
        *,
        is_current: Callable[[], bool],
    ) -> None:
        """Warm upcoming EXR scene frames without evicting existing raw entries."""
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
                loaded = self._get_or_load_scene(
                    reader,
                    resolved,
                    frame_number,
                    allow_eviction=False,
                )
                if loaded is None:
                    self._raw_prefetch_skips += 1
                    return
            except Exception:
                self._raw_prefetch_skips += 1
                continue

    def prefetch_preview(
        self,
        path: Path,
        anchor_frame: int,
        count: int,
        *,
        is_current: Callable[[], bool],
    ) -> None:
        """Warm upcoming preview frames without evicting existing preview entries."""
        resolved = _resolve_path(path)
        for offset in range(1, count + 1):
            if not is_current():
                return
            frame_number = anchor_frame + offset
            if self.get_preview(resolved, frame_number) is not None:
                continue
            try:
                # Decode under temporary path; put with no eviction.
                frame = self._read_frame_for_prefetch(resolved, frame_number)
            except Exception:
                self._preview_prefetch_skips += 1
                continue
            stored = self.put_preview(
                resolved,
                frame_number,
                frame,
                allow_eviction=False,
            )
            if not stored:
                self._preview_prefetch_skips += 1
                return

    def _read_frame_for_prefetch(
        self,
        resolved: Path,
        frame_number: int,
    ) -> NDArray[np.uint8]:
        """Like read_frame but does not write the preview cache (caller decides)."""
        with self._lock:
            transform = self._display_transform
            reader = self._reader
            tid = self._transform_id

        if _is_scene_frame_source(reader) and self._frame_is_exr_candidate(
            reader, resolved, frame_number
        ):
            scene = self._get_or_load_scene(
                reader, resolved, frame_number, allow_eviction=False
            )
            if scene is None:
                raise RuntimeError("raw prefetch could not admit scene frame")
            preview = transform.apply(scene.pixels)
            self._preview_generations += 1
        else:
            preview = reader.read_frame(resolved, frame_number)
            self._preview_generations += 1
        del tid
        return np.ascontiguousarray(preview, dtype=np.uint8)

    def _get_or_load_scene(
        self,
        reader: MediaReader,
        resolved: Path,
        frame_number: int,
        *,
        allow_eviction: bool = True,
    ) -> SceneFrame | None:
        cached = self._raw_cache.get(resolved, frame_number)
        if cached is not None:
            return cached

        # Serialize miss→load so concurrent workers share one OIIO read.
        # Do not hold RawFrameCache.lock across OIIO; hold only this load lock.
        with self._scene_load_lock:
            cached = self._raw_cache.get(resolved, frame_number)
            if cached is not None:
                return cached
            scene = reader.read_scene_frame(resolved, frame_number)  # type: ignore[attr-defined]
            self._raw_decodes += 1
            admitted = self._raw_cache.put(scene, allow_eviction=allow_eviction)
            if admitted:
                return scene
            if allow_eviction:
                return scene
            return None


    def _frame_is_exr_candidate(
        self,
        reader: MediaReader,
        resolved: Path,
        frame_number: int,
    ) -> bool:
        del reader
        try:
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
