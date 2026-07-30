from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path
from shutil import copy2, rmtree
from uuid import uuid4

from nova_layer.release_artifact import verify_wheel


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    release_directory: Path
    manifest_path: Path
    version: str
    wheel_sha256: str


@dataclass(frozen=True, slots=True)
class ReleaseCandidateAudit:
    valid: bool
    checked_files: int
    version: str | None
    wheel_sha256: str | None
    issues: tuple[str, ...]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def create_release_candidate(
    wheel_path: Path,
    wheel_report_path: Path,
    install_smoke_report_path: Path,
    acceptance_report_path: Path,
    release_root: Path,
) -> ReleaseCandidate:
    wheel_path = wheel_path.resolve()
    wheel_report_path = wheel_report_path.resolve()
    install_smoke_report_path = install_smoke_report_path.resolve()
    acceptance_report_path = acceptance_report_path.resolve()
    wheel_audit = verify_wheel(wheel_path)
    if not wheel_audit.valid or wheel_audit.package_version is None:
        detail = wheel_audit.issues[0] if wheel_audit.issues else "missing package version"
        raise ValueError(f"Wheel is not releaseable: {detail}")
    wheel_report = json.loads(wheel_report_path.read_text(encoding="utf-8"))
    if not isinstance(wheel_report, dict) or wheel_report.get("valid") is not True:
        raise ValueError("Wheel verification report is missing or failed.")
    if wheel_report.get("sha256") != wheel_audit.sha256:
        raise ValueError("Wheel differs from its verification report.")
    install_smoke = json.loads(install_smoke_report_path.read_text(encoding="utf-8"))
    if not isinstance(install_smoke, dict) or install_smoke.get("valid") is not True:
        raise ValueError("Wheel installation smoke report is missing or failed.")
    if install_smoke.get("gui_startup_passed") is not True:
        raise ValueError("Wheel installation smoke did not pass GUI startup.")
    if install_smoke.get("wheel_sha256") != wheel_audit.sha256:
        raise ValueError("Wheel differs from its installation smoke report.")
    acceptance = json.loads(acceptance_report_path.read_text(encoding="utf-8"))
    if not isinstance(acceptance, dict):
        raise ValueError("Acceptance report is invalid.")
    passed = acceptance.get("passed")
    total = acceptance.get("total")
    results = acceptance.get("results")
    if (
        not isinstance(passed, int)
        or not isinstance(total, int)
        or passed != total
        or total <= 0
        or not isinstance(results, list)
        or any(not isinstance(item, dict) or item.get("status") != "passed" for item in results)
    ):
        raise ValueError("Phase 1 acceptance report is not fully passing.")

    version = wheel_audit.package_version
    release_name = f"nova-layer-{version}-{wheel_audit.sha256[:12]}"
    release_root = release_root.resolve()
    release_directory = release_root / release_name
    if release_directory.exists():
        raise ValueError(f"Immutable release candidate already exists: {release_directory}")
    staging = release_root / f".{release_name}.{uuid4().hex}.staging"
    try:
        staging.mkdir(parents=True)
        copied_wheel = staging / wheel_path.name
        copied_wheel_report = staging / wheel_report_path.name
        copied_install_smoke = staging / install_smoke_report_path.name
        copied_acceptance = staging / acceptance_report_path.name
        copy2(wheel_path, copied_wheel)
        copy2(wheel_report_path, copied_wheel_report)
        copy2(install_smoke_report_path, copied_install_smoke)
        copy2(acceptance_report_path, copied_acceptance)
        manifest = {
            "format": "NOVA Layer Release Candidate",
            "format_version": 3,
            "created_at": datetime.now(UTC).isoformat(),
            "version": version,
            "package": wheel_audit.package_name,
            "wheel_sha256": wheel_audit.sha256,
            "acceptance": {"passed": passed, "total": total},
            "artifacts": {
                "wheel": copied_wheel.name,
                "wheel_report": copied_wheel_report.name,
                "install_smoke_report": copied_install_smoke.name,
                "acceptance_report": copied_acceptance.name,
            },
            "files": [
                {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}
                for path in (
                    copied_wheel,
                    copied_wheel_report,
                    copied_install_smoke,
                    copied_acceptance,
                )
            ],
        }
        (staging / "release_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        staging.replace(release_directory)
    except Exception:
        rmtree(staging, ignore_errors=True)
        raise
    return ReleaseCandidate(
        release_directory=release_directory,
        manifest_path=release_directory / "release_manifest.json",
        version=version,
        wheel_sha256=wheel_audit.sha256,
    )


def audit_release_candidate(release_directory: Path) -> ReleaseCandidateAudit:
    release_directory = release_directory.resolve()
    manifest_path = release_directory / "release_manifest.json"
    issues: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ReleaseCandidateAudit(False, 0, None, None, (f"Invalid manifest: {exc}",))
    if not isinstance(manifest, dict) or manifest.get("format") != "NOVA Layer Release Candidate":
        return ReleaseCandidateAudit(False, 0, None, None, ("Unknown release format.",))
    version = str(manifest["version"]) if manifest.get("version") is not None else None
    format_version = int(manifest.get("format_version", 1))
    wheel_sha256 = (
        str(manifest["wheel_sha256"]) if manifest.get("wheel_sha256") is not None else None
    )
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        return ReleaseCandidateAudit(
            False, 0, version, wheel_sha256, ("Manifest file inventory is invalid.",)
        )
    inventory: dict[str, dict[str, object]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            issues.append("Manifest contains an invalid file entry.")
            continue
        name = str(raw["name"])
        if name in inventory:
            issues.append(f"Manifest contains duplicate file entry: {name}")
            continue
        if Path(name).name != name:
            issues.append(f"Manifest contains an unsafe file path: {name}")
            continue
        inventory[name] = raw
    actual_names = {
        path.name
        for path in release_directory.iterdir()
        if path.is_file() and path.name != manifest_path.name
    }
    expected_names = set(inventory)
    for name in sorted(expected_names - actual_names):
        issues.append(f"Release file is missing: {name}")
    for name in sorted(actual_names - expected_names):
        issues.append(f"Unexpected release file: {name}")
    checked = 0
    for name in sorted(expected_names & actual_names):
        path = release_directory / name
        entry = inventory[name]
        checked += 1
        if entry.get("size") != path.stat().st_size:
            issues.append(f"Release file size mismatch: {name}")
        if entry.get("sha256") != _sha256(path):
            issues.append(f"Release file checksum mismatch: {name}")
    artifacts = manifest.get("artifacts")
    wheel_report_name = artifacts.get("wheel_report") if isinstance(artifacts, dict) else None
    wheel_report_files = (
        [release_directory / wheel_report_name]
        if isinstance(wheel_report_name, str) and wheel_report_name in expected_names
        else [release_directory / name for name in expected_names if name.endswith("wheel.json")]
    )
    historical_commands: set[str] | None = None
    if len(wheel_report_files) == 1:
        try:
            historical_report = json.loads(wheel_report_files[0].read_text(encoding="utf-8"))
            raw_commands = (
                historical_report.get("commands") if isinstance(historical_report, dict) else None
            )
            if isinstance(raw_commands, list) and all(
                isinstance(command, str) for command in raw_commands
            ):
                historical_commands = set(raw_commands)
        except (OSError, json.JSONDecodeError):
            issues.append("Embedded Wheel verification report is invalid.")
    else:
        issues.append("Release candidate must contain one Wheel verification report.")
    wheels = [release_directory / name for name in expected_names if name.endswith(".whl")]
    if len(wheels) != 1:
        issues.append("Release candidate must contain exactly one Wheel.")
    else:
        wheel_audit = verify_wheel(wheels[0], expected_commands=historical_commands)
        if not wheel_audit.valid:
            issues.append("Embedded Wheel failed structural verification.")
        if wheel_audit.sha256 != wheel_sha256:
            issues.append("Embedded Wheel does not match the release manifest.")
        if wheel_audit.package_version != version:
            issues.append("Embedded Wheel version does not match the release manifest.")
    acceptance_name = artifacts.get("acceptance_report") if isinstance(artifacts, dict) else None
    acceptance_files = (
        [release_directory / acceptance_name]
        if isinstance(acceptance_name, str) and acceptance_name in expected_names
        else [
            release_directory / name
            for name in expected_names
            if name.startswith("phase1_acceptance") and name.endswith(".json")
        ]
    )
    if len(acceptance_files) != 1:
        issues.append("Release candidate must contain one Phase 1 acceptance report.")
    else:
        try:
            acceptance = json.loads(acceptance_files[0].read_text(encoding="utf-8"))
            if (
                not isinstance(acceptance, dict)
                or acceptance.get("passed") != acceptance.get("total")
                or not isinstance(acceptance.get("total"), int)
                or acceptance["total"] <= 0
            ):
                issues.append("Embedded Phase 1 acceptance report is not fully passing.")
        except (OSError, json.JSONDecodeError):
            issues.append("Embedded Phase 1 acceptance report is invalid.")
    smoke_name = artifacts.get("install_smoke_report") if isinstance(artifacts, dict) else None
    if smoke_name is not None:
        if not isinstance(smoke_name, str) or smoke_name not in expected_names:
            issues.append("Release install-smoke artifact reference is invalid.")
        else:
            try:
                smoke = json.loads((release_directory / smoke_name).read_text(encoding="utf-8"))
                if (
                    not isinstance(smoke, dict)
                    or smoke.get("valid") is not True
                    or smoke.get("wheel_sha256") != wheel_sha256
                    or (format_version >= 3 and smoke.get("gui_startup_passed") is not True)
                ):
                    issues.append("Embedded Wheel installation smoke report is invalid.")
            except (OSError, json.JSONDecodeError):
                issues.append("Embedded Wheel installation smoke report is invalid.")
    return ReleaseCandidateAudit(not issues, checked, version, wheel_sha256, tuple(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal a verified NOVA release candidate.")
    parser.add_argument("wheel", type=Path)
    parser.add_argument("wheel_report", type=Path)
    parser.add_argument("install_smoke_report", type=Path)
    parser.add_argument("acceptance_report", type=Path)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args()
    candidate = create_release_candidate(
        args.wheel,
        args.wheel_report,
        args.install_smoke_report,
        args.acceptance_report,
        args.release_root,
    )
    print(candidate.release_directory)
    print(candidate.manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
