from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from . import paths


APT_BASE_PACKAGES = [
    "ca-certificates",
    "curl",
    "gnupg",
    "lsb-release",
    "openssl",
    "python3",
    "python3-venv",
    "python3-pip",
    "ufw",
]
APT_DOCKER_PACKAGES = [
    "docker.io",
]
APT_COMPOSE_PACKAGES = [
    "docker-compose-plugin",
    "docker-compose",
]

UFW_RULES = [
    ["ufw", "allow", "80/tcp"],
    ["ufw", "allow", "443/tcp"],
    ["ufw", "allow", "22/tcp"],
]

CERTBOT_VENV_DIR = Path("/opt/certbot")
CERTBOT_BIN = CERTBOT_VENV_DIR / "bin" / "certbot"
CERTBOT_SYMLINK = Path("/usr/local/bin/certbot")
TRANSITHUB_RUNTIME_DIR = Path("/opt/transithub")
TRANSITHUB_RUNTIME_VENV_DIR = TRANSITHUB_RUNTIME_DIR / "venv"
TRANSITHUB_RUNTIME_PYTHON = TRANSITHUB_RUNTIME_VENV_DIR / "bin" / "python"
TRANSITHUB_RENEW_SCRIPT = Path("/usr/local/bin/transithub-certbot-renew")
TRANSITHUB_NGINX_STOP_SCRIPT = Path("/usr/local/bin/transithub-nginx-stop")
TRANSITHUB_NGINX_START_SCRIPT = Path("/usr/local/bin/transithub-nginx-start")
TRANSITHUB_NGINX_RELOAD_SCRIPT = Path("/usr/local/bin/transithub-nginx-reload")
TRANSITHUB_RENEW_SERVICE = Path("/etc/systemd/system/transithub-certbot-renew.service")
TRANSITHUB_RENEW_TIMER = Path("/etc/systemd/system/transithub-certbot-renew.timer")
TRANSITHUB_MENU_LAUNCHER = Path("/usr/local/bin/menu")
DOCKER_DAEMON_DIR = Path("/etc/docker")
DOCKER_DAEMON_CONFIG = DOCKER_DAEMON_DIR / "daemon.json"
TRANSITHUB_NETBIRD_SYSCTL = Path("/etc/sysctl.d/99-transithub-netbird.conf")


def log(message: str) -> None:
    print(f"  - {message}")


def run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode == 0:
        return
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr)
    raise subprocess.CalledProcessError(
        completed.returncode,
        command,
        output=completed.stdout,
        stderr=completed.stderr,
    )


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def command_works(command: list[str]) -> bool:
    try:
        return subprocess.run(command, capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def ensure_ufw_rules() -> None:
    log("Set ufw defaults")
    run(["ufw", "default", "deny", "incoming"])
    run(["ufw", "default", "allow", "outgoing"])
    log("Open required firewall ports: 22, 80, 443")
    for rule in UFW_RULES:
        run(rule)
    log("Enable ufw")
    run(["ufw", "--force", "enable"])


def ensure_docker_service() -> None:
    log("Enable and start docker service")
    run(["systemctl", "enable", "--now", "docker"])


def restart_docker_service() -> None:
    log("Restart docker service to apply daemon settings")
    run(["systemctl", "restart", "docker"])


def ufw_allows(port: str) -> bool:
    result = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=True)
    return port in result.stdout


