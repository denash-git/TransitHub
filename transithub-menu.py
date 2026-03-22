#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import subprocess


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

BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
DIM = "\033[2m"
RESET = "\033[0m"


def main() -> int:
    require_root()
    if not INSTANCE_ENV_PATH.exists():
        print("instance.env was not found in the project root.")
        return 1

    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        clear_screen()
        render_main_menu(values)
        choice = prompt("Select an option")
        if choice == "1":
            netbird_menu()
        elif choice == "2":
            xui_menu()
        elif choice == "3":
            services_menu()
        elif choice == "0":
            clear_screen()
            return 0


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Run this menu as root.")
        raise SystemExit(1)


def clear_screen() -> None:
    print("\033c", end="")


def prompt(label: str) -> str:
    print()
    return input(f"{YELLOW}{label}:{RESET} ").strip()


def pause(message: str = "Press Enter to continue") -> None:
    print()
    input(f"{DIM}{message}{RESET}")


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


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


def command_works(command: list[str]) -> bool:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True).returncode == 0
    except OSError:
        return False


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


def service_container_name(values: dict[str, str], service: str, include_stopped: bool = True) -> str:
    command = [
        "docker",
        "ps",
        *(["-a"] if include_stopped else []),
        "--format",
        "{{.Names}}",
        "--filter",
        f"label=com.docker.compose.project={values.get('INSTANCE_NAME', '').strip() or 'xui-v1'}",
        "--filter",
        f"label=com.docker.compose.service={service}",
    ]
    completed = run(command)
    if completed.returncode != 0:
        return ""
    return next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")


def status_badge(ok: bool, text: str) -> str:
    color = GREEN if ok else RED
    return f"{color}{text}{RESET}"


def box(title: str, lines: list[str], accent: str = BLUE) -> None:
    width = max(len(title), *[len(strip_ansi(line)) for line in lines], 28)
    top = "┏" + "━" * (width + 2) + "┓"
    mid = "┣" + "━" * (width + 2) + "┫"
    bottom = "┗" + "━" * (width + 2) + "┛"
    print(f"{accent}{top}{RESET}")
    print(f"{accent}┃ {title.ljust(width)} ┃{RESET}")
    print(f"{accent}{mid}{RESET}")
    for line in lines:
        pad = width - len(strip_ansi(line))
        print(f"{accent}┃{RESET} {line}{' ' * pad} {accent}┃{RESET}")
    print(f"{accent}{bottom}{RESET}")


def strip_ansi(value: str) -> str:
    current = value
    for token in (BLUE, GREEN, YELLOW, RED, DIM, RESET):
        current = current.replace(token, "")
    return current


def print_block(title: str, lines: list[str], accent: str = BLUE) -> None:
    clear_screen()
    box(title, lines, accent=accent)
    print()


def render_main_menu(values: dict[str, str]) -> None:
    xui_running = bool(service_container_name(values, "xui", include_stopped=False))
    lines = [
        f"Project root : {PROJECT_ROOT}",
        f"x-ui         : {status_badge(xui_running, 'running' if xui_running else 'down')}",
        f"TG proxy     : {status_badge(bool_env(values.get('ENABLE_TGPROXY')), 'enabled' if bool_env(values.get('ENABLE_TGPROXY')) else 'disabled')}",
        f"NetBird      : {status_badge(bool_env(values.get('ENABLE_NETBIRD')), 'enabled' if bool_env(values.get('ENABLE_NETBIRD')) else 'disabled')}",
        "",
        "1. NetBird",
        "2. 3x-ui",
        "3. Services",
        "0. Exit",
    ]
    box("TransitHub Local Menu", lines, accent=BLUE)


def netbird_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        enabled = bool_env(values.get("ENABLE_NETBIRD"))
        lines = [
            f"Enabled        : {status_badge(enabled, 'yes' if enabled else 'no')}",
            f"Management URL : {values.get('NETBIRD_MANAGEMENT_URL', '') or '-'}",
            f"Hostname       : {values.get('NETBIRD_HOSTNAME', '') or '-'}",
            "",
            "1. Show NetBird status",
            "2. Show NetBird logs",
            "3. Reconfigure setup key / management URL",
            "4. Restart NetBird container",
            "5. Disable NetBird",
            "0. Back",
        ]
        print_block("NetBird", lines, accent=GREEN)
        choice = prompt("Select an option")
        if choice == "1":
            show_netbird_status(values)
        elif choice == "2":
            tail_service_logs(values, "netbird")
        elif choice == "3":
            reconfigure_netbird(values)
        elif choice == "4":
            restart_service(values, "netbird", always_include_netbird=True)
        elif choice == "5":
            disable_netbird(values)
        elif choice == "0":
            return


