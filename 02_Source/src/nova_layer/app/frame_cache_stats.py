from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameCacheStats:
    """Snapshot of frame-cache accounting (caller computes hit_rate if needed)."""

    count: int
    current_bytes: int
    max_bytes: int
    max_entries: int | None
    hits: int
    misses: int
    evictions: int
    oversized_rejections: int
    oversized_admissions: int


@dataclass(frozen=True, slots=True)
class PreviewPipelineStats:
    """Pipeline-level counters (decode / generate / prefetch skips)."""

    raw_decodes: int
    preview_generations: int
    raw_prefetch_skips: int
    preview_prefetch_skips: int


def bytes_from_env_mb(name: str, default_bytes: int) -> int:
    """Parse ``NOVA_*_CACHE_MB``; invalid/missing → ``default_bytes``."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default_bytes
    try:
        megabytes = int(str(raw).strip())
    except ValueError:
        return default_bytes
    if megabytes < 1:
        return default_bytes
    return megabytes * 1024 * 1024
