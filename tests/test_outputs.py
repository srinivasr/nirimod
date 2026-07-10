"""Tests for output snapping."""

from __future__ import annotations

import math
import unittest

import pytest

pytest.importorskip("gi")

from nirimod.pages.outputs import OutputsPage


def _output(
    name: str,
    x: float,
    y: float,
    width: int = 2560,
    height: int = 1440,
    scale: float = 1.1,
    transform: str = "normal",
) -> dict:
    logical_width = width / scale
    logical_height = height / scale
    if transform in ["90", "270", "flipped-90", "flipped-270"]:
        logical_width, logical_height = logical_height, logical_width

    return {
        "name": name,
        "modes": [{"width": width, "height": height, "refresh_rate": 59951}],
        "current_mode": 0,
        "logical": {
            "x": x,
            "y": y,
            "width": round(logical_width),
            "height": round(logical_height),
            "scale": scale,
            "transform": transform,
        },
    }


def _logical_size(output: dict) -> tuple[float, float]:
    mode = output["modes"][output["current_mode"]]
    width = mode["width"]
    height = mode["height"]
    transform = output["logical"]["transform"]
    if transform in ["90", "270", "flipped-90", "flipped-270"]:
        width, height = height, width
    scale = output["logical"]["scale"]
    return width / scale, height / scale


def _overlaps(first: dict, second: dict) -> bool:
    first_width, first_height = _logical_size(first)
    second_width, second_height = _logical_size(second)
    first_x = first["logical"]["x"]
    first_y = first["logical"]["y"]
    second_x = second["logical"]["x"]
    second_y = second["logical"]["y"]

    return not (
        first_x + math.ceil(first_width) <= second_x
        or second_x + math.ceil(second_width) <= first_x
        or first_y + math.ceil(first_height) <= second_y
        or second_y + math.ceil(second_height) <= first_y
    )


def _drag(outputs: list[dict], name: str, x: float, y: float) -> tuple[float, float]:
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

    def test_distant_output_does_not_supply_x_snap(self):
        exact_width = 2560 / 1.1
        upper = _output("upper", 0, 0)
        right = _output("right", 4655, 2000)
        dragged = _output("dragged", exact_width, 2000)
        outputs = [upper, right, dragged]

        position = _drag(outputs, "dragged", exact_width, 2000)

        self.assertEqual(position, (2327, 2000))
        self.assertFalse(_overlaps(dragged, upper))
        self.assertFalse(_overlaps(dragged, right))

    def test_distant_output_does_not_supply_y_snap(self):
        exact_height = 1440 / 1.1
        left = _output("left", 0, 0)
        below = _output("below", 3000, 2619)
        dragged = _output("dragged", 3000, exact_height)
        outputs = [left, below, dragged]

        position = _drag(outputs, "dragged", 3000, exact_height)

        self.assertEqual(position, (3000, 1309))
        self.assertFalse(_overlaps(dragged, left))
        self.assertFalse(_overlaps(dragged, below))

    def test_snap_left_of_vertical_stack_at_each_row(self):
        row_height = math.ceil(1440 / 1.1)

        for row in range(3):
            with self.subTest(row=row):
                stack = [
                    _output(f"stack-{index}", 0, index * row_height)
                    for index in range(3)
                ]
                dragged = _output("dragged", -2325, row * row_height)
                outputs = [*stack, dragged]

                position = _drag(outputs, "dragged", -2325, row * row_height)

                self.assertEqual(position, (-2328, row * row_height))
                self.assertTrue(all(not _overlaps(dragged, output) for output in stack))

    def test_snap_above_horizontal_row_at_each_column(self):
        column_width = math.ceil(2560 / 1.1)

        for column in range(3):
            with self.subTest(column=column):
                row = [
                    _output(f"row-{index}", index * column_width, 0)
                    for index in range(3)
                ]
                dragged = _output("dragged", column * column_width, -1305)
                outputs = [*row, dragged]

                position = _drag(outputs, "dragged", column * column_width, -1305)

                self.assertEqual(position, (column * column_width, -1310))
                self.assertTrue(all(not _overlaps(dragged, output) for output in row))

    def test_snap_into_open_corner_of_l_shaped_layout(self):
        top_left = _output("top-left", 0, 0)
        top_right = _output("top-right", 2328, 0)
        bottom_left = _output("bottom-left", 0, 1310)
        dragged = _output("dragged", 2325, 1305)
        existing = [top_left, top_right, bottom_left]

        position = _drag([*existing, dragged], "dragged", 2325, 1305)

        self.assertEqual(position, (2328, 1310))
        self.assertTrue(all(not _overlaps(dragged, output) for output in existing))

    def test_snap_right_of_negative_mixed_scale_output(self):
        laptop = _output(
            "laptop",
            -114,
            65,
            width=2560,
            height=1600,
            scale=1.45,
        )
        dragged = _output("dragged", 1648, -32)

        position = _drag([laptop, dragged], "dragged", 1648, -32)

        self.assertEqual(position, (1652, -32))
        self.assertFalse(_overlaps(dragged, laptop))


if __name__ == "__main__":
    unittest.main()