def show_netbird_status(values: dict[str, str]) -> None:
    container = service_container_name(values, "netbird", include_stopped=False)
    if not container:
        print_block("NetBird", ["NetBird container is not running."], accent=RED)
        pause()
        return
    completed = run(["docker", "exec", container, "netbird", "status"])
    output = (completed.stdout or completed.stderr or "No output").splitlines()
    print_block("NetBird Status", output[:40], accent=GREEN)
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
    clear_screen()
    current_key = values.get("NETBIRD_SETUP_KEY", "").strip()
    current_url = values.get("NETBIRD_MANAGEMENT_URL", "").strip()
    print(f"{YELLOW}Enter '-' as setup key to disable NetBird.{RESET}\n")
    new_key = input(f"NetBird setup key [{current_key or 'disabled'}]: ").strip()
    if new_key == "-":
        disable_netbird(values)
        return
    new_url = input(f"NetBird management URL [{current_url or 'https://'}]: ").strip()

    effective_key = new_key or current_key
    effective_url = new_url or current_url
    if not effective_key or not effective_url or not effective_url.startswith("https://"):
        print_block("NetBird", ["A setup key and a valid https:// management URL are required."], accent=RED)
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
        print_block("NetBird Reconfigure Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block("NetBird", ["NetBird configuration applied."], accent=GREEN)
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
        print_block("NetBird Disable Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block("NetBird", ["NetBird has been disabled in instance.env."], accent=GREEN)
    pause()


def xui_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        container = service_container_name(values, "xui", include_stopped=False)
        lines = [
            f"Container  : {container or 'not running'}",
            f"Panel URL  : https://{values.get('DOMAIN', '')}/{values.get('PANEL_PATH', '')}/" if values.get("DOMAIN") and values.get("PANEL_PATH") else "Panel URL  : -",
            "",
            "1. Show x-ui settings",
            "2. Change username / password",
            "3. Reset x-ui two-factor authentication",
            "4. Show x-ui logs",
            "5. Restart x-ui container",
            "6. Open x-ui shell",
            "7. Show x-ui container name",
            "0. Back",
        ]
        print_block("3x-ui", lines, accent=YELLOW)
        choice = prompt("Select an option")
        if choice == "1":
            show_xui_settings(values)
        elif choice == "2":
            change_xui_credentials(values)
        elif choice == "3":
            reset_xui_two_factor(values)
        elif choice == "4":
            tail_service_logs(values, "xui")
        elif choice == "5":
            restart_service(values, "xui")
        elif choice == "6":
            open_xui_shell(values)
        elif choice == "7":
            print_block("3x-ui Container", [container or "xui container not found"], accent=YELLOW)
            pause()
        elif choice == "0":
            return


def open_xui_shell(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    clear_screen()
    run(["docker", "exec", "-it", container, "/bin/sh"], interactive=True)


def show_xui_settings(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    completed = run(["docker", "exec", container, "/app/x-ui", "setting", "-show"])
    output = (completed.stdout or completed.stderr or "No output").splitlines()
    print_block("3x-ui Settings", output[:40], accent=YELLOW)
    pause()


def change_xui_credentials(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    clear_screen()
    print(f"{YELLOW}Leave a field empty to keep the current value.{RESET}\n")
    username = input("New username: ").strip()
    password = input("New password: ").strip()
    command = ["docker", "exec", container, "/app/x-ui", "setting"]
    if username:
        command.extend(["-username", username])
    if password:
        command.extend(["-password", password])
    if len(command) == 5:
        print_block("3x-ui", ["Nothing to change."], accent=RED)
        pause()
        return
    completed = run(command)
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block("3x-ui", ["Credentials updated successfully."], accent=GREEN)
    pause()


def reset_xui_two_factor(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    clear_screen()
    confirm = input("Reset x-ui two-factor authentication? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print_block("3x-ui", ["Two-factor reset cancelled."], accent=RED)
        pause()
        return
    completed = run(["docker", "exec", container, "/app/x-ui", "setting", "-resetTwoFactor"])
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block("3x-ui", ["Two-factor authentication settings were reset."], accent=GREEN)
    pause()


def require_xui_container(values: dict[str, str]) -> str:
    container = service_container_name(values, "xui", include_stopped=False)
    if not container:
        print_block("3x-ui", ["xui container is not running."], accent=RED)
        pause()
        return ""
    return container


def services_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        lines = [
            "1. Show compose status",
            "2. Tail service logs",
            "3. Restart a service",
            "0. Back",
        ]
        print_block("Services", lines, accent=BLUE)
        choice = prompt("Select an option")
        if choice == "1":
            show_compose_status(values)
        elif choice == "2":
            service = prompt("Service name (nginx/xui/conv/tgproxy/netbird)")
            if service:
                tail_service_logs(values, service)
        elif choice == "3":
            service = prompt("Service name (nginx/xui/conv/tgproxy/netbird)")
            if service:
                restart_service(values, service, always_include_netbird=(service == "netbird"))
        elif choice == "0":
            return


def show_compose_status(values: dict[str, str]) -> None:
    completed = run([*compose_command(values, always_include_netbird=True), "ps"])
    output = (completed.stdout or completed.stderr or "No output").splitlines()
    print_block("Compose Status", output, accent=BLUE)
    pause()


def tail_service_logs(values: dict[str, str], service: str) -> None:
    container = service_container_name(values, service, include_stopped=False)
    if not container:
        print_block("Logs", [f"{service} container is not running."], accent=RED)
        pause()
        return
    clear_screen()
    run(["docker", "logs", "--tail=80", "-f", container], interactive=True)


def restart_service(values: dict[str, str], service: str, always_include_netbird: bool = False) -> None:
    completed = run([*compose_command(values, always_include_netbird=always_include_netbird), "up", "-d", "--force-recreate", service])
    if completed.returncode != 0:
        lines = [line for line in [completed.stdout, completed.stderr] if line]
        print_block("Service Restart Failed", lines or ["Unknown error"], accent=RED)
    else:
        print_block("Services", [f"Service {service} has been recreated."], accent=GREEN)
    pause()


if __name__ == "__main__":
    raise SystemExit(main())
