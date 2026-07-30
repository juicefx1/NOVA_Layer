from __future__ import annotations

import argparse
from pathlib import Path

from nova_layer.benchmark_baseline import (
    activate_registered_baseline,
    audit_baseline_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or reactivate a registered baseline.")
    parser.add_argument("registry", type=Path)
    parser.add_argument("--activate")
    args = parser.parse_args()
    audit = audit_baseline_registry(args.registry)
    print(
        f"Baseline registry: {'VALID' if audit.valid else 'INVALID'} "
        f"({audit.checked_snapshots} snapshots checked)"
    )
    for issue in audit.issues:
        print(issue)
    if not audit.valid:
        return 1
    if args.activate:
        print(activate_registered_baseline(args.registry, args.activate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
