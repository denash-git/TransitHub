from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from secrets import token_urlsafe
import threading
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
INDEX_PATH = APP_DIR / "index.html"
STYLE_PATH = APP_DIR / "style.css"
SCRIPT_PATH = APP_DIR / "app.js"
UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def utc_timestamp() -> str:
    return utc_now().isoformat()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class DiagnosticsState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.session: dict[str, object] | None = None
        self.domain = os.environ.get("DOMAIN", "").strip()
        self.diag_path = os.environ.get("DIAG_PATH", "").strip().strip("/")
        self.admin_token = os.environ.get("DIAG_ADMIN_TOKEN", "").strip()
        self.ttl_seconds = env_int("DIAG_SESSION_TTL_SECONDS", 300)
        self.download_bytes = env_int("DIAG_DOWNLOAD_BYTES", 33554432)
        self.upload_bytes = env_int("DIAG_UPLOAD_BYTES", 16777216)
        self.download_streams = env_int("DIAG_DOWNLOAD_STREAMS", 3)
        self.upload_streams = env_int("DIAG_UPLOAD_STREAMS", 2)

    def cleanup_expired(self) -> None:
        with self.lock:
            if not self.session:
                return
            expires_at = datetime.fromisoformat(str(self.session["expires_at"]))
            if expires_at <= utc_now():
                self.session["status"] = "expired"
                self.session = None

    def public_url(self, token: str) -> str:
        return f"https://{self.domain}/{self.diag_path}/{token}/"

    def create_session(self) -> dict[str, object]:
        with self.lock:
            token = token_urlsafe(18)
            now = utc_now()
            self.session = {
                "token": token,
                "status": "created",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=self.ttl_seconds)).isoformat(),
                "client_ip": "",
                "user_agent": "",
                "latency_ms": None,
                "download_mbps": None,
                "upload_mbps": None,
                "download_bytes": None,
                "upload_bytes": None,
                "completed_at": "",
                "public_url": self.public_url(token),
            }
            return dict(self.session)

    def get_session(self) -> dict[str, object] | None:
        self.cleanup_expired()
        with self.lock:
            return dict(self.session) if self.session else None

    def validate_public_token(self, token: str) -> dict[str, object] | None:
        self.cleanup_expired()
        with self.lock:
            if not self.session or self.session.get("token") != token:
                return None
            return dict(self.session)

    def touch_client(self, token: str, client_ip: str, user_agent: str) -> dict[str, object] | None:
        with self.lock:
            if not self.session or self.session.get("token") != token:
                return None
            if self.session.get("status") == "created":
                self.session["status"] = "running"
            if not self.session.get("client_ip"):
                self.session["client_ip"] = client_ip
            if not self.session.get("user_agent"):
                self.session["user_agent"] = user_agent
            return dict(self.session)

    def report_result(self, token: str, payload: dict[str, object], client_ip: str, user_agent: str) -> dict[str, object] | None:
        with self.lock:
            if not self.session or self.session.get("token") != token:
                return None
            self.session.update(
                {
                    "status": "completed",
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "latency_ms": payload.get("latency_ms"),
                    "download_mbps": payload.get("download_mbps"),
                    "upload_mbps": payload.get("upload_mbps"),
                    "download_bytes": payload.get("download_bytes"),
                    "upload_bytes": payload.get("upload_bytes"),
                    "completed_at": utc_timestamp(),
                }
            )
            return dict(self.session)


STATE = DiagnosticsState()


