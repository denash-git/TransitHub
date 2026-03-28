from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest


SERVER_PATH = Path(__file__).resolve().parent.parent / "diagnostics" / "app" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("diagnostics_server_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class DiagnosticsServiceTests(unittest.TestCase):
    def test_session_lifecycle_is_in_memory_only(self) -> None:
        previous = dict(os.environ)
        try:
            os.environ["DOMAIN"] = "example.com"
            os.environ["DIAG_PATH"] = "speed-test"
            os.environ["DIAG_ADMIN_TOKEN"] = "token"
            module = load_server_module()
            state = module.DiagnosticsState()

            session = state.create_session()
            token = session["token"]
            self.assertEqual(session["status"], "created")
            self.assertIn("/speed-test/", session["public_url"])

            touched = state.touch_client(token, "127.0.0.1", "pytest")
            self.assertEqual(touched["status"], "running")

            result = state.report_result(
                token,
                {"latency_ms": 10.5, "download_mbps": 120.2, "upload_mbps": 85.1},
                "127.0.0.1",
                "pytest",
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["download_mbps"], 120.2)
            self.assertEqual(state.get_session()["upload_mbps"], 85.1)
        finally:
            os.environ.clear()
            os.environ.update(previous)


if __name__ == "__main__":
    unittest.main()
