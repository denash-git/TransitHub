from __future__ import annotations

import sys

from . import cli, project


PROJECT_COMMANDS = {
    "ensure-layout",
    "init",
    "prepare-host",
    "reconfigure",
    "seed-xui-db",
    "status",
    "sync-xui-db",
}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in PROJECT_COMMANDS:
        return project.main()
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
