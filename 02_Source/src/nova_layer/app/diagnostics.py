from __future__ import annotations

import json
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

from PySide6.QtCore import qVersion

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.app.capability_selection import (
    select_interactive_segmentation,
    select_skeleton_detection,
    select_temporal_propagation,
)
from nova_layer.domain.models import Project


class DiagnosticStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    status: DiagnosticStatus
    message: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    checks: tuple[DiagnosticCheck, ...]

    @property
    def has_failures(self) -> bool:
        return any(check.status == DiagnosticStatus.FAIL for check in self.checks)

    @property
    def warning_count(self) -> int:
        return sum(check.status == DiagnosticStatus.WARNING for check in self.checks)

    @property
    def summary(self) -> str:
        if self.has_failures:
            return "Startup diagnostics found a blocking problem."
        if self.warning_count:
            return f"Ready with {self.warning_count} capability warning(s)."
        return "All startup diagnostics passed."


def package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


class StartupDiagnostics:
    def __init__(
        self,
        bridge_probe: Callable[[str, float], dict[str, Any]] | None = None,
    ) -> None:
        self._bridge_probe = bridge_probe or probe_depth_pose_bridge

    def run(self) -> DiagnosticReport:
        checks = [
            self._runtime_check(),
            self._qt_check(),
            self._pyav_check(),
            self._numpy_check(),
            self._persistence_check(),
            self._ai_runtime_check(),
            self._segmentation_check(),
            self._propagation_check(),
            self._skeleton_detection_check(),
        ]
        return DiagnosticReport(tuple(checks))

    def _runtime_check(self) -> DiagnosticCheck:
        current = platform.python_version()
        supported = sys.version_info >= (3, 12)
        return DiagnosticCheck(
            name="Python Runtime",
            status=DiagnosticStatus.PASS if supported else DiagnosticStatus.FAIL,
            message="Python 3.12+ runtime available." if supported else "Python 3.12+ is required.",
            version=current,
        )

    def _qt_check(self) -> DiagnosticCheck:
        return DiagnosticCheck(
            name="Desktop UI",
            status=DiagnosticStatus.PASS,
            message="PySide6 and Qt Widgets available.",
            version=qVersion(),
        )

    def _pyav_check(self) -> DiagnosticCheck:
        current = package_version("av")
        return DiagnosticCheck(
            name="Media Decode",
            status=DiagnosticStatus.PASS if current else DiagnosticStatus.FAIL,
            message="PyAV media adapter available." if current else "PyAV is not installed.",
            version=current,
        )

    def _numpy_check(self) -> DiagnosticCheck:
        current = package_version("numpy")
        return DiagnosticCheck(
            name="Image Processing",
            status=DiagnosticStatus.PASS if current else DiagnosticStatus.FAIL,
            message="NumPy image interchange available." if current else "NumPy is not installed.",
            version=current,
        )

    def _persistence_check(self) -> DiagnosticCheck:
        try:
            with TemporaryDirectory() as directory:
                package = Path(directory) / "diagnostic.nova"
                store = JsonProjectStore()
                store.save(Project(name="Diagnostic"), package)
                restored = store.load(package)
                if restored.name != "Diagnostic":
                    raise RuntimeError("persistence round trip returned unexpected state")
        except Exception as exc:
            return DiagnosticCheck(
                name="Project Persistence",
                status=DiagnosticStatus.FAIL,
                message=f"Atomic project storage failed: {exc}",
            )
        return DiagnosticCheck(
            name="Project Persistence",
            status=DiagnosticStatus.PASS,
            message="Atomic save, load, and recovery journal available.",
            version="schema 1.0",
        )

    def _ai_runtime_check(self) -> DiagnosticCheck:
        current = package_version("torch")
        if current is None:
            return DiagnosticCheck(
                name="AI Runtime",
                status=DiagnosticStatus.WARNING,
                message="PyTorch is not installed. NOVA Layer will use deterministic Mock Mode.",
            )
        return DiagnosticCheck(
            name="AI Runtime",
            status=DiagnosticStatus.PASS,
            message=(
                "PyTorch runtime available. Device compatibility still requires model evaluation."
            ),
            version=current,
        )

    def _segmentation_check(self) -> DiagnosticCheck:
        selection = select_interactive_segmentation()
        if selection.mode == "sam2_mps":
            return DiagnosticCheck(
                name="Interactive Segmentation",
                status=DiagnosticStatus.PASS,
                message=selection.message,
                version="SAM 2.1 Tiny",
            )
        return DiagnosticCheck(
            name="Interactive Segmentation",
            status=DiagnosticStatus.WARNING,
            message=selection.message,
            version="mock 1.0",
        )

    def _propagation_check(self) -> DiagnosticCheck:
        selection = select_temporal_propagation()
        if selection.mode == "sam2_video_mps":
            return DiagnosticCheck(
                name="Temporal Propagation",
                status=DiagnosticStatus.PASS,
                message=selection.message,
                version="SAM 2.1 Tiny",
            )
        return DiagnosticCheck(
            name="Temporal Propagation",
            status=DiagnosticStatus.WARNING,
            message=selection.message,
            version="mock 1.0",
        )

    def _skeleton_detection_check(self) -> DiagnosticCheck:
        selection = select_skeleton_detection()
        if selection.mode == "external":
            return DiagnosticCheck(
                name="Skeleton Detection",
                status=DiagnosticStatus.PASS,
                message=selection.message,
                version="external adapter",
            )
        if selection.mode == "browser_bridge" and selection.adapter_spec is not None:
            try:
                health = self._bridge_probe(selection.adapter_spec, 0.75)
                if health.get("status") != "ready" or health.get("schema_version") != "1.0":
                    raise ValueError("unexpected health response")
            except Exception as exc:
                return DiagnosticCheck(
                    name="Skeleton Detection",
                    status=DiagnosticStatus.WARNING,
                    message=f"Depth/Pose bridge is configured but not reachable: {exc}",
                    version="browser bridge 1.0",
                )
            if health.get("worker_connected") is not True:
                return DiagnosticCheck(
                    name="Skeleton Detection",
                    status=DiagnosticStatus.WARNING,
                    message=("Depth/Pose bridge is reachable, but no browser worker is connected."),
                    version="browser bridge 1.0",
                )
            return DiagnosticCheck(
                name="Skeleton Detection",
                status=DiagnosticStatus.PASS,
                message=(
                    "Local Depth/Pose bridge is reachable; browser worker readiness is separate."
                ),
                version="browser bridge 1.0",
            )
        return DiagnosticCheck(
            name="Skeleton Detection",
            status=DiagnosticStatus.WARNING,
            message=selection.message,
            version="mock 1.0",
        )


def probe_depth_pose_bridge(endpoint: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(endpoint)
    health_url = urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))
    with urlopen(health_url, timeout=timeout) as response:  # noqa: S310 - selected URL is loopback
        raw = cast(bytes, response.read(16 * 1024 + 1))
    if len(raw) > 16 * 1024:
        raise ValueError("health response is too large")
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("health response must be a JSON object")
    return decoded