class DiagnosticsHandler(BaseHTTPRequestHandler):
    server_version = "TransitHubDiagnostics/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "ok", "time": utc_timestamp()})
            return
        if parsed.path == "/admin/health":
            if not self.require_admin():
                return
            self.send_json({"status": "ok", "time": utc_timestamp()})
            return
        if parsed.path == "/admin/session":
            if not self.require_admin():
                return
            self.send_json({"session": STATE.get_session()})
            return

        token, route_type, route_value = self.parse_public_route(parsed.path)
        if not token:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        session = STATE.validate_public_token(token)
        if not session:
            self.send_error(HTTPStatus.GONE, "Diagnostics session expired or not found.")
            return

        client_ip = self.client_ip()
        user_agent = self.headers.get("User-Agent", "")
        STATE.touch_client(token, client_ip, user_agent)

        if route_type == "page":
            self.send_html(INDEX_PATH.read_text(encoding="utf-8"))
            return
        if route_type == "asset":
            self.serve_asset(route_value)
            return
        if route_type == "api" and route_value == "config":
            self.send_json(
                {
                    "token": token,
                    "public_url": session["public_url"],
                    "download_bytes": STATE.download_bytes,
                    "upload_bytes": STATE.upload_bytes,
                    "download_streams": STATE.download_streams,
                    "upload_streams": STATE.upload_streams,
                    "expires_at": session["expires_at"],
                }
            )
            return
        if route_type == "api" and route_value == "ping":
            self.send_json({"status": "ok", "time": utc_timestamp()})
            return
        if route_type == "api" and route_value == "status":
            self.send_json({"session": STATE.get_session()})
            return
        if route_type == "api" and route_value == "download":
            byte_count = self.requested_bytes(parsed.query, STATE.download_bytes)
            self.stream_download(byte_count)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/admin/session":
            if not self.require_admin():
                return
            self.send_json({"session": STATE.create_session()}, status=HTTPStatus.CREATED)
            return

        token, route_type, route_value = self.parse_public_route(parsed.path)
        if not token:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        session = STATE.validate_public_token(token)
        if not session:
            self.send_error(HTTPStatus.GONE, "Diagnostics session expired or not found.")
            return

        client_ip = self.client_ip()
        user_agent = self.headers.get("User-Agent", "")
        STATE.touch_client(token, client_ip, user_agent)

        if route_type == "api" and route_value == "upload":
            received = self.drain_request_body()
            self.send_json({"received_bytes": received})
            return
        if route_type == "api" and route_value == "report":
            payload = self.read_json_body()
            updated = STATE.report_result(token, payload, client_ip, user_agent)
            if not updated:
                self.send_error(HTTPStatus.GONE, "Diagnostics session expired or not found.")
                return
            self.send_json({"session": updated})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def require_admin(self) -> bool:
        header = self.headers.get("X-Diagnostics-Admin-Token", "").strip()
        if not STATE.admin_token or header != STATE.admin_token:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid diagnostics admin token.")
            return False
        return True

    def client_ip(self) -> str:
        forwarded_for = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        return forwarded_for or self.headers.get("X-Real-IP", "").strip() or self.client_address[0]

    def parse_public_route(self, path: str) -> tuple[str, str, str]:
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            return "", "", ""
        token = parts[0]
        if len(parts) == 1:
            return token, "page", ""
        if parts[1] == "assets" and len(parts) == 3:
            return token, "asset", parts[2]
        if parts[1] == "api" and len(parts) == 3:
            return token, "api", parts[2]
        return "", "", ""

    def serve_asset(self, name: str) -> None:
        if name == "style.css":
            self.send_bytes(STYLE_PATH.read_bytes(), "text/css; charset=utf-8")
            return
        if name == "app.js":
            self.send_bytes(SCRIPT_PATH.read_bytes(), "application/javascript; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def requested_bytes(self, query: str, fallback: int) -> int:
        values = parse_qs(query)
        raw = values.get("bytes", [""])[0]
        try:
            requested = int(raw)
        except ValueError:
            requested = fallback
        upper_bound = max(fallback, 134217728)
        return max(1048576, min(requested, upper_bound))

    def drain_request_body(self) -> int:
        remaining = int(self.headers.get("Content-Length", "0") or "0")
        total = 0
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            total += len(chunk)
            remaining -= len(chunk)
        return total

    def read_json_body(self) -> dict[str, object]:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        if not raw:
            return {}
        loaded = json.loads(raw.decode("utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def stream_download(self, byte_count: int) -> None:
        chunk = b"0123456789abcdef" * 4096
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(byte_count))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        remaining = byte_count
        while remaining > 0:
            current = chunk if remaining >= len(chunk) else chunk[:remaining]
            self.wfile.write(current)
            remaining -= len(current)

    def send_html(self, html: str) -> None:
        self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

    def send_json(self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        rendered = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(rendered)))
        self.end_headers()
        self.wfile.write(rendered)

    def send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    port = env_int("DIAG_PORT", 8765)
    server = ThreadingHTTPServer(("0.0.0.0", port), DiagnosticsHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
