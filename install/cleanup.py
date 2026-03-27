from __future__ import annotations

from pathlib import Path
import shutil


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIRS = [
    PROJECT_ROOT / "runtime",
    PROJECT_ROOT / "deploy",
    PROJECT_ROOT / "reverse-proxy",
    PROJECT_ROOT / "__pycache__",
]
LEGACY_FILES = [
    PROJECT_ROOT / "compose.yaml",
    PROJECT_ROOT / "bootstrap_test.sqlite3",
    PROJECT_ROOT / "tmp_xui-pro.sh",
]
REQUIRED_FILES = [
    PROJECT_ROOT / "nginx" / "docker-compose.yml",
    PROJECT_ROOT / "xui" / "docker-compose.yml",
    PROJECT_ROOT / "subconverter" / "docker-compose.yml",
    PROJECT_ROOT / "tgproxy" / "docker-compose.yml",
    PROJECT_ROOT / "netbird" / "docker-compose.yml",
    PROJECT_ROOT / "netbird" / "entrypoint.sh",
    PROJECT_ROOT / "transithub_runtime" / "__init__.py",
    PROJECT_ROOT / "transithub-menu.py",
    PROJECT_ROOT / "instance.env",
]


def main() -> int:
    if not all(path.exists() for path in REQUIRED_FILES):
        return 1

    for file_path in LEGACY_FILES:
        if file_path.exists():
            file_path.unlink()

    for directory in LEGACY_DIRS:
        if directory.exists():
            shutil.rmtree(directory)

    for pycache_dir in PROJECT_ROOT.rglob("__pycache__"):
        if pycache_dir.is_dir():
            shutil.rmtree(pycache_dir, ignore_errors=True)

    for pyc_file in PROJECT_ROOT.rglob("*.pyc"):
        if pyc_file.is_file():
            pyc_file.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
