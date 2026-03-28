from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from install.cli import InstallerError, determine_install_mode, enforce_installed_lockout
from transithub_runtime.install_state import begin_install
from transithub_runtime.install_state import mark_failed
from transithub_runtime.install_state import mark_installed
from transithub_runtime.install_state import mark_step
from transithub_runtime.install_state import read_state
from transithub_runtime.install_state import STATUS_FAILED
from transithub_runtime.install_state import STATUS_FRESH
from transithub_runtime.install_state import STATUS_IN_PROGRESS
from transithub_runtime.install_state import STATUS_INSTALLED


class InstallStateTests(unittest.TestCase):
    def test_state_flow_tracks_progress_failure_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "install-state.json"

            started = begin_install("fresh", state_path)
            self.assertEqual(started["status"], STATUS_IN_PROGRESS)
            self.assertTrue(started["started_at"])

            progressed = mark_step("Prepare host dependencies and firewall", state_path)
            self.assertEqual(progressed["last_failed_step"], "Prepare host dependencies and firewall")

            failed = mark_failed("Prepare host dependencies and firewall", "apt failed", state_path)
            self.assertEqual(failed["status"], STATUS_FAILED)
            self.assertEqual(failed["last_error"], "apt failed")

            installed = mark_installed(state_path)
            self.assertEqual(installed["status"], STATUS_INSTALLED)
            self.assertTrue(installed["completed_at"])

            reloaded = read_state(state_path)
            self.assertEqual(reloaded["status"], STATUS_INSTALLED)
            self.assertEqual(reloaded["last_error"], "")

    def test_determine_install_mode_enforces_fresh_resume_lifecycle(self) -> None:
        self.assertEqual(determine_install_mode("auto", {"status": STATUS_FRESH}), "fresh")
        self.assertEqual(determine_install_mode("auto", {"status": STATUS_IN_PROGRESS}), "resume")
        self.assertEqual(determine_install_mode("auto", {"status": STATUS_FAILED}), "resume")

        with self.assertRaises(InstallerError):
            determine_install_mode("fresh", {"status": STATUS_FAILED})

        with self.assertRaises(InstallerError):
            determine_install_mode("resume", {"status": STATUS_FRESH})

    def test_installed_lockout_re_prunes_restored_installer_files(self) -> None:
        with mock.patch("install.cli.prune_deployed_tree") as prune_deployed_tree:
            with self.assertRaises(InstallerError):
                enforce_installed_lockout({"status": STATUS_INSTALLED})
            prune_deployed_tree.assert_called_once()


if __name__ == "__main__":
    unittest.main()
