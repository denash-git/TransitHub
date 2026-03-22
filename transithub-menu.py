#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
INSTANCE_ENV_PATH = PROJECT_ROOT / "instance.env"
CORE_COMPOSE_FILES = [
    PROJECT_ROOT / "nginx" / "docker-compose.yml",
    PROJECT_ROOT / "xui" / "docker-compose.yml",
    PROJECT_ROOT / "subconverter" / "docker-compose.yml",
]
TGPROXY_COMPOSE_FILE = PROJECT_ROOT / "tgproxy" / "docker-compose.yml"
NETBIRD_COMPOSE_FILE = PROJECT_ROOT / "netbird" / "docker-compose.yml"
NETBIRD_SYSCTL_PATH = Path("/etc/sysctl.d/99-transithub-netbird.conf")


def main() -> int:
    require_root()
    if not INSTANCE_ENV_PATH.exists():
        print("instance.env was not found in the project root.")
        return 1

    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        draw_box(
            "TransitHub Local Menu",
            [
                "1. NetBird",
                "2. 3x-ui",
                "3. Services",
                "0. Exit",
            ],
        )
        choice = input("Select an option: ").strip()
        if choice == "1":
            netbird_menu(values)
        elif choice == "2":
            xui_menu(values)
        elif choice == "3":
            services_menu(values)
        elif choice == "0":
            return 0


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Run this menu as root.")
        raise SystemExit(1)


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rendered: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in raw_line:
            key = raw_line.split("=", 1)[0].strip()
            if key in remaining:
                rendered.append(f"{key}={remaining.pop(key)}")
                continue
        rendered.append(raw_line)

    if remaining:
        rendered.append("")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")

    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def compose_base_command() -> list[str]:
    if command_works(["docker", "compose", "version"]):
        return ["docker", "compose"]
    if command_works(["docker-compose", "version"]):
        return ["docker-compose"]
    raise RuntimeError("Docker Compose is not available.")


def compose_command(values: dict[str, str], always_include_netbird: bool = False) -> list[str]:
    command = [
        *compose_base_command(),
        "--project-directory",
        str(PROJECT_ROOT),
        "-p",
        values.get("INSTANCE_NAME", "").strip() or "xui-v1",
        "--env-file",
        "instance.env",
    ]
    for compose_file in CORE_COMPOSE_FILES:
        command.extend(["-f", str(compose_file)])
    if bool_env(values.get("ENABLE_TGPROXY")):
        command.extend(["-f", str(TGPROXY_COMPOSE_FILE)])
    if always_include_netbird or bool_env(values.get("ENABLE_NETBIRD")):
        command.extend(["-f", str(NETBIRD_COMPOSE_FILE)])
    return command


def run(command: list[str], interactive: bool = False) -> subprocess.CompletedProcess[str]:
    if interactive:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        return subprocess.CompletedProcess(command, completed.returncode, "", "")
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)


def command_works(command: list[str]) -> bool:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def service_container_id(values: dict[str, str], service: str, include_stopped: bool = True) -> str:
    command = [
        "docker",
        "ps",
        *(["-a", "-q"] if include_stopped else ["-q"]),
        "--filter",
        f"label=com.docker.compose.project={values.get('INSTANCE_NAME', '').strip() or 'xui-v1'}",
        "--filter",
        f"label=com.docker.compose.service={service}",
    ]
    completed = run(command)
    if completed.returncode != 0:
        return ""
    return next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")


def draw_box(title: str, lines: list[str]) -> None:
    width = max([len(title), *[len(line) for line in lines]]) + 4
    print()
    print("+" + "-" * width + "+")
    print(f"|  {title.ljust(width - 2)}|")
    print("+" + "-" * width + "+")
    for line in lines:
        print(f"|  {line.ljust(width - 2)}|")
    print("+" + "-" * width + "+")
    print()


def pause() -> None:
    input("Press Enter to continue...")


def netbird_menu(values: dict[str, str]) -> None:
    while True:
        enabled = bool_env(values.get("ENABLE_NETBIRD"))
        draw_box(
            "NetBird",
            [
                f"Enabled: {'yes' if enabled else 'no'}",
                f"Management URL: {values.get('NETBIRD_MANAGEMENT_URL', '') or '-'}",
                "1. Show status",
                "2. Show logs",
                "3. Reconfigure setup key / management URL",
                "4. Restart NetBird container",
                "5. Disable NetBird",
                "0. Back",
            ],
        )
        choice = input("Select an option: ").strip()
        if choice == "1":
            show_netbird_status(values)
        elif choice == "2":
            tail_service_logs(values, "netbird")
        elif choice == "3":
            reconfigure_netbird(values)
            values = parse_env(INSTANCE_ENV_PATH)
        elif choice == "4":
            restart_service(values, "netbird", always_include_netbird=True)
        elif choice == "5":
            disable_netbird(values)
            values = parse_env(INSTANCE_ENV_PATH)
        elif choice == "0":
            return


def show_netbird_status(values: dict[str, str]) -> None:
    container_id = service_container_id(values, "netbird", include_stopped=False)
    if not container_id:
        print("NetBird container is not running.")
        pause()
        return
    completed = run(["docker", "exec", container_id, "netbird", "status"])
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
    else:
        print(completed.stdout)
    pause()


