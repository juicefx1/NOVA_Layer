"""Depth Region → existing SAM guidance proposal (Phase D3).

Depth Regions remain coarse spatial priors. This module never feeds a mask into
SAM — it only emits existing ``GuidancePoint`` / ``BoundingRegion`` types.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from nova_layer.app.depth_region import HUGE_COVERAGE, TINY_COVERAGE, DepthRegion
from nova_layer.domain.models import BoundingRegion, GuidancePoint

DEFAULT_BBOX_PADDING_FRACTION = 0.02
DEFAULT_DEDUPE_DISTANCE_PX = 3.0
DEFAULT_NEGATIVE_OUTSET_PX = 2
MIN_BBOX_SIDE_PX = 4
MAX_POSITIVE_POINTS = 4
MIN_SPREAD_AXIS_PX = 6.0


@dataclass(frozen=True, slots=True)
class DepthGuidanceProposal:
    """Session proposal mapping a DepthRegion into existing Artist Guidance."""

    frame_number: int
    positive_points: tuple[GuidancePoint, ...]
    negative_points: tuple[GuidancePoint, ...]
    bounding_region: BoundingRegion | None
    source_region_coverage: float
    warning: str | None = None


def _clamp_int(value: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(round(value)))))


def _pixel_to_normalized(
    x: int,
    y: int,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float]:
    """Map inclusive pixel centers to normalized Artist Guidance coordinates."""
    nx = float(np.clip((float(x) + 0.5) / float(image_width), 0.0, 1.0))
    ny = float(np.clip((float(y) + 0.5) / float(image_height), 0.0, 1.0))
    return nx, ny


def _point_key(point: GuidancePoint) -> tuple[float, float, str]:
    return (round(float(point.x), 6), round(float(point.y), 6), str(point.polarity))


def guidance_point_key(point: GuidancePoint) -> tuple[float, float, str]:
    """Public stable key for session provenance / dedupe tracking."""
    return _point_key(point)


def _make_point(
    x: int,
    y: int,
    *,
    polarity: str,
    image_width: int,
    image_height: int,
) -> GuidancePoint:
    nx, ny = _pixel_to_normalized(
        x, y, image_width=image_width, image_height=image_height
    )
    return GuidancePoint(x=nx, y=ny, polarity=polarity)  # type: ignore[arg-type]


def _dedupe_pixel_points(
    pixels: list[tuple[int, int]],
    *,
    min_distance: float,
) -> list[tuple[int, int]]:
    kept: list[tuple[int, int]] = []
    min_sq = float(min_distance) ** 2
    for px, py in pixels:
        too_close = False
        for kx, ky in kept:
            if (px - kx) ** 2 + (py - ky) ** 2 < min_sq:
                too_close = True
                break
        if not too_close:
            kept.append((px, py))
    return kept


def _nearest_mask_pixel(
    mask: NDArray[np.bool_],
    x: float,
    y: float,
) -> tuple[int, int] | None:
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    dx = xs.astype(np.float64) - float(x)
    dy = ys.astype(np.float64) - float(y)
    idx = int(np.argmin(dx * dx + dy * dy))
    return int(xs[idx]), int(ys[idx])


def _positive_pixels(
    region: DepthRegion,
    *,
    height: int,
    width: int,
) -> list[tuple[int, int]]:
    mask = np.asarray(region.mask, dtype=bool)
    candidates: list[tuple[int, int]] = []

    sx, sy = int(region.seed_x), int(region.seed_y)
    if 0 <= sx < width and 0 <= sy < height and bool(mask[sy, sx]):
        candidates.append((sx, sy))
    else:
        nearest = _nearest_mask_pixel(mask, float(sx), float(sy))
        if nearest is not None:
            candidates.append(nearest)

    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return candidates

    cx = float(xs.mean())
    cy = float(ys.mean())
    centroid = _nearest_mask_pixel(mask, cx, cy)
    if centroid is not None:
        candidates.append(centroid)

    if ys.size >= 3:
        coords = np.stack([xs.astype(np.float64), ys.astype(np.float64)], axis=1)
        centered = coords - coords.mean(axis=0, keepdims=True)
        # Compact SVD; deterministic for fixed inputs.
        try:
            _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            vt = None
        if vt is not None and vt.shape[0] >= 1:
            axis = vt[0]
            proj = centered @ axis
            span = float(proj.max() - proj.min())
            if span >= MIN_SPREAD_AXIS_PX:
                lo = coords[int(np.argmin(proj))]
                hi = coords[int(np.argmax(proj))]
                candidates.append((_clamp_int(lo[0], 0, width - 1), _clamp_int(lo[1], 0, height - 1)))
                candidates.append((_clamp_int(hi[0], 0, width - 1), _clamp_int(hi[1], 0, height - 1)))

    # Keep only pixels that remain inside the region mask.
    filtered = [
        (x, y)
        for x, y in candidates
        if 0 <= x < width and 0 <= y < height and bool(mask[y, x])
    ]
    return _dedupe_pixel_points(filtered, min_distance=DEFAULT_DEDUPE_DISTANCE_PX)[
        :MAX_POSITIVE_POINTS
    ]


def _negative_pixels(
    region: DepthRegion,
    *,
    height: int,
    width: int,
    outset: int = DEFAULT_NEGATIVE_OUTSET_PX,
) -> list[tuple[int, int]]:
    box = region.bounding_box
    if box is None:
        return []
    x0, y0, x1, y1 = (int(v) for v in box)
    mask = np.asarray(region.mask, dtype=bool)
    mid_x = (x0 + x1) // 2
    mid_y = (y0 + y1) // 2
    raw = (
        (x0 - outset, mid_y),  # left
        (x1 + outset, mid_y),  # right
        (mid_x, y0 - outset),  # top
        (mid_x, y1 + outset),  # bottom
    )
    out: list[tuple[int, int]] = []
    for x, y in raw:
        cx = _clamp_int(x, 0, width - 1)
        cy = _clamp_int(y, 0, height - 1)
        if bool(mask[cy, cx]):
            continue
        out.append((cx, cy))
    return _dedupe_pixel_points(out, min_distance=DEFAULT_DEDUPE_DISTANCE_PX)


def _inclusive_box_to_bounding_region(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    image_width: int,
    image_height: int,
) -> BoundingRegion | None:
    if image_width <= 0 or image_height <= 0:
        return None
    x0 = max(0, min(image_width - 1, x0))
    x1 = max(0, min(image_width - 1, x1))
    y0 = max(0, min(image_height - 1, y0))
    y1 = max(0, min(image_height - 1, y1))
    if x1 < x0 or y1 < y0:
        return None
    nx = float(x0) / float(image_width)
    ny = float(y0) / float(image_height)
    nw = float(x1 - x0 + 1) / float(image_width)
    nh = float(y1 - y0 + 1) / float(image_height)
    # Keep inside normalized frame required by BoundingRegion validator.
    nw = min(nw, max(0.0, 1.0 - nx))
    nh = min(nh, max(0.0, 1.0 - ny))
    if nw <= 0.0 or nh <= 0.0:
        return None
    try:
        return BoundingRegion(x=nx, y=ny, width=nw, height=nh)
    except ValueError:
        return None


def depth_bbox_to_bounding_region(
    region: DepthRegion,
    *,
    image_width: int,
    image_height: int,
    bbox_padding_fraction: float = DEFAULT_BBOX_PADDING_FRACTION,
) -> BoundingRegion | None:
    """Convert inclusive DepthRegion.bounding_box → normalized BoundingRegion."""
    box = region.bounding_box
    if box is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in box)
    pad_frac = float(np.clip(bbox_padding_fraction, 0.0, 0.25))
    pad_x = max(1, int(round(pad_frac * image_width)))
    pad_y = max(1, int(round(pad_frac * image_height)))
    side_w = x1 - x0 + 1
    side_h = y1 - y0 + 1
    tiny = (
        region.coverage < TINY_COVERAGE
        or side_w < MIN_BBOX_SIDE_PX
        or side_h < MIN_BBOX_SIDE_PX
        or region.pixel_count <= 2
    )
    if tiny:
        pad_x = max(pad_x, 2)
        pad_y = max(pad_y, 2)
    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(image_width - 1, x1 + pad_x)
    y1 = min(image_height - 1, y1 + pad_y)
    return _inclusive_box_to_bounding_region(
        x0,
        y0,
        x1,
        y1,
        image_width=image_width,
        image_height=image_height,
    )


def build_depth_guidance_proposal(
    region: DepthRegion,
    *,
    image_width: int,
    image_height: int,
    include_negative_points: bool = True,
    bbox_padding_fraction: float = DEFAULT_BBOX_PADDING_FRACTION,
) -> DepthGuidanceProposal:
    """Pure DepthRegion → Artist Guidance proposal (no Qt, no depth re-fetch)."""
    image_width = int(image_width)
    image_height = int(image_height)
    warnings: list[str] = []

    if image_width <= 0 or image_height <= 0:
        return DepthGuidanceProposal(
            frame_number=int(region.frame_number),
            positive_points=(),
            negative_points=(),
            bounding_region=None,
            source_region_coverage=float(region.coverage),
            warning="Invalid image size for Depth guidance.",
        )

    mask = np.asarray(region.mask, dtype=bool)
    height, width = mask.shape
    # Operate in mask space, clamp later to media bounds for normalized coords.
    work_h = min(height, image_height)
    work_w = min(width, image_width)
    if (height, width) != (image_height, image_width):
        warnings.append(
            "Depth Region resolution differs from media; guidance was clamped to media bounds."
        )

    if region.pixel_count <= 0 or not bool(np.any(mask)):
        if region.warning:
            warnings.append(region.warning)
        else:
            warnings.append("No Depth Region pixels to convert into guidance.")
        return DepthGuidanceProposal(
            frame_number=int(region.frame_number),
            positive_points=(),
            negative_points=(),
            bounding_region=None,
            source_region_coverage=float(region.coverage),
            warning=" ".join(warnings) if warnings else None,
        )

    # Work on a view clipped to media size when larger; if smaller, pad false.
    if height == image_height and width == image_width:
        work_mask_region = region
    else:
        clipped = np.zeros((image_height, image_width), dtype=bool)
        hh = min(height, image_height)
        ww = min(width, image_width)
        clipped[:hh, :ww] = mask[:hh, :ww]
        from nova_layer.app.depth_region import freeze_bool_mask, bounding_box_from_mask

        clipped_frozen = freeze_bool_mask(clipped)
        work_mask_region = DepthRegion(
            frame_number=region.frame_number,
            seed_x=min(max(0, region.seed_x), image_width - 1),
            seed_y=min(max(0, region.seed_y), image_height - 1),
            seed_depth=region.seed_depth,
            tolerance=region.tolerance,
            mask=clipped_frozen,
            bounding_box=bounding_box_from_mask(clipped_frozen),
            pixel_count=int(np.count_nonzero(clipped_frozen)),
            coverage=float(np.count_nonzero(clipped_frozen))
            / float(image_width * image_height),
            warning=region.warning,
            effective_band=region.effective_band,
        )
        del work_h, work_w

    positives_px = _positive_pixels(
        work_mask_region, height=image_height, width=image_width
    )
    positives = tuple(
        _make_point(
            x,
            y,
            polarity="positive",
            image_width=image_width,
            image_height=image_height,
        )
        for x, y in positives_px
    )

    negatives: tuple[GuidancePoint, ...] = ()
    if include_negative_points:
        negatives_px = _negative_pixels(
            work_mask_region, height=image_height, width=image_width
        )
        negatives = tuple(
            _make_point(
                x,
                y,
                polarity="negative",
                image_width=image_width,
                image_height=image_height,
            )
            for x, y in negatives_px
        )

    bbox = depth_bbox_to_bounding_region(
        work_mask_region,
        image_width=image_width,
        image_height=image_height,
        bbox_padding_fraction=bbox_padding_fraction,
    )
    if work_mask_region.bounding_box is None:
        warnings.append("Depth Region has no bounding box.")
    elif bbox is None:
        warnings.append("Could not build a valid BoundingRegion from Depth Region.")

    if region.coverage < TINY_COVERAGE or region.warning and "small" in (region.warning or "").lower():
        warnings.append("Depth Region is very small — Depth guidance may be weak.")
    if region.coverage > HUGE_COVERAGE:
        warnings.append("Depth Region covers most of the frame — review generated bbox.")
    if not positives:
        warnings.append("No positive Depth guidance points could be generated.")
    if region.warning and region.warning not in warnings:
        warnings.append(region.warning)

    return DepthGuidanceProposal(
        frame_number=int(region.frame_number),
        positive_points=positives,
        negative_points=negatives,
        bounding_region=bbox,
        source_region_coverage=float(region.coverage),
        warning=" ".join(dict.fromkeys(warnings)) if warnings else None,
    )


def merge_depth_guidance_into_points(
    existing: list[GuidancePoint],
    proposal: DepthGuidanceProposal,
    *,
    previous_depth_keys: set[tuple[float, float, str]] | frozenset[tuple[float, float, str]],
) -> tuple[list[GuidancePoint], set[tuple[float, float, str]]]:
    """Keep manual points, replace prior depth points with proposal points."""
    manual = [p for p in existing if _point_key(p) not in previous_depth_keys]
    manual_keys = {_point_key(p) for p in manual}
    depth_points = [*proposal.positive_points, *proposal.negative_points]
    new_depth_keys: set[tuple[float, float, str]] = set()
    merged = list(manual)
    for point in depth_points:
        key = _point_key(point)
        if key in manual_keys or key in new_depth_keys:
            continue
        merged.append(point)
        new_depth_keys.add(key)
    return merged, new_depth_keys