def detect_default_network_interface() -> str:
    completed = subprocess.run(
        ["ip", "route", "show", "default"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            index = parts.index("dev")
            if index + 1 < len(parts):
                return parts[index + 1].strip()
    return ""


def docker_compose_available() -> bool:
    return command_works(["docker", "compose", "version"]) or command_works(["docker-compose", "version"])


def read_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return loaded


def collect_system_dns_servers() -> list[str]:
    candidates = [
        Path("/run/systemd/resolve/resolv.conf"),
        Path("/etc/resolv.conf"),
    ]
    servers: list[str] = []
    seen: set[str] = set()

    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("nameserver "):
                continue
            server = line.split(None, 1)[1].strip()
            if not server or server.startswith("127.") or server == "::1":
                continue
            if server not in seen:
                seen.add(server)
                servers.append(server)
    return servers


def ensure_docker_dns_config() -> bool:
    servers = collect_system_dns_servers()
    if not servers:
        log("Skip explicit Docker DNS setup: no upstream resolvers found")
        return False

    DOCKER_DAEMON_DIR.mkdir(parents=True, exist_ok=True)
    config = read_json_file(DOCKER_DAEMON_CONFIG)
    current_dns = config.get("dns")
    if current_dns == servers:
        return False

    config["dns"] = servers
    DOCKER_DAEMON_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log(f"Configure Docker daemon DNS: {', '.join(servers)}")
    return True


def certbot_available() -> bool:
    return CERTBOT_BIN.exists() and command_works([str(CERTBOT_BIN), "--version"])


def ensure_certbot() -> None:
    if not certbot_available():
        log("Install official Certbot in /opt/certbot")
        if CERTBOT_VENV_DIR.exists():
            shutil.rmtree(CERTBOT_VENV_DIR, ignore_errors=True)
        run(["python3", "-m", "venv", str(CERTBOT_VENV_DIR)])
        run([str(CERTBOT_VENV_DIR / "bin" / "pip"), "install", "--upgrade", "pip"])
        run([str(CERTBOT_VENV_DIR / "bin" / "pip"), "install", "certbot"])

    log("Ensure certbot command is available at /usr/local/bin/certbot")
    if CERTBOT_SYMLINK.exists() or CERTBOT_SYMLINK.is_symlink():
        CERTBOT_SYMLINK.unlink()
    CERTBOT_SYMLINK.symlink_to(CERTBOT_BIN)


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def nginx_container_filter_script(command: str) -> str:
    project_root = str(paths.PROJECT_ROOT)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"project_root={project_root!r}",
        "mapfile -t containers < <(docker ps -aq \\",
        "  --filter \"label=com.docker.compose.project.working_dir=${project_root}\" \\",
        "  --filter \"label=com.docker.compose.service=nginx\")",
        "if [[ ${#containers[@]} -eq 0 ]]; then",
        "  exit 0",
        "fi",
        "for container in \"${containers[@]}\"; do",
        f"  {command}",
        "done",
    ]
    return "\n".join(lines) + "\n"


def ensure_certbot_renewal() -> None:
    log("Install TransitHub certbot renewal hooks")
    write_executable(
        TRANSITHUB_NGINX_STOP_SCRIPT,
        nginx_container_filter_script("docker stop \"$container\" >/dev/null || true"),
    )
    write_executable(
        TRANSITHUB_NGINX_START_SCRIPT,
        nginx_container_filter_script("docker start \"$container\" >/dev/null || true"),
    )
    write_executable(
        TRANSITHUB_NGINX_RELOAD_SCRIPT,
        nginx_container_filter_script(
            "docker exec \"$container\" nginx -s reload >/dev/null 2>&1 || docker kill --signal=HUP \"$container\" >/dev/null 2>&1 || true"
        ),
    )
    write_executable(
        TRANSITHUB_RENEW_SCRIPT,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"certbot_bin={str(CERTBOT_BIN)!r}",
                f"pre_hook={str(TRANSITHUB_NGINX_STOP_SCRIPT)!r}",
                f"post_hook={str(TRANSITHUB_NGINX_START_SCRIPT)!r}",
                f"deploy_hook={str(TRANSITHUB_NGINX_RELOAD_SCRIPT)!r}",
                "\"$certbot_bin\" renew --quiet --standalone \\",
                "  --pre-hook \"$pre_hook\" \\",
                "  --post-hook \"$post_hook\" \\",
                "  --deploy-hook \"$deploy_hook\"",
            ]
        )
        + "\n",
    )
    TRANSITHUB_RENEW_SERVICE.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=TransitHub Let's Encrypt renewal",
                "Wants=network-online.target docker.service",
                "After=network-online.target docker.service",
                "",
                "[Service]",
                "Type=oneshot",
                f"ExecStart={TRANSITHUB_RENEW_SCRIPT}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    TRANSITHUB_RENEW_TIMER.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=Run TransitHub Let's Encrypt renewal twice daily",
                "",
                "[Timer]",
                "OnCalendar=*-*-* 03,15:00:00",
                "RandomizedDelaySec=30m",
                "Persistent=true",
                "",
                "[Install]",
                "WantedBy=timers.target",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", TRANSITHUB_RENEW_TIMER.name])


