from __future__ import annotations

import argparse
import json
from pathlib import Path

from nova_layer.export.smart_layer import ExportFormat
from nova_layer.host.adapters import AfterEffectsHostAdapter, NukeHostAdapter
from nova_layer.host.session import HeadlessHostSession, HostSessionError


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Headless NOVA host session for DCC and automation integrations."
    )
    parser.add_argument("project", type=Path, help="Path to a .nova project package")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Print a JSON status snapshot")
    subparsers.add_parser("validate-media", help="Re-check the linked source media")
    subparsers.add_parser(
        "promote-production-ready",
        help="Promote a validated Smart Layer with renders to production_ready",
    )
    subparsers.add_parser("menu-nuke", help="Print the Nuke adapter menu skeleton")
    subparsers.add_parser("menu-ae", help="Print the After Effects adapter menu skeleton")

    relink_parser = subparsers.add_parser("relink", help="Relink source media")
    relink_parser.add_argument("media", type=Path)
    relink_parser.add_argument(
        "--accept-changed",
        action="store_true",
        help="Allow a replacement whose fingerprint differs from the original",
    )

    export_parser = subparsers.add_parser(
        "export-render", help="Export a Smart Layer render through the host session"
    )
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--version", type=int, default=None)
    export_parser.add_argument(
        "--format",
        choices=[item.value for item in ExportFormat],
        default=ExportFormat.PNG_SEQUENCE.value,
    )

    args = parser.parse_args()
    if args.command == "menu-nuke":
        _print(NukeHostAdapter().install_menu())
        return 0
    if args.command == "menu-ae":
        _print(AfterEffectsHostAdapter().install_menu())
        return 0

    session = HeadlessHostSession()
    try:
        session.open_project(args.project)
        if args.command == "status":
            _print(session.status())
            return 0
        if args.command == "validate-media":
            _print(session.validate_media_link())
            return 0
        if args.command == "relink":
            _print(session.relink_media(args.media, accept_changed=args.accept_changed))
            return 0
        if args.command == "promote-production-ready":
            _print(session.promote_production_ready())
            return 0
        if args.command == "export-render":
            _print(
                session.export_render(
                    args.output,
                    version=args.version,
                    format=args.format,
                )
            )
            return 0
    except HostSessionError as exc:
        _print({"error": str(exc)})
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
