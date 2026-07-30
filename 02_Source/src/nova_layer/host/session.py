from __future__ import annotations

from pathlib import Path
from typing import Any

from nova_layer.adapters.media.pyav_reader import MediaReadError, PyAvMediaReader
from nova_layer.adapters.persistence.json_store import JsonProjectStore, ProjectStoreError
from nova_layer.app.maturity import (
    MaturityPromotionError,
    production_ready_blockers,
    promote_to_production_ready,
)
from nova_layer.domain.models import MediaLinkState, Project, Shot, SmartLayer
from nova_layer.export.smart_layer import ExportFormat
from nova_layer.export_render import export_render_from_project
from nova_layer.ports.media import MediaReader

HOST_API_VERSION = "1.1"


class HostSessionError(RuntimeError):
    """Raised when a headless host session cannot complete an operation."""


class HeadlessHostSession:
    """Qt-free project session for host applications and automation."""

    def __init__(
        self,
        store: JsonProjectStore | None = None,
        media_reader: MediaReader | None = None,
    ) -> None:
        self._store = store or JsonProjectStore()
        self._media_reader: MediaReader = media_reader or PyAvMediaReader()
        self._package_path: Path | None = None
        self._project: Project | None = None

    @property
    def package_path(self) -> str | None:
        return str(self._package_path) if self._package_path is not None else None

    @property
    def project(self) -> Project | None:
        return self._project

    def open_project(self, package_path: Path | str) -> Project:
        path = Path(package_path).expanduser().resolve()
        try:
            project = self._store.load(path)
        except (OSError, ProjectStoreError, ValueError) as exc:
            raise HostSessionError(f"Could not open project: {exc}") from exc
        self._package_path = path
        self._project = project
        self.validate_media_link()
        return project

    def reload(self) -> Project:
        if self._package_path is None:
            raise HostSessionError("No project is open.")
        return self.open_project(self._package_path)

    def save(self) -> Project:
        if self._project is None or self._package_path is None:
            raise HostSessionError("No project is open.")
        try:
            self._store.save(self._project, self._package_path)
        except (OSError, ProjectStoreError, ValueError) as exc:
            raise HostSessionError(f"Could not save project: {exc}") from exc
        return self._project

    def status(self) -> dict[str, Any]:
        if self._project is None or self._package_path is None:
            return {
                "open": False,
                "package_path": None,
                "project": None,
                "shot": None,
                "smart_layer": None,
                "renders": [],
                "media": None,
                "production_ready": {"eligible": False, "blockers": ["No project is open."]},
                "host_api_version": HOST_API_VERSION,
            }
        shot = self._active_shot()
        layer = self._active_layer(shot)
        renders = self.list_renders()
        blockers = production_ready_blockers(layer) if layer is not None else ("No Smart Layer.",)
        return {
            "open": True,
            "package_path": str(self._package_path),
            "schema_version": self._project.schema_version,
            "project": {
                "id": str(self._project.id),
                "name": self._project.name,
                "sequence_count": len(self._project.sequences),
            },
            "shot": None
            if shot is None
            else {
                "id": str(shot.id),
                "name": shot.name,
                "range_start": shot.range_start,
                "range_end": shot.range_end,
                "master_frame": shot.master_frame,
                "media_link_state": shot.media.link_state.value,
                "frame_count": shot.media.frame_count,
                "frame_rate": shot.media.frame_rate,
                "width": shot.media.width,
                "height": shot.media.height,
                "source_path": shot.media.source_path,
            },
            "media": self.media_status(),
            "smart_layer": None
            if layer is None
            else {
                "id": str(layer.id),
                "name": layer.name,
                "version": layer.version,
                "maturity_state": layer.object_identity.maturity_state.value,
                "lifecycle_state": layer.object_identity.lifecycle_state.value,
                "confidence": layer.object_identity.confidence,
                "render_version_counter": layer.render_version_counter,
            },
            "renders": renders,
            "production_ready": {
                "eligible": not blockers,
                "blockers": list(blockers),
                "current_maturity": (
                    None if layer is None else layer.object_identity.maturity_state.value
                ),
            },
            "host_api_version": HOST_API_VERSION,
        }

    def list_renders(self) -> list[dict[str, Any]]:
        layer = self._active_layer(self._active_shot())
        if layer is None:
            return []
        return [
            {
                "version": render.version,
                "frame_start": render.frame_start,
                "frame_end": render.frame_end,
                "frame_count": len(render.frames),
                "protected": render.protected,
                "source_layer_version": render.source_layer_version,
            }
            for render in layer.renders
        ]

    def media_status(self) -> dict[str, Any] | None:
        shot = self._active_shot()
        if shot is None:
            return None
        source = shot.media.source_path
        return {
            "source_path": source,
            "relative_path": shot.media.relative_path,
            "fingerprint": shot.media.fingerprint,
            "link_state": shot.media.link_state.value,
            "frame_count": shot.media.frame_count,
            "frame_rate": shot.media.frame_rate,
            "width": shot.media.width,
            "height": shot.media.height,
        }

    def validate_media_link(self) -> dict[str, Any]:
        shot = self._require_shot()
        source = shot.media.source_path
        if source is None:
            shot.media.link_state = MediaLinkState.MISSING
            return {
                "link_state": MediaLinkState.MISSING.value,
                "message": "Source media path is not set.",
            }
        try:
            info = self._media_reader.inspect(Path(source))
        except (MediaReadError, OSError, ValueError) as exc:
            shot.media.link_state = MediaLinkState.MISSING
            return {"link_state": MediaLinkState.MISSING.value, "message": str(exc)}
        if info.fingerprint != shot.media.fingerprint:
            shot.media.link_state = MediaLinkState.CHANGED
            return {
                "link_state": MediaLinkState.CHANGED.value,
                "message": "Source media content has changed.",
            }
        shot.media.link_state = MediaLinkState.LINKED
        return {
            "link_state": MediaLinkState.LINKED.value,
            "message": "Source media linked.",
        }

    def relink_media(
        self,
        media_path: Path | str,
        *,
        accept_changed: bool = False,
    ) -> dict[str, Any]:
        shot = self._require_shot()
        path = Path(media_path).expanduser().resolve()
        try:
            info = self._media_reader.inspect(path)
        except (MediaReadError, OSError, ValueError) as exc:
            raise HostSessionError(str(exc)) from exc
        fingerprint_changed = info.fingerprint != shot.media.fingerprint
        if fingerprint_changed and not accept_changed:
            shot.media.link_state = MediaLinkState.CHANGED
            raise HostSessionError(
                "Replacement content differs from the original. "
                "Pass accept_changed=true to confirm."
            )
        if shot.range_end >= info.frame_count:
            raise HostSessionError(
                "Replacement media is shorter than the saved Shot Range and cannot be linked."
            )
        shot.media.source_path = str(info.path)
        shot.media.relative_path = f"media/{info.path.name}"
        shot.media.fingerprint = info.fingerprint
        shot.media.frame_count = info.frame_count
        shot.media.frame_rate = info.frame_rate
        shot.media.width = info.width
        shot.media.height = info.height
        shot.media.time_base = info.time_base
        shot.media.pixel_format = info.pixel_format
        shot.media.link_state = MediaLinkState.LINKED
        self.save()
        return {
            "link_state": MediaLinkState.LINKED.value,
            "source_path": shot.media.source_path,
            "fingerprint": shot.media.fingerprint,
            "accepted_changed_fingerprint": fingerprint_changed,
        }

    def promote_production_ready(self) -> dict[str, Any]:
        layer = self._require_layer()
        try:
            promote_to_production_ready(layer)
        except MaturityPromotionError as exc:
            raise HostSessionError(str(exc)) from exc
        self.save()
        return {
            "maturity_state": layer.object_identity.maturity_state.value,
            "layer_version": layer.version,
            "decision": "smart_layer_promoted_to_production_ready",
        }

    def export_render(
        self,
        destination_directory: Path | str,
        *,
        version: int | None = None,
        format: str | ExportFormat = ExportFormat.PNG_SEQUENCE,
    ) -> dict[str, Any]:
        if self._package_path is None:
            raise HostSessionError("No project is open.")
        try:
            export_format = (
                format if isinstance(format, ExportFormat) else ExportFormat(str(format))
            )
        except ValueError as exc:
            raise HostSessionError(f"Unsupported export format: {format}") from exc
        try:
            path = export_render_from_project(
                self._package_path,
                Path(destination_directory),
                version=version,
                format=export_format,
            )
        except Exception as exc:  # noqa: BLE001 - host boundary normalizes errors
            raise HostSessionError(f"Smart Layer export failed: {exc}") from exc
        return {
            "path": str(path),
            "format": export_format.value,
            "manifest": str(path / "manifest.json"),
        }

    def _require_shot(self) -> Shot:
        shot = self._active_shot()
        if shot is None:
            raise HostSessionError("No Shot is available.")
        return shot

    def _require_layer(self) -> SmartLayer:
        layer = self._active_layer(self._active_shot())
        if layer is None:
            raise HostSessionError("No Smart Layer is available.")
        return layer

    def _active_shot(self) -> Shot | None:
        if self._project is None or not self._project.sequences:
            return None
        shots = self._project.sequences[0].shots
        return shots[0] if shots else None

    def _active_layer(self, shot: Shot | None) -> SmartLayer | None:
        if shot is None or not shot.smart_layers:
            return None
        return shot.smart_layers[0]
