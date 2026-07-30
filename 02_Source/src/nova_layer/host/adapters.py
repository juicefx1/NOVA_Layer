from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from nova_layer.host.session import HeadlessHostSession, HostSessionError

# Thin DCC adapter stubs that wrap HeadlessHostSession.
# These modules stay free of host SDK imports so they can ship in the core Wheel.
# Real Nuke/AE packages should subclass HostAdapter and call into a running host.


class HostAdapter(ABC):
    """Base class for host-application integrations."""

    host_name: str = "generic"

    def __init__(self, session: HeadlessHostSession | None = None) -> None:
        self.session = session or HeadlessHostSession()

    def open(self, package_path: Path | str) -> dict[str, Any]:
        self.session.open_project(package_path)
        return self.session.status()

    def status(self) -> dict[str, Any]:
        return self.session.status()

    def relink(self, media_path: Path | str, *, accept_changed: bool = False) -> dict[str, Any]:
        return self.session.relink_media(media_path, accept_changed=accept_changed)

    def promote_production_ready(self) -> dict[str, Any]:
        return self.session.promote_production_ready()

    def export_render(
        self,
        destination: Path | str,
        *,
        version: int | None = None,
        format: str = "png_sequence",
    ) -> dict[str, Any]:
        return self.session.export_render(destination, version=version, format=format)

    @abstractmethod
    def install_menu(self) -> dict[str, Any]:
        """Register host UI actions. Stub adapters return a declarative menu map."""


class NukeHostAdapter(HostAdapter):
    """Declarative Nuke integration skeleton (no nukescripts import)."""

    host_name = "nuke"

    def install_menu(self) -> dict[str, Any]:
        return {
            "host": self.host_name,
            "menu": "NOVA Layer",
            "actions": [
                {"label": "Open .nova Project…", "command": "open"},
                {"label": "Show Session Status", "command": "status"},
                {"label": "Relink Source Media…", "command": "relink"},
                {"label": "Promote Production Ready", "command": "promote_production_ready"},
                {"label": "Export Smart Layer Render…", "command": "export_render"},
            ],
            "note": (
                "Wire each action to nuke.getFilename / nuke.message inside a Nuke-side "
                "bootstrap that constructs NukeHostAdapter()."
            ),
            "error_type": HostSessionError.__name__,
        }


class AfterEffectsHostAdapter(HostAdapter):
    """Declarative After Effects integration skeleton (no ExtendScript/CEP runtime)."""

    host_name = "after_effects"

    def install_menu(self) -> dict[str, Any]:
        return {
            "host": self.host_name,
            "panel": "NOVA Layer",
            "actions": [
                {"label": "Open .nova Project", "command": "open"},
                {"label": "Session Status", "command": "status"},
                {"label": "Relink Footage", "command": "relink"},
                {"label": "Promote Production Ready", "command": "promote_production_ready"},
                {"label": "Export Render", "command": "export_render"},
            ],
            "note": (
                "A CEP/UXP panel should call these Python entry points through a local "
                "nova-host-session process or embedded interpreter bridge."
            ),
            "error_type": HostSessionError.__name__,
        }
