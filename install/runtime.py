from __future__ import annotations

from pathlib import Path
import shutil

from . import paths
from .env import (
    FIELD_PROMPTS,
    PROMPTED_FIELDS,
    ensure_generated,
    interactive_defaults,
    looks_uninitialized,
    parse_env,
    render_env,
    sync_derived_fields,
    utc_timestamp,
)
from .render import render_runtime_files


def ensure_layout() -> None:
    for path in paths.REQUIRED_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    migrate_legacy_layout()


def migrate_legacy_layout() -> None:
    copy_if_missing(paths.LEGACY_INSTANCE_ENV_PATH, paths.INSTANCE_ENV_PATH)
    copy_if_missing(paths.LEGACY_DEPLOY_INSTANCE_ENV_PATH, paths.INSTANCE_ENV_PATH)
    copy_tree_contents_if_missing(paths.LEGACY_RUNTIME_PROXY_RENDERED_DIR, paths.SERVICE_PROXY_CONFIG_DIR)
    copy_tree_contents_if_missing(
        paths.LEGACY_RUNTIME_PROXY_EXTENSIONS_DIR,
        paths.SERVICE_PROXY_EXTENSIONS_DIR,
    )
    copy_tree_contents_if_missing(paths.LEGACY_RUNTIME_SUBPAGE_DIR, paths.SERVICE_CLIENT_PAGE_DIR)
    copy_tree_contents_if_missing(paths.LEGACY_RUNTIME_FAKESITE_DIR, paths.SERVICE_FAKE_SITE_DIR)
    copy_tree_contents_if_missing(paths.LEGACY_RUNTIME_XUI_DATA_DIR, paths.SERVICE_XUI_DATA_DIR)
    copy_tree_contents_if_missing(paths.LEGACY_DEPLOY_PROXY_CONFIG_DIR, paths.SERVICE_PROXY_CONFIG_DIR)
    copy_tree_contents_if_missing(
        paths.LEGACY_DEPLOY_PROXY_EXTENSIONS_DIR,
        paths.SERVICE_PROXY_EXTENSIONS_DIR,
    )
    copy_tree_contents_if_missing(paths.LEGACY_DEPLOY_SUBPAGE_SITE_DIR, paths.SERVICE_CLIENT_PAGE_DIR)
    copy_tree_contents_if_missing(paths.LEGACY_DEPLOY_FAKESITE_SITE_DIR, paths.SERVICE_FAKE_SITE_DIR)
    copy_tree_contents_if_missing(paths.LEGACY_DEPLOY_XUI_DATA_DIR, paths.SERVICE_XUI_DATA_DIR)
    copy_tree_contents_if_missing(
        paths.LEGACY_DEPLOY_SUBCONVERTER_DATA_DIR,
        paths.SERVICE_SUBCONVERTER_DATA_DIR,
    )


def copy_if_missing(source: Path, destination: Path) -> None:
    if source.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def copy_tree_contents_if_missing(source_dir: Path, destination_dir: Path) -> None:
    if not source_dir.exists():
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(source_dir)
        destination = destination_dir / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def load_instance_env() -> dict[str, str]:
    values = interactive_defaults()
    current = parse_env(paths.INSTANCE_ENV_PATH)
    legacy_candidates = [
        parse_env(paths.LEGACY_DEPLOY_INSTANCE_ENV_PATH),
        parse_env(paths.LEGACY_INSTANCE_ENV_PATH),
    ]
    for legacy in legacy_candidates:
        if legacy and (not current or looks_uninitialized(current)):
            current = legacy
            break
    values.update(current)
    return values


def save_instance_env(values: dict[str, str]) -> None:
    paths.INSTANCE_ENV_PATH.write_text(render_env(values), encoding="utf-8")


