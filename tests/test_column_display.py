"""Tests for Niri column display config helpers."""

from __future__ import annotations

import unittest

from nirimod.column_display import (
    COLUMN_DISPLAY_RULE_LABELS,
    column_display_index,
    column_display_rule_index,
    column_display_rule_value,
    column_display_value,
    normalize_column_display,
)
from nirimod.kdl_parser import KdlNode, set_child_arg, write_kdl


class TestColumnDisplay(unittest.TestCase):
    def test_layout_display_reads_tabbed_value(self):
        self.assertEqual(column_display_index("tabbed"), 1)
        self.assertEqual(column_display_value(1), "tabbed")

    def test_unknown_layout_display_defaults_to_normal(self):
        self.assertEqual(normalize_column_display("sideways"), None)
        self.assertEqual(column_display_index("sideways"), 0)
        self.assertEqual(column_display_value(99), "normal")

    def test_rule_display_supports_use_layout_default(self):
        self.assertEqual(column_display_rule_index(None), 0)
        self.assertEqual(column_display_rule_value(0), None)

    def test_rule_display_maps_tabbed_selection(self):
        selected = COLUMN_DISPLAY_RULE_LABELS.index("Tabbed")

        self.assertEqual(column_display_rule_index("tabbed"), selected)
        self.assertEqual(column_display_rule_value(selected), "tabbed")

    def test_default_column_display_serializes_as_layout_string(self):
        layout = KdlNode("layout")
        set_child_arg(layout, "default-column-display", "tabbed")

        out = write_kdl([layout])

        self.assertIn('default-column-display "tabbed"', out)
        self.assertNotIn("default-column-display tabbed", out)


if __name__ == "__main__":
    unittest.main()
