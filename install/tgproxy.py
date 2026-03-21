from __future__ import annotations


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def secret(fake_tls_domain: str) -> str:
    from .env import random_token

    normalized_domain = fake_tls_domain.strip().lower()
    if not normalized_domain:
        return ""
    server_secret = random_token(32, "0123456789abcdef")
    return f"ee{server_secret}{normalized_domain.encode('utf-8').hex()}"


def enabled(values: dict[str, str]) -> bool:
    return (
        bool_env(values.get("ENABLE_TGPROXY"))
        and bool(values.get("TGPROXY_PUBLIC_HOST", "").strip())
        and bool(values.get("TGPROXY_FAKETLS_DOMAIN", "").strip())
    )


def public_host(values: dict[str, str]) -> str:
    return values.get("TGPROXY_PUBLIC_HOST", "").strip() or values.get("DOMAIN", "").strip()


def tg_link(values: dict[str, str]) -> str:
    if not enabled(values):
        return ""
    return (
        f"tg://proxy?server={public_host(values)}"
        f"&port=443&secret={values.get('TGPROXY_SECRET', '').strip()}"
    )


def validate(values: dict[str, str]) -> None:
    if not bool_env(values.get("ENABLE_TGPROXY")):
        return

    public = values.get("TGPROXY_PUBLIC_HOST", "").strip().lower()
    fake_tls = values.get("TGPROXY_FAKETLS_DOMAIN", "").strip().lower()
    if not public:
        raise ValueError("Telegram proxy is enabled, but TGPROXY_PUBLIC_HOST is empty.")
    if not fake_tls:
        raise ValueError("Telegram proxy is enabled, but TGPROXY_FAKETLS_DOMAIN is empty.")

    forbidden = {
        values.get("DOMAIN", "").strip().lower(),
        values.get("REALITY_DOMAIN", "").strip().lower(),
        public,
    }
    if fake_tls in forbidden:
        raise ValueError("TGPROXY_FAKETLS_DOMAIN must not match DOMAIN, REALITY_DOMAIN, or TGPROXY_PUBLIC_HOST.")

    tgproxy_secret = values.get("TGPROXY_SECRET", "").strip().lower()
    if not tgproxy_secret.startswith("ee") or len(tgproxy_secret) <= 34:
        raise ValueError("TGPROXY_SECRET must be a valid FakeTLS secret starting with `ee`.")
