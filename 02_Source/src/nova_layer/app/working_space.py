"""Canonical working-space settings, identity, and intent (Phase 10C-1).

No source→working pixel conversion in this phase — contracts and diagnostics only.
"""

from __future__ import annotations

from dataclasses import dataclass


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
                "Working space will resolve OCIO scene_linear role in a later "
                "phase; no conversion is applied yet.",
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
