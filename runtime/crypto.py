from __future__ import annotations

import base64
from dataclasses import dataclass



@dataclass(frozen=True)
class RealityKeyPair:
    private_key: str
    public_key: str


def generate_reality_keypair() -> RealityKeyPair:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import x25519

    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return RealityKeyPair(
        private_key=to_xray_key(private_raw),
        public_key=to_xray_key(public_raw),
    )


def to_xray_key(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
