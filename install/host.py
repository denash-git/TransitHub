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
DOCKER_DAEMON_DIR = Path("/etc/docker")
DOCKER_DAEMON_CONFIG = DOCKER_DAEMON_DIR / "daemon.json"


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
