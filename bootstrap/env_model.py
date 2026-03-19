from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import socket
import secrets
import string
import uuid

from .crypto import generate_reality_keypair


def utc_timestamp() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def random_token(length: int = 24, alphabet: str | None = None) -> str:
    chars = alphabet or (string.ascii_lowercase + string.digits)
    return "".join(secrets.choice(chars) for _ in range(length))


def random_path_token(prefix: str, length: int = 16) -> str:
    return f"{prefix}-{random_token(length)}"


def random_username(length: int = 10) -> str:
    return secrets.choice(string.ascii_lowercase) + random_token(length - 1)


def random_port(start: int = 20000, end: int = 45000) -> int:
    return secrets.randbelow(end - start) + start


def reality_short_ids(count: int = 4, item_length: int = 8) -> str:
    alphabet = "0123456789abcdef"
    return ",".join(random_token(item_length, alphabet) for _ in range(count))


@dataclass(frozen=True)
class EnvField:
    name: str
    default: str
    mutable: bool
    comment: str


ENV_FIELDS = [
    EnvField("INSTANCE_NAME", "yn62", True, "Short instance identifier."),
    EnvField("DOMAIN", "example.com", True, "Main panel/web/subscription domain."),
    EnvField("REALITY_DOMAIN", "reality.example.com", True, "REALITY SNI destination domain."),
    EnvField("AUTODOMAIN", "false", True, "Optional domain automation flag."),
    EnvField("TZ", "Europe/Moscow", True, "Container timezone."),
    EnvField("XUI_IMAGE", "ghcr.io/mhsanaei/3x-ui:latest", True, "Official 3x-ui image."),
    EnvField("NGINX_IMAGE", "nginx:1.27-alpine", True, "Reverse proxy image."),
    EnvField("SUB2SINGBOX_IMAGE", "tindy2013/subconverter:latest", True, "Temporary conversion image placeholder."),
    EnvField("ENABLE_FAKE_SITE", "true", True, "Whether to publish a fake site."),
    EnvField("ENABLE_SUB2SINGBOX", "true", True, "Whether to expose sub2sing-box behind nginx."),
    EnvField("ENABLE_EXTENSIONS", "true", True, "Whether nginx loads extension includes."),
    EnvField("FAKE_SITE_TEMPLATE", "signal-wire", True, "Selected fake-site template."),
    EnvField("WEB_SUB_TEMPLATE", "clean-card", True, "Selected web subscription template."),
    EnvField("CLASH_TEMPLATE", "default", True, "Selected Clash template."),
    EnvField("CERTBOT_EMAIL", "", True, "Optional Let's Encrypt registration email."),
    EnvField("CERT_LIVE_DIR", "/etc/letsencrypt/live/example.com", True, "Host certificate directory mounted into runtime."),
    EnvField("BOOTSTRAP_VERSION", "0.1.0", True, "Bootstrap schema version."),
    EnvField("XUI_DB_SCHEMA_VERSION", "latest-official", True, "Pinned x-ui schema marker."),
    EnvField("INSTANCE_INITIALIZED", "false", False, "Set to true after first successful init."),
    EnvField("INIT_TIMESTAMP", "", False, "UTC timestamp of initial bootstrap."),
    EnvField("LAST_RECONFIGURE_TIMESTAMP", "", True, "UTC timestamp of last reconfigure."),
    EnvField("PANEL_PORT", "", False, "Internal 3x-ui panel port."),
    EnvField("PANEL_PATH", "", False, "Randomized panel path segment."),
    EnvField("SUB_PORT", "", False, "Internal subscription service port."),
    EnvField("SUB_PATH", "", False, "Randomized subscription path segment."),
    EnvField("JSON_PATH", "", False, "Randomized JSON subscription path."),
    EnvField("WEB_PATH", "", False, "Randomized browser helper path."),
    EnvField("SUB2SINGBOX_PATH", "", False, "Randomized converter path."),
    EnvField("WS_PORT", "", False, "Internal WebSocket transport port."),
    EnvField("WS_PATH", "", False, "Randomized WebSocket path."),
    EnvField("XHTTP_PORT", "", False, "Internal XHTTP transport port."),
    EnvField("XHTTP_PATH", "", False, "Randomized XHTTP path."),
    EnvField("TROJAN_PORT", "", False, "Internal Trojan gRPC port."),
    EnvField("TROJAN_PATH", "", False, "Randomized Trojan path."),
    EnvField("CONFIG_USERNAME", "", False, "Panel username."),
    EnvField("CONFIG_PASSWORD", "", False, "Panel password."),
    EnvField("REALITY_PRIVATE_KEY", "", False, "REALITY private key placeholder."),
    EnvField("REALITY_PUBLIC_KEY", "", False, "REALITY public key placeholder."),
    EnvField("REALITY_SHORT_IDS", "", False, "Comma-separated REALITY short IDs."),
    EnvField("CLIENT_UUID_1", "", False, "Primary client UUID."),
    EnvField("CLIENT_UUID_2", "", False, "Secondary client UUID."),
    EnvField("CLIENT_UUID_3", "", False, "Tertiary client UUID."),
    EnvField("TROJAN_PASSWORD", "", False, "Primary Trojan password."),
]

FAKE_SITE_TEMPLATES = [
    "signal-wire",
    "atlas-lab",
    "mono-grid",
    "northstar",
    "paperlane",
]

PROMPTED_FIELDS = [
    "DOMAIN",
    "REALITY_DOMAIN",
    "TZ",
    "WEB_SUB_TEMPLATE",
]

