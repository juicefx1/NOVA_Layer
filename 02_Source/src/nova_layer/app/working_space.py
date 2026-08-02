"""Canonical working-space settings, identity, and resolve helpers.

Phase 10C-1: contracts / intent. Phase 10C-2: runtime resolve + PREVIEW opt-in
conversion via :class:`~nova_layer.adapters.color.ocio_color_space_converter.OcioColorSpaceConverter`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WORKING_CONVERTER_VERSION = "working_scene_v1"


def _normalize_token(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


@dataclass(frozen=True, slots=True)
class WorkingSpaceSettings:
    """Project/session intent for canonical working-space conversion.

    Phase 10C-1 does not resolve OCIO roles or convert pixels. ``enabled=False``
    keeps the file-native SceneFrame / PREVIEW / SOURCE v1 behaviour unchanged.
    """

    enabled: bool = False
    working_color_space: str | None = None
    use_scene_linear_role: bool = True
    converter_version: str = WORKING_CONVERTER_VERSION

    def __post_init__(self) -> None:
        cs = _normalize_token(self.working_color_space)
        ver = _normalize_token(self.converter_version) or WORKING_CONVERTER_VERSION
        object.__setattr__(self, "working_color_space", cs)
        object.__setattr__(self, "converter_version", ver)


@dataclass(frozen=True, slots=True)
class WorkingTransformIdentity:
    """Immutable cache-key identity for a source→working conversion.

    All fields are non-empty normalized strings. Prefer :meth:`try_create`.
    """

    source_color_space: str
    working_color_space: str
    ocio_config_identity: str
    converter_version: str

    def __post_init__(self) -> None:
        source = _normalize_token(self.source_color_space)
        working = _normalize_token(self.working_color_space)
        config = _normalize_token(self.ocio_config_identity)
        version = _normalize_token(self.converter_version)
        if not source or not working or not config or not version:
            raise ValueError(
                "WorkingTransformIdentity requires non-empty "
                "source_color_space, working_color_space, "
                "ocio_config_identity, and converter_version"
            )
        object.__setattr__(self, "source_color_space", source)
        object.__setattr__(self, "working_color_space", working)
        object.__setattr__(self, "ocio_config_identity", config)
        object.__setattr__(self, "converter_version", version)

    @classmethod
    def try_create(
        cls,
        *,
        source_color_space: str | None,
        working_color_space: str | None,
        ocio_config_identity: str | None,
        converter_version: str | None = None,
    ) -> WorkingTransformIdentity | None:
        """Return an identity, or None when any required field is missing/blank."""
        try:
            return cls(
                source_color_space=str(source_color_space or ""),
                working_color_space=str(working_color_space or ""),
                ocio_config_identity=str(ocio_config_identity or ""),
                converter_version=str(
                    converter_version or WORKING_CONVERTER_VERSION
                ),
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class WorkingSpaceIntent:
    """Resolved *intent* for working space (no OCIO config open / no convert)."""

    enabled: bool
    requested_color_space: str | None
    resolution_source: str
    warnings: tuple[str, ...]
    converter_version: str = WORKING_CONVERTER_VERSION


def resolve_working_space_intent(
    settings: WorkingSpaceSettings | None,
) -> WorkingSpaceIntent:
    """Summarize working-space configuration intent without OCIO introspection."""
    if settings is None or not settings.enabled:
        return WorkingSpaceIntent(
            enabled=False,
            requested_color_space=None,
            resolution_source="disabled",
            warnings=(),
            converter_version=(
                settings.converter_version
                if settings is not None
                else WORKING_CONVERTER_VERSION
            ),
        )

    version = settings.converter_version or WORKING_CONVERTER_VERSION
    explicit = _normalize_token(settings.working_color_space)
    if explicit is not None:
        return WorkingSpaceIntent(
            enabled=True,
            requested_color_space=explicit,
            resolution_source="explicit",
            warnings=(),
            converter_version=version,
        )

    if settings.use_scene_linear_role:
        return WorkingSpaceIntent(
            enabled=True,
            requested_color_space="scene_linear",
            resolution_source="scene_linear_role",
            warnings=(
                "Working space requests OCIO scene_linear role; runtime resolve "
                "is performed by resolve_working_space().",
            ),
            converter_version=version,
        )

    return WorkingSpaceIntent(
        enabled=True,
        requested_color_space=None,
        resolution_source="unspecified",
        warnings=(
            "Working space is enabled but no working_color_space is set and "
            "use_scene_linear_role is False.",
        ),
        converter_version=version,
    )


@dataclass(frozen=True, slots=True)
class ResolvedWorkingSpace:
    """Runtime-resolved working-space state (may disable when OCIO resolve fails)."""

    enabled: bool
    working_color_space: str | None
    resolution_source: str
    ocio_config_identity: str | None
    converter_version: str
    warnings: tuple[str, ...]
    requested_color_space: str | None = None
    config_path: str | None = None
    config_source: str | None = None


def format_ocio_config_identity(
    config_path: str | Path | None,
    config_source: str | None,
) -> str | None:
    """Stable string for WorkingTransformIdentity / cache keys."""
    path = _normalize_token(None if config_path is None else str(config_path))
    source = _normalize_token(config_source) or "unknown"
    if path is None:
        return None
    return f"{path}|{source}"


def resolve_scene_linear_role(
    *,
    config_path: Path | None,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Resolve OCIO ``scene_linear`` role → colorspace name.

    Returns ``(colorspace_name, config_source, warnings)``.
    """
    from nova_layer.adapters.color.ocio_adapter import (
        is_ocio_available,
        resolve_ocio_config_path,
    )

    warnings: list[str] = []
    if not is_ocio_available():
        return None, None, ("PyOpenColorIO is not installed.",)

    try:
        resolved_path, config_source = resolve_ocio_config_path(config_path)
    except Exception as exc:  # noqa: BLE001
        return None, None, (f"OCIO config unavailable: {exc}",)

    try:
        import PyOpenColorIO as OCIO

        config = OCIO.Config.CreateFromFile(str(resolved_path))
    except Exception as exc:  # noqa: BLE001
        return None, None, (f"Failed to load OCIO config: {exc}",)

    role_name: str | None = None
    try:
        role_name = str(config.getRole("scene_linear") or "").strip() or None
    except Exception:  # noqa: BLE001
        role_name = None

    if role_name is None:
        try:
            if config.getColorSpace("scene_linear") is not None:
                role_name = "scene_linear"
        except Exception:  # noqa: BLE001
            role_name = None

    if role_name is None:
        return (
            None,
            config_source,
            ("OCIO config has no scene_linear role.",),
        )
    if config.getColorSpace(role_name) is None:
        return (
            None,
            config_source,
            (f"OCIO scene_linear role points to missing colorspace {role_name!r}.",),
        )
    return role_name, config_source, tuple(warnings)


