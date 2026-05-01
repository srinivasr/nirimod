"""Unit tests for updater terminal selection."""

from __future__ import annotations

import os
import subprocess
import tempfile
import pytest

pytest.importorskip("gi")

import unittest
from unittest.mock import patch

from nirimod import updater


class TestTerminalCandidates(unittest.TestCase):
    def test_terminal_env_is_preferred(self):
        with patch.dict(os.environ, {"TERMINAL": "ghostty"}, clear=False):
            candidates = list(updater._terminal_candidates())

        self.assertEqual(candidates[0], "ghostty")
        self.assertIn("xdg-terminal-exec", candidates)

    def test_ghostty_is_a_fallback_terminal(self):
        self.assertIn("ghostty", updater.FALLBACK_TERMINALS)


class TestBuildTerminalCommand(unittest.TestCase):
    def test_xdg_terminal_exec_gets_script_directly(self):
        command = updater._build_terminal_command("xdg-terminal-exec", "/tmp/update.sh")

        self.assertEqual(command, ["xdg-terminal-exec", "/tmp/update.sh"])

    def test_regular_terminal_uses_execute_flag(self):
        command = updater._build_terminal_command("ghostty", "/tmp/update.sh")

        self.assertEqual(command, ["ghostty", "-e", "/tmp/update.sh"])

    def test_terminal_command_with_existing_execute_flag(self):
        command = updater._build_terminal_command(
            "ghostty --gtk-single-instance=false -e", "/tmp/update.sh"
        )

        self.assertEqual(
            command, ["ghostty", "--gtk-single-instance=false", "-e", "/tmp/update.sh"]
        )

    def test_invalid_terminal_command_is_ignored(self):
        command = updater._build_terminal_command("ghostty '", "/tmp/update.sh")

        self.assertIsNone(command)


class TestUpdateAvailability(unittest.TestCase):
    def _run_git(self, repo: str, *args: str):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit(self, repo: str, message: str) -> str:
        self._run_git(repo, "commit", "--allow-empty", "-m", message)
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()

    def _make_repo(self) -> str:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo = temp_dir.name
        self._run_git(repo, "init")
        self._run_git(repo, "config", "user.email", "test@example.com")
        self._run_git(repo, "config", "user.name", "Test User")
        return repo

    def test_branch_ahead_of_remote_main_is_not_update(self):
        repo = self._make_repo()
        remote_hash = self._commit(repo, "remote main")
        local_hash = self._commit(repo, "local branch")

        self.assertFalse(updater._update_available(local_hash, remote_hash, repo))

    def test_dirty_worktree_still_gets_remote_update(self):
        repo = self._make_repo()
        local_hash = self._commit(repo, "installed version")
        remote_hash = self._commit(repo, "remote main")
        self._run_git(repo, "checkout", "--detach", local_hash)
        with open(os.path.join(repo, "local-change.txt"), "w") as fh:
            fh.write("local edit\n")

        self.assertTrue(updater._update_available(local_hash, remote_hash, repo))


class TestLaunchUpdaterInTerminal(unittest.TestCase):
    def test_launch_uses_terminal_env(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {"TERMINAL": "ghostty"}, clear=False),
            patch.object(updater.tempfile, "gettempdir", return_value=temp_dir),
            patch.object(updater.shutil, "which", return_value="/usr/bin/ghostty"),
            patch.object(updater.subprocess, "Popen") as popen,
        ):
            updater.launch_updater_in_terminal()

        popen.assert_called_once_with(
            ["ghostty", "-e", os.path.join(temp_dir, "nirimod_update.sh")]
        )


if __name__ == "__main__":
    unittest.main()
