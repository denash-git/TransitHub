#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import math
import os
import secrets
import shutil
import sqlite3
import string
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
CERTBOT_BIN = Path("/opt/certbot/bin/certbot")
RENEW_SCRIPT = Path("/usr/local/bin/transithub-certbot-renew")
NGINX_STOP_SCRIPT = Path("/usr/local/bin/transithub-nginx-stop")
NGINX_START_SCRIPT = Path("/usr/local/bin/transithub-nginx-start")
NGINX_RELOAD_SCRIPT = Path("/usr/local/bin/transithub-nginx-reload")
XUI_DB_PATH = PROJECT_ROOT / "xui" / "data" / "x-ui.db"

BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
DIM = "\033[2m"
RESET = "\033[0m"

MIN_HEADER_WIDTH = 55
MAX_HEADER_WIDTH = 78
INDENT = "      "
USERNAME_LENGTH = 10
PASSWORD_LENGTH = 20


def main() -> int:
    require_root()
    if not INSTANCE_ENV_PATH.exists():
        print("instance.env was not found in the project root.")
        return 1

    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        render_main_menu(values)
        choice = prompt("Select an option")
        if choice == "1":
            simple_service_menu(values, title="Nginx", service="nginx", accent=BLUE, enabled=True)
        elif choice == "2":
            xui_menu()
        elif choice == "3":
            simple_service_menu(
                values,
                title="Subconverter",
                service="conv",
                accent=BLUE,
                enabled=bool_env(values.get("ENABLE_SUBCONVERTER")),
            )
        elif choice == "4":
            simple_service_menu(
                values,
                title="TGProxy",
                service="tgproxy",
                accent=GREEN,
                enabled=bool_env(values.get("ENABLE_TGPROXY")),
            )
        elif choice == "5":
            netbird_menu()
        elif choice == "6":
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


def random_token(length: int, alphabet: str | None = None) -> str:
    chars = alphabet or (string.ascii_lowercase + string.digits)
    return "".join(secrets.choice(chars) for _ in range(length))


def random_username(length: int = USERNAME_LENGTH) -> str:
    return secrets.choice(string.ascii_lowercase) + random_token(length - 1)


def prompt_fixed_length_value(
    title: str,
    label: str,
    default: str,
    length: int,
    accent: str = YELLOW,
) -> str:
    error = ""
    while True:
        lines = [
            "Press Enter to accept the generated default value.",
            f"{label} must contain exactly {length} characters.",
            "",
        ]
        if error:
            lines.extend([f"{RED}{error}{RESET}", ""])
        print_block(title, lines, accent=accent)
        entered = input(f"{label} [{default}]: ").strip()
        if not entered:
            return default
        if len(entered) == length:
            return entered
        error = f"{label} must contain exactly {length} characters. Try again."


def credential_updated_lines(label: str, value: str) -> list[str]:
    emphasized = f"{GREEN}{value}{RESET}"
    return [
        f"{label} updated successfully.",
        "x-ui live credentials were updated from the panel database.",
        "instance.env was synchronized as a backup copy.",
        "",
        f"{label}:",
        emphasized,
        "",
        f"{YELLOW}Save this value now. Write it down before leaving this screen.{RESET}",
    ]


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


def strip_ansi(value: str) -> str:
    current = value
    for token in (BLUE, GREEN, YELLOW, RED, DIM, RESET):
        current = current.replace(token, "")
    return current


def header_width(title: str, lines: list[str]) -> int:
    terminal_width = shutil.get_terminal_size((90, 30)).columns
    content_width = max((len(strip_ansi(line)) + len(INDENT) for line in lines if line), default=0)
    target = max(MIN_HEADER_WIDTH, len(title) + 4, content_width + 2)
    return min(target, max(MIN_HEADER_WIDTH, min(MAX_HEADER_WIDTH, terminal_width - 2)))


