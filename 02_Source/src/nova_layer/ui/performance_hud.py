"""Performance HUD for Viewer Color Pipeline diagnostics (Phase 9E-1).

Read-only overlay text built from peek-safe ``ColorPipelineDiagnostics``.
Does not decode frames or mutate cache hit/miss/LRU.
"""

from __future__ import annotations

from dataclasses import dataclass

from nova_layer.app.color_pipeline_diagnostics import (
    ColorPipelineDiagnostics,
    format_hit_rate,
    format_mib,
)
from nova_layer.app.processing_frames import ProcessingColorPolicy


@dataclass(frozen=True, slots=True)
class PerformanceHudSettings:
    enabled: bool = False
    compact: bool = True
    opacity: float = 0.85

    def __post_init__(self) -> None:
        opacity = float(self.opacity)
        if opacity < 0.0 or opacity > 1.0:
            raise ValueError(f"opacity must be in [0, 1], got {opacity}")


@dataclass(frozen=True, slots=True)
class HudLine:
    text: str
    warn: bool = False


_BUDGET_WARN_RATIO = 0.80


def _budget_warn(current_mib: float, max_mib: float) -> bool:
    if max_mib <= 0:
        return False
    return (current_mib / max_mib) >= _BUDGET_WARN_RATIO


def _backend_label(diagnostics: ColorPipelineDiagnostics) -> str:
    backend = (diagnostics.active_backend or "—").strip() or "—"
    # Shorten common names for compact HUD.
    lower = backend.lower()
    if "ocio" in lower:
        return "OCIO"
    if "legacy" in lower:
        return "Legacy"
    return backend


def _frame_label(diagnostics: ColorPipelineDiagnostics) -> str:
    if diagnostics.active_frame is None and not diagnostics.media_path:
        return "No active media"
    if diagnostics.active_frame is None:
        return "Frame —"
    return f"Frame {int(diagnostics.active_frame)}"


def format_performance_hud_lines(
    diagnostics: ColorPipelineDiagnostics,
    *,
    compact: bool = True,
) -> tuple[HudLine, ...]:
    """Build HUD lines from a peek-safe diagnostics snapshot."""
    viewer_policy = (
        diagnostics.active_policy or ProcessingColorPolicy.PREVIEW.value
    ).upper()
    processing_policy = (
        diagnostics.processing_default_policy or ProcessingColorPolicy.SOURCE.value
    ).upper()
    raw_mib = float(diagnostics.raw_cache_mib)
    raw_max = float(diagnostics.raw_cache_max_mib)
    prv_mib = float(diagnostics.preview_cache_mib)
    prv_max = float(diagnostics.preview_cache_max_mib)
    src_mib = float(diagnostics.source_cache_mib)
    src_max = float(diagnostics.source_cache_max_mib)

    lines: list[HudLine] = [
        HudLine(_frame_label(diagnostics)),
        HudLine(f"{_backend_label(diagnostics)} · {viewer_policy} / {processing_policy}"),
        HudLine(
            f"RAW {format_mib(raw_mib)} / {format_mib(raw_max)} MiB",
            warn=_budget_warn(raw_mib, raw_max),
        ),
        HudLine(
            f"PRV {format_mib(prv_mib)} / {format_mib(prv_max)} MiB",
            warn=_budget_warn(prv_mib, prv_max),
        ),
        HudLine(
            f"SRC {format_mib(src_mib)} / {format_mib(src_max)} MiB",
            warn=_budget_warn(src_mib, src_max),
        ),
        HudLine(
            f"Decode {int(diagnostics.raw_decode_count)} · "
            f"Preview {int(diagnostics.preview_generation_count)}"
        ),
    ]

    if not compact:
        raw = diagnostics.raw_cache
        prv = diagnostics.preview_cache
        src = diagnostics.source_cache
        raw_entries = raw.max_entries if raw.max_entries is not None else "—"
        prv_entries = prv.max_entries if prv.max_entries is not None else "—"
        src_entries = src.max_entries if src.max_entries is not None else "—"
        lines.extend(
            [
                HudLine(
                    f"RAW {raw.count}/{raw_entries} · "
                    f"{format_mib(raw_mib)}/{format_mib(raw_max)} MiB · "
                    f"Hit {format_hit_rate(diagnostics.raw_hit_rate)}"
                ),
                HudLine(
                    f"PRV {prv.count}/{prv_entries} · "
                    f"{format_mib(prv_mib)}/{format_mib(prv_max)} MiB · "
                    f"Hit {format_hit_rate(diagnostics.preview_hit_rate)}"
                ),
                HudLine(
                    f"SRC {src.count}/{src_entries} · "
                    f"{format_mib(src_mib)}/{format_mib(src_max)} MiB · "
                    f"Hit {format_hit_rate(diagnostics.source_hit_rate)}"
                ),
                HudLine(
                    f"Evict R/P/S: {raw.evictions} / {prv.evictions} / {src.evictions}"
                ),
                HudLine(
                    "Prefetch skip R/P: "
                    f"{diagnostics.pipeline.raw_prefetch_skips} / "
                    f"{diagnostics.pipeline.preview_prefetch_skips}"
                ),
                HudLine(
                    f"Oversized admit/reject R: "
                    f"{raw.oversized_admissions}/{raw.oversized_rejections} · "
                    f"P: {prv.oversized_admissions}/{prv.oversized_rejections} · "
                    f"S: {src.oversized_admissions}/{src.oversized_rejections}"
                ),
                HudLine(
                    f"Transform: {diagnostics.transform_identity_display or diagnostics.transform_identity}"
                ),
            ]
        )

    warning_bits: list[str] = []
    if diagnostics.fallback_reason:
        warning_bits.append(str(diagnostics.fallback_reason))
    for item in diagnostics.resolve_warnings or ():
        warning_bits.append(str(item))
    for item in diagnostics.warnings or ():
        text = str(item)
        if text and text not in warning_bits:
            warning_bits.append(text)
    if warning_bits:
        joined = "; ".join(warning_bits)
        if len(joined) > 120:
            joined = joined[:117] + "..."
        lines.append(HudLine(f"Warnings: {joined}", warn=True))
    elif not compact:
        lines.append(HudLine("Warnings: None"))

    return tuple(lines)


def format_performance_hud_text(
    diagnostics: ColorPipelineDiagnostics,
    *,
    compact: bool = True,
) -> str:
    return "\n".join(
        line.text for line in format_performance_hud_lines(diagnostics, compact=compact)
    )
