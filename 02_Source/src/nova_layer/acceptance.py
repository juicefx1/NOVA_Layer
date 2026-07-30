from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    id: str
    name: str
    evidence_test: str


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    id: str
    name: str
    status: str
    duration_seconds: float
    evidence_test: str
    output: str


ACCEPTANCE_CASES = (
    AcceptanceCase(
        "P1-AT-001",
        "Basic project-to-validation flow",
        "tests/test_media_flow.py::test_hypothesis_generation_and_confirmation",
    ),
    AcceptanceCase(
        "P1-AT-002",
        "Non-zero Shot Range",
        "tests/test_media_flow.py::test_shot_selection_is_validated_and_saved",
    ),
    AcceptanceCase(
        "P1-AT-003",
        "Backward propagation",
        "tests/test_media_flow.py::test_hypothesis_generation_and_confirmation",
    ),
    AcceptanceCase(
        "P1-AT-004",
        "Forward propagation",
        "tests/test_media_flow.py::test_hypothesis_generation_and_confirmation",
    ),
    AcceptanceCase(
        "P1-AT-005",
        "Ambiguity requires artist validation",
        "tests/test_media_flow.py::test_low_confidence_propagation_requires_artist_review",
    ),
    AcceptanceCase(
        "P1-AT-006",
        "Correction and local recomputation",
        "tests/test_media_flow.py::test_hypothesis_generation_and_confirmation",
    ),
    AcceptanceCase(
        "P1-AT-007",
        "Project persistence",
        "tests/test_domain.py::DomainTests::test_project_round_trip_preserves_identity",
    ),
    AcceptanceCase(
        "P1-AT-008",
        "Missing media relink",
        "tests/test_media_flow.py::test_missing_media_requires_relink",
    ),
    AcceptanceCase(
        "P1-AT-009",
        "Capability failure preserves project state",
        "tests/test_media_flow.py::test_capability_failure_preserves_project_state",
    ),
)


class AcceptanceRunner:
    def __init__(self, source_root: Path | None = None) -> None:
        self.source_root = source_root or Path(__file__).resolve().parents[2]

    def run(self) -> list[AcceptanceResult]:
        results: list[AcceptanceResult] = []
        for case in ACCEPTANCE_CASES:
            started = monotonic()
            process = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", case.evidence_test],
                cwd=self.source_root,
                capture_output=True,
                text=True,
                check=False,
            )
            duration = monotonic() - started
            output = (process.stdout + process.stderr).strip()
            results.append(
                AcceptanceResult(
                    id=case.id,
                    name=case.name,
                    status="passed" if process.returncode == 0 else "failed",
                    duration_seconds=round(duration, 3),
                    evidence_test=case.evidence_test,
                    output=output,
                )
            )
        return results

    def write_reports(self, results: list[AcceptanceResult], output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_at = datetime.now(UTC).isoformat()
        passed = sum(result.status == "passed" for result in results)
        payload = {
            "suite": "NOVA Layer Phase 1 Acceptance",
            "generated_at": generated_at,
            "passed": passed,
            "total": len(results),
            "results": [asdict(result) for result in results],
        }
        json_path = output_dir / "phase1_acceptance_latest.json"
        markdown_path = output_dir / "phase1_acceptance_latest.md"
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        lines = [
            "# NOVA Layer Phase 1 Acceptance Report",
            "",
            f"Generated: {generated_at}",
            "",
            f"Result: {passed}/{len(results)} passed",
            "",
            "| ID | Acceptance Criterion | Status | Duration | Evidence |",
            "|---|---|---:|---:|---|",
        ]
        for result in results:
            lines.append(
                f"| {result.id} | {result.name} | {result.status.upper()} | "
                f"{result.duration_seconds:.3f}s | `{result.evidence_test}` |"
            )
        lines.extend(["", "## Evidence Output", ""])
        for result in results:
            lines.extend(
                [
                    f"### {result.id} — {result.name}",
                    "",
                    "```text",
                    result.output or "No output.",
                    "```",
                    "",
                ]
            )
        markdown_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NOVA Layer Phase 1 acceptance checks.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "06_Test" / "reports",
    )
    args = parser.parse_args()
    runner = AcceptanceRunner()
    results = runner.run()
    json_path, markdown_path = runner.write_reports(results, args.output)
    passed = sum(result.status == "passed" for result in results)
    print(f"Phase 1 acceptance: {passed}/{len(results)} passed")
    print(json_path)
    print(markdown_path)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
