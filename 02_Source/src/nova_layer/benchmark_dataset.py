from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import file_digest, sha256
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.domain.models import MaturityState, ValidationState


@dataclass(frozen=True, slots=True)
class DatasetExport:
    manifest_path: Path
    mask_path: Path
    case_id: str


def review_record_sha256(record: dict[str, object]) -> str:
    canonical = {key: value for key, value in record.items() if key != "review_sha256"}
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_review_history(history: object) -> tuple[dict[str, object], ...]:
    if not isinstance(history, list) or not history:
        raise ValueError("Review history is empty or invalid.")
    validated: list[dict[str, object]] = []
    previous_hash: str | None = None
    for index, raw in enumerate(history):
        if not isinstance(raw, dict):
            raise ValueError(f"Review history entry {index} is invalid.")
        record = dict(raw)
        if record.get("previous_review_sha256") != previous_hash:
            raise ValueError(f"Review history chain is broken at entry {index}.")
        expected = review_record_sha256(record)
        if record.get("review_sha256") != expected:
            raise ValueError(f"Review history checksum mismatch at entry {index}.")
        validated.append(record)
        previous_hash = expected
    return tuple(validated)


def export_validated_master_case(
    package_path: Path,
    output_directory: Path,
    case_id: str,
    *,
    minimum_iou: float = 0.85,
) -> DatasetExport:
    safe_case_id = re.sub(r"[^A-Za-z0-9_-]+", "-", case_id).strip("-")
    if not safe_case_id:
        raise ValueError("Case ID must contain at least one letter or number.")
    if not 0.0 <= minimum_iou <= 1.0:
        raise ValueError("Minimum IoU must be between 0 and 1.")

    package_path = package_path.resolve()
    project = JsonProjectStore().load(package_path)
    if not project.sequences or not project.sequences[0].shots:
        raise ValueError("Project does not contain a Shot.")
    shot = project.sequences[0].shots[0]
    if not shot.smart_layers:
        raise ValueError("Shot does not contain a Smart Layer.")
    layer = shot.smart_layers[0]
    if layer.object_identity.maturity_state not in {
        MaturityState.VALIDATED,
        MaturityState.PRODUCTION_READY,
    }:
        raise ValueError("Smart Layer must be fully validated before dataset export.")
    master = next((item for item in layer.frame_results if item.direction == "master"), None)
    if master is None or master.validation_state != ValidationState.ACCEPTED:
        raise ValueError("Master Frame must have an accepted mask.")
    if shot.media.source_path is None or not Path(shot.media.source_path).is_file():
        raise ValueError("Source media must be linked and available.")
    source_mask = package_path / master.mask_reference
    if not source_mask.is_file():
        raise ValueError(f"Accepted Master Frame mask is missing: {source_mask}")

    output_directory = output_directory.resolve()
    masks_directory = output_directory / "ground_truth"
    manifest_path = output_directory / "real_footage_manifest.json"
    destination_mask = masks_directory / f"{safe_case_id}_{master.frame_number:06d}.png"
    if destination_mask.exists():
        raise ValueError(f"Dataset mask already exists: {destination_mask}")

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
            raise ValueError("Existing dataset manifest is invalid.")
    else:
        manifest = {
            "suite": "NOVA Layer Real-Footage Dataset",
            "gates": {"minimum_mean_iou": 0.85, "minimum_pass_rate": 1.0},
            "cases": [],
        }
    cases = manifest["cases"]
    if any(isinstance(item, dict) and item.get("id") == safe_case_id for item in cases):
        raise ValueError(f"Dataset case already exists: {safe_case_id}")

    intent = layer.artist_intent
    case = {
        "id": safe_case_id,
        "media": str(Path(shot.media.source_path).resolve()),
        "source_media_fingerprint": shot.media.fingerprint,
        "frame": master.frame_number,
        "ground_truth_mask": str(destination_mask.relative_to(output_directory)),
        "points": [point.model_dump(mode="json") for point in intent.points],
        "bounding_region": (
            intent.bounding_region.model_dump(mode="json")
            if intent.bounding_region is not None
            else None
        ),
        "skeleton_guidance": intent.skeleton_guidance.model_dump(mode="json"),
        "skeleton_corrections": [
            correction.model_dump(mode="json") for correction in layer.skeleton_corrections
        ],
        "minimum_iou": minimum_iou,
        "annotation_source": "artist_validated_smart_layer",
        "annotation_status": "candidate",
        "source_project_id": str(project.id),
        "source_shot_id": str(shot.id),
        "source_layer_id": str(layer.id),
        "source_layer_version": layer.version,
    }
    updated_manifest = {**manifest, "cases": [*cases, case]}
    output_directory.mkdir(parents=True, exist_ok=True)
    masks_directory.mkdir(parents=True, exist_ok=True)
    temporary_manifest = output_directory / f".{manifest_path.name}.{uuid4().hex}.tmp"
    temporary_mask = masks_directory / f".{destination_mask.name}.{uuid4().hex}.tmp"
    try:
        copy2(source_mask, temporary_mask)
        temporary_manifest.write_text(
            json.dumps(updated_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_mask, destination_mask)
        os.replace(temporary_manifest, manifest_path)
    except Exception:
        temporary_mask.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        destination_mask.unlink(missing_ok=True)
        raise
    return DatasetExport(manifest_path, destination_mask, safe_case_id)


def review_dataset_case(
    manifest_path: Path,
    case_id: str,
    *,
    status: str,
    reviewer: str,
    notes: str = "",
) -> None:
    if status not in {"approved", "rejected"}:
        raise ValueError("Review status must be approved or rejected.")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer is required for dataset QA decisions.")
    manifest_path = manifest_path.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Dataset manifest is invalid.")
    matching = [
        item for item in payload["cases"] if isinstance(item, dict) and item.get("id") == case_id
    ]
    if not matching:
        raise ValueError(f"Dataset case does not exist: {case_id}")
    if len(matching) > 1:
        raise ValueError(f"Dataset manifest contains duplicate case IDs: {case_id}")
    case = matching[0]
    ground_truth_value = case.get("ground_truth_mask")
    if not isinstance(ground_truth_value, str):
        raise ValueError(f"Dataset case has no ground-truth mask: {case_id}")
    ground_truth_path = (manifest_path.parent / ground_truth_value).resolve()
    if not ground_truth_path.is_file():
        raise ValueError(f"Ground-truth mask is missing: {ground_truth_path}")
    with ground_truth_path.open("rb") as stream:
        ground_truth_sha256 = file_digest(stream, "sha256").hexdigest()
    review_history = case.get("review_history", [])
    if not isinstance(review_history, list):
        raise ValueError(f"Dataset case has invalid review history: {case_id}")
    if review_history:
        validated_history = validate_review_history(review_history)
        previous_review_sha256 = str(validated_history[-1]["review_sha256"])
    else:
        previous_review_sha256 = None
    review_record: dict[str, object] = {
        "status": status,
        "reviewer": reviewer,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "notes": notes.strip(),
        "ground_truth_sha256": ground_truth_sha256,
        "source_media_fingerprint": case.get("source_media_fingerprint"),
        "previous_review_sha256": previous_review_sha256,
    }
    review_record["review_sha256"] = review_record_sha256(review_record)
    case["annotation_status"] = status
    case["review"] = {key: value for key, value in review_record.items() if key != "status"}
    case["review_history"] = [*review_history, review_record]
    temporary = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, manifest_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export an artist-validated NOVA Master Frame as a benchmark case."
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--minimum-iou", type=float, default=0.85)
    args = parser.parse_args()
    exported = export_validated_master_case(
        args.project,
        args.output,
        args.case_id,
        minimum_iou=args.minimum_iou,
    )
    print(exported.manifest_path)
    print(exported.mask_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
