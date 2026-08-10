"""Depth region extraction and visualization (Phase D2).

Depth Regions are coarse spatial priors — never final mattes or object masks.
Connected-component policy: **8-connected** (orthogonal + diagonal).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from nova_layer.ports.depth import DepthFrame, freeze_valid_mask

DEFAULT_DEPTH_TOLERANCE = 0.08
TINY_COVERAGE = 0.0005
HUGE_COVERAGE = 0.55

# D3.7 tolerance-cliff UX (from D3.6 sweeps: e.g. 5%→37%, 16%→85% at 0.08→0.10).
TOLERANCE_CLIFF_GROWTH_RATIO = 2.5
TOLERANCE_CLIFF_ABS_COVERAGE = 0.35
TOLERANCE_CLIFF_WARNING = (
    "Depth region expanded sharply. Consider lowering tolerance."
)


@dataclass(frozen=True, slots=True)
class DepthRegion:
    """Candidate depth band around a click seed (not an object segmentation)."""

    frame_number: int
    seed_x: int
    seed_y: int
    seed_depth: float
    tolerance: float
    mask: NDArray[np.bool_]
    bounding_box: tuple[int, int, int, int] | None
    pixel_count: int
    coverage: float
    warning: str | None = None
    effective_band: float = 0.0


def freeze_bool_mask(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    frozen = np.asarray(mask, dtype=bool).copy()
    frozen.setflags(write=False)
    return frozen


def _valid_depth_mask(frame: DepthFrame) -> NDArray[np.bool_]:
    finite = np.isfinite(frame.depth)
    if frame.valid_mask is None:
        return finite
    return np.asarray(frame.valid_mask, dtype=bool) & finite


def robust_depth_range(
    depth: NDArray[np.float32],
    valid: NDArray[np.bool_],
    *,
    low_percentile: float = 5.0,
    high_percentile: float = 95.0,
) -> tuple[float, float]:
    """Return (p_low, p_high) over valid finite depths."""
    values = depth[valid]
    if values.size == 0:
        return 0.0, 0.0
    lo = float(np.percentile(values, low_percentile))
    hi = float(np.percentile(values, high_percentile))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def effective_depth_band(
    depth: NDArray[np.float32],
    valid: NDArray[np.bool_],
    tolerance: float,
) -> float:
    """Map UI tolerance in [0, 1] to a raw depth half-width via p5–p95 range."""
    tolerance = float(np.clip(tolerance, 0.0, 1.0))
    lo, hi = robust_depth_range(depth, valid)
    span = hi - lo
    if span <= 0.0:
        # Degenerate / near-flat: absolute zero band (caller warns).
        return 0.0
    return tolerance * span


def connected_component_8(
    candidate: NDArray[np.bool_],
    *,
    seed_x: int,
    seed_y: int,
) -> NDArray[np.bool_]:
    """Keep only the 8-connected component that contains the seed."""
    height, width = candidate.shape
    out = np.zeros((height, width), dtype=bool)
    if not (0 <= seed_x < width and 0 <= seed_y < height):
        return out
    if not bool(candidate[seed_y, seed_x]):
        return out

    queue: deque[tuple[int, int]] = deque()
    queue.append((seed_x, seed_y))
    out[seed_y, seed_x] = True
    while queue:
        x, y = queue.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                if out[ny, nx] or not candidate[ny, nx]:
                    continue
                out[ny, nx] = True
                queue.append((nx, ny))
    return out


def bounding_box_from_mask(mask: NDArray[np.bool_]) -> tuple[int, int, int, int] | None:
    """Return inclusive (x0, y0, x1, y1) or None when empty."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def inclusive_bbox_area(box: tuple[int, int, int, int] | None) -> float:
    """Pixel area of an inclusive (x0, y0, x1, y1) box, or 0 when missing."""
    if box is None:
        return 0.0
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 < x0 or y1 < y0:
        return 0.0
    return float((x1 - x0 + 1) * (y1 - y0 + 1))


def detect_tolerance_cliff(
    previous: DepthRegion | None,
    current: DepthRegion,
    *,
    growth_ratio: float = TOLERANCE_CLIFF_GROWTH_RATIO,
    abs_coverage: float = TOLERANCE_CLIFF_ABS_COVERAGE,
) -> str | None:
    """Return a non-blocking cliff warning, or None when growth is smooth / first pick.

    Triggers when coverage or inclusive bbox area grows by ``growth_ratio`` vs the
    previous same-seed region, or when absolute coverage crosses ``abs_coverage``
    while still growing by at least 1.5× (guards false positives on tiny→tiny).
    No automatic tolerance rollback — caller only surfaces the message.
    """
    if previous is None:
        return None
    if int(previous.frame_number) != int(current.frame_number):
        return None
    if int(previous.seed_x) != int(current.seed_x) or int(previous.seed_y) != int(
        current.seed_y
    ):
        return None

    prev_cov = float(previous.coverage)
    new_cov = float(current.coverage)
    prev_area = inclusive_bbox_area(previous.bounding_box)
    new_area = inclusive_bbox_area(current.bounding_box)
    ratio = float(growth_ratio)

    coverage_jump = prev_cov > 0.0 and new_cov > prev_cov * ratio
    bbox_jump = prev_area > 0.0 and new_area > prev_area * ratio
    absolute_jump = (
        new_cov > float(abs_coverage)
        and prev_cov > 0.0
        and new_cov > prev_cov * 1.5
    )
    if coverage_jump or bbox_jump or absolute_jump:
        return TOLERANCE_CLIFF_WARNING
    return None


