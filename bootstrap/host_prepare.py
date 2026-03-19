from __future__ import annotations

import json
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
    "certbot",
    "ufw",
]
APT_DOCKER_PACKAGES = [
    "docker.io",
]
APT_COMPOSE_PACKAGES = [
    "docker-compose-plugin",
]

UFW_RULES = [
    ["ufw", "allow", "80/tcp"],
    ["ufw", "allow", "443/tcp"],
    ["ufw", "limit", "22/tcp"],
]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def ensure_ufw_rules() -> None:
    subprocess.run(["ufw", "default", "deny", "incoming"], check=True)
    subprocess.run(["ufw", "default", "allow", "outgoing"], check=True)
    for rule in UFW_RULES:
        subprocess.run(rule, check=True)
    subprocess.run(["ufw", "--force", "enable"], check=True)


def ensure_docker_service() -> None:
    subprocess.run(["systemctl", "enable", "--now", "docker"], check=True)


def ufw_allows(port: str) -> bool:
    result = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=True)
    return port in result.stdout


def prepare_host() -> dict[str, object]:
    run(["apt-get", "update"])
    run(["apt-get", "install", "-y", *APT_BASE_PACKAGES])
    docker_installed = command_exists("docker")
    if not docker_installed:
        run(["apt-get", "install", "-y", *APT_DOCKER_PACKAGES])
        docker_installed = command_exists("docker")

    compose_installed = False
    if docker_installed:
        compose_installed = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
        ).returncode == 0
        if not compose_installed:
            run(["apt-get", "install", "-y", *APT_COMPOSE_PACKAGES])
            compose_installed = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
            ).returncode == 0
        ensure_docker_service()

    ensure_ufw_rules()

    result = {
        "python3": command_exists("python3"),
        "python3_venv": command_exists("python3"),
        "certbot": command_exists("certbot"),
        "ufw": command_exists("ufw"),
        "ufw_80": ufw_allows("80/tcp"),
        "ufw_443": ufw_allows("443/tcp"),
        "ufw_22": ufw_allows("22/tcp"),
        "docker": docker_installed,
        "docker_compose": compose_installed,
    }
    paths.HOST_PREPARE_STATUS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
