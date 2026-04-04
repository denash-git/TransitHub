#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import base64
from pathlib import Path
import math
import os
import re
import secrets
import shutil
import sqlite3
import string
import subprocess
import sys
import time
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from transithub_runtime.env import parse_env as shared_parse_env, update_env as shared_update_env
from transithub_runtime.backup import (
    BACKUP_DIR as RUNTIME_BACKUP_DIR,
    RESTORE_INBOX_DIR as RUNTIME_RESTORE_INBOX_DIR,
    BackupError,
    backup_bundle as runtime_backup_bundle,
    latest_restore_bundle as runtime_latest_restore_bundle,
    restore_bundle as runtime_restore_bundle,
    verify_bundle as runtime_verify_bundle,
)
from transithub_runtime.tgproxy import (
    build_secret as shared_build_tgproxy_secret,
    enabled as shared_tgproxy_enabled,
    faketls_domain as shared_tgproxy_faketls_domain,
    public_host as shared_tgproxy_public_host,
    split_secret as shared_split_tgproxy_secret,
)
from transithub_runtime.xui_db import (
    update_xui_db_credentials as shared_update_xui_db_credentials,
    upsert_xui_setting as shared_upsert_xui_setting,
    xui_user_record as shared_xui_user_record,
)

try:
    import qrcode
except ModuleNotFoundError:
    qrcode = None


PROJECT_ROOT = Path(__file__).resolve().parent
INSTANCE_ENV_PATH = PROJECT_ROOT / "instance.env"
CORE_COMPOSE_FILES = [
    PROJECT_ROOT / "nginx" / "docker-compose.yml",
    PROJECT_ROOT / "xui" / "docker-compose.yml",
    PROJECT_ROOT / "subconverter" / "docker-compose.yml",
]
TGPROXY_COMPOSE_FILE = PROJECT_ROOT / "tgproxy" / "docker-compose.yml"
NETBIRD_COMPOSE_FILE = PROJECT_ROOT / "netbird" / "docker-compose.yml"
DIAGNOSTICS_COMPOSE_FILE = PROJECT_ROOT / "diagnostics" / "docker-compose.yml"
NETBIRD_SYSCTL_PATH = Path("/etc/sysctl.d/99-transithub-netbird.conf")
CERTBOT_BIN = Path("/opt/certbot/bin/certbot")
RENEW_SCRIPT = Path("/usr/local/bin/transithub-certbot-renew")
NGINX_STOP_SCRIPT = Path("/usr/local/bin/transithub-nginx-stop")
NGINX_START_SCRIPT = Path("/usr/local/bin/transithub-nginx-start")
NGINX_RELOAD_SCRIPT = Path("/usr/local/bin/transithub-nginx-reload")
SPEEDTEST_BIN = Path("/usr/local/bin/speedtest")
XUI_DB_PATH = PROJECT_ROOT / "xui" / "data" / "x-ui.db"
NGINX_SITE_CONF_PATH = PROJECT_ROOT / "nginx" / "config" / "site.conf"

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
PANEL_PATH_LENGTH = 16
TGPROXY_CODE_LENGTH = 32
DIAG_PATH_LENGTH = 24


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
            tgproxy_menu()
        elif choice == "5":
            netbird_menu()
        elif choice == "6":
            services_menu()
        elif choice == "7":
            diagnostics_menu()
        elif choice == "0":
            clear_screen()
            return 0


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Run this menu as root.")
        raise SystemExit(1)


def clear_screen() -> None:
    print("\033c", end="")


def read_input(prompt_text: str) -> str:
    try:
        return input(prompt_text)
    except EOFError:
        print()
        print("Input stream is not interactive. Run `menu` in a TTY session.")
        raise SystemExit(0)


def prompt(label: str) -> str:
    print()
    choice = read_input(f"{YELLOW}{label}:{RESET} ").strip()
    if choice == "00":
        clear_screen()
        raise SystemExit(0)
    return choice


def pause(message: str = "Press Enter to continue") -> None:
    print()
    read_input(f"{DIM}{message}{RESET}")


def copy_to_clipboard(value: str) -> bool:
    if not value or not sys.stdout.isatty():
        return False
    payload = base64.b64encode(value.encode("utf-8")).decode("ascii")
    print(f"\033]52;c;{payload}\a", end="", flush=True)
    return True


def clipboard_notice_lines(label: str, value: str) -> list[str]:
    if copy_to_clipboard(value):
        return [
            f"{YELLOW}Clipboard copy was requested for {label}.{RESET}",
            f"{YELLOW}If your terminal supports OSC52 over SSH, this value should now be in your clipboard.{RESET}",
        ]
    return [f"{YELLOW}Clipboard copy is not available here. Save this value now.{RESET}"]


def danger_menu_option(label: str) -> str:
    return f"{RED}0. {label}{RESET}"


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_env(path: Path) -> dict[str, str]:
    return shared_parse_env(path)


def update_env(path: Path, updates: dict[str, str]) -> None:
    shared_update_env(path, updates)


def random_token(length: int, alphabet: str | None = None) -> str:
    chars = alphabet or (string.ascii_lowercase + string.digits)
    return "".join(secrets.choice(chars) for _ in range(length))


