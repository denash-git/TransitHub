from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from transithub_runtime.xui_db import seed_xui_db


def create_schema(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                password TEXT
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                value TEXT
            );
            CREATE TABLE inbounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                up INTEGER,
                down INTEGER,
                total INTEGER,
                remark TEXT,
                enable INTEGER,
                expiry_time INTEGER,
                listen TEXT,
                port INTEGER,
                protocol TEXT,
                settings TEXT,
                stream_settings TEXT,
                tag TEXT,
                sniffing TEXT
            );
            CREATE TABLE client_traffics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inbound_id INTEGER,
                enable INTEGER,
                email TEXT,
                up INTEGER,
                down INTEGER,
                expiry_time INTEGER,
                total INTEGER,
                reset INTEGER
            );
            """
        )
        cur.execute(
            """
            INSERT INTO inbounds (
                user_id, up, down, total, remark, enable, expiry_time, listen,
                port, protocol, settings, stream_settings, tag, sniffing
            ) VALUES (1, 0, 0, 0, 'custom', 1, 0, '', 9999, 'vless', '{}', '{}', 'custom-tag', '{}')
            """
        )
        conn.commit()
    finally:
        conn.close()


def seed_values() -> dict[str, str]:
    return {
        "CONFIG_USERNAME": "admin",
        "CONFIG_PASSWORD": "secret",
        "TZ": "UTC",
        "PANEL_PORT": "2053",
        "PANEL_PATH": "panel-123",
        "SUB_PORT": "2080",
        "SUB_PATH": "sub-123",
        "JSON_PATH": "json-123",
        "DOMAIN": "example.com",
        "CLIENT_UUID_1": "11111111-1111-1111-1111-111111111111",
        "CLIENT_UUID_2": "22222222-2222-2222-2222-222222222222",
        "CLIENT_UUID_3": "33333333-3333-3333-3333-333333333333",
        "REALITY_DOMAIN": "reality.example.com",
        "REALITY_PRIVATE_KEY": "priv",
        "REALITY_PUBLIC_KEY": "pub",
        "REALITY_SHORT_IDS": "aaaa1111,bbbb2222",
        "WS_PORT": "3001",
        "WS_PATH": "ws-path",
        "XHTTP_PORT": "3003",
        "XHTTP_PATH": "xhttp-path",
        "TROJAN_PORT": "3002",
        "TROJAN_PATH": "trojan-path",
        "TROJAN_PASSWORD": "trojan-secret",
    }


class XuiSeedTests(unittest.TestCase):
    def test_seed_preserves_user_created_inbounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "x-ui.db"
            create_schema(db_path)

            result = seed_xui_db(seed_values(), db_path)

            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                remarks = [row[0] for row in cur.execute("SELECT remark FROM inbounds ORDER BY id")]
            finally:
                conn.close()

            self.assertIn("custom", remarks)
            self.assertIn("reality", remarks)
            self.assertIn("ws", remarks)
            self.assertIn("xhttp", remarks)
            self.assertIn("trojan-grpc", remarks)
            self.assertTrue(result["updated_values"]["MANAGED_REALITY_INBOUND_ID"])
            self.assertTrue(result["updated_values"]["MANAGED_WS_INBOUND_ID"])
            self.assertTrue(result["updated_values"]["MANAGED_XHTTP_INBOUND_ID"])
            self.assertTrue(result["updated_values"]["MANAGED_TROJAN_INBOUND_ID"])


if __name__ == "__main__":
    unittest.main()
