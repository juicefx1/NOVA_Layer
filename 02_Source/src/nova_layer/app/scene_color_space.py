"""File-native SceneFrame contracts and SOURCE Legacy bake risk hints."""

from __future__ import annotations

# Tags treated as compatible with fixed Legacy linear→sRGB SOURCE bake
# (Rec.709 / sRGB linear family or OCIO scene_linear role naming).
_SAFE_SOURCE_TAGS: frozenset[str] = frozenset(
    {
        "scene_linear",
        "lin_rec709",
        "linear rec.709",
        "linear_rec709",
        "rec709",
        "rec.709",
        "lin_srgb",
        "linear srgb",
        "linear_srgb",
        "utility - linear - srgb",
        "utility - lin - srgb",
        "role_scene_linear",
    }
)

# Conservative wide-gamut / non-Rec709 markers (substring match on lowercased tag).
_RISKY_SOURCE_MARKERS: tuple[str, ...] = (
    "acescg",
    "aces2065",
    "aces 2065",
    "ap0",
    "ap1",
    "linear p3",
    "lin_p3",
    "p3-d65",
    "p3 d65",
    "rec2020",
    "rec.2020",
    "rec 2020",
    "arri wide",
    "awg",
    "redwide",
    "wide gamut",
)


def source_transform_warning(color_space: str | None) -> str | None:
    """Return a SOURCE Legacy bake risk warning, or None when no warning.

    SOURCE always applies fixed Legacy linear→sRGB (Rec.709-linear-family
    assumption). Tagged wide-gamut / ACES spaces get an explicit warning;
    unspecified/unknown tags do not warn (informational gap only).
    """
    if color_space is None:
        return None
    text = str(color_space).strip()
    if not text:
        return None
    lowered = text.casefold().replace("_", " ")
    compact = lowered.replace(" ", "")
    for safe in _SAFE_SOURCE_TAGS:
        safe_l = safe.casefold().replace("_", " ")
        if lowered == safe_l or compact == safe_l.replace(" ", ""):
            return None
        if "utility" in lowered and "linear" in lowered and "srgb" in lowered:
            return None
        if "linear" in lowered and ("rec.709" in lowered or "rec709" in lowered):
            return None
    for marker in _RISKY_SOURCE_MARKERS:
        marker_l = marker.casefold()
        if marker_l in lowered or marker_l.replace(" ", "") in compact:
            return (
                "SOURCE uses fixed Legacy linear→sRGB bake (Rec.709-linear family "
                f"assumption); tagged file color space {text!r} may be incorrect "
                "for SOURCE processing."
            )
    return None


def normalize_color_space_source(value: str | None) -> str:
    text = (value or "").strip().casefold()
    if text in {"oiio", "user", "unspecified"}:
        return text
    return "unspecified"
