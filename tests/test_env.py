from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.env import defaults, ensure_generated, parse_env, update_env


class EnvTests(unittest.TestCase):
    def test_update_env_preserves_existing_values_and_appends_new_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "instance.env"
            path.write_text("DOMAIN=example.com\nTZ=UTC\n", encoding="utf-8")

            update_env(path, {"TZ": "Europe/Moscow", "NEW_KEY": "value"})
            loaded = parse_env(path)

            self.assertEqual(loaded["DOMAIN"], "example.com")
            self.assertEqual(loaded["TZ"], "Europe/Moscow")
            self.assertEqual(loaded["NEW_KEY"], "value")

    def test_ensure_generated_populates_diagnostics_runtime_fields(self) -> None:
        values = ensure_generated(defaults())

        self.assertTrue(values["DIAG_PATH"])
        self.assertTrue(values["DIAG_ADMIN_TOKEN"])
        self.assertTrue(values["DIAG_HOST_PORT"].isdigit())


if __name__ == "__main__":
    unittest.main()
