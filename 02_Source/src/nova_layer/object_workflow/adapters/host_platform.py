from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nova_layer.object_workflow.application.errors import ApplicationError


class SubprocessProcessLauncher:
    """Trusted argv-array process launcher. Never uses shell=True."""

    def run(self, argv: list[str], *, timeout_seconds: float = 30.0) -> int:
        if not argv:
            raise ApplicationError("INVALID_LAUNCH_ARGV", "empty process argv")
        if any(not isinstance(item, str) or item == "" for item in argv):
            raise ApplicationError("INVALID_LAUNCH_ARGV", "process argv must be non-empty strings")
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                argv,
                check=False,
                shell=False,
                timeout=timeout_seconds,
                capture_output=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise ApplicationError("HOST_LAUNCH_TIMEOUT", f"process timed out: {argv[0]}") from exc
        except OSError as exc:
            raise ApplicationError("HOST_LAUNCH_FAILED", str(exc)) from exc
        return int(completed.returncode)


def reveal_argv_for_platform(path: Path, *, platform: str | None = None) -> list[str]:
    target = str(path.resolve())
    system = (platform or sys.platform).lower()
    if system.startswith("darwin"):
        return ["open", "-R", target]
    if system.startswith("win"):
        # explorer /select,path — keep as two argv tokens; no shell.
        return ["explorer", f"/select,{target}"]
    return ["xdg-open", str(path.resolve().parent)]


def open_file_argv_for_platform(path: Path, *, platform: str | None = None) -> list[str]:
    target = str(path.resolve())
    system = (platform or sys.platform).lower()
    if system.startswith("darwin"):
        return ["open", target]
    if system.startswith("win"):
        return ["cmd", "/c", "start", "", target]
    return ["xdg-open", target]
