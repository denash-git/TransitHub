from __future__ import annotations

from pathlib import Path
import runpy


if __name__ == "__main__":
    install_module = runpy.run_path(str(Path(__file__).resolve().parent / "install" / "cli.py"))
    raise SystemExit(install_module["main"]())
