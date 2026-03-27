from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import time

from .crypto import hash_password
from . import paths


MANAGED_INBOUND_FIELDS = {
    "reality": "MANAGED_REALITY_INBOUND_ID",
    "ws": "MANAGED_WS_INBOUND_ID",
    "xhttp": "MANAGED_XHTTP_INBOUND_ID",
    "trojan-grpc": "MANAGED_TROJAN_INBOUND_ID",
}


def sync_xui_db(username: str, password: str, db_path: Path | None = None) -> dict[str, object]:
    target = db_path or default_xui_db_path()
    if not target.exists():
        raise FileNotFoundError(f"x-ui.db not found: {target}")

    conn = sqlite3.connect(target)
    try:
        cur = conn.cursor()
        password_hash = hash_password(password)
        cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET username = ?, password = ? WHERE id = ?",
                (username, password_hash, row[0]),
            )
            user_id = row[0]
        else:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password_hash),
            )
            user_id = cur.lastrowid

        upsert_setting(cur, "secret", secrets_token())

        conn.commit()
        return {
            "db_path": str(target),
            "user_id": user_id,
            "username": username,
            "secret_updated": True,
        }
    finally:
        conn.close()


def seed_xui_db(values: dict[str, str], db_path: Path | None = None) -> dict[str, object]:
    target = db_path or default_xui_db_path()
    if not target.exists():
        raise FileNotFoundError(f"x-ui.db not found: {target}")

    conn = sqlite3.connect(target)
    try:
        cur = conn.cursor()
        sync_users_and_settings(cur, values)

        created: list[dict[str, object]] = []
        managed_ids: dict[str, int] = {}

        reality = upsert_vless_reality_inbound(
            cur,
            managed_id=resolve_managed_inbound_id(cur, values, "reality", "vless", 8443),
            port=8443,
            remark="reality",
            client_id=values["CLIENT_UUID_1"],
            domain=values["DOMAIN"],
            reality_domain=values["REALITY_DOMAIN"],
            private_key=values["REALITY_PRIVATE_KEY"],
            public_key=values["REALITY_PUBLIC_KEY"],
            short_ids=values["REALITY_SHORT_IDS"].split(","),
        )
        created.append(reality)
        managed_ids["reality"] = int(reality["id"])

        ws = upsert_vless_ws_inbound(
            cur,
            managed_id=resolve_managed_inbound_id(cur, values, "ws", "vless", int(values["WS_PORT"])),
            port=int(values["WS_PORT"]),
            remark="ws",
            client_id=values["CLIENT_UUID_2"],
            domain=values["DOMAIN"],
            path=f"/{values['WS_PORT']}/{values['WS_PATH']}",
        )
        created.append(ws)
        managed_ids["ws"] = int(ws["id"])

        xhttp = upsert_vless_xhttp_inbound(
            cur,
            managed_id=resolve_managed_inbound_id(cur, values, "xhttp", "vless", int(values["XHTTP_PORT"])),
            port=int(values["XHTTP_PORT"]),
            remark="xhttp",
            client_id=values["CLIENT_UUID_3"],
            domain=values["DOMAIN"],
            path=f"/{values['XHTTP_PATH']}",
        )
        created.append(xhttp)
        managed_ids["xhttp"] = int(xhttp["id"])

        trojan = upsert_trojan_grpc_inbound(
            cur,
            managed_id=resolve_managed_inbound_id(cur, values, "trojan-grpc", "trojan", int(values["TROJAN_PORT"])),
            port=int(values["TROJAN_PORT"]),
            remark="trojan-grpc",
            password=values["TROJAN_PASSWORD"],
            domain=values["DOMAIN"],
            service_name=f"/{values['TROJAN_PORT']}/{values['TROJAN_PATH']}",
        )
        created.append(trojan)
        managed_ids["trojan-grpc"] = int(trojan["id"])

        conn.commit()

        updated_values = dict(values)
        for remark, field_name in MANAGED_INBOUND_FIELDS.items():
            inbound_id = managed_ids.get(remark)
            if inbound_id is not None:
                updated_values[field_name] = str(inbound_id)

        return {
            "db_path": str(target),
            "seeded_inbounds": len(created),
            "inbounds": created,
            "managed_inbound_ids": managed_ids,
            "panel_base_path": panel_base_path(values),
            "updated_values": updated_values,
        }
    finally:
        conn.close()