def print_header(title: str, width: int, accent: str = BLUE) -> None:
    print(f"{accent}┏{'━' * width}┓{RESET}")
    print(f"{accent}┃{title.center(width)}┃{RESET}")
    print(f"{accent}┗{'━' * width}┛{RESET}")


def print_block(title: str, lines: list[str], accent: str = BLUE) -> None:
    clear_screen()
    print_header(title, header_width(title, lines), accent=accent)
    print()
    for line in lines:
        if line:
            print(f"{INDENT}{line}")
        else:
            print()
    print()


def service_state_line(values: dict[str, str], label: str, service: str, enabled_field: str | None = None) -> str:
    if enabled_field and not bool_env(values.get(enabled_field)):
        return f"{label:<13}: disabled"
    container = service_container_name(values, service, include_stopped=True)
    running = service_is_running(container)
    return f"{label:<13}: {status_badge(running, 'running' if running else 'stopped')}"


def xui_db_state() -> dict[str, str]:
    state = {
        "username": "-",
        "webPort": "-",
        "webBasePath": "-",
        "timeLocation": "-",
        "db_path": str(XUI_DB_PATH),
    }
    if not XUI_DB_PATH.exists():
        return state

    conn = sqlite3.connect(XUI_DB_PATH)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT username FROM users ORDER BY id LIMIT 1").fetchone()
        if row and row[0]:
            state["username"] = str(row[0])
        for key, value in cur.execute("SELECT key, value FROM settings").fetchall():
            if key in state and value:
                state[key] = str(value)
    finally:
        conn.close()
    return state


def render_main_menu(values: dict[str, str]) -> None:
    lines = [
        service_state_line(values, "nginx", "nginx"),
        service_state_line(values, "3x-ui", "xui"),
        service_state_line(values, "subconverter", "conv", enabled_field="ENABLE_SUBCONVERTER"),
        service_state_line(values, "tgproxy", "tgproxy", enabled_field="ENABLE_TGPROXY"),
        service_state_line(values, "netbird", "netbird", enabled_field="ENABLE_NETBIRD"),
        "",
        "1. Nginx",
        "2. 3x-ui",
        "3. Subconverter",
        "4. TGProxy",
        "5. NetBird",
        "6. Services",
        "0. Exit",
    ]
    print_block("TransitHub Local Menu", lines, accent=BLUE)