def random_username(length: int = USERNAME_LENGTH) -> str:
    return secrets.choice(string.ascii_lowercase) + random_token(length - 1)


def random_panel_path(length: int = PANEL_PATH_LENGTH) -> str:
    return random_token(length)


def random_hex_token(length: int) -> str:
    return random_token(length, "0123456789abcdef")


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
        entered = read_input(f"{label} [{default}]: ").strip()
        if not entered:
            return default
        if len(entered) == length:
            return entered
        error = f"{label} must contain exactly {length} characters. Try again."


def prompt_panel_path_value(current: str) -> str:
    default = random_panel_path(max(len(current), PANEL_PATH_LENGTH))
    error = ""
    while True:
        lines = [
            "Press Enter to accept the generated default value.",
            "Panel path must contain only lowercase letters and digits.",
            f"Required length: {len(default)} characters.",
            "",
        ]
        if error:
            lines.extend([f"{RED}{error}{RESET}", ""])
        print_block("3x-ui Panel Path", lines, accent=YELLOW)
        entered = read_input(f"New panel path [{default}]: ").strip()
        if not entered:
            return default
        if len(entered) != len(default):
            error = f"Panel path must contain exactly {len(default)} characters."
            continue
        if any(ch not in (string.ascii_lowercase + string.digits) for ch in entered):
            error = "Panel path can use only lowercase letters and digits."
            continue
        return entered


def prompt_tgproxy_access_code(current_code: str) -> str:
    default = random_hex_token(TGPROXY_CODE_LENGTH)
    error = ""
    while True:
        lines = [
            "Press Enter to accept the generated default value.",
            f"Current code     : {current_code}",
            f"Required format  : {TGPROXY_CODE_LENGTH} lowercase hexadecimal characters.",
            "",
        ]
        if error:
            lines.extend([f"{RED}{error}{RESET}", ""])
        print_block("TGProxy Access Code", lines, accent=GREEN)
        entered = read_input(f"New access code [{default}]: ").strip().lower()
        if not entered:
            return default
        if len(entered) != TGPROXY_CODE_LENGTH:
            error = f"Access code must contain exactly {TGPROXY_CODE_LENGTH} characters."
            continue
        if any(ch not in "0123456789abcdef" for ch in entered):
            error = "Access code can use only lowercase hexadecimal characters."
            continue
        return entered


def prompt_diag_path_value(current: str) -> str:
    default = random_token(max(len(current), DIAG_PATH_LENGTH))
    error = ""
    while True:
        lines = [
            "Press Enter to accept the generated default value.",
            "Diagnostics path must contain only lowercase letters and digits.",
            f"Required length: {len(default)} characters.",
            "",
        ]
        if error:
            lines.extend([f"{RED}{error}{RESET}", ""])
        print_block("Diagnostics Route Prefix", lines, accent=YELLOW)
        entered = read_input(f"New diagnostics path [{default}]: ").strip()
        if not entered:
            return default
        if len(entered) != len(default):
            error = f"Diagnostics path must contain exactly {len(default)} characters."
            continue
        if any(ch not in (string.ascii_lowercase + string.digits) for ch in entered):
            error = "Diagnostics path can use only lowercase letters and digits."
            continue
        return entered


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
        *clipboard_notice_lines(label, value),
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
    command.extend(["-f", str(DIAGNOSTICS_COMPOSE_FILE)])
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


def print_qr_block(title: str, link: str, accent: str = GREEN, prefix_lines: list[str] | None = None) -> None:
    if qrcode is None:
        raise RuntimeError("The qrcode runtime dependency is not installed.")
    matrix = qr_matrix(link, border=1)
    qr_lines = render_qr_halfblock_lines(matrix)

    intro_lines = prefix_lines or []
    width = header_width(title, [*intro_lines, link, "Scan this QR code in Telegram."])
    clear_screen()
    print_header(title, width, accent=accent)
    print()
    for line in intro_lines:
        if line:
            print(f"{INDENT}{line}")
        else:
            print()
    print(f"{INDENT}{link}")
    print()
    for rendered in qr_lines:
        print(f"{INDENT}{rendered}")
    print()
    print(f"{INDENT}Scan this QR code in Telegram or copy the TG Proxy URL above.")
    print()


def qr_matrix(link: str, border: int) -> list[list[bool]]:
    if qrcode is None:
        raise RuntimeError("The qrcode runtime dependency is not installed.")
    qr = qrcode.QRCode(border=border)
    qr.add_data(link)
    qr.make(fit=True)
    return qr.get_matrix()


def render_qr_halfblock_lines(matrix: list[list[bool]]) -> list[str]:
    if not matrix:
        return []
    lines: list[str] = []
    for index in range(0, len(matrix), 2):
        top = matrix[index]
        bottom = matrix[index + 1] if index + 1 < len(matrix) else [False] * len(top)
        rendered_parts: list[str] = []
        for top_cell, bottom_cell in zip(top, bottom):
            if top_cell and bottom_cell:
                rendered_parts.append("\u2588")
            elif top_cell and not bottom_cell:
                rendered_parts.append("\u2580")
            elif not top_cell and bottom_cell:
                rendered_parts.append("\u2584")
            else:
                rendered_parts.append(" ")
        lines.append("".join(rendered_parts).rstrip())
    return lines


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


