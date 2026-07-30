from __future__ import annotations

import argparse
from pathlib import Path

from nova_layer.benchmark_dataset import review_dataset_case


def main() -> int:
    parser = argparse.ArgumentParser(description="Record human QA for a benchmark annotation.")
    parser.add_argument("manifest")
    parser.add_argument("case_id")
    parser.add_argument("--status", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    manifest = Path(args.manifest)
    review_dataset_case(
        manifest,
        args.case_id,
        status=args.status,
        reviewer=args.reviewer,
        notes=args.notes,
    )
    print(manifest.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
