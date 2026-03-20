from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from .certbot import CertbotError
from .certbot import ensure_certificate
from .mtproxy import enabled as mtproxy_enabled
from .mtproxy import tg_link as mtproxy_tg_link
from . import paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
XUI_DB_PATH = PROJECT_ROOT / "xui" / "data" / "x-ui.db"
PRUNE_TOP_LEVEL = [
    VENV_DIR,
    PROJECT_ROOT / "bootstrap.sh",
    PROJECT_ROOT / "docs",
    PROJECT_ROOT / "install",
    PROJECT_ROOT / "templates",
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "requirements.txt",
    PROJECT_ROOT / "install.sh",
    PROJECT_ROOT / "instance.env.example",
    PROJECT_ROOT / "__pycache__",
]
PRUNE_RUNTIME_DIRS = [
    PROJECT_ROOT / "install" / "host",
    PROJECT_ROOT / "nginx" / "logs",
    PROJECT_ROOT / "subconverter" / "config",
    PROJECT_ROOT / "subconverter" / "logs",
    PROJECT_ROOT / "fake-site",
    PROJECT_ROOT / "web-sub",
    PROJECT_ROOT / "xui" / "backup",
    PROJECT_ROOT / "xui" / "logs",
]
TOTAL_STEPS = 10
BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
RESET = "\033[0m"


class InstallerError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TransitHub v2 installer")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--non-interactive", action="store_true")
    return parser


def main() -> int:
    try:
        return run_install()
    except InstallerError as exc:
        print()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print()
        print(f"ERROR: Command failed: {format_command(exc.cmd)}", file=sys.stderr)
        return 1


def run_install() -> int:
    args = build_parser().parse_args()
    overrides = parse_key_value(args.set)

    banner("TransitHub v2 Installer", "Clean host deploy with local service directories")

    step(1, "Run preflight checks")
    preflight(overrides)

    step(2, "Prepare Python virtual environment")
    ensure_venv()
    python = venv_python()

    step(3, "Install Python packages")
    note("Upgrade pip in project virtual environment")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    note("Install installer Python dependencies")
    run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)])

    step(4, "Create project layout")
    run([str(python), "-m", "install", "ensure-layout"])

    step(5, "Prepare host dependencies and firewall")
    run([str(python), "-m", "install", "prepare-host"], stream_output=True)

    step(6, "Initialize instance settings")
    init_command = [str(python), "-m", "install", "init"]
    if args.non_interactive:
        init_command.append("--non-interactive")
    for key, value in overrides.items():
        init_command.extend(["--set", f"{key}={value}"])
    run(init_command)
    values = load_instance_env(str(python))
    enabled_services = runtime_services(values)

    step(7, "Issue or reuse TLS certificate")
    note(f"Resolve main domain {values['DOMAIN']}")
    resolve_domain_or_raise(values["DOMAIN"])
    resolve_mtproxy_tls_domain(values)
    issue_certificate(values["DOMAIN"], values.get("CERTBOT_EMAIL", ""))

    step(8, "Start core containers")
    cleanup_previous_stack()
    note("Create or reuse external Docker network proxy-net")
    ensure_proxy_network()
    note(f"Start {', '.join(enabled_services)} containers")
    run(compose_up_command(values, *enabled_services))
    note("Wait for xui service startup")
    wait_for_service_ready("xui")
    wait_for_service_ready("conv")
    if mtproxy_enabled(values):
        wait_for_service_ready("mtproxy")
    wait_for_xui_db()

    step(9, "Seed panel settings and inbounds")
    run([str(python), "-m", "install", "seed-xui-db"])

    step(10, "Start full stack and finalize deployment")
    note("Start all runtime services")
    run(compose_up_command(values, "--force-recreate", "--remove-orphans"))
    note("Wait for nginx, xui, conv, and optional mtproxy services")
    wait_for_service_ready("nginx")
    wait_for_service_ready("xui")
    wait_for_service_ready("conv")
    if mtproxy_enabled(values):
        wait_for_service_ready("mtproxy")
    note("Remove installer-only sources from deployed VPS tree")
    run([str(python), str(PROJECT_ROOT / "install" / "cleanup.py")])
    prune_deployed_tree()
    print_summary(values)
    return 0


