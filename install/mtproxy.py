from __future__ import annotations


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def base_secret() -> str:
    from .env import random_token

    return random_token(32, "0123456789abcdef")


def client_secret(server_secret: str, tls_domain: str) -> str:
    normalized_secret = server_secret.strip().lower()
    normalized_domain = tls_domain.strip().lower()
    if not normalized_secret:
        return ""
    if normalized_domain:
        return f"ee{normalized_secret}{normalized_domain.encode('utf-8').hex()}"
    return f"dd{normalized_secret}"


def enabled(values: dict[str, str]) -> bool:
    return bool_env(values.get("ENABLE_MTPROXY")) and bool(values.get("MTPROXY_TLS_DOMAIN", "").strip())


def public_host(values: dict[str, str]) -> str:
    return values.get("MTPROXY_PUBLIC_HOST", "").strip() or values.get("DOMAIN", "").strip()


def tg_link(values: dict[str, str]) -> str:
    if not enabled(values):
        return ""
    return (
        f"tg://proxy?server={public_host(values)}"
        f"&port=443&secret={values.get('MTPROXY_CLIENT_SECRET', '').strip()}"
    )


def validate(values: dict[str, str]) -> None:
    if not bool_env(values.get("ENABLE_MTPROXY")):
        return

    tls_domain = values.get("MTPROXY_TLS_DOMAIN", "").strip().lower()
    if not tls_domain:
        raise ValueError("MTProxy is enabled, but MTPROXY_TLS_DOMAIN is empty.")

    forbidden = {
        values.get("DOMAIN", "").strip().lower(),
        values.get("REALITY_DOMAIN", "").strip().lower(),
    }
    if tls_domain in forbidden:
        raise ValueError("MTPROXY_TLS_DOMAIN must not match DOMAIN or REALITY_DOMAIN.")

    server_secret = values.get("MTPROXY_SECRET", "").strip().lower()
    if len(server_secret) != 32 or any(ch not in "0123456789abcdef" for ch in server_secret):
        raise ValueError("MTPROXY_SECRET must be exactly 32 lowercase hex characters.")
