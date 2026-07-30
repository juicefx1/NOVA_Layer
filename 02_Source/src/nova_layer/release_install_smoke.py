from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path

SMOKE_MODULES = (
    "nova_layer.acceptance",
    "nova_layer.model_evaluation",
    "nova_layer.sam2_video_benchmark",
    "nova_layer.real_footage_benchmark",
    "nova_layer.benchmark_dataset",
    "nova_layer.benchmark_review",
    "nova_layer.benchmark_review_assets",
    "nova_layer.benchmark_comparison",
    "nova_layer.benchmark_baseline",
    "nova_layer.benchmark_baseline_activate",
    "nova_layer.release_artifact",
    "nova_layer.release_candidate",
    "nova_layer.release_candidate_audit",
    "nova_layer.skeleton_adapter_check",
    "nova_layer.depth_pose_bridge_server",
    "nova_layer.depth_pose_benchmark",
    "nova_layer.depth_pose_review_assets",
    "nova_layer.depth_pose_dataset",
    "nova_layer.depth_pose_comparison",
    "nova_layer.depth_pose_smoke",
    "nova_layer.export_render",
    "nova_layer.host_session",
)


@dataclass(frozen=True, slots=True)
class InstallSmokeResult:
    valid: bool
    wheel_path: str
    wheel_sha256: str
    installed_package_path: str | None
    checked_modules: int
    gui_startup_passed: bool
    failures: tuple[str, ...]


def wheel_smoke_modules(wheel_path: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel_path) as archive:
        entrypoint_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
        ]
        if len(entrypoint_names) != 1:
            raise ValueError("Wheel must contain exactly one entry_points.txt file.")
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entrypoint_names[0]).decode("utf-8"))
    if not parser.has_section("console_scripts"):
        raise ValueError("Wheel has no console_scripts entry points.")
    modules = {
        target.split(":", maxsplit=1)[0].strip()
        for command, target in parser["console_scripts"].items()
        if command not in {"nova-layer", "nova-install-smoke"}
    }
    return tuple(sorted(modules))


def smoke_test_wheel_install(wheel_path: Path) -> InstallSmokeResult:
    wheel_path = wheel_path.resolve()
    with wheel_path.open("rb") as stream:
        wheel_sha256 = file_digest(stream, "sha256").hexdigest()
    failures: list[str] = []
    installed_path: str | None = None
    try:
        smoke_modules = wheel_smoke_modules(wheel_path)
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        return InstallSmokeResult(False, str(wheel_path), wheel_sha256, None, 0, False, (str(exc),))
    with tempfile.TemporaryDirectory(prefix="nova-wheel-smoke-") as temporary:
        target = Path(temporary) / "site-packages"
        install = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                str(wheel_path),
                "--no-deps",
                "--target",
                str(target),
                "--disable-pip-version-check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if install.returncode != 0:
            return InstallSmokeResult(
                False,
                str(wheel_path),
                wheel_sha256,
                None,
                0,
                False,
                (f"Wheel installation failed: {(install.stdout + install.stderr).strip()}",),
            )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(target)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["NOVA_AI_MODE"] = "mock"
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import nova_layer; print(nova_layer.__file__)",
            ],
            cwd=temporary,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            failures.append(f"Installed package import failed: {probe.stderr.strip()}")
        else:
            installed_path = probe.stdout.strip()
            try:
                Path(installed_path).resolve().relative_to(target.resolve())
            except ValueError:
                failures.append("Import resolved outside the temporary Wheel installation.")
        checked = 0
        for module in smoke_modules:
            checked += 1
            try:
                process = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=temporary,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if process.returncode != 0:
                    failures.append(
                        f"{module} --help failed: {(process.stdout + process.stderr).strip()}"
                    )
            except subprocess.TimeoutExpired:
                failures.append(f"{module} --help timed out.")
        gui_startup_passed = False
        gui_script = (
            "from PySide6.QtCore import QTimer; "
            "from PySide6.QtWidgets import QApplication; "
            "from nova_layer.ui.main_window import MainWindow; "
            "app=QApplication([]); window=MainWindow(); window.show(); "
            "QTimer.singleShot(150, app.quit); raise SystemExit(app.exec())"
        )
        try:
            gui_startup = subprocess.run(
                [sys.executable, "-c", gui_script],
                cwd=temporary,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            gui_startup_passed = gui_startup.returncode == 0
            if not gui_startup_passed:
                failures.append(
                    f"GUI startup failed: {(gui_startup.stdout + gui_startup.stderr).strip()}"
                )
        except subprocess.TimeoutExpired:
            failures.append("GUI startup timed out.")
    return InstallSmokeResult(
        valid=not failures,
        wheel_path=str(wheel_path),
        wheel_sha256=wheel_sha256,
        installed_package_path=installed_path,
        checked_modules=checked,
        gui_startup_passed=gui_startup_passed,
        failures=tuple(failures),
    )


def write_report(output_path: Path, result: InstallSmokeResult) -> Path:
    payload = {"generated_at": datetime.now(UTC).isoformat(), **asdict(result)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed NOVA Wheel.")
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = smoke_test_wheel_install(args.wheel)
    if args.report:
        print(write_report(args.report, result))
    print(
        f"NOVA Wheel install smoke: {'PASS' if result.valid else 'FAIL'} · "
        f"{result.checked_modules} modules checked"
    )
    for failure in result.failures:
        print(failure)
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