def preflight(overrides: dict[str, str]) -> None:
    if os.name == "nt":
        return
    require_root()
    validate_supported_os()
    require_command("apt-get", "apt-get is not available. This installer supports Debian 12+ only.")
    validate_apt_access()
    validate_port_available(80)
    validate_port_available(443)
    validate_proxy_network_state()
    domain = overrides.get("DOMAIN", "").strip()
    if domain and domain != "example.com":
        resolve_domain_or_raise(domain)
    mtproxy_tls_domain = overrides.get("MTPROXY_TLS_DOMAIN", "").strip()
    if mtproxy_tls_domain:
        resolve_domain_or_raise(mtproxy_tls_domain)


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise InstallerError("This installer must run as root. Run `sudo bash install.sh` or use the root user.")


def validate_supported_os() -> None:
    os_release = parse_os_release()
    distro_id = os_release.get("ID", "")
    version = os_release.get("VERSION_ID", "").strip('"')
    if distro_id != "debian":
        raise InstallerError("Unsupported OS. This installer currently targets Debian 12 and Debian 13.")
    try:
        major_version = int(version.split(".", 1)[0])
    except ValueError as exc:
        raise InstallerError(f"Could not determine Debian version from VERSION_ID={version!r}.") from exc
    if major_version < 12:
        raise InstallerError(f"Unsupported Debian version: {version}. Supported versions are Debian 12 and 13.")


def parse_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.exists():
        raise InstallerError("/etc/os-release is missing. Cannot validate operating system.")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip()
    return result


def require_command(command: str, error_message: str) -> None:
    if shutil.which(command) is None:
        raise InstallerError(error_message)


