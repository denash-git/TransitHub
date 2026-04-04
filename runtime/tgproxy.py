from __future__ import annotations


TGPROXY_CODE_LENGTH = 32


def bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def secret(fake_tls_domain: str) -> str:
    from .env import random_token

    normalized_domain = fake_tls_domain.strip().lower()
    if not normalized_domain:
        return ""
    server_secret = random_token(TGPROXY_CODE_LENGTH, "0123456789abcdef")
    return f"ee{server_secret}{normalized_domain.encode('utf-8').hex()}"


def enabled(values: dict[str, str]) -> bool:
    return bool_env(values.get("ENABLE_TGPROXY")) and bool(values.get("TGPROXY_PUBLIC_HOST", "").strip())


def public_host(values: dict[str, str]) -> str:
    return values.get("TGPROXY_PUBLIC_HOST", "").strip() or values.get("DOMAIN", "").strip()


def faketls_domain(values: dict[str, str]) -> str:
    return values.get("TGPROXY_FAKETLS_DOMAIN", "").strip() or public_host(values)


def tg_link(values: dict[str, str]) -> str:
    if not enabled(values):
        return ""
    return (
        f"tg://proxy?server={public_host(values)}"
        f"&port=443&secret={values.get('TGPROXY_SECRET', '').strip()}"
    )


def split_secret(current_secret: str) -> tuple[str, str, str]:
    normalized_secret = current_secret.strip().lower()
    if not normalized_secret.startswith("ee") or len(normalized_secret) <= 2 + TGPROXY_CODE_LENGTH:
        raise ValueError("Current TGProxy secret is invalid.")
    prefix = "ee"
    code = normalized_secret[2 : 2 + TGPROXY_CODE_LENGTH]
    domain_hex = normalized_secret[2 + TGPROXY_CODE_LENGTH :]
    return prefix, code, domain_hex


def build_secret(access_code: str, fake_tls_domain: str) -> str:
    normalized_code = access_code.strip().lower()
    if len(normalized_code) != TGPROXY_CODE_LENGTH or any(ch not in "0123456789abcdef" for ch in normalized_code):
        raise ValueError(f"TGProxy access code must be exactly {TGPROXY_CODE_LENGTH} hexadecimal characters.")
    normalized_domain = fake_tls_domain.strip().lower()
    if not normalized_domain:
        raise ValueError("TGProxy FakeTLS domain is empty.")
    return f"ee{normalized_code}{normalized_domain.encode('utf-8').hex()}"


def validate(values: dict[str, str]) -> None:
    if not bool_env(values.get("ENABLE_TGPROXY")):
        return

    public = public_host(values).strip().lower()
    fake_tls = faketls_domain(values).strip().lower()
    if not public:
        raise ValueError("Telegram proxy is enabled, but TGPROXY_PUBLIC_HOST is empty.")
    if not fake_tls:
        raise ValueError("Telegram proxy is enabled, but TGPROXY_FAKETLS_DOMAIN is empty.")
    if fake_tls != public:
        raise ValueError("TGPROXY_FAKETLS_DOMAIN must match TGPROXY_PUBLIC_HOST in this build.")

    forbidden = {
        values.get("DOMAIN", "").strip().lower(),
        values.get("REALITY_DOMAIN", "").strip().lower(),
    }
    if public in forbidden:
        raise ValueError("TGPROXY_PUBLIC_HOST must not match DOMAIN or REALITY_DOMAIN.")

    tgproxy_secret = values.get("TGPROXY_SECRET", "").strip().lower()
    if not tgproxy_secret.startswith("ee") or len(tgproxy_secret) <= 34:
        raise ValueError("TGPROXY_SECRET must be a valid FakeTLS secret starting with `ee`.")