def resolve_working_space(
    settings: WorkingSpaceSettings | None,
    *,
    ocio_config_path: Path | None = None,
    ocio_config_source: str | None = None,
) -> ResolvedWorkingSpace:
    """Resolve working-space settings against an optional OCIO config.

    Does not convert pixels. On failure, returns ``enabled=False`` with warnings —
    never claims Legacy as a working space.
    """
    intent = resolve_working_space_intent(settings)
    version = intent.converter_version

    if not intent.enabled:
        return ResolvedWorkingSpace(
            enabled=False,
            working_color_space=None,
            resolution_source="disabled",
            ocio_config_identity=None,
            converter_version=version,
            warnings=(),
            requested_color_space=None,
            config_path=None if ocio_config_path is None else str(ocio_config_path),
            config_source=ocio_config_source,
        )

    requested = intent.requested_color_space
    if intent.resolution_source == "unspecified":
        return ResolvedWorkingSpace(
            enabled=False,
            working_color_space=None,
            resolution_source="unspecified",
            ocio_config_identity=None,
            converter_version=version,
            warnings=intent.warnings,
            requested_color_space=None,
            config_path=None if ocio_config_path is None else str(ocio_config_path),
            config_source=ocio_config_source,
        )

    if intent.resolution_source == "explicit":
        assert requested is not None
        identity = format_ocio_config_identity(ocio_config_path, ocio_config_source)
        if identity is None:
            return ResolvedWorkingSpace(
                enabled=False,
                working_color_space=None,
                resolution_source="explicit",
                ocio_config_identity=None,
                converter_version=version,
                warnings=(
                    "Working space explicit request requires an OCIO config path; "
                    "working path disabled.",
                ),
                requested_color_space=requested,
                config_path=None,
                config_source=ocio_config_source,
            )
        return ResolvedWorkingSpace(
            enabled=True,
            working_color_space=requested,
            resolution_source="explicit",
            ocio_config_identity=identity,
            converter_version=version,
            warnings=(),
            requested_color_space=requested,
            config_path=str(Path(str(ocio_config_path)).expanduser().resolve())
            if ocio_config_path is not None
            else None,
            config_source=ocio_config_source,
        )

    # scene_linear_role
    role_name, cfg_source, role_warnings = resolve_scene_linear_role(
        config_path=ocio_config_path
    )
    source = ocio_config_source or cfg_source
    if role_name is None:
        return ResolvedWorkingSpace(
            enabled=False,
            working_color_space=None,
            resolution_source="scene_linear_role",
            ocio_config_identity=None,
            converter_version=version,
            warnings=tuple(role_warnings) or (
                "Could not resolve OCIO scene_linear role; working path disabled.",
            ),
            requested_color_space=requested,
            config_path=None if ocio_config_path is None else str(ocio_config_path),
            config_source=source,
        )

    path_for_id = ocio_config_path
    if path_for_id is None:
        try:
            from nova_layer.adapters.color.ocio_adapter import resolve_ocio_config_path

            path_for_id, source = resolve_ocio_config_path(None)
        except Exception:  # noqa: BLE001
            path_for_id = None
    identity = format_ocio_config_identity(path_for_id, source)
    if identity is None:
        return ResolvedWorkingSpace(
            enabled=False,
            working_color_space=None,
            resolution_source="scene_linear_role",
            ocio_config_identity=None,
            converter_version=version,
            warnings=("OCIO config identity unavailable; working path disabled.",),
            requested_color_space=requested,
            config_path=None,
            config_source=source,
        )

    return ResolvedWorkingSpace(
        enabled=True,
        working_color_space=role_name,
        resolution_source="scene_linear_role",
        ocio_config_identity=identity,
        converter_version=version,
        warnings=tuple(role_warnings),
        requested_color_space=requested,
        config_path=str(Path(path_for_id).expanduser().resolve()),
        config_source=source,
    )


def resolve_working_source_color_space(
    scene_color_space: str | None,
    interpretation_color_space: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve converter source CS: SceneFrame tag → interpretation → unresolved.

    Returns ``(source_color_space_or_none, warnings)``.
    """
    tag = _normalize_token(scene_color_space)
    interpretation = _normalize_token(interpretation_color_space)
    warnings: list[str] = []

    if tag is not None and interpretation is not None and tag != interpretation:
        warnings.append(
            f"SceneFrame color_space {tag!r} differs from interpretation "
            f"{interpretation!r}; using SceneFrame tag for working conversion."
        )

    if tag is not None:
        return tag, tuple(warnings)
    if interpretation is not None:
        warnings.append(
            "SceneFrame color_space is unspecified; using interpretation_color_space "
            f"{interpretation!r} as working-conversion source."
        )
        return interpretation, tuple(warnings)
    return None, (
        "Working conversion source unresolved: SceneFrame.color_space and "
        "interpretation_color_space are both missing.",
    )
