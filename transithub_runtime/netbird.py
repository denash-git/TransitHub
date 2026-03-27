from __future__ import annotations

from urllib.parse import urlparse


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def setup_key(values: dict[str, str]) -> str:
    return values.get("NETBIRD_SETUP_KEY", "").strip()


def management_url(values: dict[str, str]) -> str:
    return values.get("NETBIRD_MANAGEMENT_URL", "").strip()


def hostname(values: dict[str, str]) -> str:
    return values.get("NETBIRD_HOSTNAME", "").strip()


def enabled(values: dict[str, str]) -> bool:
    return (
        bool_env(values.get("ENABLE_NETBIRD"))
        and bool(setup_key(values))
        and bool(management_url(values))
    )


def validate(values: dict[str, str]) -> None:
    if not bool_env(values.get("ENABLE_NETBIRD")):
        return

    current_setup_key = setup_key(values)
    current_management_url = management_url(values)
    if not current_setup_key:
        raise ValueError("NetBird is enabled, but NETBIRD_SETUP_KEY is empty.")
    if not current_management_url:
        raise ValueError("NetBird is enabled, but NETBIRD_MANAGEMENT_URL is empty.")

    parsed = urlparse(current_management_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("NETBIRD_MANAGEMENT_URL must be a valid https:// URL.")
