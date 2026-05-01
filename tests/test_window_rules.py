"""Tests for window-rule editor serialization helpers."""

from __future__ import annotations

import unittest
import pytest

pytest.importorskip("gi")

from nirimod.kdl_parser import KdlNode, write_kdl
from nirimod.pages.window_rules import (
    DEFAULT_FLOATING_POSITION_RELATIVE_TO,
    FLOATING_POSITION_LOCATION_LABELS,
    SCREENCAST_BLOCK_KEY,
    _bool_action_active,
    _bool_action_node,
    _floating_position_setting,
    _make_floating_position_node,
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

    def test_floating_position_default_writes_no_override(self):
        self.assertIsNone(
            _make_floating_position_node(
                False, 0, 0, DEFAULT_FLOATING_POSITION_RELATIVE_TO
            )
        )

    def test_floating_position_locations_are_edges_plus_custom(self):
        self.assertEqual(
            FLOATING_POSITION_LOCATION_LABELS,
            ["Top", "Bottom", "Left", "Right", "Custom"],
        )

    def test_floating_position_writes_anchor_properties(self):
        node = _make_floating_position_node(True, 0, 0, "right")
        out = write_kdl([KdlNode("window-rule", children=[node])])

        self.assertIn(
            'default-floating-position x=0 y=0 relative-to="right"',
            out,
        )

    def test_floating_position_writes_custom_offset(self):
        node = _make_floating_position_node(True, 12, 34, "right")
        out = write_kdl([KdlNode("window-rule", children=[node])])

        self.assertIn(
            'default-floating-position x=12 y=34 relative-to="right"',
            out,
        )

    def test_floating_position_reads_existing_anchor(self):
        rule = KdlNode(
            "window-rule",
            children=[
                KdlNode(
                    "default-floating-position",
                    props={"x": 12, "y": 34, "relative-to": "bottom-right"},
                )
            ],
        )

        self.assertEqual(
            _floating_position_setting(rule),
            (True, 12, 34, "bottom-right"),
        )


if __name__ == "__main__":
    unittest.main()