def ensure_netbird_host_prerequisites() -> None:
    NETBIRD_SYSCTL_PATH.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
    run(["sysctl", "-p", str(NETBIRD_SYSCTL_PATH)])
    run(["ufw", "allow", "in", "on", "wt0"])
    default_iface = detect_default_interface()
    if default_iface:
        run(["ufw", "route", "allow", "in", "on", "wt0", "out", "on", default_iface])


def detect_default_interface() -> str:
    completed = run(["ip", "route", "show", "default"])
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            index = parts.index("dev")
            if index + 1 < len(parts):
                return parts[index + 1]
    return ""


def reconfigure_netbird(values: dict[str, str]) -> None:
    current_key = values.get("NETBIRD_SETUP_KEY", "").strip()
    current_url = values.get("NETBIRD_MANAGEMENT_URL", "").strip()
    print("Enter '-' as setup key to disable NetBird.")
    new_key = input(f"NetBird setup key [{current_key or 'disabled'}]: ").strip()
    if new_key == "-":
        disable_netbird(values)
        return
    new_url = input(f"NetBird management URL [{current_url or 'https://'}]: ").strip()

    effective_key = new_key or current_key
    effective_url = new_url or current_url
    if not effective_key or not effective_url or not effective_url.startswith("https://"):
        print("A setup key and a valid https:// management URL are required.")
        pause()
        return

    updates = {
        "NETBIRD_SETUP_KEY": effective_key,
        "NETBIRD_MANAGEMENT_URL": effective_url,
        "ENABLE_NETBIRD": "true",
    }
    if not values.get("NETBIRD_HOSTNAME", "").strip():
        instance_name = values.get("INSTANCE_NAME", "").strip() or "transithub"
        updates["NETBIRD_HOSTNAME"] = f"{instance_name}-netbird"
    update_env(INSTANCE_ENV_PATH, updates)
    ensure_netbird_host_prerequisites()
    refreshed = parse_env(INSTANCE_ENV_PATH)
    completed = run([*compose_command(refreshed, always_include_netbird=True), "up", "-d", "--force-recreate", "netbird"])
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
    else:
        print("NetBird configuration applied.")
    pause()


def disable_netbird(values: dict[str, str]) -> None:
    update_env(
        INSTANCE_ENV_PATH,
        {
            "NETBIRD_SETUP_KEY": "",
            "NETBIRD_MANAGEMENT_URL": "",
            "ENABLE_NETBIRD": "false",
        },
    )
    refreshed = parse_env(INSTANCE_ENV_PATH)
    completed = run([*compose_command(refreshed, always_include_netbird=True), "rm", "-f", "-s", "netbird"])
    if completed.returncode not in {0, 1}:
        print(completed.stdout)
        print(completed.stderr)
    print("NetBird has been disabled in instance.env.")
    pause()


def xui_menu(values: dict[str, str]) -> None:
    while True:
        draw_box(
            "3x-ui",
            [
                "1. Launch x-ui CLI menu",
                "2. Open x-ui shell",
                "3. Show x-ui container name",
                "0. Back",
            ],
        )
        choice = input("Select an option: ").strip()
        if choice == "1":
            launch_xui_cli(values)
        elif choice == "2":
            open_xui_shell(values)
        elif choice == "3":
            container_id = service_container_id(values, "xui", include_stopped=False)
            print(container_id or "xui container not found")
            pause()
        elif choice == "0":
            return


def launch_xui_cli(values: dict[str, str]) -> None:
    container_id = service_container_id(values, "xui", include_stopped=False)
    if not container_id:
        print("xui container is not running.")
        pause()
        return
    run(["docker", "exec", "-it", container_id, "/bin/sh", "-lc", "x-ui"], interactive=True)


def open_xui_shell(values: dict[str, str]) -> None:
    container_id = service_container_id(values, "xui", include_stopped=False)
    if not container_id:
        print("xui container is not running.")
        pause()
        return
    run(["docker", "exec", "-it", container_id, "/bin/sh"], interactive=True)


def services_menu(values: dict[str, str]) -> None:
    while True:
        draw_box(
            "Services",
            [
                "1. Show compose status",
                "2. Tail service logs",
                "3. Restart a service",
                "0. Back",
            ],
        )
        choice = input("Select an option: ").strip()
        if choice == "1":
            show_compose_status(values)
        elif choice == "2":
            service = input("Service name (nginx/xui/conv/tgproxy/netbird): ").strip()
            if service:
                tail_service_logs(values, service)
        elif choice == "3":
            service = input("Service name (nginx/xui/conv/tgproxy/netbird): ").strip()
            if service:
                restart_service(values, service, always_include_netbird=(service == "netbird"))
        elif choice == "0":
            return


def show_compose_status(values: dict[str, str]) -> None:
    completed = run([*compose_command(values, always_include_netbird=True), "ps"])
    print(completed.stdout or completed.stderr)
    pause()


def tail_service_logs(values: dict[str, str], service: str) -> None:
    container_id = service_container_id(values, service, include_stopped=False)
    if not container_id:
        print(f"{service} container is not running.")
        pause()
        return
    run(["docker", "logs", "--tail=80", "-f", container_id], interactive=True)


def restart_service(values: dict[str, str], service: str, always_include_netbird: bool = False) -> None:
    completed = run([*compose_command(values, always_include_netbird=always_include_netbird), "up", "-d", "--force-recreate", service])
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
    else:
        print(f"Service {service} has been recreated.")
    pause()


if __name__ == "__main__":
    raise SystemExit(main())