def validate_templates(values: dict[str, str]) -> None:
    expected = [
        paths.TEMPLATES_SUBPAGE_DIR / f"{values['WEB_SUB_TEMPLATE']}.html.template",
        paths.TEMPLATES_CLASH_DIR / f"{values['CLASH_TEMPLATE']}.yaml.template",
        paths.TEMPLATES_FAKESITE_DIR / values["FAKE_SITE_TEMPLATE"] / "index.html.template",
    ]
    missing = [str(path) for path in expected if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing templates:\n" + "\n".join(missing))


def validate_cert_path(values: dict[str, str]) -> list[str]:
    cert_dir = Path(values["CERT_LIVE_DIR"])
    required = ["fullchain.pem", "privkey.pem"]
    return [str(cert_dir / item) for item in required if not (cert_dir / item).exists()]


def render(values: dict[str, str]) -> list[Path]:
    validate_templates(values)
    return render_runtime_files(values)


def prompt_for_init(values: dict[str, str]) -> dict[str, str]:
    prompted = dict(values)
    print()
    print("+----------------------------------------------------+")
    print("|  3XUI V1 Initial Setup                             |")
    print("+----------------------------------------------------+")
    print()
    for key in PROMPTED_FIELDS:
        current = prompted.get(key, "")
        label = FIELD_PROMPTS.get(key, key)
        if key == "TZ":
            entered = input(f"{label} [{current}, Enter = keep default]: ").strip()
        else:
            entered = input(f"{label} [{current}]: ").strip()
        if entered:
            prompted[key] = entered
    return sync_derived_fields(prompted)


def apply_overrides(values: dict[str, str], overrides: dict[str, str] | None) -> dict[str, str]:
    merged = dict(values)
    if overrides:
        merged.update(overrides)
    return sync_derived_fields(merged)


def init_instance(
    interactive: bool = True,
    overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    ensure_layout()
    values = apply_overrides(load_instance_env(), overrides)
    if interactive and looks_uninitialized(values):
        values = prompt_for_init(values)
    values = ensure_generated(values)
    if values["INSTANCE_INITIALIZED"] != "true":
        values["INSTANCE_INITIALIZED"] = "true"
        if not values["INIT_TIMESTAMP"]:
            values["INIT_TIMESTAMP"] = utc_timestamp()
    save_instance_env(values)
    rendered = render(values)
    return {
        "instance_env": str(paths.INSTANCE_ENV_PATH),
        "rendered": [str(path) for path in rendered],
        "missing_certs": validate_cert_path(values),
    }


def reconfigure_instance(overrides: dict[str, str] | None = None) -> dict[str, object]:
    ensure_layout()
    values = ensure_generated(apply_overrides(load_instance_env(), overrides))
    save_instance_env(values)
    rendered = render(values)
    return {
        "instance_env": str(paths.INSTANCE_ENV_PATH),
        "rendered": [str(path) for path in rendered],
        "missing_certs": validate_cert_path(values),
    }


def status() -> dict[str, object]:
    ensure_layout()
    values = load_instance_env()
    return {
        "instance_initialized": values.get("INSTANCE_INITIALIZED", "false"),
        "domain": values.get("DOMAIN", ""),
        "reality_domain": values.get("REALITY_DOMAIN", ""),
        "panel_url": panel_url(values),
        "subscription_url": subscription_url(values),
        "web_url": web_url(values),
        "cert_path": values.get("CERT_LIVE_DIR", ""),
        "missing_certs": validate_cert_path(values),
        "rendered_nginx_files": sorted(
            str(path) for path in paths.SERVICE_NGINX_CONFIG_DIR.glob("*.conf")
        ),
    }


def panel_url(values: dict[str, str]) -> str:
    return f"https://{values['DOMAIN']}/{values['PANEL_PATH']}/"


def subscription_url(values: dict[str, str]) -> str:
    return f"https://{values['DOMAIN']}/{values['SUB_PATH']}/first"


def web_url(values: dict[str, str]) -> str:
    return f"https://{values['DOMAIN']}/{values['WEB_PATH']}/"