def ensure_netbird_host_ready() -> dict[str, str]:
    log("Enable IPv4 forwarding for NetBird routing and exit-node capability")
    TRANSITHUB_NETBIRD_SYSCTL.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
    run(["sysctl", "-p", str(TRANSITHUB_NETBIRD_SYSCTL)])

    log("Allow inbound traffic on NetBird interface wt0")
    run(["ufw", "allow", "in", "on", "wt0"])

    default_iface = detect_default_network_interface()
    if default_iface:
        log(f"Allow routed NetBird traffic from wt0 to {default_iface}")
        run(["ufw", "route", "allow", "in", "on", "wt0", "out", "on", default_iface])
    else:
        log("Skip routed wt0 firewall rule: default egress interface could not be detected")

    return {
        "netbird_sysctl": str(TRANSITHUB_NETBIRD_SYSCTL),
        "default_interface": default_iface,
    }


def ensure_menu_launcher() -> None:
    log("Install local runtime menu launcher at /usr/local/bin/menu")
    write_executable(
        TRANSITHUB_MENU_LAUNCHER,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"project_root={str(paths.PROJECT_ROOT)!r}",
                f"runtime_python={str(TRANSITHUB_RUNTIME_PYTHON)!r}",
                'if [[ ! -x "$runtime_python" ]]; then',
                '  printf "TransitHub runtime environment is missing: %s\\n" "$runtime_python" >&2',
                "  exit 1",
                "fi",
                'exec "$runtime_python" "${project_root}/transithub-menu.py" "$@"',
            ]
        )
        + "\n",
    )


def ensure_runtime_menu_venv() -> None:
    packages = ["bcrypt", "qrcode"]
    if not TRANSITHUB_RUNTIME_PYTHON.exists():
        log(f"Create TransitHub runtime venv in {TRANSITHUB_RUNTIME_VENV_DIR}")
        if TRANSITHUB_RUNTIME_VENV_DIR.exists():
            shutil.rmtree(TRANSITHUB_RUNTIME_VENV_DIR, ignore_errors=True)
        TRANSITHUB_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        run(["python3", "-m", "venv", str(TRANSITHUB_RUNTIME_VENV_DIR)])

    log("Install TransitHub runtime Python dependencies")
    run([str(TRANSITHUB_RUNTIME_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(TRANSITHUB_RUNTIME_PYTHON), "-m", "pip", "install", *packages])


def install_compose_support() -> bool:
    failures: list[tuple[str, str, str]] = []
    for package in APT_COMPOSE_PACKAGES:
        log(f"Try install Compose package: {package}")
        completed = subprocess.run(
            ["apt-get", "install", "-y", package],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and docker_compose_available():
            return True
        failures.append((package, completed.stdout, completed.stderr))

    for package, stdout, stderr in failures:
        if stdout:
            print(stdout)
        if stderr:
            print(f"[apt install failed: {package}]\n{stderr}")
    return docker_compose_available()


def prepare_host() -> dict[str, object]:
    log("Refresh apt package lists")
    run(["apt-get", "update"])

    log("Install base host packages")
    run(["apt-get", "install", "-y", *APT_BASE_PACKAGES])
    ensure_certbot()
    ensure_certbot_renewal()

    docker_installed = command_exists("docker")
    if not docker_installed:
        log("Install Docker Engine from Debian packages")
        run(["apt-get", "install", "-y", *APT_DOCKER_PACKAGES])
        docker_installed = command_exists("docker")

    compose_installed = False
    docker_dns_changed = False
    if docker_installed:
        docker_dns_changed = ensure_docker_dns_config()
        compose_installed = docker_compose_available()
        if not compose_installed:
            log("Install Docker Compose support")
            compose_installed = install_compose_support()
        ensure_docker_service()
        if docker_dns_changed:
            restart_docker_service()

    ensure_ufw_rules()

    result = {
        "python3": command_exists("python3"),
        "python3_venv": command_works(["python3", "-Im", "ensurepip", "--version"]),
        "certbot": certbot_available(),
        "certbot_timer": command_works(["systemctl", "is-enabled", TRANSITHUB_RENEW_TIMER.name]),
        "ufw": command_exists("ufw"),
        "ufw_80": ufw_allows("80/tcp"),
        "ufw_443": ufw_allows("443/tcp"),
        "ufw_22": ufw_allows("22/tcp"),
        "docker": docker_installed,
        "docker_compose": compose_installed,
        "docker_dns_configured": bool(docker_installed),
    }
    paths.HOST_PREPARE_STATUS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
