import json
from pathlib import Path

from nova_layer.model_evaluation import RuntimeProbe, evaluation_gates, write_report


def test_missing_torch_blocks_runtime_and_accelerator_gates() -> None:
    probe = RuntimeProbe(
        system="Darwin",
        release="test",
        machine="arm64",
        python="3.12.0",
        torch_installed=False,
        torch_version=None,
        mps_available=None,
        mps_smoke_passed=None,
        mps_smoke_message="PyTorch is not installed",
    )

    gates = {item["gate"]: item for item in evaluation_gates(probe)}

    assert gates["runtime"]["status"] == "blocked"
    assert gates["accelerator"]["status"] == "blocked"
    assert gates["weights"]["status"] == "pending"


def test_preflight_report_is_machine_readable(tmp_path: Path) -> None:
    probe = RuntimeProbe(
        system="Darwin",
        release="test",
        machine="arm64",
        python="3.12.0",
        torch_installed=True,
        torch_version="2.7.0",
        mps_available=True,
        mps_smoke_passed=True,
        mps_smoke_message="MPS matrix operation completed",
    )

    json_path, markdown_path = write_report(tmp_path, probe)
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["recommendation"] == "SAM 2.1 Hiera Small"
    assert payload["gates"][0]["status"] == "ready"
    assert payload["gates"][1]["status"] == "ready"
    assert payload["candidates"][0]["decision"] == "primary"
    assert "SAM 3.1" in markdown_path.read_text(encoding="utf-8")
