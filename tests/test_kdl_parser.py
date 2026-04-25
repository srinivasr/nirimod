"""Unit tests for the KDL parser and writer.

Tests the core parse → mutate → write round-trip logic that underpins
all config changes in NiriMod.
"""

from __future__ import annotations

import unittest

from nirimod.kdl_parser import (
    KdlNode,
    KdlRawString,
    find_or_create,
    parse_kdl,
    remove_child,
    set_child_arg,
    set_node_flag,
    write_kdl,
)


class TestKdlRoundTrip(unittest.TestCase):
    """parse_kdl → write_kdl should produce semantically equivalent output."""

    def _roundtrip(self, text: str) -> list[KdlNode]:
        nodes = parse_kdl(text)
        out = write_kdl(nodes)
        return parse_kdl(out)

    def test_simple_node(self):
        nodes = parse_kdl("prefer-no-csd\n")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "prefer-no-csd")

    def test_node_with_string_arg(self):
        nodes = parse_kdl('output "eDP-1" {\n    scale 2.0\n}\n')
        self.assertEqual(nodes[0].name, "output")
        self.assertEqual(nodes[0].args[0], "eDP-1")
        scale = nodes[0].get_child("scale")
        self.assertIsNotNone(scale)
        self.assertAlmostEqual(scale.args[0], 2.0)

    def test_boolean_values(self):
        nodes = parse_kdl(
            "input {\n    keyboard {\n        repeat-rate 30\n        xkb-numlock true\n    }\n}\n"
        )
        kb = nodes[0].get_child("keyboard")
        self.assertIsNotNone(kb)
        numlock = kb.get_child("xkb-numlock")
        self.assertIsNotNone(numlock)
        self.assertIs(numlock.args[0], True)

    def test_raw_string(self):
        text = "spawn-at-startup r#\"bash -c 'echo hi'\"#\n"
        nodes = parse_kdl(text)
        self.assertIsInstance(nodes[0].args[0], KdlRawString)

    def test_raw_string_property_preserves_backslash(self):
        src = 'match app-id="steam" title=r#"^notificationtoasts_\\d+_desktop$"#\n'
        nodes = parse_kdl(src)
        title = nodes[0].props["title"]
        self.assertIsInstance(title, KdlRawString)
        self.assertEqual(title, r"^notificationtoasts_\d+_desktop$")
        self.assertIn(r'title=r"^notificationtoasts_\d+_desktop$"', write_kdl(nodes))

    def test_write_preserves_children(self):
        src = "layout {\n    gaps 16\n    border {\n        width 2\n    }\n}\n"
        nodes = self._roundtrip(src)
        layout = nodes[0]
        self.assertEqual(layout.name, "layout")
        border = layout.get_child("border")
        self.assertIsNotNone(border)
        self.assertEqual(border.get_child("width").args[0], 2)

    def test_null_value(self):
        nodes = parse_kdl("cursor-warps null\n")
        self.assertIsNone(nodes[0].args[0])

    def test_props(self):
        nodes = parse_kdl("position x=0 y=1080\n")
        self.assertEqual(nodes[0].props["x"], 0)
        self.assertEqual(nodes[0].props["y"], 1080)

    def test_empty_input(self):
        nodes = parse_kdl("")
        self.assertEqual(nodes, [])
        self.assertIn("NiriMod", write_kdl(nodes))

    def test_comments_are_preserved_as_trivia(self):
        src = "// top-level comment\nprefer-no-csd\n"
        out = write_kdl(parse_kdl(src))
        self.assertIn("prefer-no-csd", out)


class TestMutationHelpers(unittest.TestCase):
    """Tests for find_or_create, set_child_arg, remove_child, set_node_flag."""

    def setUp(self):
        self.nodes = parse_kdl("layout {\n    gaps 8\n}\n")

    def test_find_existing(self):
        node = find_or_create(self.nodes, "layout")
        self.assertEqual(node.name, "layout")

    def test_create_missing(self):
        node = find_or_create(self.nodes, "input")
        self.assertEqual(node.name, "input")
        self.assertIn(node, self.nodes)

    def test_find_or_create_nested(self):
        node = find_or_create(self.nodes, "layout", "struts")
        self.assertEqual(node.name, "struts")

    def test_set_child_arg_creates(self):
        parent = self.nodes[0]
        set_child_arg(parent, "border-rule", 4)
        child = parent.get_child("border-rule")
        self.assertIsNotNone(child)
        self.assertEqual(child.args[0], 4)

    def test_set_child_arg_updates(self):
        parent = self.nodes[0]
        set_child_arg(parent, "gaps", 16)
        self.assertEqual(parent.get_child("gaps").args[0], 16)

    def test_remove_child(self):
        parent = self.nodes[0]
        remove_child(parent, "gaps")
        self.assertIsNone(parent.get_child("gaps"))

    def test_remove_nonexistent_is_noop(self):
        parent = self.nodes[0]
        remove_child(parent, "nonexistent")
        self.assertEqual(len(parent.children), 1)

    def test_set_node_flag_add(self):
        parent = KdlNode("input")
        set_node_flag(parent, "warp-mouse-to-focus", True)
        self.assertIsNotNone(parent.get_child("warp-mouse-to-focus"))

    def test_set_node_flag_remove(self):
        parent = KdlNode("input")
        parent.children.append(KdlNode("warp-mouse-to-focus"))
        set_node_flag(parent, "warp-mouse-to-focus", False)
        self.assertIsNone(parent.get_child("warp-mouse-to-focus"))

    def test_set_node_flag_idempotent_add(self):
        parent = KdlNode("input")
        set_node_flag(parent, "warp-mouse-to-focus", True)
        set_node_flag(parent, "warp-mouse-to-focus", True)
        count = sum(1 for c in parent.children if c.name == "warp-mouse-to-focus")
        self.assertEqual(count, 1)


class TestWriteKdl(unittest.TestCase):
    """Tests for the KDL serializer."""

    def test_write_empty(self):
        out = write_kdl([])
        self.assertIn("NiriMod", out)

    def test_write_simple(self):
        nodes = [KdlNode("prefer-no-csd")]
        out = write_kdl(nodes)
        self.assertIn("prefer-no-csd", out)

    def test_write_raw_string(self):
        # A value containing a double-quote triggers the hash-delimited r#"..."# form
        node = KdlNode("env", args=[KdlRawString('value with "double" quotes')])
        out = write_kdl([node])
        self.assertIn('r#"', out)

    def test_write_nested(self):
        parent = KdlNode("layout")
        parent.children.append(KdlNode("gaps", args=[16]))
        out = write_kdl([parent])
        self.assertIn("gaps", out)
        self.assertIn("16", out)


if __name__ == "__main__":
    unittest.main()
