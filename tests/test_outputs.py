"""Tests for output snapping."""

from __future__ import annotations

import unittest

from nirimod.pages.outputs import OutputsPage


def _output(name: str, x: int, y: int) -> dict:
    width = 2560
    height = 1440
    scale = 1.1
    return {
        "name": name,
        "modes": [{"width": width, "height": height, "refresh_rate": 59951}],
        "current_mode": 0,
        "logical": {
            "x": x,
            "y": y,
            "width": round(width / scale),
            "height": round(height / scale),
            "scale": scale,
            "transform": "normal",
        },
    }


def _drag(outputs: list[dict], name: str, x: int, y: int) -> tuple[int, int]:
    page = object.__new__(OutputsPage)
    page._outputs = outputs
    page._drag_output = name
    page._drag_current_lx = x
    page._drag_current_ly = y
    page._drag_start_scale = 1
    page._canvas_scale = 1
    page._last_dx = 0
    page._last_dy = 0
    page._canvas = None

    page._on_drag_update(None, 0, 0)

    dragged = next(output for output in outputs if output["name"] == name)
    position = dragged["logical"]
    return position["x"], position["y"]


class TestOutputSnapping(unittest.TestCase):
    def test_snap_right_rounds_outward(self):
        outputs = [_output("left", 1652, -32), _output("right", 3975, -32)]

        x, _ = _drag(outputs, "right", 3975, -32)

        self.assertEqual(x, 3980)

    def test_snap_left_rounds_outward(self):
        outputs = [_output("left", 1655, -32), _output("right", 3980, -32)]

        x, _ = _drag(outputs, "left", 1655, -32)

        self.assertEqual(x, 1652)

    def test_snap_below_rounds_outward(self):
        outputs = [_output("top", 0, 0), _output("bottom", 0, 1305)]

        _, y = _drag(outputs, "bottom", 0, 1305)

        self.assertEqual(y, 1310)

    def test_snap_above_rounds_outward(self):
        outputs = [_output("top", 0, -1305), _output("bottom", 0, 0)]

        _, y = _drag(outputs, "top", 0, -1305)

        self.assertEqual(y, -1310)


if __name__ == "__main__":
    unittest.main()
