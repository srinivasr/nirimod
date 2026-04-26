"""Unit tests for updater terminal selection."""

from __future__ import annotations

import os
import tempfile
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
