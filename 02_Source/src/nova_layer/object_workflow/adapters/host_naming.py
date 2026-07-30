from __future__ import annotations

import re
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename_component(value: str, *, fallback: str = "item") -> str:
    cleaned = _INVALID.sub("_", value.strip())
    cleaned = _WHITESPACE.sub("_", cleaned)
    cleaned = cleaned.strip("._")
    if not cleaned:
        return fallback
    return cleaned[:80]


def suggested_export_filename(
    *,
    source_name: str,
    generation_number: int | None,
    candidate_number: int | None,
    extraction_provider: str,
) -> str:
    source = sanitize_filename_component(Path(source_name).stem or "source", fallback="source")
    provider = sanitize_filename_component(
        extraction_provider.replace(".", "-").replace("_", "-"),
        fallback="extraction",
    )
    gen = f"g{generation_number}" if generation_number is not None else "g0"
    cand = f"c{candidate_number}" if candidate_number is not None else "c0"
    return f"{source}_nova_{gen}_{cand}_{provider}.png"


def unique_destination(path: Path, *, allow_overwrite: bool) -> Path:
    if not path.exists():
        return path
    if allow_overwrite:
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def to_file_uri(path: Path) -> str:
    return path.resolve().as_uri()
