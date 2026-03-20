from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import re
import shutil
import subprocess


LETSENCRYPT_LIVE_DIR = Path("/etc/letsencrypt/live")
LETSENCRYPT_RENEWAL_DIR = Path("/etc/letsencrypt/renewal")
DNS_NAME_PATTERN = re.compile(r"DNS:([^,\s]+)")
STAGING_SERVER_FRAGMENT = "acme-staging-v02.api.letsencrypt.org"


class CertbotError(RuntimeError):
    pass


class CertbotRateLimitError(CertbotError):
    pass


def certbot_executable() -> str:
    managed = Path("/opt/certbot/bin/certbot")
    if managed.exists():
        return str(managed)
    resolved = shutil.which("certbot")
    if resolved:
        return resolved
    raise FileNotFoundError("certbot executable was not found.")


def cert_files_exist(cert_dir: Path) -> bool:
    return (cert_dir / "fullchain.pem").exists() and (cert_dir / "privkey.pem").exists()


def cert_name_for(domain: str, staging: bool = False) -> str:
    return f"{domain}-staging" if staging else domain


def renewal_config_path(cert_name: str) -> Path:
    return LETSENCRYPT_RENEWAL_DIR / f"{cert_name}.conf"


def renewal_is_staging(cert_dir: Path) -> bool | None:
    config_path = renewal_config_path(cert_dir.name)
    if not config_path.exists():
        return None
    contents = config_path.read_text(encoding="utf-8", errors="ignore")
    return STAGING_SERVER_FRAGMENT in contents


def certificate_domains(cert_dir: Path) -> set[str]:
    fullchain = cert_dir / "fullchain.pem"
    if not fullchain.exists():
        return set()
    completed = subprocess.run(
        ["openssl", "x509", "-in", str(fullchain), "-noout", "-ext", "subjectAltName"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return set()
    return {match.group(1) for match in DNS_NAME_PATTERN.finditer(completed.stdout)}


def candidate_certificate_dirs(domain: str, staging: bool = False) -> list[Path]:
    if not LETSENCRYPT_LIVE_DIR.exists():
        return []

    candidates: list[Path] = []
    exact = LETSENCRYPT_LIVE_DIR / cert_name_for(domain, staging)
    if cert_files_exist(exact):
        candidates.append(exact)

    for cert_dir in sorted(LETSENCRYPT_LIVE_DIR.iterdir()):
        if not cert_dir.is_dir() or cert_dir == exact:
            continue
        if not cert_files_exist(cert_dir):
            continue
        cert_staging = renewal_is_staging(cert_dir)
        if cert_staging is not None and cert_staging != staging:
            continue
        if domain in certificate_domains(cert_dir):
            candidates.append(cert_dir)
    return candidates


def best_existing_certificate_dir(domain: str, staging: bool = False) -> Path | None:
    candidates = candidate_certificate_dirs(domain, staging)
    if not candidates:
        return None
    if candidates[0].name == cert_name_for(domain, staging):
        return candidates[0]
    return max(candidates, key=lambda path: (path / "fullchain.pem").stat().st_mtime)


def normalize_cert_dir(domain: str, staging: bool = False) -> Path | None:
    return best_existing_certificate_dir(domain, staging)


def extract_retry_after(output: str) -> str | None:
    match = re.search(r"retry after ([0-9:\-\sUTC]+)", output, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def format_rate_limit_error(domain: str, output: str) -> str:
    retry_after = extract_retry_after(output)
    retry_suffix = f" Retry after {retry_after}." if retry_after else ""
    return (
        f"Let's Encrypt rate limit reached for `{domain}`.{retry_suffix} "
        "This usually happens after repeated fresh installs on the same domain. "
        "Wait for the rate limit window to expire, or reuse an existing certificate lineage from this host."
    )


def certificate_expiry(cert_dir: Path) -> datetime | None:
    fullchain = cert_dir / "fullchain.pem"
    if not fullchain.exists():
        return None
    completed = subprocess.run(
        ["openssl", "x509", "-in", str(fullchain), "-noout", "-enddate"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    line = completed.stdout.strip()
    if not line.startswith("notAfter="):
        return None
    value = line.split("=", 1)[1].strip()
    try:
        expires_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at.astimezone(timezone.utc)


def certificate_status(domain: str, staging: bool = False) -> dict[str, object]:
    cert_dir = best_existing_certificate_dir(domain, staging)
    if cert_dir is None or not cert_files_exist(cert_dir):
        return {
            "present": False,
            "domain": domain,
            "cert_dir": "",
            "staging": staging,
            "expires_at": "",
            "days_remaining": None,
        }

    expires_at = certificate_expiry(cert_dir)
    days_remaining: int | None = None
    expires_at_str = ""
    if expires_at is not None:
        remaining = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
        days_remaining = math.ceil(remaining / 86400) if remaining else 0
        expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "present": True,
        "domain": domain,
        "cert_dir": str(cert_dir),
        "staging": staging,
        "expires_at": expires_at_str,
        "days_remaining": days_remaining,
    }


def ensure_certificate(domain: str, email: str = "", staging: bool = False) -> dict[str, object]:
    cert_name = cert_name_for(domain, staging)
    existing = normalize_cert_dir(domain, staging)
    if existing and cert_files_exist(existing):
        return {
            "domain": domain,
            "cert_dir": str(existing),
            "staging": staging,
            "changed": False,
        }

    command = [
        certbot_executable(),
        "certonly",
        "--standalone",
        "--non-interactive",
        "--agree-tos",
        "--cert-name",
        cert_name,
        "-d",
        domain,
    ]
    if staging:
        command.append("--staging")
    if email.strip():
        command.extend(["-m", email.strip()])
    else:
        command.append("--register-unsafely-without-email")

    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        existing = normalize_cert_dir(domain, staging)
        if existing and cert_files_exist(existing):
            return {
                "domain": domain,
                "cert_dir": str(existing),
                "staging": staging,
                "changed": False,
            }
        if "too many certificates" in output.lower():
            raise CertbotRateLimitError(format_rate_limit_error(domain, output))
        raise CertbotError(output or f"certbot failed for `{domain}` with exit code {completed.returncode}.")

    cert_dir = normalize_cert_dir(domain, staging) or (LETSENCRYPT_LIVE_DIR / cert_name)
    return {
        "domain": domain,
        "cert_dir": str(cert_dir),
        "staging": staging,
        "changed": True,
    }