def tgproxy_enabled(values: dict[str, str]) -> bool:
    return shared_tgproxy_enabled(values)


def tgproxy_public_host(values: dict[str, str]) -> str:
    return shared_tgproxy_public_host(values)


def tgproxy_faketls_domain(values: dict[str, str]) -> str:
    return shared_tgproxy_faketls_domain(values)


def tgproxy_secret(values: dict[str, str]) -> str:
    config_path = PROJECT_ROOT / "tgproxy" / "config.toml"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            if line.startswith('secret = "'):
                return line.split('"', 2)[1].strip().lower()
    return values.get("TGPROXY_SECRET", "").strip().lower()


def tgproxy_url(values: dict[str, str]) -> str:
    if not tgproxy_enabled(values):
        return "-"
    return f"tg://proxy?server={tgproxy_public_host(values)}&port=443&secret={tgproxy_secret(values)}"


def tgproxy_secret_parts(values: dict[str, str]) -> tuple[str, str, str]:
    return shared_split_tgproxy_secret(tgproxy_secret(values))


def build_tgproxy_secret(access_code: str, fake_tls_domain: str) -> str:
    return shared_build_tgproxy_secret(access_code, fake_tls_domain)


def update_tgproxy_config_secret(new_secret: str) -> None:
    config_path = PROJECT_ROOT / "tgproxy" / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(f"TGProxy config was not found: {config_path}")
    original = config_path.read_text(encoding="utf-8")
    current_line_prefix = 'secret = "'
    replaced = False
    rendered: list[str] = []
    for line in original.splitlines():
        if line.startswith(current_line_prefix):
            rendered.append(f'secret = "{new_secret}"')
            replaced = True
        else:
            rendered.append(line)
    if not replaced:
        raise ValueError("Could not find TGProxy secret line in config.toml.")
    config_path.write_text("\n".join(rendered) + "\n", encoding="utf-8")


def xui_user_record() -> dict[str, object]:
    return shared_xui_user_record(XUI_DB_PATH)


def update_xui_db_credentials(username: str | None = None, password: str | None = None) -> str:
    return shared_update_xui_db_credentials(username=username, password=password, db_path=XUI_DB_PATH)


def upsert_xui_setting(key: str, value: str) -> None:
    shared_upsert_xui_setting(key, value, db_path=XUI_DB_PATH)


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
        "7. Diagnostics",
        danger_menu_option("Exit"),
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
            "2. Show logs",
            "3. Reconfigure setup key / management URL",
            "4. Start",
            "5. Stop",
            "6. Restart",
            "7. Disable NetBird",
            danger_menu_option("Back"),
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


def tgproxy_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        enabled = tgproxy_enabled(values)
        container = service_container_name(values, "tgproxy", include_stopped=True)
        running = service_is_running(container)
        try:
            _, code, _ = tgproxy_secret_parts(values)
        except Exception:
            code = "-"
        lines = [
            f"Container        : {container or 'not running'}",
            f"Status           : {status_badge(running, 'running' if running else 'stopped') if enabled else 'disabled'}",
            f"Public host      : {tgproxy_public_host(values) or '-'}",
            f"FakeTLS domain   : {tgproxy_faketls_domain(values) or '-'}",
            f"Access code      : {code}",
            f"TG Proxy URL     : {tgproxy_url(values)}",
            "",
            "1. Show TGProxy QR code",
            "2. Change access code",
            "3. Show logs",
            "4. Start",
            "5. Stop",
            "6. Restart",
            danger_menu_option("Back"),
        ]
        print_block("TGProxy", lines, accent=GREEN)
        choice = prompt("Select an option")
        if choice == "1":
            show_tgproxy_qr(values)
        elif choice == "2":
            change_tgproxy_access_code(values)
        elif choice == "3":
            tail_service_logs(values, "tgproxy")
        elif choice == "4":
            service_start(values, "tgproxy", "TGProxy")
        elif choice == "5":
            service_stop(values, "tgproxy", "TGProxy")
        elif choice == "6":
            service_restart(values, "tgproxy", "TGProxy")
        elif choice == "0":
            return


def show_tgproxy_qr(values: dict[str, str]) -> None:
    link = tgproxy_url(values)
    if link == "-":
        print_block("TGProxy QR", ["TGProxy is disabled or TG Proxy URL is empty."], accent=RED)
        pause()
        return
    try:
        print_qr_block("TGProxy QR", link, accent=GREEN, prefix_lines=[*clipboard_notice_lines("TG Proxy URL", link), ""])
    except Exception as exc:
        print_block("TGProxy QR", [str(exc)], accent=RED)
    pause()


