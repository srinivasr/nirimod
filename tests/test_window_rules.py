"""Tests for window-rule editor serialization helpers."""

from __future__ import annotations

import unittest
import pytest

pytest.importorskip("gi")

from nirimod.kdl_parser import KdlNode, write_kdl
from nirimod.pages.window_rules import (
    CUSTOM_FLOATING_POSITION_INDEX,
    DEFAULT_FLOATING_POSITION_RELATIVE_TO,
    FLOATING_POSITION_CUSTOM_FIELD_LABELS,
    FLOATING_POSITION_LOCATION_LABELS,
    SCREENCAST_BLOCK_KEY,
    SIZE_PERCENT_PRESETS,
    _bool_action_active,
    _bool_action_node,
    _floating_position_location_index,
    _floating_position_setting,
    _make_floating_position_node,
    _make_size_node,
    _window_size_setting,
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

    def test_window_rule_size_default_writes_no_override(self):
        self.assertIsNone(_make_size_node("default-column-width", "default", None))
        self.assertIsNone(_make_size_node("default-window-height", "default", None))

    def test_window_rule_size_presets_include_full_size(self):
        self.assertIn(("100%", 1.0), SIZE_PERCENT_PRESETS)

    def test_window_rule_width_preset_writes_proportion_node(self):
        node = _make_size_node("default-column-width", "proportion", 0.25)
        out = write_kdl([KdlNode("window-rule", children=[node])])

        self.assertIn("default-column-width", out)
        self.assertIn("proportion 0.25", out)
        self.assertNotIn("default-column-width 0.25", out)

    def test_window_rule_height_preset_writes_proportion_node(self):
        node = _make_size_node("default-window-height", "proportion", 1.0)
        out = write_kdl([KdlNode("window-rule", children=[node])])

        self.assertIn("default-window-height", out)
        self.assertIn("proportion 1.0", out)
        self.assertNotIn("default-window-height 1.0", out)

    def test_window_rule_size_reads_nested_fixed_value(self):
        rule = KdlNode(
            "window-rule",
            children=[
                KdlNode(
                    "default-window-height",
                    children=[KdlNode("fixed", args=[270])],
                )
            ],
        )

        self.assertEqual(
            _window_size_setting(rule, "default-window-height"),
            ("fixed", 270),
        )

    def test_window_rule_size_reads_legacy_direct_fixed_value(self):
        rule = KdlNode(
            "window-rule",
            children=[KdlNode("default-window-height", args=[270])],
        )

        self.assertEqual(
            _window_size_setting(rule, "default-window-height"),
            ("fixed", 270),
        )

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

    def test_floating_position_custom_fields_are_offsets_only(self):
        self.assertEqual(
            FLOATING_POSITION_CUSTOM_FIELD_LABELS,
            ["X Offset (px)", "Y Offset (px)"],
        )

    def test_floating_position_edge_locations_use_zero_offsets(self):
        self.assertEqual(
            _floating_position_location_index(0, 0, "right"),
            FLOATING_POSITION_LOCATION_LABELS.index("Right"),
        )

    def test_floating_position_edge_offsets_are_custom(self):
        self.assertEqual(
            _floating_position_location_index(20, 0, "right"),
            CUSTOM_FLOATING_POSITION_INDEX,
        )

    def test_floating_position_custom_location_is_for_non_edge_anchors(self):
        self.assertEqual(
            _floating_position_location_index(12, 34, "bottom-right"),
            CUSTOM_FLOATING_POSITION_INDEX,
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
