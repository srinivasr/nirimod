"""Tests for output layout cascading, overlap separation, and gap preservation."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from nirimod.kdl_parser import KdlNode, parse_kdl, write_kdl
from nirimod.output_layout import (
    cascade_positions,
    flush_links,
    separate_overlaps,
)

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from nirimod.pages.outputs import OutputsPage

    HAS_GI = True
except (ImportError, ValueError):
    HAS_GI = False
    OutputsPage = None  # type: ignore[assignment,misc]


class DummyWindow:
    def __init__(self, nodes: list[KdlNode]):
        self._nodes = nodes
        self.app_state = MagicMock()
        self.app_state.nodes = nodes
        self.app_state.undo = MagicMock()
        self.pushed_undo: list[tuple[str, str, str]] = []

    def get_nodes(self) -> list[KdlNode]:
        return self._nodes

    def push_undo(self, description: str, before: str, after: str):
        self.pushed_undo.append((description, before, after))

    def mark_clean(self):
        pass

    def mark_dirty(self):
        pass

    def show_toast(self, msg: str, timeout: int = 3):
        pass


class TestOutputLayout(unittest.TestCase):
    def test_flush_links_identifies_horizontal_and_vertical_neighbors(self):
        rects = [
            {"name": "main", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "right", "x": 1920, "y": 0, "w": 1920, "h": 1080},
            {"name": "bottom", "x": 0, "y": 1080, "w": 1920, "h": 1080},
        ]
        right, bottom = flush_links(rects)

        self.assertEqual(right["main"], ["right"])
        self.assertEqual(bottom["main"], ["bottom"])
        self.assertEqual(right["right"], [])
        self.assertEqual(bottom["bottom"], [])

    def test_cascade_positions_carries_neighbors_when_size_changes(self):
        rects = [
            {"name": "main", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "right", "x": 1920, "y": 0, "w": 1920, "h": 1080},
            {"name": "bottom", "x": 0, "y": 1080, "w": 1920, "h": 1080},
        ]
        links = flush_links(rects)
        deltas = {"main": (640, 360)}

        moved = cascade_positions(rects, deltas, links)

        self.assertIn("right", moved)
        self.assertIn("bottom", moved)

        right_rect = next(r for r in rects if r["name"] == "right")
        bottom_rect = next(r for r in rects if r["name"] == "bottom")

        self.assertEqual(right_rect["x"], 2560)
        self.assertEqual(bottom_rect["y"], 1440)

    def test_cascade_positions_leaves_detached_outputs_untouched(self):
        rects = [
            {"name": "main", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "isolated", "x": 3000, "y": 0, "w": 1920, "h": 1080},
        ]
        links = flush_links(rects)
        deltas = {"main": (640, 0)}

        moved = cascade_positions(rects, deltas, links)

        self.assertEqual(moved, [])
        isolated_rect = next(r for r in rects if r["name"] == "isolated")
        self.assertEqual(isolated_rect["x"], 3000)

    def test_separate_overlaps_pushes_mover_to_closest_edge(self):
        rects = [
            {"name": "fixed", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "moved", "x": 1000, "y": 0, "w": 1920, "h": 1080},
        ]
        order = {"fixed": 1, "moved": 2}

        moved = separate_overlaps(rects, order)

        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0][0], "moved")

        moved_rect = next(r for r in rects if r["name"] == "moved")
        self.assertEqual(moved_rect["x"], 1920)
        self.assertEqual(moved_rect["y"], 0)


@unittest.skipUnless(HAS_GI, "gi (GTK4/libadwaita) required for OutputsPage")
class TestOutputsPageNormalization(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            KdlNode("output", args=["DP-1"]),
            KdlNode("output", args=["HDMI-A-1"]),
        ]
        self.win = DummyWindow(self.nodes)
        self.page = object.__new__(OutputsPage)
        self.page._win = self.win
        self.page._size_deltas = {}
        self.page._pending_links = None
        self.page._touch_order = {}
        self.page._touch_seq = 0
        self.page._syncing_pos = False
        self.page._canvas = None
        self.page._outputs = [
            {
                "name": "DP-1",
                "logical": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            },
            {
                "name": "HDMI-A-1",
                "logical": {"x": 1920, "y": 0, "width": 1920, "height": 1080},
            },
        ]

    def test_normalize_preserves_intentional_gaps(self):
        self.page._outputs = [
            {
                "name": "DP-1",
                "logical": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            },
            {
                "name": "HDMI-A-1",
                "logical": {"x": 2500, "y": 0, "width": 1920, "height": 1080},
            },
        ]

        corrections = self.page._normalize_positions()

        self.assertEqual(corrections, [])
        self.assertEqual(self.page._outputs[1]["logical"]["x"], 2500)

    def test_normalize_shifts_negative_origins_to_zero(self):
        self.page._outputs = [
            {
                "name": "DP-1",
                "logical": {"x": -500, "y": -200, "width": 1920, "height": 1080},
            },
            {
                "name": "HDMI-A-1",
                "logical": {"x": 1420, "y": -200, "width": 1920, "height": 1080},
            },
        ]

        corrections = self.page._normalize_positions()

        self.assertIn("DP-1", corrections)
        self.assertIn("HDMI-A-1", corrections)
        self.assertEqual(self.page._outputs[0]["logical"]["x"], 0)
        self.assertEqual(self.page._outputs[0]["logical"]["y"], 0)
        self.assertEqual(self.page._outputs[1]["logical"]["x"], 1920)
        self.assertEqual(self.page._outputs[1]["logical"]["y"], 0)

    def test_mode_change_cascades_flush_neighbors(self):
        self.page._pending_links = flush_links(self.page._desired_rects())
        self.page._size_deltas["DP-1"] = (-640, 0)
        self.page._outputs[0]["logical"]["width"] = 1280

        corrections = self.page._normalize_positions()

        self.assertIn("HDMI-A-1", corrections)
        self.assertEqual(self.page._outputs[1]["logical"]["x"], 1280)


class TestOutputKdlIntegration(unittest.TestCase):
    def test_kdl_mode_change_cascades_and_serializes(self):
        kdl_text = (
            'output "DP-1" {\n'
            '    mode "1920x1080@60.000"\n'
            "    position x=0 y=0\n"
            "}\n"
            'output "HDMI-A-1" {\n'
            '    mode "1920x1080@60.000"\n'
            "    position x=1920 y=0\n"
            "}\n"
        )
        nodes = parse_kdl(kdl_text)
        hdmi = next(n for n in nodes if n.args and n.args[0] == "HDMI-A-1")

        rects = [
            {"name": "DP-1", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "HDMI-A-1", "x": 1920, "y": 0, "w": 1920, "h": 1080},
        ]
        links = flush_links(rects)
        deltas = {"DP-1": (640, 360)}
        rects[0]["w"] = 2560
        rects[0]["h"] = 1440

        moved = cascade_positions(rects, deltas, links)
        self.assertIn("HDMI-A-1", moved)

        hdmi.get_child("position").props["x"] = rects[1]["x"]
        hdmi.get_child("position").props["y"] = rects[1]["y"]

        out = write_kdl(nodes)
        self.assertIn("position x=2560 y=0", out)

        reparsed = parse_kdl(out)
        reparsed_hdmi = next(n for n in reparsed if n.args and n.args[0] == "HDMI-A-1")
        self.assertEqual(reparsed_hdmi.get_child("position").props["x"], 2560)
        self.assertEqual(reparsed_hdmi.get_child("position").props["y"], 0)

    def test_kdl_preserves_intentional_gaps(self):
        kdl_text = (
            'output "DP-1" {\n'
            "    position x=0 y=0\n"
            "}\n"
            'output "HDMI-A-1" {\n'
            "    position x=3500 y=0\n"
            "}\n"
        )
        nodes = parse_kdl(kdl_text)
        rects = [
            {"name": "DP-1", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "HDMI-A-1", "x": 3500, "y": 0, "w": 1920, "h": 1080},
        ]
        moved = separate_overlaps(rects, {"DP-1": 1, "HDMI-A-1": 2})
        self.assertEqual(moved, [])
        self.assertEqual(rects[1]["x"], 3500)

        out = write_kdl(nodes)
        self.assertIn("position x=3500 y=0", out)

    def test_kdl_overlap_resolution_writes_separated_position(self):
        kdl_text = (
            'output "DP-1" {\n'
            "    position x=0 y=0\n"
            "}\n"
            'output "HDMI-A-1" {\n'
            "    position x=1900 y=0\n"
            "}\n"
        )
        nodes = parse_kdl(kdl_text)
        hdmi = next(n for n in nodes if n.args and n.args[0] == "HDMI-A-1")

        rects = [
            {"name": "DP-1", "x": 0, "y": 0, "w": 1920, "h": 1080},
            {"name": "HDMI-A-1", "x": 1900, "y": 0, "w": 1920, "h": 1080},
        ]
        moved = separate_overlaps(rects, {"DP-1": 1, "HDMI-A-1": 2})
        self.assertEqual(len(moved), 1)
        self.assertEqual(rects[1]["x"], 1920)

        hdmi.get_child("position").props["x"] = rects[1]["x"]
        out = write_kdl(nodes)
        self.assertIn("position x=1920 y=0", out)

    def test_kdl_negative_origin_shifted_to_zero(self):
        kdl_text = (
            'output "DP-1" {\n'
            "    position x=-500 y=-200\n"
            "}\n"
            'output "HDMI-A-1" {\n'
            "    position x=1420 y=-200\n"
            "}\n"
        )
        nodes = parse_kdl(kdl_text)
        dp = next(n for n in nodes if n.args and n.args[0] == "DP-1")
        hdmi = next(n for n in nodes if n.args and n.args[0] == "HDMI-A-1")

        rects = [
            {"name": "DP-1", "x": -500, "y": -200, "w": 1920, "h": 1080},
            {"name": "HDMI-A-1", "x": 1420, "y": -200, "w": 1920, "h": 1080},
        ]
        min_x = min(r["x"] for r in rects)
        min_y = min(r["y"] for r in rects)
        if min_x < 0 or min_y < 0:
            shift_x = -min_x if min_x < 0 else 0
            shift_y = -min_y if min_y < 0 else 0
            for r in rects:
                r["x"] += shift_x
                r["y"] += shift_y

        dp.get_child("position").props["x"] = rects[0]["x"]
        dp.get_child("position").props["y"] = rects[0]["y"]
        hdmi.get_child("position").props["x"] = rects[1]["x"]
        hdmi.get_child("position").props["y"] = rects[1]["y"]

        out = write_kdl(nodes)
        self.assertIn("position x=0 y=0", out)
        self.assertIn("position x=1920 y=0", out)


if __name__ == "__main__":
    unittest.main()
