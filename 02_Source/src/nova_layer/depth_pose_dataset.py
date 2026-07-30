from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from nova_layer.adapters.persistence.json_store import JsonProjectStore
from nova_layer.domain.models import SkeletonGuidance


@dataclass(frozen=True, slots=True)
class DepthPoseDatasetExport:
    manifest_path: Path
    case_id: str
    ground_truth_source: str


def _candidate_skeletons(
    package_path: Path,
) -> tuple[SkeletonGuidance, SkeletonGuidance, str, dict[str, object]]:
    project = JsonProjectStore().load(package_path)
    if not project.sequences or not project.sequences[0].shots:
        raise ValueError("Project does not contain a Shot.")
    shot = project.sequences[0].shots[0]
    if not shot.smart_layers:
        raise ValueError("Shot does not contain a Smart Layer.")
    layer = shot.smart_layers[0]
    artist = layer.artist_intent.skeleton_guidance
    if not artist.semantic_joint_map():
        raise ValueError("Artist guidance requires semantic joint labels.")
    corrections = [
        correction
        for correction in layer.skeleton_corrections
        if correction.frame_number == shot.master_frame
    ]
    if corrections:
        ground_truth = corrections[-1].skeleton
        source = "artist_master_frame_correction"
    else:
        accepted = [
            candidate
            for candidate in layer.skeleton_fusion_candidates
            if candidate.frame_number == shot.master_frame and candidate.status == "accepted"
        ]
        if not accepted:
            raise ValueError(
                "Master Frame requires an artist correction or accepted fusion candidate."
            )
        ground_truth = accepted[-1].fused_skeleton
        artist = accepted[-1].artist_skeleton
        source = "artist_accepted_fusion"
    if not ground_truth.semantic_joint_map():
        raise ValueError("Ground-truth candidate requires semantic joint labels.")
    if shot.media.source_path is None or not Path(shot.media.source_path).is_file():
        raise ValueError("Source media must be linked and available.")
    metadata: dict[str, object] = {
        "media": str(Path(shot.media.source_path).resolve()),
        "source_media_fingerprint": shot.media.fingerprint,
        "frame": shot.master_frame,
        "source_project_id": str(project.id),
        "source_shot_id": str(shot.id),
        "source_layer_id": str(layer.id),
        "source_layer_version": layer.version,
    }
    return artist, ground_truth, source, metadata


def export_case(package_path: Path, output_directory: Path, case_id: str) -> DepthPoseDatasetExport:
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", case_id).strip("-")
    if not safe_id:
        raise ValueError("Case ID must contain at least one letter or number.")
    package_path = package_path.resolve()
    artist, ground_truth, source, metadata = _candidate_skeletons(package_path)
    output_directory = output_directory.resolve()
    manifest_path = output_directory / "depth_pose_manifest.json"
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
            raise ValueError("Existing Depth/Pose manifest is invalid.")
    else:
        payload = {
            "suite": "NOVA Depth/Pose Dataset",
            "gates": {
                "maximum_mean_temporal_relative_depth_delta": None,
                "minimum_temporal_transition_coverage": None,
            },
            "cases": [],
        }
    cases = payload["cases"]
    if any(isinstance(item, dict) and item.get("id") == safe_id for item in cases):
        raise ValueError(f"Depth/Pose case already exists: {safe_id}")
    case = {
        "id": safe_id,
        **metadata,
        "pck_threshold": 0.05,
        "minimum_pck": 0.8,
        "minimum_joint_coverage": 0.8,
        "minimum_depth_coverage": 0.8,
        "minimum_sampled_depth_coverage": 0.8,
        "maximum_duration_seconds": 20.0,
        "depth_sequence": str(metadata["source_layer_id"]),
        "artist_skeleton": artist.model_dump(mode="json"),
        "ground_truth_skeleton": ground_truth.model_dump(mode="json"),
        "ground_truth_source": source,
        "annotation_status": "candidate",
        "review": None,
        "review_history": [],
    }
    updated = {**payload, "cases": [*cases, case]}
    output_directory.mkdir(parents=True, exist_ok=True)
    temporary = output_directory / f".{manifest_path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, manifest_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return DepthPoseDatasetExport(manifest_path, safe_id, source)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a reviewed NOVA Master Frame pose as a benchmark candidate."
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    exported = export_case(args.project, args.output, args.case_id)
    print(exported.manifest_path)
    print(exported.ground_truth_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
