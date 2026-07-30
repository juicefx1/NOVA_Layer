from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from nova_layer.benchmark_comparison import report_sha256


@dataclass(frozen=True, slots=True)
class BaselinePromotion:
    baseline_path: Path
    registry_path: Path
    report_sha256: str
    label: str


@dataclass(frozen=True, slots=True)
class BaselineRegistryAudit:
    valid: bool
    checked_snapshots: int
    issues: tuple[str, ...]


def promote_benchmark_baseline(
    candidate_report: Path,
    comparison_report: Path,
    registry_directory: Path,
    *,
    label: str,
) -> BaselinePromotion:
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-.")
    if not safe_label:
        raise ValueError("Baseline label must contain a letter or number.")
    candidate_report = candidate_report.resolve()
    comparison_report = comparison_report.resolve()
    candidate = json.loads(candidate_report.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_report.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict) or not isinstance(comparison, dict):
        raise ValueError("Candidate and comparison reports must be JSON objects.")
    if comparison.get("passed") is not True:
        raise ValueError("Only a passing regression comparison can promote a baseline.")
    candidate_hash = report_sha256(candidate_report)
    if comparison.get("candidate_report_sha256") != candidate_hash:
        raise ValueError("Candidate report differs from the report approved by comparison.")
    summary = candidate.get("summary")
    if not isinstance(summary, dict) or summary.get("passed") is not True:
        raise ValueError("Candidate report did not pass its configured suite gates.")

    registry_directory = registry_directory.resolve()
    baselines_directory = registry_directory / "baselines"
    registry_path = registry_directory / "baseline_registry.json"
    baseline_path = baselines_directory / f"{safe_label}_{candidate_hash[:12]}.json"
    if baseline_path.exists():
        raise ValueError(f"Immutable baseline snapshot already exists: {baseline_path}")
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict) or not isinstance(registry.get("history"), list):
            raise ValueError("Existing baseline registry is invalid.")
    else:
        registry = {"format_version": 1, "history": []}

    promoted_at = datetime.now(UTC).isoformat()
    entry = {
        "label": safe_label,
        "suite": candidate.get("suite"),
        "runtime_mode": candidate.get("runtime_mode"),
        "model_provenance": candidate.get("model_provenance"),
        "checkpoint": candidate.get("checkpoint"),
        "report_sha256": candidate_hash,
        "snapshot": str(baseline_path.relative_to(registry_directory)),
        "promoted_at": promoted_at,
        "comparison_report": str(comparison_report),
    }
    updated_registry = {
        **registry,
        "active_baseline": entry,
        "history": [*registry["history"], entry],
    }
    registry_directory.mkdir(parents=True, exist_ok=True)
    baselines_directory.mkdir(parents=True, exist_ok=True)
    temporary_baseline = baselines_directory / f".{baseline_path.name}.{uuid4().hex}.tmp"
    temporary_registry = registry_directory / f".{registry_path.name}.{uuid4().hex}.tmp"
    try:
        copy2(candidate_report, temporary_baseline)
        temporary_registry.write_text(
            json.dumps(updated_registry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_baseline, baseline_path)
        os.replace(temporary_registry, registry_path)
    except Exception:
        temporary_baseline.unlink(missing_ok=True)
        temporary_registry.unlink(missing_ok=True)
        baseline_path.unlink(missing_ok=True)
        raise
    return BaselinePromotion(baseline_path, registry_path, candidate_hash, safe_label)


def audit_baseline_registry(registry_directory: Path) -> BaselineRegistryAudit:
    registry_directory = registry_directory.resolve()
    registry_path = registry_directory / "baseline_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return BaselineRegistryAudit(False, 0, (f"Could not read registry: {exc}",))
    history = registry.get("history") if isinstance(registry, dict) else None
    if not isinstance(history, list):
        return BaselineRegistryAudit(False, 0, ("Registry history is invalid.",))
    issues: list[str] = []
    checked = 0
    for entry in history:
        if not isinstance(entry, dict):
            issues.append("Registry history contains an invalid entry.")
            continue
        relative_snapshot = entry.get("snapshot")
        expected_hash = entry.get("report_sha256")
        if not isinstance(relative_snapshot, str) or not isinstance(expected_hash, str):
            issues.append("Registry entry is missing snapshot integrity metadata.")
            continue
        snapshot = (registry_directory / relative_snapshot).resolve()
        try:
            snapshot.relative_to(registry_directory)
        except ValueError:
            issues.append(f"Snapshot path escapes the registry: {relative_snapshot}")
            continue
        if not snapshot.is_file():
            issues.append(f"Baseline snapshot is missing: {relative_snapshot}")
            continue
        checked += 1
        if report_sha256(snapshot) != expected_hash:
            issues.append(f"Baseline checksum mismatch: {relative_snapshot}")
    return BaselineRegistryAudit(not issues, checked, tuple(issues))


def activate_registered_baseline(registry_directory: Path, label: str) -> Path:
    registry_directory = registry_directory.resolve()
    audit = audit_baseline_registry(registry_directory)
    if not audit.valid:
        raise ValueError(f"Baseline registry failed integrity audit: {audit.issues[0]}")
    registry_path = registry_directory / "baseline_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    history = registry["history"]
    matching = [entry for entry in history if entry.get("label") == label]
    if not matching:
        raise ValueError(f"Registered baseline does not exist: {label}")
    selected = matching[-1]
    selected_snapshot = str(selected["snapshot"])
    activation = {
        "label": selected["label"],
        "report_sha256": selected["report_sha256"],
        "snapshot": selected_snapshot,
        "activated_at": datetime.now(UTC).isoformat(),
    }
    updated = {
        **registry,
        "active_baseline": selected,
        "activation_history": [*registry.get("activation_history", []), activation],
    }
    temporary = registry_directory / f".{registry_path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, registry_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return (registry_directory / selected_snapshot).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote a passing benchmark as the baseline.")
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("comparison_report", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    promotion = promote_benchmark_baseline(
        args.candidate_report,
        args.comparison_report,
        args.registry,
        label=args.label,
    )
    print(promotion.baseline_path)
    print(promotion.registry_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
