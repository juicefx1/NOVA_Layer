from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np

from nova_layer.app.capability_selection import (
    load_skeleton_adapter,
    load_skeleton_detection_adapter,
)
from nova_layer.domain.models import SkeletonBone, SkeletonGuidance, SkeletonJoint
from nova_layer.ports.capabilities import VideoFrame


def check_adapter(spec: str) -> dict[str, Any]:
    adapter = load_skeleton_adapter(spec)
    shoulder = SkeletonJoint(x=0.35, y=0.3, label="shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="wrist")
    reference = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    frames = [
        VideoFrame(
            frame_number=frame_number,
            image=np.zeros((32, 32, 3), dtype=np.uint8),
        )
        for frame_number in (9, 10, 11)
    ]
    results = adapter.track(
        master_frame=10,
        reference_skeleton=reference,
        frames=frames,
    )
    provenance = adapter.provenance
    return {
        "status": "passed",
        "role": "tracking",
        "adapter_spec": spec,
        "provenance": provenance.model_dump(mode="json"),
        "input_frames": [frame.frame_number for frame in frames],
        "result_frames": [result.frame_number for result in results],
        "result_count": len(results),
        "contract_checks": [
            "loadable factory",
            "skeleton_tracking provenance",
            "requested frame scope",
            "unique result frames",
            "preserved joint identities",
            "preserved bone topology",
        ],
    }


def check_detection_adapter(spec: str) -> dict[str, Any]:
    adapter = load_skeleton_detection_adapter(spec)
    shoulder = SkeletonJoint(x=0.35, y=0.3, label="left_shoulder")
    wrist = SkeletonJoint(x=0.6, y=0.65, label="left_wrist")
    artist = SkeletonGuidance(
        joints=[shoulder, wrist],
        bones=[SkeletonBone(start_joint_id=shoulder.id, end_joint_id=wrist.id)],
    )
    result = adapter.detect(
        frame_number=10,
        image=np.zeros((32, 32, 3), dtype=np.uint8),
        artist_skeleton=artist,
    )
    return {
        "status": "passed",
        "role": "detection",
        "adapter_spec": spec,
        "provenance": result.provenance.model_dump(mode="json"),
        "detected_labels": sorted(result.skeleton.semantic_joint_map()),
        "joint_confidences": result.joint_confidences,
        "depth_confidences": result.depth_confidences,
        "joint_depths": result.joint_depths,
        "contract_checks": [
            "loadable factory",
            "skeleton_detection provenance",
            "semantic artist-prompt overlap",
            "known confidence labels",
            "joint confidence range",
            "depth confidence range",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an external skeleton adapter against the NOVA contract."
    )
    parser.add_argument("adapter", help="Adapter factory in python.module:factory form")
    parser.add_argument(
        "--role",
        choices=("tracking", "detection"),
        default="tracking",
        help="Capability role implemented by the adapter (default: tracking)",
    )
    args = parser.parse_args()
    try:
        report = (
            check_detection_adapter(args.adapter)
            if args.role == "detection"
            else check_adapter(args.adapter)
        )
    except Exception as exc:
        report = {
            "status": "failed",
            "role": args.role,
            "adapter_spec": args.adapter,
            "error": str(exc),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(1) from exc
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