FIELD_PROMPTS = {
    "DOMAIN": "Main domain",
    "REALITY_DOMAIN": "REALITY domain",
    "TZ": "Timezone",
    "WEB_SUB_TEMPLATE": "Web subscription template",
}


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def render_env(values: dict[str, str]) -> str:
    lines = [
        "# Generated by bootstrap. Edit only documented mutable values.",
        "",
    ]
    for field in ENV_FIELDS:
        lines.append(f"# {field.comment}")
        lines.append(f"{field.name}={values.get(field.name, field.default)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def defaults() -> dict[str, str]:
    return {field.name: field.default for field in ENV_FIELDS}


def interactive_defaults() -> dict[str, str]:
    values = defaults()
    hostname = socket.gethostname().split(".")[0]
    if hostname:
        values["INSTANCE_NAME"] = hostname
    detected_tz = detect_system_timezone()
    if detected_tz:
        values["TZ"] = detected_tz
    values["FAKE_SITE_TEMPLATE"] = pick_fake_site_template(values.get("FAKE_SITE_TEMPLATE", ""))
    return values


def detect_system_timezone() -> str | None:
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz:
        return env_tz

    timezone_file = Path("/etc/timezone")
    if timezone_file.exists():
        value = timezone_file.read_text(encoding="utf-8").strip()
        if value:
            return value

    localtime_path = Path("/etc/localtime")
    if localtime_path.exists():
        try:
            resolved = localtime_path.resolve()
            zoneinfo_root = Path("/usr/share/zoneinfo")
            if zoneinfo_root in resolved.parents:
                return str(resolved.relative_to(zoneinfo_root)).replace("\\", "/")
        except OSError:
            pass

    for command in (
        ["timedatectl", "show", "-p", "Timezone", "--value"],
        ["date", "+%Z"],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except (OSError, subprocess.SubprocessError):
            continue
        value = result.stdout.strip()
        if value and value not in {"UTC", "GMT", "Coordinated Universal Time"}:
            return value
    return None


def ensure_generated(values: dict[str, str]) -> dict[str, str]:
    generated = dict(values)
    generated["FAKE_SITE_TEMPLATE"] = pick_fake_site_template(generated.get("FAKE_SITE_TEMPLATE", ""))
    generated.setdefault("INIT_TIMESTAMP", "")
    generated["LAST_RECONFIGURE_TIMESTAMP"] = utc_timestamp()
    fill_if_empty(generated, "PANEL_PORT", str(random_port()))
    fill_if_empty(generated, "PANEL_PATH", random_token(16))
    fill_if_empty(generated, "SUB_PORT", str(random_port()))
    fill_if_empty(generated, "SUB_PATH", random_path_token("sub"))
    fill_if_empty(generated, "JSON_PATH", random_path_token("json"))
    fill_if_empty(generated, "WEB_PATH", random_path_token("web"))
    fill_if_empty(generated, "SUB2SINGBOX_PATH", random_path_token("sb"))
    fill_if_empty(generated, "WS_PORT", str(random_port()))
    fill_if_empty(generated, "WS_PATH", random_path_token("ws"))
    fill_if_empty(generated, "XHTTP_PORT", str(random_port()))
    fill_if_empty(generated, "XHTTP_PATH", random_path_token("xhttp"))
    fill_if_empty(generated, "TROJAN_PORT", str(random_port()))
    fill_if_empty(generated, "TROJAN_PATH", random_path_token("trojan"))
    fill_if_empty(generated, "CONFIG_USERNAME", random_username(10))
    fill_if_empty(generated, "CONFIG_PASSWORD", random_token(20))
    if generated.get("REALITY_PRIVATE_KEY") in {"", "REPLACE_WITH_XRAY_PRIVATE_KEY"} or generated.get(
        "REALITY_PUBLIC_KEY"
    ) in {"", "REPLACE_WITH_XRAY_PUBLIC_KEY"}:
        keypair = generate_reality_keypair()
        generated["REALITY_PRIVATE_KEY"] = keypair.private_key
        generated["REALITY_PUBLIC_KEY"] = keypair.public_key
    fill_if_empty(generated, "REALITY_SHORT_IDS", reality_short_ids())
    fill_if_empty(generated, "CLIENT_UUID_1", str(uuid.uuid4()))
    fill_if_empty(generated, "CLIENT_UUID_2", str(uuid.uuid4()))
    fill_if_empty(generated, "CLIENT_UUID_3", str(uuid.uuid4()))
    fill_if_empty(generated, "TROJAN_PASSWORD", random_token(28))
    return generated


def fill_if_empty(values: dict[str, str], key: str, value: str) -> None:
    if not values.get(key):
        values[key] = value


def sync_derived_fields(values: dict[str, str]) -> dict[str, str]:
    synced = dict(values)
    domain = synced.get("DOMAIN", "").strip()
    if domain:
        synced["CERT_LIVE_DIR"] = f"/etc/letsencrypt/live/{domain}"
    synced["FAKE_SITE_TEMPLATE"] = pick_fake_site_template(synced.get("FAKE_SITE_TEMPLATE", ""))
    return synced


def available_fake_site_templates() -> list[str]:
    root = Path(__file__).resolve().parent.parent / "templates" / "fakesite"
    if not root.exists():
        return list(FAKE_SITE_TEMPLATES)
    available = [
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "index.html.template").exists()
    ]
    return sorted(available) or list(FAKE_SITE_TEMPLATES)


def pick_fake_site_template(current: str) -> str:
    available = available_fake_site_templates()
    if current in available:
        return current
    return secrets.choice(available)


def looks_uninitialized(values: dict[str, str]) -> bool:
    return (
        values.get("INSTANCE_INITIALIZED", "false") != "true"
        or values.get("DOMAIN") in {"", "example.com"}
        or values.get("REALITY_DOMAIN") in {"", "reality.example.com"}
    )
