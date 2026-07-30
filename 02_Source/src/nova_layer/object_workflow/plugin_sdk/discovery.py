from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from nova_layer.object_workflow.plugin_sdk.constants import (
    DEFAULT_PLUGINS_DIRNAME,
    ENV_PLUGINS_DIR,
)
from nova_layer.object_workflow.plugin_sdk.package.paths import default_plugin_install_root


def resolve_plugin_roots(
    *,
    explicit: Path | str | Sequence[Path | str] | None = None,
    environ: dict[str, str] | None = None,
    cwd: Path | None = None,
    include_defaults: bool = True,
    install_roots: Path | str | Sequence[Path | str] | None = None,
    include_install_root: bool = True,
) -> list[Path]:
    """Resolve local plugin search roots. No downloads; no online registry.

    ``install_roots`` / default Feature 12 install directory are searched in
    addition to developer ``plugins/`` trees so packaged installs remain visible
    to PluginManager without a second discovery architecture.
    """
    env = environ if environ is not None else os.environ
    roots: list[Path] = []
    if explicit is not None:
        if isinstance(explicit, (str, Path)):
            roots.append(Path(explicit))
        else:
            roots.extend(Path(item) for item in explicit)
    env_path = str(env.get(ENV_PLUGINS_DIR, "")).strip()
    if env_path:
        roots.append(Path(env_path).expanduser())
    if install_roots is not None:
        if isinstance(install_roots, (str, Path)):
            roots.append(Path(install_roots))
        else:
            roots.extend(Path(item) for item in install_roots)
    elif include_install_root and include_defaults:
        roots.append(default_plugin_install_root(environ=env))
    if include_defaults:
        base = cwd if cwd is not None else Path.cwd()
        roots.append(base / DEFAULT_PLUGINS_DIRNAME)
        # Prefer workspace plugins/ next to 02_Source when running from package tree.
        package_anchor = Path(__file__).resolve().parents[4]  # .../02_Source
        candidates = [
            package_anchor / DEFAULT_PLUGINS_DIRNAME,
            package_anchor.parent / DEFAULT_PLUGINS_DIRNAME,
        ]
        roots.extend(candidates)

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.expanduser()
        try:
            key = resolved.resolve()
        except OSError:
            key = resolved
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def discover_plugin_directories(roots: Sequence[Path]) -> list[Path]:
    """Return plugin directories that contain a manifest.json."""
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / "manifest.json").is_file():
                continue
            try:
                key = child.resolve()
            except OSError:
                key = child
            if key in seen:
                continue
            seen.add(key)
            found.append(child)
    return found