def sync_users_and_settings(cur: sqlite3.Cursor, values: dict[str, str]) -> None:
    password_hash = hash_password(values["CONFIG_PASSWORD"])
    cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE users SET username = ?, password = ? WHERE id = ?",
            (values["CONFIG_USERNAME"], password_hash, row[0]),
        )
    else:
        cur.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (values["CONFIG_USERNAME"], password_hash),
        )

    upsert_setting(cur, "secret", secrets_token())
    upsert_setting(cur, "timeLocation", values["TZ"])
    upsert_setting(cur, "webPort", values["PANEL_PORT"])
    upsert_setting(cur, "webBasePath", panel_base_path(values))
    upsert_setting(cur, "sessionMaxAge", "30")
    upsert_setting(cur, "subShowInfo", "true")
    upsert_setting(cur, "subEnable", "true")
    upsert_setting(cur, "subJsonEnable", "true")
    upsert_setting(cur, "subEnableRouting", "true")
    upsert_setting(cur, "subListen", "")
    upsert_setting(cur, "subPort", values["SUB_PORT"])
    upsert_setting(cur, "subUpdates", "12")
    upsert_setting(cur, "subEncrypt", "true")
    upsert_setting(cur, "subPath", f"/{values['SUB_PATH']}/")
    upsert_setting(cur, "subDomain", values["DOMAIN"])
    upsert_setting(cur, "subCertFile", "")
    upsert_setting(cur, "subKeyFile", "")
    upsert_setting(cur, "subJsonPath", f"/{values['JSON_PATH']}/")
    upsert_setting(cur, "subURI", f"https://{values['DOMAIN']}/{values['SUB_PATH']}/")
    upsert_setting(cur, "subJsonURI", f"https://{values['DOMAIN']}/{values['JSON_PATH']}/")
    upsert_setting(cur, "webCertFile", "")
    upsert_setting(cur, "webKeyFile", "")


def xui_user_record(db_path: Path | None = None) -> dict[str, object]:
    target = db_path or default_xui_db_path()
    if not target.exists():
        raise FileNotFoundError(f"x-ui database was not found: {target}")

    conn = sqlite3.connect(target)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT id, username, password FROM users ORDER BY id LIMIT 1").fetchone()
        if not row:
            return {"id": None, "username": "", "password_hash": ""}
        return {
            "id": int(row[0]),
            "username": str(row[1] or ""),
            "password_hash": str(row[2] or ""),
        }
    finally:
        conn.close()


def update_xui_db_credentials(
    username: str | None = None,
    password: str | None = None,
    db_path: Path | None = None,
) -> str:
    if username is None and password is None:
        raise ValueError("No x-ui credential changes were requested.")

    target = db_path or default_xui_db_path()
    current = xui_user_record(target)
    target_username = username if username is not None else str(current.get("username") or "")
    target_password_hash = hash_password(password) if password is not None else str(current.get("password_hash") or "")

    if not target_username:
        raise ValueError("x-ui username can not be empty.")
    if not target_password_hash:
        raise ValueError("x-ui password hash can not be empty.")

    conn = sqlite3.connect(target)
    try:
        cur = conn.cursor()
        if current.get("id") is None:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (target_username, target_password_hash),
            )
        else:
            cur.execute(
                "UPDATE users SET username = ?, password = ? WHERE id = ?",
                (target_username, target_password_hash, int(current["id"])),
            )
        conn.commit()
    finally:
        conn.close()

    return target_username


def panel_base_path(values: dict[str, str]) -> str:
    return f"/{values['PANEL_PATH'].strip('/')}/"


def upsert_setting(cur: sqlite3.Cursor, key: str, value: str) -> None:
    cur.execute("SELECT id FROM settings WHERE key = ? LIMIT 1", (key,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE settings SET value = ? WHERE id = ?", (value, row[0]))
    else:
        cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))


def upsert_xui_setting(key: str, value: str, db_path: Path | None = None) -> None:
    target = db_path or default_xui_db_path()
    if not target.exists():
        raise FileNotFoundError(f"x-ui database was not found: {target}")

    conn = sqlite3.connect(target)
    try:
        cur = conn.cursor()
        upsert_setting(cur, key, value)
        conn.commit()
    finally:
        conn.close()


def resolve_managed_inbound_id(
    cur: sqlite3.Cursor,
    values: dict[str, str],
    remark: str,
    protocol: str,
    port: int,
) -> int | None:
    field_name = MANAGED_INBOUND_FIELDS[remark]
    configured_id = values.get(field_name, "").strip()
    if configured_id.isdigit():
        row = cur.execute("SELECT id FROM inbounds WHERE id = ?", (int(configured_id),)).fetchone()
        if row:
            return int(row[0])

    row = cur.execute(
        "SELECT id FROM inbounds WHERE protocol = ? AND remark = ? AND port = ? ORDER BY id LIMIT 1",
        (protocol, remark, port),
    ).fetchone()
    if row:
        return int(row[0])
    return None


