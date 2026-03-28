from __future__ import annotations

import unittest

from install.cleanup import REQUIRED_FILES
from install.cli import PRUNE_TOP_LEVEL, PROJECT_ROOT


class CleanupTests(unittest.TestCase):
    def test_cleanup_prunes_installer_but_keeps_runtime_core(self) -> None:
        self.assertIn(PROJECT_ROOT / "install", PRUNE_TOP_LEVEL)
        self.assertIn(PROJECT_ROOT / "tests", PRUNE_TOP_LEVEL)
        self.assertIn(PROJECT_ROOT / "diagnostics" / "docker-compose.yml", REQUIRED_FILES)
        self.assertIn(PROJECT_ROOT / "transithub_runtime" / "__init__.py", REQUIRED_FILES)
        self.assertIn(PROJECT_ROOT / "transithub-menu.py", REQUIRED_FILES)


if __name__ == "__main__":
    unittest.main()
