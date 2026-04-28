"""Tests for global window effect rule helpers."""

from __future__ import annotations

import unittest

from nirimod.kdl_parser import KdlNode, parse_kdl, write_kdl
from nirimod.window_effects import (
    focused_window_blur_enabled,
    get_global_draw_border_with_background,
    get_global_corner_radius,
    get_global_window_opacity,
    global_window_blur_enabled,
    global_window_xray_enabled,
    set_focused_window_blur,
    set_global_draw_border_with_background,
    set_global_corner_radius,
    set_global_window_blur,
    set_global_window_opacity,
    set_global_window_xray,
)


class TestGlobalWindowEffects(unittest.TestCase):
    def test_enabling_blur_creates_matchless_window_rule(self):
        nodes: list[KdlNode] = []

        set_global_window_blur(nodes, True)

        out = write_kdl(nodes)
        self.assertIn("window-rule", out)
        self.assertIn("background-effect", out)
        self.assertIn("blur true", out)
        self.assertNotIn("draw-border-with-background", out)
        self.assertTrue(global_window_blur_enabled(nodes))

    def test_disabling_blur_preserves_other_window_effect_settings(self):
        nodes = parse_kdl(
            """
window-rule {
    geometry-corner-radius 16
    draw-border-with-background false
    background-effect {
        blur true
        xray false
    }
}
"""
        )

        set_global_window_blur(nodes, False)

        rule = nodes[0]
        self.assertEqual(rule.child_arg("geometry-corner-radius"), 16)
        self.assertIsNotNone(rule.get_child("draw-border-with-background"))
        self.assertIsNotNone(rule.get_child("background-effect"))
        self.assertIsNone(rule.get_child("background-effect").get_child("blur"))
        self.assertIsNotNone(rule.get_child("background-effect").get_child("xray"))
        self.assertFalse(global_window_blur_enabled(nodes))

    def test_corner_radius_writes_clip_and_can_be_removed(self):
        nodes: list[KdlNode] = []

        set_global_corner_radius(nodes, 16)

        self.assertEqual(get_global_corner_radius(nodes), 16)
        out = write_kdl(nodes)
        self.assertIn("geometry-corner-radius 16", out)
        self.assertIn("clip-to-geometry true", out)

        set_global_corner_radius(nodes, 0)

        self.assertEqual(nodes, [])

    def test_matched_rules_are_not_reused_as_global_effect_rules(self):
        nodes = parse_kdl(
            """
window-rule {
    match app-id="Alacritty"
    background-effect {
        blur true
    }
}
"""
        )

        set_global_corner_radius(nodes, 12)

        self.assertEqual(len([n for n in nodes if n.name == "window-rule"]), 2)
        self.assertIsNone(nodes[0].get_child("geometry-corner-radius"))
        self.assertEqual(get_global_corner_radius(nodes), 12)

    def test_global_opacity_is_removed_when_opaque(self):
        nodes: list[KdlNode] = []

        set_global_window_opacity(nodes, 0.9)

        self.assertEqual(get_global_window_opacity(nodes), 0.9)
        self.assertIn("opacity 0.9", write_kdl(nodes))

        set_global_window_opacity(nodes, 1.0)

        self.assertEqual(nodes, [])

    def test_draw_border_with_background_can_be_toggled(self):
        nodes: list[KdlNode] = []

        self.assertTrue(get_global_draw_border_with_background(nodes))

        set_global_draw_border_with_background(nodes, False)

        self.assertFalse(get_global_draw_border_with_background(nodes))
        self.assertIn("draw-border-with-background false", write_kdl(nodes))

        set_global_draw_border_with_background(nodes, True)

        self.assertTrue(get_global_draw_border_with_background(nodes))
        self.assertEqual(nodes, [])

    def test_xray_false_is_written_with_blur(self):
        nodes: list[KdlNode] = []

        set_global_window_blur(nodes, True)
        set_global_window_xray(nodes, False)

        out = write_kdl(nodes)
        self.assertIn("blur true", out)
        self.assertIn("xray false", out)
        self.assertFalse(global_window_xray_enabled(nodes))

    def test_xray_toggle_does_not_enable_blur(self):
        nodes: list[KdlNode] = []

        set_global_window_xray(nodes, True)

        out = write_kdl(nodes)
        self.assertIn("xray true", out)
        self.assertNotIn("blur true", out)
        self.assertFalse(global_window_blur_enabled(nodes))

    def test_generated_global_window_effect_rule_is_compact(self):
        nodes: list[KdlNode] = []

        set_global_corner_radius(nodes, 16)
        set_global_draw_border_with_background(nodes, False)
        set_global_window_blur(nodes, True)
        set_global_window_xray(nodes, False)
        set_global_window_opacity(nodes, 0.75)

        self.assertEqual(
            write_kdl(nodes).strip(),
            """window-rule {
    geometry-corner-radius 16
    clip-to-geometry true
    draw-border-with-background false
    opacity 0.75
    background-effect {
        blur true
        xray false
    }
}""",
        )

    def test_focused_blur_rule_does_not_duplicate_global_effect_settings(self):
        nodes: list[KdlNode] = []
        set_global_window_blur(nodes, True)
        set_global_window_xray(nodes, False)
        set_global_window_opacity(nodes, 0.75)

        set_focused_window_blur(nodes, True)

        out = write_kdl(nodes)
        self.assertIn("match is-focused=true", out)
        self.assertEqual(out.count("opacity 0.75"), 1)
        self.assertEqual(out.count("blur true"), 2)
        self.assertEqual(out.count("xray false"), 1)
        self.assertTrue(focused_window_blur_enabled(nodes))

    def test_disabling_focused_blur_preserves_other_focused_rule_settings(self):
        nodes = parse_kdl(
            """
window-rule {
    match is-focused=true
    block-out-from "screen-capture"
    draw-border-with-background false
    opacity 0.75
    background-effect {
        blur true
        xray false
    }
}
"""
        )

        set_focused_window_blur(nodes, False)

        out = write_kdl(nodes)
        self.assertIn('block-out-from "screen-capture"', out)
        self.assertIn("draw-border-with-background false", out)
        self.assertIn("opacity 0.75", out)
        self.assertNotIn("blur true", out)
        self.assertIn("xray false", out)
        self.assertFalse(focused_window_blur_enabled(nodes))


if __name__ == "__main__":
    unittest.main()
