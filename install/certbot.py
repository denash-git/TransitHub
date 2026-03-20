from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def certbot_executable() -> str:
    managed = Path("/opt/certbot/bin/certbot")
    if managed.exists():
        return str(managed)
    resolved = shutil.which("certbot")
    if resolved:
        return resolved
    raise FileNotFoundError("certbot executable was not found.")


def ensure_certificate(domain: str, email: str = "") -> dict[str, object]:
    cert_dir = Path("/etc/letsencrypt/live") / domain
    fullchain = cert_dir / "fullchain.pem"
    privkey = cert_dir / "privkey.pem"
    if fullchain.exists() and privkey.exists():
        return {
            "domain": domain,
            "cert_dir": str(cert_dir),
            "changed": False,
        }

    command = [
        certbot_executable(),
        "certonly",
        "--standalone",
        "--non-interactive",
        "--agree-tos",
        "-d",
        domain,
    ]
    if email.strip():
        command.extend(["-m", email.strip()])
    else:
        command.append("--register-unsafely-without-email")

    subprocess.run(command, check=True)
    return {
        "domain": domain,
        "cert_dir": str(cert_dir),
        "changed": True,
    }
