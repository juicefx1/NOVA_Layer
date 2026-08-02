"""Read-only Color Pipeline diagnostics snapshot (Phase 9B / 10B / 10C-1).

Assembles existing cache / transform / resolve state without duplicating cache
policy or mutating runtime caches beyond optional raw-cache peek.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova_layer.adapters.color.display_transform import DisplayTransformDiagnostics
from nova_layer.adapters.color.settings import ResolvedColorSettings
from nova_layer.app.frame_cache_stats import FrameCacheStats, PreviewPipelineStats
from nova_layer.app.preview_pipeline import PreviewPipeline, TransformIdentity
from nova_layer.app.scene_color_space import source_transform_warning as warning_for_source
from nova_layer.app.working_space import (
    WORKING_CONVERTER_VERSION,
    WorkingSpaceSettings,
    resolve_working_space_intent,
)

_BYTES_PER_MIB = 1024 * 1024

_EMPTY_CACHE = FrameCacheStats(
    count=0,
    current_bytes=0,
    max_bytes=0,
    max_entries=None,
    hits=0,
    misses=0,
    evictions=0,
    oversized_rejections=0,
    oversized_admissions=0,
)

_EMPTY_PIPELINE = PreviewPipelineStats(
    raw_decodes=0,
    preview_generations=0,
    raw_prefetch_skips=0,
    preview_prefetch_skips=0,
)


def hit_rate(hits: int, misses: int) -> float | None:
    denominator = int(hits) + int(misses)
    if denominator <= 0:
        return None
    return float(hits) / float(denominator)


def bytes_to_mib(nbytes: int) -> float:
    return float(nbytes) / float(_BYTES_PER_MIB)


def format_hit_rate(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{rate * 100.0:.1f}%"


def format_mib(value: float) -> str:
    return f"{value:.1f}"


def format_transform_identity(identity: TransformIdentity | None) -> str:
    if identity is None:
        return "—"
    return (
        f"backend={identity.backend}; "
        f"ics={identity.input_color_space}; "
        f"display={identity.display or '—'}; "
        f"view={identity.view or '—'}; "
        f"exposure={identity.exposure:g}; "
        f"config={identity.config_path or '—'}; "
        f"config_source={identity.config_source or '—'}"
    )


@dataclass(frozen=True, slots=True)
class ColorPipelineDiagnostics:
    """Immutable snapshot of Viewer Color Pipeline runtime state."""

    active_backend: str
    active_policy: str | None
    transform_identity: str
    input_color_space: str | None
    display: str | None
    view: str | None
    exposure: float
    config_path: str | None
    config_source: str | None
    fallback_reason: str | None

    media_path: str | None
    shot_name: str | None

    raw_cache: FrameCacheStats
    preview_cache: FrameCacheStats
    source_cache: FrameCacheStats
    pipeline: PreviewPipelineStats

    raw_hit_rate: float | None
    preview_hit_rate: float | None
    source_hit_rate: float | None

    raw_cache_mib: float
    preview_cache_mib: float
    source_cache_mib: float
    raw_cache_max_mib: float
    preview_cache_max_mib: float
    source_cache_max_mib: float

    raw_decode_count: int
    preview_generation_count: int

    last_render_color_policy: str | None
    warnings: tuple[str, ...]

    # Phase 10B — SceneFrame tag / SOURCE risk (None when no cached scene frame).
    active_source_color_space: str | None = None
    source_color_space_source: str | None = None
    interpretation_color_space: str | None = None
    source_transform_warning: str | None = None

    # Phase 10C — working-space intent / runtime resolve.
    working_enabled: bool = False
    requested_working_color_space: str | None = None
    resolved_working_color_space: str | None = None
    working_resolution_source: str | None = None
    working_converter_version: str | None = None
    working_cache: FrameCacheStats = field(default=_EMPTY_CACHE)
    working_warnings: tuple[str, ...] = ()
    working_source_color_space: str | None = None
    working_conversion_applied: bool | None = None


def empty_frame_cache_stats() -> FrameCacheStats:
    return _EMPTY_CACHE


def _peek_cached_scene_tags(
    pipeline: PreviewPipeline | None,
    media_path: str | Path | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (color_space, color_space_source, warning) if frame 0 is already cached."""
    if pipeline is None or media_path is None:
        return None, None, None
    try:
        path = Path(media_path)
        if not pipeline.raw_cache.contains(path, 0):
            return None, None, None
        frame = pipeline.raw_cache.get(path, 0)
        if frame is None:
            return None, None, None
        warn = warning_for_source(frame.color_space)
        return frame.color_space, frame.color_space_source, warn
    except Exception:
        return None, None, None


