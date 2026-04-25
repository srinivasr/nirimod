"""Tests for window-rule editor serialization helpers."""

from __future__ import annotations

import unittest

from nirimod.kdl_parser import KdlNode, write_kdl
from nirimod.pages.window_rules import (
    SCREENCAST_BLOCK_KEY,
    _bool_action_active,
    _bool_action_node,
)


class TestWindowRuleActions(unittest.TestCase):
    def test_screencast_block_action_writes_valid_niri_syntax(self):
        node = _bool_action_node(SCREENCAST_BLOCK_KEY)
        out = write_kdl([KdlNode("window-rule", children=[node])])

        self.assertIn('block-out-from "screencast"', out)
        self.assertNotIn("block-out-from-screencast", out)

    def test_screencast_block_action_reads_current_syntax(self):
        rule = KdlNode(
            "window-rule", children=[KdlNode("block-out-from", args=["screencast"])]
        )

        self.assertTrue(_bool_action_active(rule, SCREENCAST_BLOCK_KEY))

    def test_screencast_block_action_reads_legacy_syntax(self):
        rule = KdlNode(
            "window-rule", children=[KdlNode("block-out-from-screencast", args=[True])]
        )

        self.assertTrue(_bool_action_active(rule, SCREENCAST_BLOCK_KEY))


if __name__ == "__main__":
    unittest.main()