def upsert_vless_reality_inbound(
    cur: sqlite3.Cursor,
    *,
    managed_id: int | None,
    port: int,
    remark: str,
    client_id: str,
    domain: str,
    reality_domain: str,
    private_key: str,
    public_key: str,
    short_ids: list[str],
) -> dict[str, object]:
    created_at = now_ms()
    settings = {
        "clients": [
            vless_client(
                client_id,
                email="first",
                sub_id="first",
                flow="xtls-rprx-vision",
                created_at=created_at,
            )
        ],
        "decryption": "none",
        "fallbacks": [],
    }
    stream_settings = {
        "network": "tcp",
        "security": "reality",
        "externalProxy": [{"forceTls": "same", "dest": domain, "port": 443, "remark": ""}],
        "realitySettings": {
            "show": False,
            "xver": 0,
            "target": "nginx:9443",
            "serverNames": [reality_domain],
            "privateKey": private_key,
            "minClient": "",
            "maxClient": "",
            "maxTimediff": 0,
            "shortIds": short_ids,
            "settings": {
                "publicKey": public_key,
                "fingerprint": "random",
                "serverName": "",
                "spiderX": "/",
            },
        },
        "tcpSettings": {
            "acceptProxyProtocol": False,
            "header": {"type": "none"},
        },
    }
    inbound_id = upsert_inbound(
        cur,
        inbound_id=managed_id,
        listen="",
        port=port,
        protocol="vless",
        remark=remark,
        settings=settings,
        stream_settings=stream_settings,
        tag=f"inbound-{port}",
        sniffing=disabled_sniffing(),
    )
    upsert_client_traffic(cur, inbound_id, "first")
    return {"id": inbound_id, "remark": remark, "protocol": "vless", "port": port}


def upsert_vless_ws_inbound(
    cur: sqlite3.Cursor,
    *,
    managed_id: int | None,
    port: int,
    remark: str,
    client_id: str,
    domain: str,
    path: str,
) -> dict[str, object]:
    created_at = now_ms()
    settings = {
        "clients": [
            vless_client(
                client_id,
                email="first_1",
                sub_id="first",
                flow="",
                created_at=created_at,
            )
        ],
        "decryption": "none",
        "fallbacks": [],
    }
    stream_settings = {
        "network": "ws",
        "security": "none",
        "externalProxy": [{"forceTls": "tls", "dest": domain, "port": 443, "remark": ""}],
        "wsSettings": {
            "acceptProxyProtocol": False,
            "path": path,
            "host": domain,
            "headers": {},
        },
    }
    inbound_id = upsert_inbound(
        cur,
        inbound_id=managed_id,
        listen="",
        port=port,
        protocol="vless",
        remark=remark,
        settings=settings,
        stream_settings=stream_settings,
        tag=f"inbound-{port}",
        sniffing=disabled_sniffing(),
    )
    upsert_client_traffic(cur, inbound_id, "first_1")
    return {"id": inbound_id, "remark": remark, "protocol": "vless", "port": port}


def upsert_vless_xhttp_inbound(
    cur: sqlite3.Cursor,
    *,
    managed_id: int | None,
    port: int,
    remark: str,
    client_id: str,
    domain: str,
    path: str,
) -> dict[str, object]:
    created_at = now_ms()
    settings = {
        "clients": [
            vless_client(
                client_id,
                email="firstX",
                sub_id="first",
                flow="",
                created_at=created_at,
            )
        ],
        "decryption": "none",
        "fallbacks": [],
    }
    stream_settings = {
        "network": "xhttp",
        "security": "none",
        "externalProxy": [{"forceTls": "tls", "dest": domain, "port": 443, "remark": ""}],
        "xhttpSettings": {
            "path": path,
            "host": "",
            "headers": {},
            "scMaxBufferedPosts": 30,
            "scMaxEachPostBytes": "1000000",
            "noSSEHeader": False,
            "xPaddingBytes": "100-1000",
            "mode": "packet-up",
        },
        "sockopt": {
            "acceptProxyProtocol": False,
            "tcpFastOpen": True,
            "mark": 0,
            "tproxy": "off",
            "tcpMptcp": True,
            "tcpNoDelay": True,
            "domainStrategy": "UseIP",
            "tcpMaxSeg": 1440,
            "dialerProxy": "",
            "tcpKeepAliveInterval": 0,
            "tcpKeepAliveIdle": 300,
            "tcpUserTimeout": 10000,
            "tcpcongestion": "bbr",
            "V6Only": False,
            "tcpWindowClamp": 600,
            "interface": "",
        },
    }
    inbound_id = upsert_inbound(
        cur,
        inbound_id=managed_id,
        listen="",
        port=port,
        protocol="vless",
        remark=remark,
        settings=settings,
        stream_settings=stream_settings,
        tag=f"inbound-{port}",
        sniffing=enabled_sniffing(),
    )
    upsert_client_traffic(cur, inbound_id, "firstX")
    return {"id": inbound_id, "remark": remark, "protocol": "vless", "port": port}