def build_color_pipeline_diagnostics(
    *,
    pipeline: PreviewPipeline | None = None,
    transform_diagnostics: DisplayTransformDiagnostics | None = None,
    transform_identity: TransformIdentity | None = None,
    resolved: ResolvedColorSettings | None = None,
    media_path: str | Path | None = None,
    shot_name: str | None = None,
    last_render_color_policy: str | None = None,
    extra_warnings: Sequence[str] = (),
    active_policy: str | None = "preview",
    working_settings: WorkingSpaceSettings | None = None,
    working_cache_stats: FrameCacheStats | None = None,
) -> ColorPipelineDiagnostics:
    """Compose a safe diagnostics snapshot from available runtime pieces."""
    raw = pipeline.raw_cache_stats if pipeline is not None else _EMPTY_CACHE
    preview = pipeline.preview_cache_stats if pipeline is not None else _EMPTY_CACHE
    source = pipeline.source_cache_stats if pipeline is not None else _EMPTY_CACHE
    pipe = pipeline.pipeline_stats if pipeline is not None else _EMPTY_PIPELINE
    identity = (
        transform_identity
        if transform_identity is not None
        else (pipeline.transform_identity if pipeline is not None else None)
    )

    warnings: list[str] = []
    if resolved is not None:
        warnings.extend(str(item) for item in resolved.warnings)
    if transform_diagnostics is not None and transform_diagnostics.fallback_reason:
        warnings.append(f"fallback: {transform_diagnostics.fallback_reason}")
    for item in extra_warnings:
        text = str(item).strip()
        if text and text not in warnings:
            warnings.append(text)

    backend = "unknown"
    input_cs: str | None = None
    display: str | None = None
    view: str | None = None
    exposure = 0.0
    config_path: str | None = None
    config_source: str | None = None
    fallback: str | None = None

    if transform_diagnostics is not None:
        backend = str(transform_diagnostics.backend)
        input_cs = str(transform_diagnostics.input_color_space)
        display = transform_diagnostics.display
        view = transform_diagnostics.view
        exposure = float(transform_diagnostics.exposure)
        config_path = transform_diagnostics.config_path
        config_source = transform_diagnostics.config_source
        fallback = transform_diagnostics.fallback_reason
    elif resolved is not None:
        backend = str(resolved.backend)
        input_cs = str(resolved.input_color_space)
        display = resolved.display
        view = resolved.view
        exposure = float(resolved.exposure)
        config_path = str(resolved.config_path) if resolved.config_path else None
        config_source = resolved.config_source
    elif identity is not None:
        backend = str(identity.backend)
        input_cs = str(identity.input_color_space)
        display = identity.display
        view = identity.view
        exposure = float(identity.exposure)
        config_path = identity.config_path
        config_source = identity.config_source

    media_text = None if media_path is None else str(media_path)
    active_source, source_src, src_warn = _peek_cached_scene_tags(pipeline, media_path)
    if src_warn and src_warn not in warnings:
        warnings.append(src_warn)

    intent = resolve_working_space_intent(
        working_settings
        if working_settings is not None
        else (None if pipeline is None else pipeline.working_space_settings)
    )
    if working_cache_stats is not None:
        working_cache = working_cache_stats
    elif pipeline is not None:
        working_cache = pipeline.working_cache_stats
    else:
        working_cache = _EMPTY_CACHE

    working_enabled = intent.enabled
    requested_cs = intent.requested_color_space
    resolved_cs: str | None = None
    resolution_source = intent.resolution_source
    converter_version = (
        intent.converter_version if intent.enabled else WORKING_CONVERTER_VERSION
    )
    working_warns = list(intent.warnings)
    working_source: str | None = None
    conversion_applied: bool | None = None

    if pipeline is not None:
        try:
            resolved_ws = pipeline.resolved_working_space
            working_enabled = resolved_ws.enabled
            requested_cs = resolved_ws.requested_color_space or requested_cs
            resolved_cs = resolved_ws.working_color_space
            resolution_source = resolved_ws.resolution_source
            converter_version = resolved_ws.converter_version
            for item in resolved_ws.warnings:
                if item not in working_warns:
                    working_warns.append(item)
            for item in pipeline.working_warnings:
                if item not in working_warns:
                    working_warns.append(item)
            working_source = pipeline.last_working_source_color_space
            conversion_applied = (
                pipeline.last_working_conversion_applied
                if working_enabled
                else False
            )
        except Exception:
            pass

    if transform_diagnostics is not None:
        interpretation = str(transform_diagnostics.input_color_space)
    elif pipeline is not None:
        interpretation = pipeline.interpretation_color_space or input_cs
    else:
        interpretation = input_cs

    return ColorPipelineDiagnostics(
        active_backend=backend,
        active_policy=active_policy,
        transform_identity=format_transform_identity(identity),
        input_color_space=input_cs,
        display=display,
        view=view,
        exposure=exposure,
        config_path=config_path,
        config_source=config_source,
        fallback_reason=fallback,
        media_path=media_text,
        shot_name=shot_name,
        raw_cache=raw,
        preview_cache=preview,
        source_cache=source,
        pipeline=pipe,
        raw_hit_rate=hit_rate(raw.hits, raw.misses),
        preview_hit_rate=hit_rate(preview.hits, preview.misses),
        source_hit_rate=hit_rate(source.hits, source.misses),
        raw_cache_mib=bytes_to_mib(raw.current_bytes),
        preview_cache_mib=bytes_to_mib(preview.current_bytes),
        source_cache_mib=bytes_to_mib(source.current_bytes),
        raw_cache_max_mib=bytes_to_mib(raw.max_bytes),
        preview_cache_max_mib=bytes_to_mib(preview.max_bytes),
        source_cache_max_mib=bytes_to_mib(source.max_bytes),
        raw_decode_count=int(pipe.raw_decodes),
        preview_generation_count=int(pipe.preview_generations),
        last_render_color_policy=last_render_color_policy,
        warnings=tuple(warnings),
        active_source_color_space=active_source,
        source_color_space_source=source_src,
        interpretation_color_space=interpretation,
        source_transform_warning=src_warn,
        working_enabled=working_enabled,
        requested_working_color_space=requested_cs,
        resolved_working_color_space=resolved_cs,
        working_resolution_source=resolution_source,
        working_converter_version=converter_version,
        working_cache=working_cache,
        working_warnings=tuple(working_warns),
        working_source_color_space=working_source,
        working_conversion_applied=conversion_applied,
    )


