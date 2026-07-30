from __future__ import annotations

from typing import Any, Protocol


class HostSession(Protocol):
    """Headless project session for future DCC / host-application adapters."""

    @property
    def package_path(self) -> str | None: ...

    def status(self) -> dict[str, Any]: ...

    def export_render(
        self,
        destination_directory: str,
        *,
        version: int | None = None,
        format: str = "png_sequence",
    ) -> dict[str, Any]: ...