def netbird_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        enabled = bool_env(values.get("ENABLE_NETBIRD"))
        container = service_container_name(values, "netbird", include_stopped=True)
        if not enabled:
            status = "disabled"
        else:
            status = status_badge(service_is_running(container), "running" if service_is_running(container) else "stopped")
        lines = [
            f"Container        : {container or 'not running'}",
            f"Status           : {status}",
            f"Management URL   : {values.get('NETBIRD_MANAGEMENT_URL', '') or '-'}",
            f"Hostname         : {values.get('NETBIRD_HOSTNAME', '') or '-'}",
            "",
            "1. Show NetBird status",
            "2. Show NetBird logs",
            "3. Reconfigure setup key / management URL",
            "4. Start NetBird",
            "5. Stop NetBird",
            "6. Restart NetBird",
            "7. Disable NetBird",
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
            service_start(values, "netbird", "NetBird")
        elif choice == "5":
            service_stop(values, "netbird", "NetBird")
        elif choice == "6":
            service_restart(values, "netbird", "NetBird")
        elif choice == "7":
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
        db_state = xui_db_state()
        container = service_container_name(values, "xui", include_stopped=True)
        running = service_is_running(container)
        lines = [
            f"Container        : {container or 'not running'}",
            f"Status           : {status_badge(running, 'running' if running else 'stopped')}",
            f"Panel URL        : {panel_url(values, db_state)}",
            "",
            "1. Show stored settings",
            "2. Change username",
            "3. Change password",
            "4. Show x-ui logs",
            "5. Start x-ui",
            "6. Stop x-ui",
            "7. Restart x-ui",
            "8. Open x-ui shell",
            "0. Back",
        ]
        print_block("3x-ui", lines, accent=YELLOW)
        choice = prompt("Select an option")
        if choice == "1":
            show_xui_settings(values)
        elif choice == "2":
            change_xui_username(values)
        elif choice == "3":
            change_xui_password(values)
        elif choice == "4":
            tail_service_logs(values, "xui")
        elif choice == "5":
            service_start(values, "xui", "x-ui")
        elif choice == "6":
            service_stop(values, "xui", "x-ui")
        elif choice == "7":
            service_restart(values, "xui", "x-ui")
        elif choice == "8":
            open_xui_shell(values)
        elif choice == "0":
            return


def panel_url(values: dict[str, str], db_state: dict[str, str] | None = None) -> str:
    domain = values.get("DOMAIN", "").strip()
    source = db_state or xui_db_state()
    panel_path = source.get("webBasePath", "").strip("/")
    if not domain or not panel_path:
        return "-"
    return f"https://{domain}/{panel_path}/"


def show_xui_settings(values: dict[str, str]) -> None:
    db_state = xui_db_state()
    container = service_container_name(values, "xui", include_stopped=True)
    running = service_is_running(container)
    lines = [
        f"Container name   : {container or 'not running'}",
        f"Container status : {status_badge(running, 'running' if running else 'stopped')}",
        f"Panel URL        : {panel_url(values, db_state)}",
        f"Main domain      : {values.get('DOMAIN', '') or '-'}",
        f"Panel path       : {db_state.get('webBasePath', '-')}",
        f"Panel port       : {db_state.get('webPort', '-')}",
        f"Current username : {db_state.get('username', '-')}",
        f"DB path          : {db_state.get('db_path', '-')}",
    ]
    print_block("3x-ui Stored Settings", lines, accent=YELLOW)
    pause()


def change_xui_username(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    suggested = random_username(USERNAME_LENGTH)
    new_username = prompt_fixed_length_value(
        "3x-ui Username",
        "New username",
        suggested,
        USERNAME_LENGTH,
        accent=YELLOW,
    )
    completed = run(["docker", "exec", container, "/app/x-ui", "setting", "-username", new_username])
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        update_env(INSTANCE_ENV_PATH, {"CONFIG_USERNAME": new_username})
        print_block("3x-ui Username", credential_updated_lines("Username", new_username), accent=GREEN)
    pause()


def change_xui_password(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    suggested = random_token(PASSWORD_LENGTH)
    new_password = prompt_fixed_length_value(
        "3x-ui Password",
        "New password",
        suggested,
        PASSWORD_LENGTH,
        accent=YELLOW,
    )
    completed = run(["docker", "exec", container, "/app/x-ui", "setting", "-password", new_password])
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        update_env(INSTANCE_ENV_PATH, {"CONFIG_PASSWORD": new_password})
        print_block("3x-ui Password", credential_updated_lines("Password", new_password), accent=GREEN)
    pause()


def open_xui_shell(values: dict[str, str]) -> None:
    container = require_xui_container(values)
    if not container:
        return
    clear_screen()
    run(["docker", "exec", "-it", container, "/bin/sh"], interactive=True)


def require_xui_container(values: dict[str, str]) -> str:
    container = service_container_name(values, "xui", include_stopped=True)
    if not container:
        print_block("3x-ui", ["xui container is not running."], accent=RED)
        pause()
        return ""
    return container


def service_is_running(container_name: str) -> bool:
    if not container_name:
        return False
    completed = run(["docker", "inspect", "-f", "{{.State.Running}}", container_name])
    return completed.returncode == 0 and completed.stdout.strip().lower() == "true"


def service_start(values: dict[str, str], service: str, label: str) -> None:
    container = service_container_name(values, service, include_stopped=True)
    if not container:
        print_block(label, [f"{label} container is not available."], accent=RED)
        pause()
        return
    completed = run(["docker", "start", container])
    if completed.returncode != 0:
        print_block(f"{label} Start Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block(label, [f"{label} started successfully."], accent=GREEN)
    pause()


def service_stop(values: dict[str, str], service: str, label: str) -> None:
    container = service_container_name(values, service, include_stopped=True)
    if not container:
        print_block(label, [f"{label} container is not available."], accent=RED)
        pause()
        return
    completed = run(["docker", "stop", container])
    if completed.returncode != 0:
        print_block(f"{label} Stop Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block(label, [f"{label} stopped successfully."], accent=GREEN)
    pause()


def service_restart(values: dict[str, str], service: str, label: str) -> None:
    container = service_container_name(values, service, include_stopped=True)
    if not container:
        print_block(label, [f"{label} container is not available."], accent=RED)
        pause()
        return
    completed = run(["docker", "restart", container])
    if completed.returncode != 0:
        print_block(f"{label} Restart Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block(label, [f"{label} restarted successfully."], accent=GREEN)
    pause()


def simple_service_menu(values: dict[str, str], title: str, service: str, accent: str, enabled: bool) -> None:
    while True:
        current_values = parse_env(INSTANCE_ENV_PATH)
        container = service_container_name(current_values, service, include_stopped=True)
        if not enabled:
            status = "disabled"
        else:
            running = service_is_running(container)
            status = status_badge(running, "running" if running else "stopped")
        lines = [
            f"Container        : {container or 'not available'}",
            f"Status           : {status}",
            "",
            "1. Show logs",
            "2. Start",
            "3. Stop",
            "4. Restart",
            "0. Back",
        ]
        print_block(title, lines, accent=accent)
        choice = prompt("Select an option")
        if choice == "1":
            tail_service_logs(current_values, service)
        elif choice == "2":
            service_start(current_values, service, title)
        elif choice == "3":
            service_stop(current_values, service, title)
        elif choice == "4":
            service_restart(current_values, service, title)
        elif choice == "0":
            return


def services_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        lines = [
            "1. Show compose status",
            "2. Show service logs",
            "3. TLS certificate",
            "4. Time settings",
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
            certificate_menu(values)
        elif choice == "4":
            time_menu(values)
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
        print_block("Service Recreate Failed", lines or ["Unknown error"], accent=RED)
    else:
        print_block("Services", [f"Service {service} has been recreated."], accent=GREEN)
    pause()


def certificate_menu(values: dict[str, str]) -> None:
    while True:
        cert = certificate_status(values)
        lines = [
            f"Mode            : {'staging' if cert['staging'] else 'production'}",
            f"Domains         : {', '.join(certificate_domains(values))}",
            f"Cert dir        : {cert['cert_dir']}",
            f"Expires at      : {cert['expires_at']}",
            f"Days remaining  : {cert['days_remaining']}",
            "",
            "1. Run renew now",
            "2. Force reissue certificate",
            "0. Back",
        ]
        print_block("TLS Certificate", lines, accent=BLUE)
        choice = prompt("Select an option")
        if choice == "1":
            run_certificate_renew_now()
        elif choice == "2":
            force_reissue_certificate(values)
        elif choice == "0":
            return


def certificate_domains(values: dict[str, str]) -> list[str]:
    domains = [values.get("DOMAIN", "").strip()]
    tgproxy_host = values.get("TGPROXY_PUBLIC_HOST", "").strip()
    if bool_env(values.get("ENABLE_TGPROXY")) and tgproxy_host and tgproxy_host not in domains:
        domains.append(tgproxy_host)
    return [domain for domain in domains if domain]


def certificate_status(values: dict[str, str]) -> dict[str, object]:
    cert_dir = values.get("CERT_LIVE_DIR", "").strip() or "-"
    fullchain = Path(cert_dir) / "fullchain.pem" if cert_dir != "-" else Path("")
    result: dict[str, object] = {
        "staging": bool_env(values.get("CERTBOT_STAGING")),
        "cert_dir": cert_dir,
        "expires_at": "-",
        "days_remaining": "-",
        "summary": "missing",
    }
    if not fullchain.exists():
        return result
    completed = run(["openssl", "x509", "-in", str(fullchain), "-noout", "-enddate"])
    if completed.returncode != 0:
        result["summary"] = "present, expiry unreadable"
        return result
    line = completed.stdout.strip()
    if not line.startswith("notAfter="):
        result["summary"] = "present, expiry unreadable"
        return result
    try:
        expires_at = parsedate_to_datetime(line.split("=", 1)[1].strip())
    except (TypeError, ValueError):
        result["summary"] = "present, expiry unreadable"
        return result
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    expires_at = expires_at.astimezone(timezone.utc)
    remaining = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
    days_remaining = math.ceil(remaining / 86400) if remaining else 0
    result["expires_at"] = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    result["days_remaining"] = str(days_remaining)
    result["summary"] = f"{days_remaining} day(s) left"
    return result


def run_certificate_renew_now() -> None:
    if not RENEW_SCRIPT.exists():
        print_block("TLS Certificate", [f"Renew script was not found: {RENEW_SCRIPT}"], accent=RED)
        pause()
        return
    completed = run([str(RENEW_SCRIPT)])
    lines = [line for line in [completed.stdout, completed.stderr] if line]
    title = "TLS Renew Failed" if completed.returncode != 0 else "TLS Renew"
    accent = RED if completed.returncode != 0 else GREEN
    if completed.returncode == 0:
        lines.insert(0, "Manual renew attempt completed.")
        lines.insert(1, "This does not force a new certificate if renewal is not yet due.")
    print_block(title, lines or ["No output"], accent=accent)
    pause()


def force_reissue_certificate(values: dict[str, str]) -> None:
    clear_screen()
    print(f"{RED}Force reissue requests a brand new certificate and may hit Let's Encrypt rate limits.{RESET}\n")
    confirm = input("Continue with force reissue? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print_block("TLS Certificate", ["Force reissue cancelled."], accent=RED)
        pause()
        return

    certbot_bin = str(CERTBOT_BIN) if CERTBOT_BIN.exists() else "certbot"
    domains = certificate_domains(values)
    if not domains:
        print_block("TLS Certificate", ["No domains are configured for certificate issuance."], accent=RED)
        pause()
        return

    cert_name = values.get("DOMAIN", "").strip()
    if bool_env(values.get("CERTBOT_STAGING")):
        cert_name = f"{cert_name}-staging"

    command = [
        certbot_bin,
        "certonly",
        "--standalone",
        "--non-interactive",
        "--agree-tos",
        "--force-renewal",
        "--cert-name",
        cert_name,
        "--pre-hook",
        str(NGINX_STOP_SCRIPT),
        "--post-hook",
        str(NGINX_START_SCRIPT),
        "--deploy-hook",
        str(NGINX_RELOAD_SCRIPT),
    ]
    for domain in domains:
        command.extend(["-d", domain])
    if bool_env(values.get("CERTBOT_STAGING")):
        command.append("--staging")
    email = values.get("CERTBOT_EMAIL", "").strip()
    if email:
        command.extend(["-m", email])
    else:
        command.append("--register-unsafely-without-email")

    completed = run(command)
    lines = [line for line in [completed.stdout, completed.stderr] if line]
    title = "Force Reissue Failed" if completed.returncode != 0 else "TLS Certificate"
    accent = RED if completed.returncode != 0 else GREEN
    if completed.returncode == 0:
        lines.insert(0, "Certificate force reissue completed.")
    print_block(title, lines or ["No output"], accent=accent)
    pause()


def time_menu(values: dict[str, str]) -> None:
    while True:
        lines = [
            "1. Show time status",
            "2. Show timezone examples",
            "3. Change timezone",
            "0. Back",
        ]
        print_block("Time Settings", lines, accent=BLUE)
        choice = prompt("Select an option")
        if choice == "1":
            show_time_status(values)
        elif choice == "2":
            show_timezone_examples(values)
        elif choice == "3":
            change_timezone(values)
        elif choice == "0":
            return


def timedatectl_show(fields: list[str]) -> dict[str, str]:
    if not command_works(["timedatectl", "--version"]):
        return {}
    command = ["timedatectl", "show"]
    for field in fields:
        command.extend(["-p", field])
    completed = run(command)
    if completed.returncode != 0:
        return {}
    result: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def time_status(values: dict[str, str] | None = None) -> dict[str, str]:
    timed = timedatectl_show(["Timezone", "NTPSynchronized", "NTP"])
    local_time = run(["date"]).stdout.strip() or "-"
    timezone_name = timed.get("Timezone", (values or {}).get("TZ", "-"))
    ntp_sync = timed.get("NTPSynchronized", "")
    ntp_enabled = timed.get("NTP", "")
    if ntp_sync.lower() == "yes":
        sync = "synchronized"
    elif ntp_sync.lower() == "no":
        sync = "not synchronized"
    elif ntp_enabled.lower() == "yes":
        sync = "enabled, state unknown"
    else:
        sync = "unknown"
    return {
        "timezone": timezone_name or "-",
        "local_time": local_time,
        "sync": sync,
    }


def show_time_status(values: dict[str, str]) -> None:
    state = time_status(values)
    sync_ok = state["sync"] == "synchronized"
    lines = [
        f"Host timezone   : {state['timezone']}",
        f"Host local time : {state['local_time']}",
        f"Time sync       : {status_badge(sync_ok, state['sync']) if state['sync'] != 'unknown' else state['sync']}",
        f"TransitHub TZ   : {values.get('TZ', '') or '-'}",
    ]
    print_block("Time Status", lines, accent=BLUE)
    pause()


def timezone_examples() -> list[str]:
    return [
        "Use canonical format: Region/City",
        "",
        "Examples:",
        "UTC",
        "Europe/Moscow",
        "Europe/Berlin",
        "America/New_York",
        "Asia/Almaty",
        "",
        "Full list on host:",
        "timedatectl list-timezones",
    ]


def show_timezone_examples(values: dict[str, str]) -> None:
    lines = [
        f"Current host TZ : {time_status(values)['timezone']}",
        f"TransitHub TZ   : {values.get('TZ', '') or '-'}",
        "",
        *timezone_examples(),
    ]
    print_block("Timezone Examples", lines, accent=BLUE)
    pause()


def change_timezone(values: dict[str, str]) -> None:
    clear_screen()
    current = values.get("TZ", "").strip()
    print("Use canonical format: Region/City")
    print("Examples: UTC, Europe/Moscow, America/New_York, Asia/Almaty")
    print("Full list: timedatectl list-timezones")
    print()
    new_timezone = input(f"New timezone [{current or 'Europe/Moscow'}]: ").strip()
    if not new_timezone:
        print_block("Time Settings", ["Timezone was not changed."], accent=RED)
        pause()
        return
    if command_works(["timedatectl", "--version"]):
        completed = run(["timedatectl", "set-timezone", new_timezone])
        if completed.returncode != 0:
            lines = [line for line in [completed.stdout, completed.stderr] if line]
            lines.extend(["", *timezone_examples()])
            print_block("Time Settings Failed", lines, accent=RED)
            pause()
            return
    update_env(INSTANCE_ENV_PATH, {"TZ": new_timezone})
    print_block(
        "Time Settings",
        [
            "Timezone updated in host configuration and instance.env.",
            "Running containers keep the old timezone until they are recreated.",
        ],
        accent=GREEN,
    )
    pause()


if __name__ == "__main__":
    raise SystemExit(main())
