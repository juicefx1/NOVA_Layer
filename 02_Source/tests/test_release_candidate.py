import json
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from nova_layer.release_artifact import EXPECTED_COMMANDS, verify_wheel
from nova_layer.release_candidate import audit_release_candidate, create_release_candidate


def _wheel(path: Path) -> None:
    entry_points = "[console_scripts]\n" + "\n".join(
        f"{command} = nova_layer.__main__:main" for command in sorted(EXPECTED_COMMANDS)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("nova_layer/__init__.py", "")
        archive.writestr(
            "nova_layer-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: nova-layer\nVersion: 0.1.0\n",
        )
        archive.writestr("nova_layer-0.1.0.dist-info/entry_points.txt", entry_points)
        archive.writestr("nova_layer-0.1.0.dist-info/RECORD", "")


def test_release_candidate_requires_verified_wheel_and_full_acceptance(tmp_path: Path) -> None:
    wheel = tmp_path / "nova_layer-0.1.0-py3-none-any.whl"
    _wheel(wheel)
    wheel_report = tmp_path / "wheel-report.json"
    wheel_audit = verify_wheel(wheel)
    wheel_report.write_text(json.dumps(asdict(wheel_audit)), encoding="utf-8")
    smoke_report = tmp_path / "install-smoke.json"
    smoke_report.write_text(
        json.dumps(
            {
                "valid": True,
                "wheel_sha256": wheel_audit.sha256,
                "gui_startup_passed": True,
            }
        ),
        encoding="utf-8",
    )
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(
        json.dumps(
            {
                "passed": 2,
                "total": 2,
                "results": [{"status": "passed"}, {"status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    candidate = create_release_candidate(
        wheel,
        wheel_report,
        smoke_report,
        acceptance,
        tmp_path / "release",
    )
    assert candidate.manifest_path.is_file()
    manifest = json.loads(candidate.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format_version"] == 3
    assert manifest["acceptance"] == {"passed": 2, "total": 2}
    assert len(manifest["files"]) == 4
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    audit = audit_release_candidate(candidate.release_directory)
    assert audit.valid
    assert audit.checked_files == 4

    with pytest.raises(ValueError, match="already exists"):
        create_release_candidate(
            wheel, wheel_report, smoke_report, acceptance, tmp_path / "release"
        )

    embedded_acceptance = candidate.release_directory / acceptance.name
    embedded_acceptance.write_text('{"passed": 0, "total": 1}', encoding="utf-8")
    tampered = audit_release_candidate(candidate.release_directory)
    assert not tampered.valid
    assert any("checksum mismatch" in issue for issue in tampered.issues)
    assert any("not fully passing" in issue for issue in tampered.issues)


def test_release_candidate_blocks_failed_acceptance(tmp_path: Path) -> None:
    wheel = tmp_path / "nova_layer-0.1.0-py3-none-any.whl"
    _wheel(wheel)
    wheel_report = tmp_path / "wheel-report.json"
    wheel_audit = verify_wheel(wheel)
    wheel_report.write_text(json.dumps(asdict(wheel_audit)), encoding="utf-8")
    smoke_report = tmp_path / "install-smoke.json"
    smoke_report.write_text(
        json.dumps(
            {
                "valid": True,
                "wheel_sha256": wheel_audit.sha256,
                "gui_startup_passed": True,
            }
        ),
        encoding="utf-8",
    )
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(
        json.dumps({"passed": 0, "total": 1, "results": [{"status": "failed"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not fully passing"):
        create_release_candidate(
            wheel, wheel_report, smoke_report, acceptance, tmp_path / "release"
        )
