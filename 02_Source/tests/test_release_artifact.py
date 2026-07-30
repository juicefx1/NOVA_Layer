import zipfile
from pathlib import Path

from nova_layer.release_artifact import EXPECTED_COMMANDS, verify_wheel


def test_wheel_verifier_checks_commands_and_excludes_model_weights(tmp_path: Path) -> None:
    wheel = tmp_path / "nova_layer-0.1.0-py3-none-any.whl"
    entry_points = "[console_scripts]\n" + "\n".join(
        f"{command} = nova_layer.__main__:main" for command in sorted(EXPECTED_COMMANDS)
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("nova_layer/__init__.py", "")
        archive.writestr(
            "nova_layer-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: nova-layer\nVersion: 0.1.0\n",
        )
        archive.writestr("nova_layer-0.1.0.dist-info/entry_points.txt", entry_points)
        archive.writestr("nova_layer-0.1.0.dist-info/RECORD", "")
    report = verify_wheel(wheel)
    assert report.valid
    assert report.package_name == "nova-layer"
    assert set(report.commands) == EXPECTED_COMMANDS
    assert len(report.sha256) == 64

    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("nova_layer/models/weights.pt", b"forbidden")
    tampered = verify_wheel(wheel)
    assert not tampered.valid
    assert tampered.issues == ("Wheel must not embed model weights.",)
