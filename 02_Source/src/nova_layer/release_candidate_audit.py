from __future__ import annotations

import argparse
from pathlib import Path

from nova_layer.release_candidate import audit_release_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a sealed NOVA release candidate.")
    parser.add_argument("release_directory", type=Path)
    args = parser.parse_args()
    audit = audit_release_candidate(args.release_directory)
    print(
        f"NOVA release candidate: {'VALID' if audit.valid else 'INVALID'} · "
        f"{audit.checked_files} files checked"
    )
    for issue in audit.issues:
        print(issue)
    return 0 if audit.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