def validate_apt_access() -> None:
    completed = subprocess.run(
        ["apt-get", "--version"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise InstallerError("apt-get is present but not working correctly on this host.")


def validate_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as exc:
            raise InstallerError(f"Required host port {port} is already in use. Free port {port} and retry.") from exc


def validate_proxy_network_state() -> None:
    if shutil.which("docker") is None:
        return
    version = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if version.returncode != 0:
        return

    inspect = subprocess.run(
        ["docker", "network", "inspect", "proxy-net", "--format", "{{json .}}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        return
    details = json.loads(inspect.stdout)
    driver = details.get("Driver", "")
    internal = details.get("Internal", False)
    if driver != "bridge" or internal:
        raise InstallerError(
            "Docker network `proxy-net` already exists but is not a usable external bridge network."
        )


def resolve_domain_or_raise(domain: str, label: str = "Main domain") -> None:
    try:
        socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        extra = " Point its DNS record to this VPS before installation." if label == "Main domain" else ""
        raise InstallerError(
            f"{label} `{domain}` does not resolve yet.{extra}"
        ) from exc


def resolve_mtproxy_tls_domain(values: dict[str, str]) -> None:
    if not mtproxy_enabled(values):
        return
    resolve_domain_or_raise(values["MTPROXY_TLS_DOMAIN"], "MTProxy TLS domain")


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

    note("Refresh apt package lists for Python venv support")
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
    raise InstallerError("Unable to install Python venv support automatically.")


def load_instance_env(python: str) -> dict[str, str]:
    completed = subprocess.run(
        [
            python,
            "-c",
            "from install.runtime import load_instance_env; import json; print(json.dumps(load_instance_env()))",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def issue_certificate(domain: str, email: str) -> None:
    try:
        ensure_certificate(domain, email)
    except CertbotError as exc:
        raise InstallerError(str(exc)) from exc


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
        note("Remove stale containers from previous installer runs")
        run(["docker", "rm", "-f", *container_ids], stream_output=True)


def ensure_proxy_network() -> None:
    network_name = "proxy-net"
    completed = subprocess.run(
        ["docker", "network", "inspect", network_name],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    run(["docker", "network", "create", network_name], stream_output=True)


def wait_for_service_ready(service: str, timeout_seconds: int = 90) -> None:
    values = load_instance_env(str(venv_python()))
    project_name = values.get("INSTANCE_NAME", "").strip() or "xui-v1"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        container_id = compose_service_container_id(project_name, service)
        if not container_id:
            time.sleep(2)
            continue

        state = inspect_container_state(container_id)
        status = state.get("Status")
        health = (state.get("Health") or {}).get("Status")
        if health == "healthy":
            return
        if service == "mtproxy" and status == "running":
            return
        if health is None and status == "running":
            return
        if status == "exited":
            logs = recent_service_logs(project_name, service)
            raise InstallerError(f"Service `{service}` exited during startup.\n{logs}")
        time.sleep(2)

    logs = recent_service_logs(project_name, service)
    raise TimeoutError(f"Service `{service}` did not become ready in time.\n{logs}")


def compose_service_container_id(project_name: str, service: str) -> str:
    completed = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")


def inspect_container_state(container_id: str) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "inspect", container_id, "--format", "{{json .State}}"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def recent_service_logs(project_name: str, service: str, tail: int = 80) -> str:
    container_id = compose_service_container_id(project_name, service)
    if not container_id:
        return f"No container found for service `{service}`."

    completed = subprocess.run(
        ["docker", "logs", f"--tail={tail}", container_id],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    chunks = []
    if stdout:
        chunks.append(stdout)
    if stderr:
        chunks.append(stderr)
    if not chunks:
        return f"No recent logs for service `{service}`."
    return f"Recent logs for `{service}`:\n" + "\n".join(chunks)


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
    raise InstallerError("Docker Compose is not available. Neither `docker compose` nor `docker-compose` was found.")


def compose_files(values: dict[str, str]) -> list[Path]:
    files = [
        paths.SERVICE_NGINX_COMPOSE_PATH,
        paths.SERVICE_XUI_COMPOSE_PATH,
        paths.SERVICE_SUBCONVERTER_COMPOSE_PATH,
    ]
    if mtproxy_enabled(values):
        files.append(paths.SERVICE_MTPROXY_COMPOSE_PATH)
    return files


def runtime_services(values: dict[str, str]) -> list[str]:
    services = ["xui", "conv"]
    if mtproxy_enabled(values):
        services.append("mtproxy")
    return services


def compose_command(values: dict[str, str], *arguments: str) -> list[str]:
    project_name = values.get("INSTANCE_NAME", "").strip() or "xui-v1"
    command = [
        *compose_base_command(),
        "--project-directory",
        str(PROJECT_ROOT),
        "-p",
        project_name,
        "--env-file",
        "instance.env",
    ]
    for compose_file in compose_files(values):
        command.extend(["-f", str(compose_file)])
    command.extend(arguments)
    return command


def compose_up_command(values: dict[str, str], *arguments: str) -> list[str]:
    return compose_command(values, "up", "-d", "--build", *arguments)


def parse_key_value(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise InstallerError(f"Invalid --set value: {item}")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def banner(title: str, subtitle: str) -> None:
    lines = [title, subtitle]
    width = max(len(line) for line in lines) + 4
    print("\n" * 2, end="")
    print(f"{BLUE}+" + "-" * width + f"+{RESET}")
    for line in lines:
        print(f"{BLUE}|  {line.ljust(width - 2)}|{RESET}")
    print(f"{BLUE}+" + "-" * width + f"+{RESET}")
    print()


def step(number: int, title: str) -> None:
    print()
    print(f"{GREEN}[{number:02d}/{TOTAL_STEPS:02d}] {title}{RESET}")


def note(message: str) -> None:
    print(f"  - {message}")


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
    if mtproxy_enabled(values):
        lines.append(f"MTProxy URL  : {mtproxy_tg_link(values)}")
        lines.append(f"MTProxy SNI  : {values['MTPROXY_TLS_DOMAIN']}")
    width = max(len(line) for line in lines) + 2
    print("\n" * 2, end="")
    print("Connection details")
    print()
    print("+" + "-" * width + "+")
    for line in lines:
        print(f"| {line.ljust(width - 1)}|")
    print("+" + "-" * width + "+")
    print()


def prune_deployed_tree() -> None:
    if os.name == "nt":
        return

    for path in PRUNE_TOP_LEVEL:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

    for path in PRUNE_RUNTIME_DIRS:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    for gitkeep_file in PROJECT_ROOT.rglob(".gitkeep"):
        if gitkeep_file.is_file():
            gitkeep_file.unlink()


def run(command: list[str], cwd: Path | None = None, stream_output: bool = False) -> None:
    if stream_output:
        completed = subprocess.run(
            command,
            cwd=cwd or PROJECT_ROOT,
            check=False,
            text=True,
        )
    else:
        completed = subprocess.run(
            command,
            cwd=cwd or PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            if completed.stdout:
                print(completed.stdout)
            if completed.stderr:
                print(completed.stderr, file=sys.stderr)

    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=getattr(completed, "stdout", None),
            stderr=getattr(completed, "stderr", None),
        )


def format_command(command: object) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(item) for item in command)
    return str(command)


if __name__ == "__main__":
    raise SystemExit(main())
