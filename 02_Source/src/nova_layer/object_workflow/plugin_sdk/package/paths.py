from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from nova_layer.object_workflow.plugin_sdk.package.constants import (
    DEFAULT_INSTALL_DIRNAME,
    DEFAULT_INSTALLED_SUBDIR,
    ENV_PLUGIN_INSTALL_DIR,
)


def default_plugin_install_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the local install root for .nova-plugin packages."""
    env = environ if environ is not None else os.environ
    configured = str(env.get(ENV_PLUGIN_INSTALL_DIR, "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".nova_layer" / DEFAULT_INSTALL_DIRNAME / DEFAULT_INSTALLED_SUBDIR


def safe_install_dirname(plugin_id: str) -> str:
    """Map a plugin_id to a filesystem-safe directory name."""
    token = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in plugin_id.strip())
    return token or "plugin"
