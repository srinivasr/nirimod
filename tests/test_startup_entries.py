"""Unit tests for startup program entry helpers."""

from __future__ import annotations

import unittest

from nirimod.kdl_parser import KdlNode
from nirimod.startup_entries import make_startup_node, startup_values_from_node


class TestStartupEntryDelay(unittest.TestCase):
    def test_delay_wraps_direct_command_as_shell_entry(self):
        node = make_startup_node("waybar --config /etc/waybar.json", False, 7)

        self.assertEqual(node.name, "spawn-sh-at-startup")
        self.assertEqual(node.args, ["sleep 7 && exec waybar --config /etc/waybar.json"])

    def test_delayed_direct_command_can_be_edited_without_sleep_prefix(self):
        node = KdlNode(
            "spawn-sh-at-startup",
            args=["sleep 12 && exec alacritty --class scratch"],
        )

        command, is_sh, delay = startup_values_from_node(node)

        self.assertEqual(command, "alacritty --class scratch")
        self.assertTrue(is_sh)
        self.assertEqual(delay, 12)

    def test_shell_command_delay_preserves_shell_syntax(self):
        node = make_startup_node("echo $PATH | grep local", True, 3)

        self.assertEqual(node.name, "spawn-sh-at-startup")
        self.assertEqual(node.args, ["sleep 3 && echo $PATH | grep local"])

    def test_direct_entry_form_text_quotes_arguments_with_spaces(self):
        node = KdlNode("spawn-at-startup", args=["launcher", "--name", "My App"])

        command, is_sh, delay = startup_values_from_node(node)

        self.assertEqual(command, "launcher --name 'My App'")
        self.assertFalse(is_sh)
        self.assertEqual(delay, 0)


if __name__ == "__main__":
    unittest.main()
