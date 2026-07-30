from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    name: str
    role: str
    prompt_types: tuple[str, ...]
    video_propagation: bool
    minimum_torch: str
    official_accelerator: str
    license: str
    local_m1_status: str
    decision: str


CANDIDATES = (
    ModelCandidate(
        name="SAM 2.1 Hiera Small",
        role="Phase 1 baseline",
        prompt_types=("positive point", "negative point", "box", "mask refinement"),
        video_propagation=True,
        minimum_torch="2.5.1",
        official_accelerator="CUDA; MPS requires NOVA compatibility validation",
        license="Apache-2.0",
        local_m1_status="evaluate",
        decision="primary",
    ),
    ModelCandidate(
        name="SAM 2.1 Hiera Tiny",
        role="memory and latency fallback",
        prompt_types=("positive point", "negative point", "box", "mask refinement"),
        video_propagation=True,
        minimum_torch="2.5.1",
        official_accelerator="CUDA; MPS requires NOVA compatibility validation",
        license="Apache-2.0",
        local_m1_status="evaluate",
        decision="fallback",
    ),
    ModelCandidate(
        name="SAM 3.1",
        role="future multi-object CUDA benchmark",
        prompt_types=("visual prompt", "text prompt"),
        video_propagation=True,
        minimum_torch="2.7",
        official_accelerator="CUDA 12.6+",
        license="SAM License",
        local_m1_status="defer",
        decision="not a Phase 1 local baseline",
    ),
)


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    system: str
    release: str
    machine: str
    python: str
    torch_installed: bool
    torch_version: str | None
    mps_available: bool | None
    mps_smoke_passed: bool | None
    mps_smoke_message: str


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def probe_runtime() -> RuntimeProbe:
    torch_version = _package_version("torch")
    mps_available: bool | None = None
    mps_smoke_passed: bool | None = None
    mps_smoke_message = "PyTorch is not installed"
    if torch_version is not None and importlib.util.find_spec("torch") is not None:
        torch = importlib.import_module("torch")
        mps_available = bool(torch.backends.mps.is_available())
        if mps_available:
            try:
                tensor = torch.arange(256, dtype=torch.float32, device="mps").reshape(16, 16)
                result = tensor @ tensor.T
                torch.mps.synchronize()
                checksum = float(result.sum().cpu())
                mps_smoke_passed = checksum > 0
                mps_smoke_message = f"MPS matrix operation completed (checksum={checksum:.1f})"
            except Exception as exc:
                mps_smoke_passed = False
                mps_smoke_message = f"MPS matrix operation failed: {exc}"
        else:
            mps_smoke_passed = False
            mps_smoke_message = "MPS is built but unavailable in this process"
    return RuntimeProbe(
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        python=platform.python_version(),
        torch_installed=torch_version is not None,
        torch_version=torch_version,
        mps_available=mps_available,
        mps_smoke_passed=mps_smoke_passed,
        mps_smoke_message=mps_smoke_message,
    )


def evaluation_gates(probe: RuntimeProbe) -> tuple[dict[str, str], ...]:
    return (
        {
            "gate": "runtime",
            "status": "ready" if probe.torch_installed else "blocked",
            "evidence": (
                f"PyTorch {probe.torch_version} installed"
                if probe.torch_installed
                else "Install the optional AI runtime before model execution"
            ),
        },
        {
            "gate": "accelerator",
            "status": "ready" if probe.mps_smoke_passed else "blocked",
            "evidence": (
                probe.mps_smoke_message
                if probe.mps_smoke_passed is not None
                else "MPS availability has not been demonstrated"
            ),
        },
        {
            "gate": "weights",
            "status": "pending",
            "evidence": "Model weights are intentionally external to the repository",
        },
        {
            "gate": "quality",
            "status": "pending",
            "evidence": "Run the representative-shot benchmark after runtime validation",
        },
    )


def write_report(output_dir: Path, probe: RuntimeProbe | None = None) -> tuple[Path, Path]:
    runtime = probe or probe_runtime()
    generated_at = datetime.now(UTC).isoformat()
    gates = evaluation_gates(runtime)
    payload = {
        "suite": "NOVA Layer Model Evaluation Preflight",
        "generated_at": generated_at,
        "recommendation": "SAM 2.1 Hiera Small",
        "runtime": asdict(runtime),
        "gates": list(gates),
        "candidates": [asdict(candidate) for candidate in CANDIDATES],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "model_evaluation_preflight_latest.json"
    markdown_path = output_dir / "model_evaluation_preflight_latest.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# NOVA Layer Model Evaluation Preflight",
        "",
        f"Generated: {generated_at}",
        "",
        "Recommendation: **SAM 2.1 Hiera Small** as the Phase 1 baseline.",
        "",
        "## Runtime",
        "",
        f"- Platform: {runtime.system} {runtime.release} ({runtime.machine})",
        f"- Python: {runtime.python}",
        f"- PyTorch: {runtime.torch_version or 'not installed'}",
        f"- MPS available: {runtime.mps_available}",
        f"- MPS smoke test: {runtime.mps_smoke_message}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {gate['gate']} | {gate['status'].upper()} | {gate['evidence']} |" for gate in gates
    )
    lines.extend(
        [
            "",
            "## Candidate Decision",
            "",
            "| Candidate | Role | Local status | Decision |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {item.name} | {item.role} | {item.local_m1_status} | {item.decision} |"
        for item in CANDIDATES
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect readiness for real AI model evaluation.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "06_Test" / "reports",
    )
    args = parser.parse_args()
    json_path, markdown_path = write_report(args.output)
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