def annotate_tolerance_cliff(
    region: DepthRegion,
    previous: DepthRegion | None,
) -> DepthRegion:
    """Attach a tolerance-cliff warning onto ``region`` when criteria match."""
    cliff = detect_tolerance_cliff(previous, region)
    if cliff is None:
        return region
    existing = (region.warning or "").strip()
    if cliff in existing:
        return region
    merged = f"{existing} {cliff}".strip() if existing else cliff
    return replace(region, warning=merged)


def extract_depth_region(
    frame: DepthFrame,
    *,
    seed_x: int,
    seed_y: int,
    tolerance: float = DEFAULT_DEPTH_TOLERANCE,
) -> DepthRegion:
    """Build a seed-connected depth band candidate from a DepthFrame.

    Algorithm:
    1. Require seed in-bounds and valid/finite.
    2. ``effective_band = tolerance * (p95 - p5)`` of valid depths.
    3. Candidate = ``abs(depth - d0) <= effective_band`` AND valid.
    4. Keep 8-connected component containing the seed only.
    """
    depth = frame.depth
    height, width = depth.shape
    tolerance = float(np.clip(tolerance, 0.0, 1.0))
    valid = _valid_depth_mask(frame)
    empty = freeze_bool_mask(np.zeros((height, width), dtype=bool))

    def _empty(*, warning: str, seed_depth: float = float("nan")) -> DepthRegion:
        return DepthRegion(
            frame_number=int(frame.frame_number),
            seed_x=int(seed_x),
            seed_y=int(seed_y),
            seed_depth=float(seed_depth),
            tolerance=tolerance,
            mask=empty,
            bounding_box=None,
            pixel_count=0,
            coverage=0.0,
            warning=warning,
            effective_band=0.0,
        )

    if seed_x < 0 or seed_y < 0 or seed_x >= width or seed_y >= height:
        return _empty(warning="Click is outside the depth map.")
    if not bool(valid[seed_y, seed_x]):
        return _empty(warning="Seed depth is invalid (non-finite or masked).")

    seed_depth = float(depth[seed_y, seed_x])
    band = effective_depth_band(depth, valid, tolerance)
    if band <= 0.0 and tolerance > 0.0:
        return _empty(
            warning="Depth range is too flat to form a Depth Region.",
            seed_depth=seed_depth,
        )

    candidate = valid & (np.abs(depth - np.float32(seed_depth)) <= np.float32(band))
    if tolerance == 0.0:
        # Exact seed match only (still connected — just the seed when unique).
        candidate = valid & (depth == np.float32(seed_depth))

    component = connected_component_8(candidate, seed_x=seed_x, seed_y=seed_y)
    pixel_count = int(np.count_nonzero(component))
    coverage = float(pixel_count) / float(height * width) if height * width else 0.0
    warning: str | None = None
    if pixel_count == 0:
        warning = "No connected Depth Region at this seed."
    elif coverage < TINY_COVERAGE:
        warning = "Depth Region is very small — increase Depth Tolerance."
    elif coverage > HUGE_COVERAGE:
        warning = "Depth Region covers most of the frame — decrease Depth Tolerance."

    return DepthRegion(
        frame_number=int(frame.frame_number),
        seed_x=int(seed_x),
        seed_y=int(seed_y),
        seed_depth=seed_depth,
        tolerance=tolerance,
        mask=freeze_bool_mask(component),
        bounding_box=bounding_box_from_mask(component),
        pixel_count=pixel_count,
        coverage=coverage,
        warning=warning,
        effective_band=float(band if tolerance > 0.0 else 0.0),
    )


def depth_to_grayscale(
    frame: DepthFrame,
    *,
    percentile_range: tuple[float, float] = (5.0, 95.0),
    near_white: bool = True,
) -> NDArray[np.uint8]:
    """Viewer-only grayscale remap. Does not mutate ``frame.depth``.

    When ``near_white`` is True, near depth values map toward white using
    ``frame.near_is`` (high→bright when near_is='high', low→bright when 'low').
    Invalid pixels are 0.
    """
    depth = np.asarray(frame.depth, dtype=np.float32)
    valid = _valid_depth_mask(frame)
    out = np.zeros(depth.shape, dtype=np.uint8)
    if not bool(np.any(valid)):
        return out

    lo_p, hi_p = percentile_range
    lo, hi = robust_depth_range(depth, valid, low_percentile=lo_p, high_percentile=hi_p)
    span = hi - lo
    if span <= 1e-12:
        out[valid] = 128
        return out

    normalized = (depth - lo) / span
    normalized = np.clip(normalized, 0.0, 1.0)
    # near_is='high' means larger values are nearer.
    if near_white:
        if frame.near_is == "high":
            display = normalized
        else:
            display = 1.0 - normalized
    else:
        display = normalized if frame.near_is == "high" else 1.0 - normalized

    values = np.rint(display * 255.0).astype(np.uint8)
    out = np.where(valid, values, np.uint8(0))
    return np.ascontiguousarray(out)


def blend_depth_overlay(
    base_rgb: NDArray[np.uint8],
    gray: NDArray[np.uint8],
    *,
    opacity: float,
) -> NDArray[np.uint8]:
    """Blend single-channel depth visualization onto an RGB preview (new array)."""
    opacity = float(np.clip(opacity, 0.0, 1.0))
    base = np.asarray(base_rgb, dtype=np.float32)
    gray3 = np.stack([gray, gray, gray], axis=-1).astype(np.float32)
    mixed = base * (1.0 - opacity) + gray3 * opacity
    return np.ascontiguousarray(np.clip(np.rint(mixed), 0, 255).astype(np.uint8))


# Re-export helper for callers that already freeze masks.
_ = freeze_valid_mask
