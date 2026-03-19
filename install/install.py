from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
XUI_DB_PATH = PROJECT_ROOT / "xui" / "data" / "x-ui.db"
COMPOSE_FILES = [
    PROJECT_ROOT / "docker-compose.yml",
    PROJECT_ROOT / "nginx" / "docker-compose.yml",
    PROJECT_ROOT / "xui" / "docker-compose.yml",
    PROJECT_ROOT / "sub2sing-box" / "docker-compose.yml",
]
PRUNE_TOP_LEVEL = [
    PROJECT_ROOT / "docs",
    PROJECT_ROOT / "temp",
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "__pycache__",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="3XUI V1 installer")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--non-interactive", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    overrides = parse_key_value(args.set)

    banner("3XUI V1 Installer", "Clean host deploy with local service directories")
    ensure_venv()
    python = venv_python()

    step(1, "Prepare Python environment")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)])

    step(2, "Create project layout")
    run([str(python), "-m", "bootstrap", "ensure-layout"])
    step(3, "Prepare host dependencies and firewall")
    run([str(python), "-m", "bootstrap", "prepare-host"])

    step(4, "Initialize instance settings")
    init_command = [str(python), "-m", "bootstrap", "init"]
    if args.non_interactive:
        init_command.append("--non-interactive")
    for key, value in overrides.items():
        init_command.extend(["--set", f"{key}={value}"])
    run(init_command)
    values = load_instance_env(str(python))

    step(5, "Issue or reuse TLS certificate")
    issue_certificate(str(python), values["DOMAIN"], values.get("CERTBOT_EMAIL", ""))

    step(6, "Start core containers")
    cleanup_previous_stack()
    run(compose_command("up", "-d", "xui", "sub2sing-box"))
    wait_for_xui_db()

    step(7, "Seed panel settings and inbounds")
    run([str(python), "-m", "bootstrap", "seed-xui-db"])

    step(8, "Start full stack")
    run(compose_command("up", "-d", "--force-recreate", "--remove-orphans"))
    run([str(python), str(PROJECT_ROOT / "install" / "cleanup.py")])
    prune_deployed_tree(values)
    print_summary(values)
    return 0


def ensure_venv() -> None:
    if venv_ready():
        return
    ensure_system_venv_support()
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    command = [sys.executable, "-m", "venv", str(VENV_DIR)]
    try:
        run(command)
    except subprocess.CalledProcessError as exc:
        if not should_install_venv_support(exc):
            raise
        install_python_venv_support()
        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        run(command)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_ready() -> bool:
    python = venv_python()
    if not VENV_DIR.exists() or not python.exists():
        return False
    completed = subprocess.run(
        [str(python), "-c", "import sys; print(sys.executable)"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def ensure_system_venv_support() -> None:
    if os.name == "nt" or shutil.which("apt-get") is None:
        return
    completed = subprocess.run(
        [sys.executable, "-Im", "ensurepip", "--version"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    install_python_venv_support()


def should_install_venv_support(error: subprocess.CalledProcessError) -> bool:
    if os.name == "nt" or shutil.which("apt-get") is None:
        return False
    output = f"{error.output or ''}\n{error.stderr or ''}"
    markers = (
        "ensurepip is not available",
        "install the python3-venv package",
        "No module named venv",
    )
    return any(marker in output for marker in markers)


def install_python_venv_support() -> None:
    versioned_package = f"python{sys.version_info.major}.{sys.version_info.minor}-venv"
    attempts = [
        [versioned_package],
        ["python3-venv"],
    ]

    run(["apt-get", "update"])
    failures: list[tuple[list[str], str, str]] = []
    for packages in attempts:
        completed = subprocess.run(
            ["apt-get", "install", "-y", *packages],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
        failures.append((packages, completed.stdout, completed.stderr))

    for packages, stdout, stderr in failures:
        label = " ".join(packages)
        if stdout:
            print(stdout)
        if stderr:
            print(f"[apt install failed: {label}]\n{stderr}", file=sys.stderr)
    raise RuntimeError("Unable to install Python venv support automatically.")


def load_instance_env(python: str) -> dict[str, str]:
    completed = subprocess.run(
        [python, "-c", "from bootstrap.runtime import load_instance_env; import json; print(json.dumps(load_instance_env()))"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def issue_certificate(python: str, domain: str, email: str) -> None:
    run(
        [
            python,
            "-c",
            (
                "from bootstrap.certbot import ensure_certificate; "
                f"ensure_certificate({domain!r}, {email!r})"
            ),
        ],
    )


def wait_for_xui_db(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if XUI_DB_PATH.exists() and XUI_DB_PATH.stat().st_size > 0:
            return
        time.sleep(2)
    raise TimeoutError(f"x-ui.db was not created in time: {XUI_DB_PATH}")


def cleanup_previous_stack() -> None:
    completed = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project.working_dir={PROJECT_ROOT}",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    container_ids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if container_ids:
        run(["docker", "rm", "-f", *container_ids])


def compose_base_command() -> list[str]:
    if subprocess.run(
        ["docker", "compose", "version"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose") and subprocess.run(
        ["docker-compose", "version"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0:
        return ["docker-compose"]
    raise RuntimeError("Docker Compose is not available. Neither 'docker compose' nor 'docker-compose' was found.")


def compose_command(*arguments: str) -> list[str]:
    command = [*compose_base_command(), "--env-file", "instance.env"]
    for compose_file in COMPOSE_FILES:
        command.extend(["-f", str(compose_file)])
    command.extend(arguments)
    return command


def parse_key_value(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --set value: {item}")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def banner(title: str, subtitle: str) -> None:
    lines = [title, subtitle]
    width = max(len(line) for line in lines) + 4
    print("+" + "-" * width + "+")
    for line in lines:
        print(f"|  {line.ljust(width - 2)}|")
    print("+" + "-" * width + "+")


def step(number: int, title: str) -> None:
    print(f"[{number:02d}/08] {title}")


def print_summary(values: dict[str, str]) -> None:
    panel_url = f"https://{values['DOMAIN']}/{values['PANEL_PATH']}/"
    sub_url = f"https://{values['DOMAIN']}/{values['SUB_PATH']}/first"
    json_url = f"https://{values['DOMAIN']}/{values['JSON_PATH']}/first"
    lines = [
        f"Panel URL    : {panel_url}",
        f"Username     : {values['CONFIG_USERNAME']}",
        f"Password     : {values['CONFIG_PASSWORD']}",
        f"Sub URL      : {sub_url}",
        f"JSON Sub URL : {json_url}",
        f"Fake site    : {values['FAKE_SITE_TEMPLATE']}",
    ]
    width = max(len(line) for line in lines) + 2
    print("+" + "-" * width + "+")
    for line in lines:
        print(f"| {line.ljust(width - 1)}|")
    print("+" + "-" * width + "+")


def prune_deployed_tree(values: dict[str, str]) -> None:
    if os.name == "nt":
        return

    for path in PRUNE_TOP_LEVEL:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

    fake_templates_root = PROJECT_ROOT / "templates" / "fakesite"
    selected = values["FAKE_SITE_TEMPLATE"]
    if fake_templates_root.exists():
        for path in fake_templates_root.iterdir():
            if path.name == selected:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


def run(command: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd or PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)
    raise subprocess.CalledProcessError(
        completed.returncode,
        command,
        output=completed.stdout,
        stderr=completed.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
