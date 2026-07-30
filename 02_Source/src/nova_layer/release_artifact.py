from __future__ import annotations

import argparse
import configparser
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.parser import Parser
from hashlib import file_digest
from pathlib import Path

EXPECTED_COMMANDS = {
    "nova-layer",
    "nova-acceptance",
    "nova-model-preflight",
    "nova-video-benchmark",
    "nova-real-benchmark",
    "nova-dataset-export",
    "nova-dataset-review",
    "nova-review-assets",
    "nova-benchmark-compare",
    "nova-baseline-promote",
    "nova-baseline-activate",
    "nova-release-verify",
    "nova-release-candidate",
    "nova-release-audit",
    "nova-install-smoke",
}


@dataclass(frozen=True, slots=True)
class ReleaseArtifactReport:
    valid: bool
    wheel_path: str
    package_name: str | None
    package_version: str | None
    size_bytes: int
    sha256: str
    commands: tuple[str, ...]
    file_count: int
    issues: tuple[str, ...]


def verify_wheel(
    wheel_path: Path, *, expected_commands: set[str] | None = None
) -> ReleaseArtifactReport:
    wheel_path = wheel_path.resolve()
    if not wheel_path.is_file():
        return ReleaseArtifactReport(
            valid=False,
            wheel_path=str(wheel_path),
            package_name=None,
            package_version=None,
            size_bytes=0,
            sha256="",
            commands=(),
            file_count=0,
            issues=("Wheel file does not exist.",),
        )
    issues: list[str] = []
    package_name: str | None = None
    package_version: str | None = None
    commands: tuple[str, ...] = ()
    names: list[str] = []
    with wheel_path.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            entrypoint_names = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
            if len(metadata_names) != 1:
                issues.append("Wheel must contain exactly one METADATA file.")
            else:
                metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
                package_name = metadata.get("Name")
                package_version = metadata.get("Version")
            if len(entrypoint_names) != 1:
                issues.append("Wheel must contain exactly one entry_points.txt file.")
            else:
                parser = configparser.ConfigParser()
                parser.read_string(archive.read(entrypoint_names[0]).decode("utf-8"))
                commands = (
                    tuple(sorted(parser["console_scripts"]))
                    if parser.has_section("console_scripts")
                    else ()
                )
                required_commands = expected_commands or EXPECTED_COMMANDS
                missing_commands = sorted(required_commands - set(commands))
                if missing_commands:
                    issues.append(f"Missing console commands: {', '.join(missing_commands)}")
            if len(record_names) != 1:
                issues.append("Wheel must contain exactly one RECORD file.")
            if "nova_layer/__init__.py" not in names:
                issues.append("Wheel does not contain the NOVA Layer package.")
            embedded_weights = [name for name in names if name.endswith((".pt", ".pth", ".ckpt"))]
            if embedded_weights:
                issues.append("Wheel must not embed model weights.")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        issues.append(f"Could not inspect wheel: {exc}")
    return ReleaseArtifactReport(
        valid=not issues,
        wheel_path=str(wheel_path),
        package_name=package_name,
        package_version=package_version,
        size_bytes=wheel_path.stat().st_size,
        sha256=digest,
        commands=commands,
        file_count=len(names),
        issues=tuple(issues),
    )


def write_report(output_path: Path, report: ReleaseArtifactReport) -> Path:
    payload = {"generated_at": datetime.now(UTC).isoformat(), **asdict(report)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a NOVA Layer wheel artifact.")
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify_wheel(args.wheel)
    if args.report:
        print(write_report(args.report, report))
    print(f"NOVA wheel: {'VALID' if report.valid else 'INVALID'} · {report.sha256}")
    for issue in report.issues:
        print(issue)
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
