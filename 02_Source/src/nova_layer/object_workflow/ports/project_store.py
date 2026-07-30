from __future__ import annotations

from pathlib import Path
from typing import Protocol

from nova_layer.object_workflow.domain.models import Project


class ProjectStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProjectStore(Protocol):
    def save(self, project: Project, package_path: Path, assets: dict[str, bytes]) -> None: ...

    def load(self, package_path: Path) -> tuple[Project, dict[str, bytes]]: ...
