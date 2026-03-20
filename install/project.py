from __future__ import annotations

import argparse
import json
import sys

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="3XUI V2 instance management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Create or refresh a local instance state.")
    init_parser.add_argument("--non-interactive", action="store_true")
    init_parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")

    reconfigure_parser = subparsers.add_parser(
        "reconfigure", help="Re-render service files from root instance.env."
    )
    reconfigure_parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    subparsers.add_parser("status", help="Show current instance state.")
    subparsers.add_parser("ensure-layout", help="Create project directories.")
    subparsers.add_parser(
        "prepare-host",
        help="Install and validate required host dependencies on Debian.",
    )
    subparsers.add_parser(
        "sync-xui-db",
        help="Update x-ui.db admin credentials using root instance.env values.",
    )
    subparsers.add_parser(
        "seed-xui-db",
        help="Apply panel settings and create the baseline inbound set in x-ui.db.",
    )
    return parser


def parse_key_value(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --set value: {item}")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()

        if args.command == "ensure-layout":
            from . import paths
            from .runtime import ensure_layout

            ensure_layout()
            print(paths.PROJECT_ROOT)
            return 0

        if args.command == "init":
            from .runtime import init_instance

            print(
                json.dumps(
                    init_instance(
                        interactive=not args.non_interactive,
                        overrides=parse_key_value(args.set),
                    ),
                    indent=2,
                )
            )
            return 0

        if args.command == "reconfigure":
            from .runtime import reconfigure_instance

            print(json.dumps(reconfigure_instance(parse_key_value(args.set)), indent=2))
            return 0

        if args.command == "status":
            from .runtime import status

            print(json.dumps(status(), indent=2))
            return 0

        if args.command == "prepare-host":
            from .host import prepare_host

            prepare_host()
            return 0

        if args.command == "sync-xui-db":
            from .runtime import load_instance_env
            from .xui_db import sync_xui_db

            values = load_instance_env()
            print(
                json.dumps(
                    sync_xui_db(
                        username=values["CONFIG_USERNAME"],
                        password=values["CONFIG_PASSWORD"],
                    ),
                    indent=2,
                )
            )
            return 0

        if args.command == "seed-xui-db":
            from .runtime import load_instance_env
            from .xui_db import seed_xui_db

            values = load_instance_env()
            print(json.dumps(seed_xui_db(values), indent=2))
            return 0

        parser.print_help()
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