def change_tgproxy_access_code(values: dict[str, str]) -> None:
    if not tgproxy_enabled(values):
        print_block("TGProxy", ["TGProxy is disabled in instance.env."], accent=RED)
        pause()
        return

    container = service_container_name(values, "tgproxy", include_stopped=True)
    if not container:
        print_block("TGProxy", ["TGProxy container is not available."], accent=RED)
        pause()
        return

    try:
        _, current_code, _ = tgproxy_secret_parts(values)
    except Exception as exc:
        print_block("TGProxy", [str(exc)], accent=RED)
        pause()
        return

    new_code = prompt_tgproxy_access_code(current_code)
    if new_code == current_code:
        print_block("TGProxy Access Code", ["Access code was not changed."], accent=RED)
        pause()
        return

    original_env = INSTANCE_ENV_PATH.read_text(encoding="utf-8")
    config_path = PROJECT_ROOT / "tgproxy" / "config.toml"
    original_config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

    try:
        new_secret = build_tgproxy_secret(new_code, tgproxy_faketls_domain(values))
        update_env(INSTANCE_ENV_PATH, {"TGPROXY_SECRET": new_secret})
        update_tgproxy_config_secret(new_secret)
        restart_result = run(["docker", "restart", container])
        if restart_result.returncode != 0:
            raise RuntimeError((restart_result.stdout or "") + (restart_result.stderr or ""))
    except Exception as exc:
        INSTANCE_ENV_PATH.write_text(original_env, encoding="utf-8")
        if config_path.exists():
            config_path.write_text(original_config, encoding="utf-8")
        if container:
            run(["docker", "restart", container])
        print_block("TGProxy Update Failed", [str(exc)], accent=RED)
        pause()
        return

    refreshed = parse_env(INSTANCE_ENV_PATH)
    link = tgproxy_url(refreshed)
    lines = [
        "TGProxy access code updated successfully.",
        f"Access code  : {new_code}",
        "",
        *clipboard_notice_lines("TG Proxy URL", link),
        "",
    ]
    print_qr_block("TGProxy QR", link, accent=GREEN, prefix_lines=lines)
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
    new_key = read_input(f"NetBird setup key [{current_key or 'disabled'}]: ").strip()
    if new_key == "-":
        disable_netbird(values)
        return
    new_url = read_input(f"NetBird management URL [{current_url or 'https://'}]: ").strip()

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
            "4. Change panel path",
            "5. Show logs",
            "6. Start",
            "7. Stop",
            "8. Restart",
            "9. Open shell",
            danger_menu_option("Back"),
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
            change_xui_panel_path(values)
        elif choice == "5":
            tail_service_logs(values, "xui")
        elif choice == "6":
            service_start(values, "xui", "x-ui")
        elif choice == "7":
            service_stop(values, "xui", "x-ui")
        elif choice == "8":
            service_restart(values, "xui", "x-ui")
        elif choice == "9":
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
    print_block("3x-ui Runtime Settings", lines, accent=YELLOW)
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
    try:
        update_xui_db_credentials(username=new_username)
        update_env(INSTANCE_ENV_PATH, {"CONFIG_USERNAME": new_username})
    except Exception as exc:
        print_block("3x-ui Update Failed", [str(exc)], accent=RED)
        pause()
        return

    completed = run(["docker", "restart", container])
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
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
    try:
        update_xui_db_credentials(password=new_password)
        update_env(INSTANCE_ENV_PATH, {"CONFIG_PASSWORD": new_password})
    except Exception as exc:
        print_block("3x-ui Update Failed", [str(exc)], accent=RED)
        pause()
        return

    completed = run(["docker", "restart", container])
    if completed.returncode != 0:
        print_block("3x-ui Update Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block("3x-ui Password", credential_updated_lines("Password", new_password), accent=GREEN)
    pause()


def update_site_conf_panel_path(old_path: str, new_path: str) -> tuple[str, str]:
    if not NGINX_SITE_CONF_PATH.exists():
        raise FileNotFoundError(f"Nginx site config was not found: {NGINX_SITE_CONF_PATH}")

    original = NGINX_SITE_CONF_PATH.read_text(encoding="utf-8")
    replaced = original.replace(f"/{old_path}", f"/{new_path}")
    if replaced == original:
        raise ValueError(f"Panel path /{old_path} was not found in {NGINX_SITE_CONF_PATH}.")
    NGINX_SITE_CONF_PATH.write_text(replaced, encoding="utf-8")
    return original, replaced


def update_site_conf_diag_path(old_path: str, new_path: str) -> tuple[str, str]:
    if not NGINX_SITE_CONF_PATH.exists():
        raise FileNotFoundError(f"Nginx site config was not found: {NGINX_SITE_CONF_PATH}")

    original = NGINX_SITE_CONF_PATH.read_text(encoding="utf-8")
    replaced = original.replace(f"location /{old_path}/ {{", f"location /{new_path}/ {{")
    if replaced == original:
        raise ValueError(f"Diagnostics path /{old_path}/ was not found in {NGINX_SITE_CONF_PATH}.")
    NGINX_SITE_CONF_PATH.write_text(replaced, encoding="utf-8")
    return original, replaced


def nginx_test_and_reload(values: dict[str, str]) -> None:
    container = service_container_name(values, "nginx", include_stopped=True)
    if not container:
        raise RuntimeError("nginx container is not available.")
    test = run(["docker", "exec", container, "nginx", "-t"])
    if test.returncode != 0:
        raise RuntimeError((test.stdout or "") + (test.stderr or ""))
    reload_result = run(["docker", "exec", container, "nginx", "-s", "reload"])
    if reload_result.returncode != 0:
        raise RuntimeError((reload_result.stdout or "") + (reload_result.stderr or ""))


def change_xui_panel_path(values: dict[str, str]) -> None:
    xui_container = require_xui_container(values)
    if not xui_container:
        return

    db_state = xui_db_state()
    current_db_path = db_state.get("webBasePath", "").strip("/")
    current_env_path = values.get("PANEL_PATH", "").strip("/")
    current_path = current_db_path or current_env_path
    if not current_path:
        print_block("3x-ui Update Failed", ["Current panel path is empty."], accent=RED)
        pause()
        return

    new_path = prompt_panel_path_value(current_path)
    if new_path == current_path:
        print_block("3x-ui Panel Path", ["Panel path was not changed."], accent=RED)
        pause()
        return

    original_site_conf = ""
    original_env = INSTANCE_ENV_PATH.read_text(encoding="utf-8")
    try:
        upsert_xui_setting("webBasePath", f"/{new_path}/")
        update_env(INSTANCE_ENV_PATH, {"PANEL_PATH": new_path})
        original_site_conf, _ = update_site_conf_panel_path(current_env_path or current_path, new_path)

        restart_result = run(["docker", "restart", xui_container])
        if restart_result.returncode != 0:
            raise RuntimeError((restart_result.stdout or "") + (restart_result.stderr or ""))

        nginx_test_and_reload(parse_env(INSTANCE_ENV_PATH))
    except Exception as exc:
        try:
            upsert_xui_setting("webBasePath", f"/{current_path}/")
        except Exception:
            pass
        INSTANCE_ENV_PATH.write_text(original_env, encoding="utf-8")
        if original_site_conf:
            NGINX_SITE_CONF_PATH.write_text(original_site_conf, encoding="utf-8")
        if xui_container:
            run(["docker", "restart", xui_container])
        try:
            nginx_test_and_reload(parse_env(INSTANCE_ENV_PATH))
        except Exception:
            pass
        print_block("3x-ui Update Failed", [str(exc)], accent=RED)
        pause()
        return

    lines = [
        "Panel path updated successfully.",
        "",
        f"New panel path : /{new_path}/",
        f"Panel URL      : {panel_url(parse_env(INSTANCE_ENV_PATH), xui_db_state())}",
        "",
        *clipboard_notice_lines("Panel URL", panel_url(parse_env(INSTANCE_ENV_PATH), xui_db_state())),
    ]
    print_block("3x-ui Panel Path", lines, accent=GREEN)
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


def service_restart(
    values: dict[str, str],
    service: str,
    label: str,
    pause_after: bool = True,
) -> subprocess.CompletedProcess[str]:
    container = service_container_name(values, service, include_stopped=True)
    if not container:
        print_block(label, [f"{label} container is not available."], accent=RED)
        if pause_after:
            pause()
        return subprocess.CompletedProcess(["docker", "restart", service], 1, "", f"{label} container is not available.")
    completed = run(["docker", "restart", container])
    if completed.returncode != 0:
        print_block(f"{label} Restart Failed", [completed.stdout, completed.stderr], accent=RED)
    else:
        print_block(label, [f"{label} restarted successfully."], accent=GREEN)
    if pause_after:
        pause()
    return completed


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
            danger_menu_option("Back"),
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
            "5. Backup Bundle",
            "6. Restore Bundle",
            danger_menu_option("Back"),
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
        elif choice == "5":
            create_backup_bundle_action()
        elif choice == "6":
            restore_backup_bundle_action()
        elif choice == "0":
            return


def create_backup_bundle_action() -> None:
    print_block(
        "Backup Bundle",
        [
            f"Project root      : {PROJECT_ROOT}",
            f"Backup directory  : {RUNTIME_BACKUP_DIR}",
            "",
            "Creating same-instance backup bundle...",
        ],
        accent=BLUE,
    )
    try:
        summary = runtime_backup_bundle()
        verify_summary = runtime_verify_bundle(summary.bundle_path)
    except Exception as exc:
        print_block("Backup Bundle Failed", [str(exc)], accent=RED)
        pause()
        return

    lines = [
        "Backup bundle created successfully.",
        "",
        f"Bundle file       : {summary.bundle_path}",
        f"Bundle schema     : {verify_summary.manifest.get('schema_version', '-')}",
        f"Domain            : {verify_summary.manifest.get('domain', '-') or '-'}",
        f"TGProxy host      : {verify_summary.manifest.get('tgproxy_public_host', '-') or '-'}",
        f"Files in payload  : {len(verify_summary.project_files)}",
        "",
        f"To restore later, place a bundle into {RUNTIME_RESTORE_INBOX_DIR}",
        "Restore uses the newest *.thbundle.tar.gz file from that directory.",
    ]
    print_block("Backup Bundle", lines, accent=GREEN)
    pause()


def restore_backup_bundle_action() -> None:
    try:
        bundle_path = runtime_latest_restore_bundle()
    except BackupError as exc:
        print_block(
            "Restore Bundle",
            [
                str(exc),
                "",
                f"Place exactly the bundle file into: {RUNTIME_RESTORE_INBOX_DIR}",
                "Restore will use the newest *.thbundle.tar.gz file from that directory.",
            ],
            accent=RED,
        )
        pause()
        return

    print_block(
        "Restore Bundle",
        [
            f"Bundle file       : {bundle_path}",
            f"Restore inbox     : {RUNTIME_RESTORE_INBOX_DIR}",
            "",
            "Verifying bundle, creating rollback snapshot,",
            "restoring runtime state, and restarting services...",
        ],
        accent=BLUE,
    )
    try:
        verify_summary = runtime_verify_bundle(bundle_path)
        result = runtime_restore_bundle(bundle_path)
    except Exception as exc:
        print_block("Restore Bundle Failed", [str(exc)], accent=RED)
        pause()
        return

    lines = [
        "Restore bundle completed successfully.",
        "",
        f"Bundle used       : {result.get('bundle_path', '-')}",
        f"Rollback bundle   : {result.get('rollback_path', '-')}",
        f"Domain            : {result.get('domain', '-') or '-'}",
        f"TGProxy host      : {result.get('tgproxy_public_host', '-') or '-'}",
        f"Files restored    : {result.get('project_files_restored', '-')}",
        f"Bundle schema     : {verify_summary.manifest.get('schema_version', '-')}",
        "",
        "Compose status:",
        *result.get("service_lines", []),
    ]
    print_block("Restore Bundle", lines, accent=GREEN)
    pause()


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


def diagnostics_menu() -> None:
    while True:
        values = parse_env(INSTANCE_ENV_PATH)
        container = service_container_name(values, "diag", include_stopped=True)
        running = service_is_running(container)
        lines = [
            f"Container        : {container or 'not running'}",
            f"Status           : {status_badge(running, 'running' if running else 'stopped')}",
            f"Browser route    : /{values.get('DIAG_PATH', '').strip('/') or '-'}" + ("/" if values.get('DIAG_PATH', '').strip('/') else ""),
            "",
            "1. VPS <--> Internet speed test",
            "2. PC <--> VPS speed test",
            "3. Rotate browser route prefix",
            danger_menu_option("Back"),
        ]
        print_block("Diagnostics", lines, accent=BLUE)
        choice = prompt("Select an option")
        if choice == "1":
            diagnostics_vps_speed_menu(values)
        elif choice == "2":
            start_browser_speed_test(values)
        elif choice == "3":
            rotate_diagnostics_path(values)
        elif choice == "0":
            return


def diagnostics_vps_speed_menu(values: dict[str, str]) -> None:
    while True:
        lines = [
            f"Speedtest CLI    : {status_badge(speedtest_available(), 'ready' if speedtest_available() else 'missing')}",
            "",
            "1. Run auto test",
            "2. Choose server",
            danger_menu_option("Back"),
        ]
        print_block("VPS Internet Speed", lines, accent=BLUE)
        choice = prompt("Select an option")
        if choice == "1":
            run_vps_speedtest()
        elif choice == "2":
            choose_speedtest_server()
        elif choice == "0":
            return


def speedtest_available() -> bool:
    return SPEEDTEST_BIN.exists() and command_works([str(SPEEDTEST_BIN), "--version"])


def ensure_speedtest_cli_available() -> bool:
    if speedtest_available():
        return True
    print_block(
        "VPS Internet Speed",
        ["Speedtest CLI is missing on this host.", "It should be installed during TransitHub installation."],
        accent=RED,
    )
    pause()
    return False


def speedtest_base_command() -> list[str]:
    return [str(SPEEDTEST_BIN), "--accept-license", "--accept-gdpr"]


def run_speedtest_command(command: list[str], title: str, subtitle: str) -> subprocess.CompletedProcess[str]:
    clear_screen()
    print_header(title, header_width(title, [subtitle]), accent=BLUE)
    print()
    print(f"{INDENT}{subtitle}")
    print(f"{INDENT}The test may take 20-30 seconds.")
    print()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started_at = time.time()
    spinner = ["|", "/", "-", "\\"]
    index = 0

    while process.poll() is None:
        elapsed = int(time.time() - started_at)
        status_line = f"{INDENT}Status          : running {spinner[index % len(spinner)]}   Elapsed: {elapsed}s   "
        print(f"\r{status_line}", end="", flush=True)
        time.sleep(0.2)
        index += 1

    stdout, stderr = process.communicate()
    print("\r" + " " * 120, end="")
    print(f"\r{INDENT}Status          : completed")
    print()
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def parse_speedtest_result(payload: dict[str, object]) -> list[str]:
    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    interface = payload.get("interface") if isinstance(payload.get("interface"), dict) else {}
    ping = payload.get("ping") if isinstance(payload.get("ping"), dict) else {}
    download = payload.get("download") if isinstance(payload.get("download"), dict) else {}
    upload = payload.get("upload") if isinstance(payload.get("upload"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    packet_loss = payload.get("packetLoss", "-")

    def bandwidth_to_mbps(section: dict[str, object]) -> str:
        try:
            return f"{float(section.get('bandwidth', 0)) * 8 / 1_000_000:.2f}"
        except (TypeError, ValueError):
            return "-"

    started_at = str(payload.get("timestamp", "") or payload.get("date", "") or "-")
    server_label = ", ".join(
        part for part in [str(server.get("name", "") or ""), str(server.get("location", "") or ""), str(server.get("country", "") or "")] if part
    ) or "-"
    result_url = str(result.get("url", "") or "")
    lines = [
        f"Started at      : {started_at}",
        f"Server          : {server_label}",
        f"Ping            : {ping.get('latency', '-')} ms",
        f"Jitter          : {ping.get('jitter', '-')} ms",
        f"Packet loss     : {packet_loss}",
        f"Download        : {bandwidth_to_mbps(download)} Mbps",
        f"Upload          : {bandwidth_to_mbps(upload)} Mbps",
        f"Share URL       : {result_url or '-'}",
        "",
        "Latency is the round-trip delay to the selected speedtest server.",
        "Jitter is how much that latency changes between samples.",
    ]
    if result_url:
        lines.extend(["", *clipboard_notice_lines("Speedtest share URL", result_url)])
    return lines


def run_vps_speedtest(server_id: str | None = None) -> None:
    if not ensure_speedtest_cli_available():
        return
    command = [*speedtest_base_command(), "--format=json"]
    subtitle = "Running automatic VPS speed test"
    if server_id:
        command.append(f"--server-id={server_id}")
        subtitle = f"Running VPS speed test against server {server_id}"
    else:
        auto_servers = list_speedtest_servers(excluded_countries={"russia", "ukraine"}, show_loading=False)
        if not auto_servers:
            print_block(
                "VPS Internet Speed",
                ["No eligible auto-selected server was found outside Russia and Ukraine."],
                accent=RED,
            )
            pause()
            return
        auto_server_id, auto_label = auto_servers[0]
        command.append(f"--server-id={auto_server_id}")
        subtitle = f"Running VPS speed test against {format_speedtest_server_label(auto_label)}"
    completed = run_speedtest_command(command, "VPS Internet Speed", subtitle)
    if completed.returncode != 0:
        print_block("VPS Internet Speed", [completed.stdout, completed.stderr], accent=RED)
        pause()
        return
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        print_block("VPS Internet Speed", [completed.stdout or "Speedtest did not return valid JSON."], accent=RED)
        pause()
        return
    print_block("VPS Internet Speed", parse_speedtest_result(payload), accent=GREEN)
    pause()


def speedtest_server_country(label: str) -> str:
    parts = [part.strip() for part in re.split(r"\s{2,}", label) if part.strip()]
    return parts[-1] if parts else ""


def format_speedtest_server_label(label: str) -> str:
    parts = [part.strip() for part in re.split(r"\s{2,}", label) if part.strip()]
    if len(parts) >= 3:
        name, location, country = parts[0], parts[1], parts[2]
        return f"{country} | {location} | {name}"
    return label


def list_speedtest_servers(
    *,
    excluded_countries: set[str] | None = None,
    show_loading: bool = True,
) -> list[tuple[str, str]]:
    if not ensure_speedtest_cli_available():
        return []
    if show_loading:
        print_block(
            "Choose Speedtest Server",
            ["Loading available speedtest servers.", "Ukraine is excluded from the manual list."],
            accent=BLUE,
        )
    completed = run([*speedtest_base_command(), "--servers"])
    if completed.returncode != 0:
        print_block("Choose Speedtest Server", [completed.stdout, completed.stderr], accent=RED)
        pause()
        return []
    entries: list[tuple[str, str]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\)\s+(.+)$", line)
        if match:
            entries.append((match.group(1), match.group(2).strip()))
            continue
        match = re.match(r"^(\d+)\s+(.+)$", line)
        if match:
            entries.append((match.group(1), match.group(2).strip()))
    blocked = {country.strip().lower() for country in (excluded_countries or set()) if country.strip()}
    filtered = [(server_id, label) for server_id, label in entries if speedtest_server_country(label).lower() not in blocked]
    unique_by_country: list[tuple[str, str]] = []
    country_seen: set[str] = set()
    remainder: list[tuple[str, str]] = []
    for server_id, label in filtered:
        country = speedtest_server_country(label).strip().lower()
        if country and country not in country_seen:
            unique_by_country.append((server_id, label))
            country_seen.add(country)
        else:
            remainder.append((server_id, label))
    return unique_by_country + remainder


def choose_speedtest_server() -> None:
    servers = list_speedtest_servers(excluded_countries={"ukraine"})
    if not servers:
        return
    shown = servers[:18]
    lines = [
        "Manual list: Ukraine is excluded. Russia is allowed here.",
        "",
        *[f"{index}. {format_speedtest_server_label(label)} [{server_id}]" for index, (server_id, label) in enumerate(shown, start=1)],
        "",
        danger_menu_option("Back"),
    ]
    print_block("Choose Speedtest Server", lines, accent=BLUE)
    choice = prompt("Select a listed server")
    if choice == "0":
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(shown)):
        print_block("Choose Speedtest Server", ["Select one of the listed servers."], accent=RED)
        pause()
        return
    server_id = shown[int(choice) - 1][0]
    run_vps_speedtest(server_id)


def diagnostics_admin_base_url(values: dict[str, str]) -> str:
    return f"http://127.0.0.1:{values.get('DIAG_HOST_PORT', '').strip() or '18765'}"


def diagnostics_admin_request(
    values: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    url = diagnostics_admin_base_url(values) + path
    data = None
    headers = {"X-Diagnostics-Admin-Token": values.get("DIAG_ADMIN_TOKEN", "").strip()}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Diagnostics API error {exc.code}: {body}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Diagnostics service is not reachable: {exc.reason}") from exc


def diagnostics_current_session(values: dict[str, str]) -> dict[str, object] | None:
    try:
        response = diagnostics_admin_request(values, "GET", "/admin/session")
    except RuntimeError:
        return None
    session = response.get("session")
    return session if isinstance(session, dict) else None


def diagnostics_session_url(session: dict[str, object] | None) -> str:
    if not session:
        return ""
    return str(session.get("public_url", "") or "")


def diagnostics_session_status(session: dict[str, object] | None) -> str:
    if not session:
        return "idle"
    status = str(session.get("status", "unknown"))
    if status == "completed":
        return status_badge(True, status)
    if status in {"running", "created"}:
        return f"{YELLOW}{status}{RESET}"
    return status_badge(False, status)


def start_browser_speed_test(values: dict[str, str]) -> None:
    try:
        response = diagnostics_admin_request(values, "POST", "/admin/session")
    except RuntimeError as exc:
        print_block("VPS Local PC Speed", [str(exc)], accent=RED)
        pause()
        return
    session = response.get("session")
    if not isinstance(session, dict):
        print_block("VPS Local PC Speed", ["Could not create a diagnostics session."], accent=RED)
        pause()
        return
    url = diagnostics_session_url(session)
    lines = [
        "Browser test link is ready.",
        "This link is valid for 5 minutes.",
        "Open it on your local PC and start the test from the page itself.",
        "",
        f"Test URL        : {url}",
        "",
        *clipboard_notice_lines("Diagnostics URL", url),
    ]
    print_block("Browser Test Link", lines, accent=GREEN)
    pause()


def recreate_runtime_service(values: dict[str, str], service: str) -> subprocess.CompletedProcess[str]:
    return run([*compose_command(values, always_include_netbird=True), "up", "-d", "--force-recreate", service])


def rotate_diagnostics_path(values: dict[str, str]) -> None:
    current_path = values.get("DIAG_PATH", "").strip("/")
    if not current_path:
        print_block("Diagnostics Route Prefix", ["Current diagnostics route is empty."], accent=RED)
        pause()
        return

    new_path = prompt_diag_path_value(current_path)
    if new_path == current_path:
        print_block("Diagnostics Route Prefix", ["Diagnostics route was not changed."], accent=RED)
        pause()
        return

    original_env = INSTANCE_ENV_PATH.read_text(encoding="utf-8")
    original_site_conf = ""
    try:
        update_env(INSTANCE_ENV_PATH, {"DIAG_PATH": new_path})
        original_site_conf, _ = update_site_conf_diag_path(current_path, new_path)
        refreshed_values = parse_env(INSTANCE_ENV_PATH)
        recreate_result = recreate_runtime_service(refreshed_values, "diag")
        if recreate_result.returncode != 0:
            raise RuntimeError((recreate_result.stdout or "") + (recreate_result.stderr or ""))
        nginx_test_and_reload(refreshed_values)
    except Exception as exc:
        INSTANCE_ENV_PATH.write_text(original_env, encoding="utf-8")
        if original_site_conf:
            NGINX_SITE_CONF_PATH.write_text(original_site_conf, encoding="utf-8")
        restored_values = parse_env(INSTANCE_ENV_PATH)
        try:
            recreate_runtime_service(restored_values, "diag")
        except Exception:
            pass
        try:
            nginx_test_and_reload(restored_values)
        except Exception:
            pass
        print_block("Diagnostics Route Prefix", [str(exc)], accent=RED)
        pause()
        return

    domain = values.get("DOMAIN", "").strip()
    browser_url = f"https://{domain}/{new_path}/<token>/" if domain else f"/{new_path}/<token>/"
    lines = [
        "Diagnostics browser route updated successfully.",
        "",
        f"Old route      : /{current_path}/",
        f"New route      : /{new_path}/",
        f"URL pattern    : {browser_url}",
        "",
        "All previously issued browser links are now invalid.",
    ]
    print_block("Diagnostics Route Prefix", lines, accent=GREEN)
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
            danger_menu_option("Back"),
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
    confirm = read_input("Continue with force reissue? [y/N]: ").strip().lower()
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
            danger_menu_option("Back"),
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
    new_timezone = read_input(f"New timezone [{current or 'Europe/Moscow'}]: ").strip()
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
