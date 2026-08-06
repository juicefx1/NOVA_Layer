"""Render/export color-policy metadata (sidecar + export manifest).

Project schema is not modified: metadata lives in ``color_policy.json`` next to
render frames and is copied into export manifests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from nova_layer.adapters.color.display_transform import (
    DisplayTransformDiagnostics,
    DisplayTransformProtocol,
)
from nova_layer.adapters.persistence.safe_paths import (
    UnsafePackagePathError,
    assert_path_within_root,
    resolve_within_root,
)
from nova_layer.app.processing_frames import (
    SOURCE_TRANSFORM_VERSION,
    ProcessingColorPolicy,
)
from nova_layer.domain.models import SmartLayerRender
from nova_layer.ports.media import MediaReadError

RENDER_COLOR_POLICY_FILENAME = "color_policy.json"


def validate_render_color_policy(policy: ProcessingColorPolicy) -> ProcessingColorPolicy:
    if policy is ProcessingColorPolicy.SCENE:
        raise MediaReadError(
            "Render/export does not support ProcessingColorPolicy.SCENE in Phase 8D; "
            "use PREVIEW or SOURCE."
        )
    if policy not in (ProcessingColorPolicy.PREVIEW, ProcessingColorPolicy.SOURCE):
        raise MediaReadError(f"Unsupported render color policy: {policy!r}")
    return policy


def build_render_color_metadata(
    policy: ProcessingColorPolicy,
    *,
    display_transform: DisplayTransformProtocol | None = None,
    alpha_mode: str = "straight",
    premultiplied: bool = False,
) -> dict[str, Any]:
    """Build sidecar/manifest color diagnostics for a Smart Layer render."""
    policy = validate_render_color_policy(policy)
    diagnostics = _diagnostics_from_transform(display_transform)

    base: dict[str, Any] = {
        "color_policy": policy.value,
        "alpha_mode": alpha_mode,
        "premultiplied": bool(premultiplied),
        "scene_linear": False,
        "pixel_encoding": "display_or_source_uint8_scaled",
    }

    if policy is ProcessingColorPolicy.SOURCE:
        base.update(
            {
                "source_transform_version": SOURCE_TRANSFORM_VERSION,
                "color_backend": SOURCE_TRANSFORM_VERSION,
                "config_path": None,
                "config_source": None,
                "input_color_space": "scene_linear",
                "display": None,
                "view": None,
                "exposure": None,
            }
        )
        return base

    # PREVIEW — record active viewer look identity when available.
    if diagnostics is None:
        base.update(
            {
                "source_transform_version": None,
                "color_backend": "unknown",
                "config_path": None,
                "config_source": None,
                "input_color_space": None,
                "display": None,
                "view": None,
                "exposure": None,
            }
        )
        return base

    base.update(
        {
            "source_transform_version": None,
            "color_backend": str(diagnostics.backend),
            "config_path": diagnostics.config_path,
            "config_source": diagnostics.config_source,
            "input_color_space": str(diagnostics.input_color_space),
            "display": diagnostics.display,
            "view": diagnostics.view,
            "exposure": float(diagnostics.exposure),
        }
    )
    return base


def write_render_color_metadata(directory: Path, metadata: Mapping[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RENDER_COLOR_POLICY_FILENAME
    path.write_text(
        json.dumps(dict(metadata), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_render_color_metadata(
    package_path: Path,
    render: SmartLayerRender,
) -> dict[str, Any] | None:
    if not render.frames:
        return None
    try:
        frame_path = resolve_within_root(
            package_path,
            render.frames[0].image_reference,
            must_exist=False,
            expect="file",
        )
        parent = assert_path_within_root(
            package_path, frame_path.parent, label="render directory"
        )
        path = resolve_within_root(parent, RENDER_COLOR_POLICY_FILENAME, must_exist=False)
    except UnsafePackagePathError:
        return None
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _diagnostics_from_transform(
    transform: DisplayTransformProtocol | None,
) -> DisplayTransformDiagnostics | None:
    if transform is None:
        return None
    diagnostics = getattr(transform, "diagnostics", None)
    if isinstance(diagnostics, DisplayTransformDiagnostics):
        return diagnostics
    return None