def upsert_trojan_grpc_inbound(
    cur: sqlite3.Cursor,
    *,
    managed_id: int | None,
    port: int,
    remark: str,
    password: str,
    domain: str,
    service_name: str,
) -> dict[str, object]:
    created_at = now_ms()
    settings = {
        "clients": [
            {
                "comment": "",
                "created_at": created_at,
                "email": "firstT",
                "enable": True,
                "expiryTime": 0,
                "limitIp": 0,
                "password": password,
                "reset": 0,
                "subId": "first",
                "tgId": 0,
                "totalGB": 0,
                "updated_at": created_at,
            }
        ],
        "fallbacks": [],
    }
    stream_settings = {
        "network": "grpc",
        "security": "none",
        "externalProxy": [{"forceTls": "tls", "dest": domain, "port": 443, "remark": ""}],
        "grpcSettings": {
            "serviceName": service_name,
            "authority": domain,
            "multiMode": False,
        },
    }
    inbound_id = upsert_inbound(
        cur,
        inbound_id=managed_id,
        listen="",
        port=port,
        protocol="trojan",
        remark=remark,
        settings=settings,
        stream_settings=stream_settings,
        tag=f"inbound-{port}",
        sniffing=disabled_sniffing(),
    )
    upsert_client_traffic(cur, inbound_id, "firstT")
    return {"id": inbound_id, "remark": remark, "protocol": "trojan", "port": port}


def upsert_inbound(
    cur: sqlite3.Cursor,
    *,
    inbound_id: int | None,
    listen: str,
    port: int,
    protocol: str,
    remark: str,
    settings: dict[str, object],
    stream_settings: dict[str, object],
    tag: str,
    sniffing: dict[str, object],
) -> int:
    payload = (
        remark,
        1,
        0,
        listen,
        port,
        protocol,
        compact_json(settings),
        compact_json(stream_settings),
        tag,
        compact_json(sniffing),
    )
    if inbound_id is not None:
        cur.execute(
            """
            UPDATE inbounds
            SET remark = ?, enable = ?, expiry_time = ?, listen = ?, port = ?, protocol = ?,
                settings = ?, stream_settings = ?, tag = ?, sniffing = ?
            WHERE id = ?
            """,
            (*payload, inbound_id),
        )
        if cur.rowcount:
            return inbound_id

    cur.execute(
        """
        INSERT INTO inbounds (
            user_id, up, down, total, remark, enable, expiry_time, listen,
            port, protocol, settings, stream_settings, tag, sniffing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            0,
            0,
            0,
            remark,
            1,
            0,
            listen,
            port,
            protocol,
            compact_json(settings),
            compact_json(stream_settings),
            tag,
            compact_json(sniffing),
        ),
    )
    return int(cur.lastrowid)


def upsert_client_traffic(cur: sqlite3.Cursor, inbound_id: int, email: str) -> None:
    row = cur.execute(
        "SELECT id FROM client_traffics WHERE inbound_id = ? AND email = ? ORDER BY id LIMIT 1",
        (inbound_id, email),
    ).fetchone()
    if row:
        cur.execute(
            """
            UPDATE client_traffics
            SET enable = ?, expiry_time = ?, total = ?, reset = ?
            WHERE id = ?
            """,
            (1, 0, 0, 0, int(row[0])),
        )
        return
    cur.execute(
        """
        INSERT INTO client_traffics (inbound_id, enable, email, up, down, expiry_time, total, reset)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (inbound_id, 1, email, 0, 0, 0, 0, 0),
    )


def vless_client(
    client_id: str,
    *,
    email: str,
    sub_id: str,
    flow: str,
    created_at: int,
) -> dict[str, object]:
    return {
        "id": client_id,
        "flow": flow,
        "email": email,
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": True,
        "tgId": "",
        "subId": sub_id,
        "reset": 0,
        "created_at": created_at,
        "updated_at": created_at,
    }


def disabled_sniffing() -> dict[str, object]:
    return {
        "enabled": False,
        "destOverride": ["http", "tls", "quic", "fakedns"],
        "metadataOnly": False,
        "routeOnly": False,
    }


def enabled_sniffing() -> dict[str, object]:
    result = disabled_sniffing()
    result["enabled"] = True
    return result


def compact_json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def now_ms() -> int:
    return int(time.time() * 1000)


def default_xui_db_path() -> Path:
    primary = paths.SERVICE_XUI_DATA_DIR / "x-ui.db"
    if primary.exists():
        return primary
    legacy = paths.LEGACY_RUNTIME_XUI_DATA_DIR / "x-ui.db"
    return legacy if legacy.exists() else primary


def secrets_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)
