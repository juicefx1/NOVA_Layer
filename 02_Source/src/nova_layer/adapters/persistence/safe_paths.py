"""Package-relative path containment for Smart Layer / mask / render I/O.

Rejects absolute paths, parent traversal, and symlink escapes that would
leave a trusted package (or export destination) root.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "UnsafePackagePathError",
    "resolve_within_root",
    "sanitize_path_segment",
    "sanitize_export_stem",
    "assert_path_within_root",
]


class UnsafePackagePathError(ValueError):
    """Raised when a relative path escapes its declared package/root."""


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Single path segment used for export stems / frame basenames.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def sanitize_path_segment(name: str, *, field: str = "path segment") -> str:
    """Validate a single filename component (no separators or traversal)."""
    if not isinstance(name, str):
        raise UnsafePackagePathError(f"Invalid {field}: expected a string.")
    candidate = name.strip()
    if not candidate:
        raise UnsafePackagePathError(f"Empty {field} is not allowed.")
    if candidate in {".", ".."}:
        raise UnsafePackagePathError(f"Invalid {field}: {candidate!r}.")
    if "/" in candidate or "\\" in candidate:
        raise UnsafePackagePathError(f"{field} must not contain path separators.")
    if _CONTROL_CHARS.search(candidate):
        raise UnsafePackagePathError(f"{field} contains control characters.")
    if not _SAFE_SEGMENT.match(candidate):
        raise UnsafePackagePathError(
            f"Invalid {field}: {candidate!r}. "
            "Use letters, digits, and limited punctuation only."
        )
    return candidate


def sanitize_export_stem(stem: str) -> str:
    """Validate the export folder name written under a user destination."""
    return sanitize_path_segment(stem, field="export name")


def _reject_absolute_relative(relative: str) -> None:
    text = relative.replace("\\", "/")
    if not text or text in {".", "./"}:
        raise UnsafePackagePathError("Empty or '.' package-relative path is not allowed.")
    pure = PurePosixPath(text)
    if pure.is_absolute() or text.startswith("/"):
        raise UnsafePackagePathError(f"Absolute package paths are not allowed: {relative!r}")
    win = PureWindowsPath(relative)
    if win.is_absolute() or bool(getattr(win, "drive", "")) or text.startswith("//"):
        raise UnsafePackagePathError(f"Absolute package paths are not allowed: {relative!r}")
    if text.startswith("~"):
        raise UnsafePackagePathError(f"Home-relative package paths are not allowed: {relative!r}")
    # Inspect raw segments before pathlib collapses "/./".
    for part in text.split("/"):
        if part in {".", ".."}:
            raise UnsafePackagePathError(
                f"Package-relative path must not contain '.' or '..': {relative!r}"
            )
    if any(part == "" for part in pure.parts):
        raise UnsafePackagePathError(f"Invalid package-relative path: {relative!r}")


def resolve_within_root(
    root: Path,
    relative: str | Path,
    *,
    must_exist: bool = False,
    expect: str = "any",
) -> Path:
    """Resolve ``relative`` under ``root`` or raise :class:`UnsafePackagePathError`.

    * ``root`` may itself be a symlink; containment uses ``root.resolve()``.
    * Symlinks under ``root`` that resolve outside ``root`` are rejected.
    * ``expect`` is ``"file"``, ``"dir"``, or ``"any"`` when ``must_exist`` or
      after existence is confirmed.
    """
    if expect not in {"file", "dir", "any"}:
        raise ValueError(f"Unsupported expect mode: {expect!r}")
    if not isinstance(relative, (str, Path)):
        raise UnsafePackagePathError("Package-relative path must be a string or Path.")
    relative_text = relative.as_posix() if isinstance(relative, Path) else str(relative)
    relative_text = relative_text.strip()
    _reject_absolute_relative(relative_text)

    try:
        root_resolved = root.expanduser().resolve(strict=False)
    except OSError as exc:
        raise UnsafePackagePathError(f"Could not resolve package root: {root}") from exc

    # Join using POSIX parts so Windows-style absolute segments never inject a drive.
    posix = PurePosixPath(relative_text.replace("\\", "/"))
    candidate = root_resolved.joinpath(*posix.parts)
    try:
        target = candidate.resolve(strict=False)
    except OSError as exc:
        raise UnsafePackagePathError(
            f"Could not resolve package path: {relative_text!r}"
        ) from exc

    try:
        if not target.is_relative_to(root_resolved):
            raise UnsafePackagePathError(
                f"Path escapes package root: {relative_text!r}"
            )
    except AttributeError:  # pragma: no cover - Python <3.9 compatibility guard
        if root_resolved not in target.parents and target != root_resolved:
            raise UnsafePackagePathError(
                f"Path escapes package root: {relative_text!r}"
            ) from None

    if target == root_resolved:
        raise UnsafePackagePathError(
            f"Package-relative path must address a child of the root: {relative_text!r}"
        )

    if must_exist and not target.exists():
        raise UnsafePackagePathError(f"Package path does not exist: {relative_text!r}")

    if target.exists():
        if expect == "file" and not target.is_file():
            raise UnsafePackagePathError(
                f"Expected a file inside the package: {relative_text!r}"
            )
        if expect == "dir" and not target.is_dir():
            raise UnsafePackagePathError(
                f"Expected a directory inside the package: {relative_text!r}"
            )
    return target


def assert_path_within_root(root: Path, path: Path, *, label: str = "path") -> Path:
    """Ensure an already-joined path remains inside ``root`` after resolve."""
    try:
        root_resolved = root.expanduser().resolve(strict=False)
        target = path.expanduser().resolve(strict=False)
    except OSError as exc:
        raise UnsafePackagePathError(f"Could not resolve {label}: {path}") from exc
    if not target.is_relative_to(root_resolved):
        raise UnsafePackagePathError(f"{label} escapes containment root: {path}")
    return target