def format_color_pipeline_diagnostics(diagnostics: ColorPipelineDiagnostics) -> str:
    """Plain-text dump suitable for clipboard copy."""
    working_hit = hit_rate(
        diagnostics.working_cache.hits,
        diagnostics.working_cache.misses,
    )
    lines = [
        "NOVA Layer Color Pipeline Diagnostics",
        f"Backend: {diagnostics.active_backend}",
        f"Active policy: {diagnostics.active_policy or '—'}",
        f"Input: {diagnostics.input_color_space or '—'}",
        f"Display/View: {diagnostics.display or '—'} / {diagnostics.view or '—'}",
        f"Exposure: {diagnostics.exposure:g}",
        f"Transform Identity: {diagnostics.transform_identity}",
        f"Config: {diagnostics.config_path or '—'} "
        f"(source={diagnostics.config_source or '—'})",
        f"Fallback: {diagnostics.fallback_reason or '—'}",
        f"Shot: {diagnostics.shot_name or '—'}",
        f"Media: {diagnostics.media_path or '—'}",
        f"Active source color space: "
        f"{diagnostics.active_source_color_space or '—'}",
        f"Source color space source: "
        f"{diagnostics.source_color_space_source or '—'}",
        f"Interpretation color space: "
        f"{diagnostics.interpretation_color_space or '—'}",
        f"SOURCE transform warning: "
        f"{diagnostics.source_transform_warning or '—'}",
        "",
        "Working Space:",
        f"  Enabled: {diagnostics.working_enabled}",
        f"  Requested: {diagnostics.requested_working_color_space or '—'}",
        f"  Resolved: {diagnostics.resolved_working_color_space or '—'}",
        f"  Resolution source: {diagnostics.working_resolution_source or '—'}",
        f"  Converter version: {diagnostics.working_converter_version or '—'}",
        f"  Working source: {diagnostics.working_source_color_space or '—'}",
        f"  Conversion applied: "
        f"{diagnostics.working_conversion_applied if diagnostics.working_conversion_applied is not None else '—'}",
        f"  "
        + _format_cache_line(
            "Working Cache",
            diagnostics.working_cache,
            working_hit,
            bytes_to_mib(diagnostics.working_cache.current_bytes),
            bytes_to_mib(diagnostics.working_cache.max_bytes),
        ),
        "",
        _format_cache_line(
            "Raw Cache",
            diagnostics.raw_cache,
            diagnostics.raw_hit_rate,
            diagnostics.raw_cache_mib,
            diagnostics.raw_cache_max_mib,
        ),
        _format_cache_line(
            "Preview Cache",
            diagnostics.preview_cache,
            diagnostics.preview_hit_rate,
            diagnostics.preview_cache_mib,
            diagnostics.preview_cache_max_mib,
        ),
        _format_cache_line(
            "Source Cache",
            diagnostics.source_cache,
            diagnostics.source_hit_rate,
            diagnostics.source_cache_mib,
            diagnostics.source_cache_max_mib,
        ),
        "",
        f"Raw decodes: {diagnostics.raw_decode_count}",
        f"Preview generations: {diagnostics.preview_generation_count}",
        f"Raw prefetch skips: {diagnostics.pipeline.raw_prefetch_skips}",
        f"Preview prefetch skips: {diagnostics.pipeline.preview_prefetch_skips}",
        f"Last render color policy: {diagnostics.last_render_color_policy or '—'}",
    ]
    if diagnostics.working_warnings:
        lines.append("")
        lines.append("Working warnings:")
        lines.extend(f"  - {item}" for item in diagnostics.working_warnings)
    if diagnostics.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {item}" for item in diagnostics.warnings)
    return "\n".join(lines) + "\n"


def _format_cache_line(
    label: str,
    stats: FrameCacheStats,
    rate: float | None,
    current_mib: float,
    max_mib: float,
) -> str:
    return (
        f"{label}: {stats.count} entries, "
        f"{format_mib(current_mib)} / {format_mib(max_mib)} MiB, "
        f"hit rate {format_hit_rate(rate)}, "
        f"evictions {stats.evictions}"
    )


def diagnostics_field(diagnostics: ColorPipelineDiagnostics, key: str) -> Any:
    """Test helper: safe getattr with None for missing."""
    return getattr(diagnostics, key, None)
