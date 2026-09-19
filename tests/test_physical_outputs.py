"""Unit tests for dual-monitor physical alignment and physical sizing."""

from __future__ import annotations

import unittest

from nirimod.pages.outputs import (
    PRESET_DIMENSIONS,
    PHYSICAL_SIZE_PRESETS,
    OutputsPage,
    get_output_physical_size,
    get_physical_canvas_rects,
)


class TestPhysicalOutputs(unittest.TestCase):
    def test_presets_exist(self):
        self.assertIn("24_16_9", PRESET_DIMENSIONS)
        self.assertIn("27_16_9", PRESET_DIMENSIONS)
        self.assertEqual(PRESET_DIMENSIONS["24_16_9"], (531, 299))
        self.assertEqual(PRESET_DIMENSIONS["27_16_9"], (598, 336))

    def test_get_output_physical_size_from_edid(self):
        output = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "logical": {"transform": "normal"},
        }
        w, h, label = get_output_physical_size(output)
        self.assertEqual(w, 530)
        self.assertEqual(h, 300)
        self.assertIn("530×300 mm", label)

    def test_get_output_physical_size_respects_transform(self):
        output = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "logical": {"transform": "90"},
        }
        w, h, label = get_output_physical_size(output, respect_transform=True)
        self.assertEqual(w, 300)
        self.assertEqual(h, 530)
        self.assertIn("300×530 mm", label)

    def test_get_output_physical_size_preset_override(self):
        output = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "logical": {"transform": "normal"},
        }
        overrides = {"DP-2": {"preset": "27_16_9"}}
        w, h, label = get_output_physical_size(output, custom_overrides=overrides)
        self.assertEqual(w, 598)
        self.assertEqual(h, 336)

    def test_get_output_physical_size_custom_override(self):
        output = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "logical": {"transform": "normal"},
        }
        overrides = {"DP-2": {"preset": "custom", "width_mm": 610, "height_mm": 350}}
        w, h, label = get_output_physical_size(output, custom_overrides=overrides)
        self.assertEqual(w, 610)
        self.assertEqual(h, 350)

    def test_get_output_physical_size_fallback(self):
        output = {
            "name": "fake-1",
            "modes": [{"width": 1920, "height": 1080}],
            "current_mode": 0,
            "logical": {"transform": "normal"},
        }
        w, h, label = get_output_physical_size(output)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertAlmostEqual(w, 508, delta=5)

    def test_center_to_center_snapping(self):
        from nirimod.pages.outputs import OutputsPage

        def _make_out(name, x, y, w, h):
            return {
                "name": name,
                "modes": [{"width": w, "height": h, "refresh_rate": 60000}],
                "current_mode": 0,
                "logical": {
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "scale": 1.0,
                    "transform": "normal",
                },
            }

        out1 = _make_out("left", 0, 0, 1920, 1080)
        out2 = _make_out("right", 1920, -170, 2560, 1440)

        page = object.__new__(OutputsPage)
        page._outputs = [out1, out2]
        page._drag_output = "right"
        page._drag_current_lx = 1920
        page._drag_current_ly = -170
        page._drag_start_scale = 1
        page._canvas_scale = 1
        page._last_dx = 0
        page._last_dy = 0
        page._canvas = None
        page._view_mode = "physical"
        page._custom_physical = {}

        page._on_drag_update(None, 0, 0)
        self.assertEqual(out2["logical"]["y"], -180)

    def test_quick_align_actions(self):
        from nirimod.pages.outputs import OutputsPage

        def _make_out(name, x, y, w, h):
            return {
                "name": name,
                "modes": [{"width": w, "height": h, "refresh_rate": 60000}],
                "current_mode": 0,
                "logical": {
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "scale": 1.0,
                    "transform": "normal",
                },
            }

        out1 = _make_out("left", 0, 0, 1920, 1080)
        out2 = _make_out("right", 1920, 200, 2560, 1440)

        page = object.__new__(OutputsPage)
        page._outputs = [out1, out2]
        page._current_out = out2
        page._canvas = None
        set_calls = []
        page._set_output_pos = lambda name, x, y: set_calls.append((name, x, y))

        page._align_outputs("right", "center")
        self.assertEqual(set_calls[-1], ("right", 1920, -180))

        page._align_outputs("right", "top")
        self.assertEqual(set_calls[-1], ("right", 1920, 0))

        page._align_outputs("right", "bottom")
        self.assertEqual(set_calls[-1], ("right", 1920, -360))

    def test_physical_canvas_rects_contact_and_alignment(self):
        dp1 = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "logical": {
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "scale": 1.0,
                "transform": "90",
            },
        }
        dp2 = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "logical": {
                "x": 1080,
                "y": 240,
                "width": 2560,
                "height": 1440,
                "scale": 1.0,
                "transform": "normal",
            },
        }

        rects = get_physical_canvas_rects([dp1, dp2])
        self.assertEqual(len(rects), 2)
        bx1, by1, bw1, bh1, _ = rects[0]
        bx2, by2, bw2, bh2, _ = rects[1]

        self.assertEqual((bw1, bh1), (300.0, 530.0))
        self.assertEqual((bw2, bh2), (600.0, 340.0))
        self.assertEqual(bx1 + bw1, bx2)
        self.assertEqual(bx2, 300.0)

        center1 = by1 + bh1 / 2.0
        center2 = by2 + bh2 / 2.0
        self.assertEqual(center1, 265.0)
        self.assertEqual(center2, 265.0)

        dp2_top = dict(dp2, logical=dict(dp2["logical"], y=0))
        rects_top = get_physical_canvas_rects([dp1, dp2_top])
        self.assertEqual(rects_top[1][1], 0.0)

        dp2_bottom = dict(dp2, logical=dict(dp2["logical"], y=480))
        rects_bottom = get_physical_canvas_rects([dp1, dp2_bottom])
        self.assertEqual(rects_bottom[1][1] + rects_bottom[1][3], 530.0)

    def test_stable_red_line_reference(self):
        from nirimod.pages.outputs import OutputsPage

        out1 = {
            "name": "DP-1",
            "logical": {"x": 0, "y": 0, "width": 1080, "height": 1920},
        }
        out2 = {
            "name": "DP-2",
            "logical": {"x": 1080, "y": 0, "width": 2560, "height": 1440},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [out1, out2]
        page._drag_output = None

        # When out1 is active, out2 is reference (center = 720.0)
        page._current_out = out1
        active, ref = page._get_active_and_ref_outputs()
        self.assertEqual(active["name"], "DP-1")
        self.assertEqual(ref["name"], "DP-2")
        self.assertEqual(page._get_alignment_reference_y(), 720.0)

        # When out2 is active, out1 is reference (center = 960.0)
        page._current_out = out2
        active, ref = page._get_active_and_ref_outputs()
        self.assertEqual(active["name"], "DP-2")
        self.assertEqual(ref["name"], "DP-1")
        self.assertEqual(page._get_alignment_reference_y(), 960.0)

    def test_overlay_payload_stationarity(self):
        """Verify that dragging Monitor A only moves Monitor A's red line, while B stays stationary."""
        import io
        import json
        from unittest.mock import MagicMock
        from nirimod.pages.outputs import OutputsPage

        dp1 = {
            "name": "DP-1",
            "logical": {"x": 0, "y": 0, "width": 1080, "height": 1920},
        }
        dp2 = {
            "name": "DP-2",
            "logical": {"x": 1080, "y": 240, "width": 2560, "height": 1440},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp1, dp2]
        page._current_out = dp1
        page._drag_output = "DP-1"  # Dragging DP-1

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_stdin = io.BytesIO()
        mock_proc.stdin = mock_stdin
        page._overlay_proc = mock_proc

        page._send_overlay_update()
        data1 = json.loads(mock_stdin.getvalue().decode().strip())
        outs1 = {o["name"]: o for o in data1["outputs"]}

        # DP-2 is stationary reference: fixed at its vertical center (1440/2 = 720)
        self.assertEqual(outs1["DP-2"]["local_y"], 720.0)
        self.assertFalse(outs1["DP-2"]["is_active"])
        self.assertIn("Reference", outs1["DP-2"]["label"])

        # DP-1 is active: ref_y is 240 + 720 = 960. local_y = 960 - 0 = 960
        self.assertEqual(outs1["DP-1"]["local_y"], 960.0)
        self.assertTrue(outs1["DP-1"]["is_active"])

        # Now simulate dragging DP-1 downwards by 50px
        dp1["logical"]["y"] = 50
        mock_stdin.seek(0)
        mock_stdin.truncate(0)
        page._send_overlay_update()
        data2 = json.loads(mock_stdin.getvalue().decode().strip())
        outs2 = {o["name"]: o for o in data2["outputs"]}

        # DP-2 STILL stationary at 720.0!
        self.assertEqual(outs2["DP-2"]["local_y"], 720.0)
        # DP-1 moved to 960 - 50 = 910.0!
        self.assertEqual(outs2["DP-1"]["local_y"], 910.0)

        # Now simulate dragging DP-2 instead
        page._drag_output = "DP-2"
        page._current_out = dp2
        dp2["logical"]["y"] = 240
        mock_stdin.seek(0)
        mock_stdin.truncate(0)
        page._send_overlay_update()
        data3 = json.loads(mock_stdin.getvalue().decode().strip())
        outs3 = {o["name"]: o for o in data3["outputs"]}

        # DP-1 is now stationary reference: fixed at 1920/2 = 960.0
        self.assertEqual(outs3["DP-1"]["local_y"], 960.0)
        self.assertFalse(outs3["DP-1"]["is_active"])
        self.assertIn("Reference", outs3["DP-1"]["label"])

        # DP-2 is now active: ref_y is 50 + 960 = 1010. local_y = 1010 - 240 = 770.0
        self.assertEqual(outs3["DP-2"]["local_y"], 770.0)
        self.assertTrue(outs3["DP-2"]["is_active"])

    def test_symmetrical_1_to_1_drag_feel(self):
        """Verify that dragging either monitor moves 1:1 on the physical canvas while the other stays still."""
        from nirimod.pages.outputs import OutputsPage

        dp1 = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "modes": [{"width": 1920, "height": 1080}],
            "current_mode": 0,
            "logical": {
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "scale": 1.0,
                "transform": "90",
            },
        }
        dp2 = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "modes": [{"width": 2560, "height": 1440}],
            "current_mode": 0,
            "logical": {
                "x": 1080,
                "y": 240,
                "width": 2560,
                "height": 1440,
                "scale": 1.0,
                "transform": "normal",
            },
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp1, dp2]
        page._canvas = None
        page._view_mode = "physical"
        page._custom_physical = {}
        page._canvas_scale = 1.0
        page._canvas_offset = (0, 0)
        page._overlay_proc = None
        page._current_out = None
        page._apply_position = lambda name: None

        # --- Test dragging DP-1 (left monitor) ---
        page._on_drag_begin(None, 100, 100)
        self.assertEqual(page._drag_output, "DP-1")
        self.assertEqual(page._drag_ref_name, "DP-2")
        self.assertEqual(page._drag_ref_origin, (300.0, 95.0))

        # Move mouse down by 19 canvas pixels
        page._on_drag_update(None, 0, 19)
        # Logical Y should change by (19 / 1.0) * (1440 - 1920) / (340 - 530) = 19 * (-480 / -190) = 48
        self.assertEqual(dp1["logical"]["y"], 48)

        # In physical canvas rects: DP-2 is fixed at (300, 95), DP-1 moved from by=0 to by=19
        rects = get_physical_canvas_rects(
            page._outputs,
            reference_name=page._drag_ref_name,
            reference_origin=page._drag_ref_origin,
        )
        rect_map = {r[4]["name"]: r for r in rects}
        self.assertAlmostEqual(rect_map["DP-2"][1], 95.0, places=4)
        self.assertAlmostEqual(rect_map["DP-1"][1], 19.0, places=4)

        # End drag on DP-1
        page._on_drag_end(None, 0, 19)
        self.assertIsNone(page._drag_output)
        self.assertIsNone(page._drag_ref_name)

        # --- Test dragging DP-2 (right monitor) ---
        dp1["logical"]["y"] = 0
        dp2["logical"]["y"] = 240
        page._on_drag_begin(None, 400, 200)
        self.assertEqual(page._drag_output, "DP-2")
        self.assertEqual(page._drag_ref_name, "DP-1")
        self.assertEqual(page._drag_ref_origin, (0.0, 0.0))

        # Move mouse down by 19 canvas pixels
        page._on_drag_update(None, 0, 19)
        # Logical Y should change by 19 * (1920 - 1440) / (530 - 340) = 19 * (480 / 190) = 48
        self.assertEqual(dp2["logical"]["y"], 240 + 48)

        # In physical canvas rects: DP-1 is fixed at (0, 0), DP-2 moved from by=95 to by=114
        rects2 = get_physical_canvas_rects(
            page._outputs,
            reference_name=page._drag_ref_name,
            reference_origin=page._drag_ref_origin,
        )
        rect_map2 = {r[4]["name"]: r for r in rects2}
        self.assertAlmostEqual(rect_map2["DP-1"][1], 0.0, places=4)
        self.assertAlmostEqual(rect_map2["DP-2"][1], 114.0, places=4)

    def test_reduced_bottom_snap_sensitivity(self):
        from nirimod.pages.outputs import OutputsPage

        dp1 = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "modes": [{"width": 1920, "height": 1080}],
            "current_mode": 0,
            "logical": {
                "x": -1019,
                "y": -777,
                "width": 1080,
                "height": 1920,
                "scale": 1.0,
                "transform": "90",
            },
        }
        dp2 = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "modes": [{"width": 2560, "height": 1440}],
            "current_mode": 0,
            "logical": {
                "x": 61,
                "y": -260,
                "width": 2560,
                "height": 1440,
                "scale": 1.0,
                "transform": "normal",
            },
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp1, dp2]
        page._drag_output = "DP-2"
        page._drag_start_lx = 61
        page._drag_start_ly = -260
        page._drag_start_scale = 0.52
        page._canvas_scale = 0.52
        page._canvas = None
        page._view_mode = "physical"
        page._custom_physical = {}

        page._on_drag_update(None, 0, 0)
        self.assertEqual(dp2["logical"]["y"], -260)

        page._drag_start_ly = -293
        page._on_drag_update(None, 0, 0)
        self.assertEqual(dp2["logical"]["y"], -297)

    def test_independent_monitor_movement(self):
        dp1 = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "logical": {
                "x": -1019,
                "y": -777,
                "width": 1080,
                "height": 1920,
                "scale": 1.0,
                "transform": "90",
            },
        }
        dp2 = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "logical": {
                "x": 61,
                "y": -142,
                "width": 2560,
                "height": 1440,
                "scale": 1.0,
                "transform": "normal",
            },
        }

        r_init = get_physical_canvas_rects([dp1, dp2])
        dp2_moved = dict(dp2, logical=dict(dp2["logical"], x=161))
        r_after_dp2 = get_physical_canvas_rects([dp1, dp2_moved])

        self.assertAlmostEqual(r_after_dp2[0][0], r_init[0][0], places=5)
        self.assertAlmostEqual(r_after_dp2[0][1], r_init[0][1], places=5)
        self.assertGreater(r_after_dp2[1][0], r_init[1][0])

    def test_keyboard_micro_adjustments(self):
        """Verify that keyboard arrow keys nudge position by 1px (or 10px with Shift)."""
        from gi.repository import Gdk
        from nirimod.pages.outputs import OutputsPage

        dp = {
            "name": "DP-1",
            "logical": {"x": 100, "y": 200, "width": 1920, "height": 1080},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp]
        page._current_out = dp
        page._canvas = None
        page._view_mode = "physical"
        page._custom_physical = {}
        page._overlay_proc = None

        set_calls = []
        page._set_output_pos = lambda name, x, y: (
            set_calls.append((name, x, y)),
            dp["logical"].update({"x": x, "y": y}),
        )

        # Arrow Up (1px)
        handled = page._on_canvas_key_pressed(None, Gdk.KEY_Up, 0, Gdk.ModifierType(0))
        self.assertTrue(handled)
        self.assertEqual(dp["logical"]["y"], 199)

        # Arrow Down with Shift (10px)
        handled = page._on_canvas_key_pressed(None, Gdk.KEY_Down, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertTrue(handled)
        self.assertEqual(dp["logical"]["y"], 209)

        # Arrow Left (1px)
        handled = page._on_canvas_key_pressed(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0))
        self.assertTrue(handled)
        self.assertEqual(dp["logical"]["x"], 99)

        # Arrow Right with Shift (10px)
        handled = page._on_canvas_key_pressed(None, Gdk.KEY_Right, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertTrue(handled)
        self.assertEqual(dp["logical"]["x"], 109)

    def test_perfect_alignment_badge_and_millimeter_readout(self):
        """Verify that delta_mm and PERFECTLY ALIGNED are generated in overlay update."""
        import io
        import json
        from unittest.mock import MagicMock
        from nirimod.pages.outputs import OutputsPage

        dp1 = {
            "name": "DP-1",
            "physical_size": [530, 300],
            "logical": {"x": 0, "y": 0, "width": 1080, "height": 1920},
        }
        dp2 = {
            "name": "DP-2",
            "physical_size": [600, 340],
            "logical": {"x": 1080, "y": 240, "width": 2560, "height": 1440},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp1, dp2]
        page._current_out = dp1
        page._drag_output = "DP-1"

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_stdin = io.BytesIO()
        mock_proc.stdin = mock_stdin
        page._overlay_proc = mock_proc

        # Perfectly aligned: y1 = 0. Center of DP-2 is 240 + 720 = 960. DP-1 local_y = 960. Delta = 960 - 960 = 0
        page._send_overlay_update()
        data = json.loads(mock_stdin.getvalue().decode().strip())
        self.assertTrue(data["is_aligned"])
        outs = {o["name"]: o for o in data["outputs"]}
        self.assertTrue(outs["DP-1"]["is_aligned"])
        self.assertIn("PERFECTLY ALIGNED", outs["DP-1"]["label"])
        self.assertEqual(outs["DP-1"]["delta_y"], 0)
        self.assertEqual(outs["DP-1"]["delta_mm"], 0.0)

        # Now offset by 32px
        dp1["logical"]["y"] = 32
        mock_stdin.seek(0)
        mock_stdin.truncate(0)
        page._send_overlay_update()
        data2 = json.loads(mock_stdin.getvalue().decode().strip())
        self.assertFalse(data2["is_aligned"])
        outs2 = {o["name"]: o for o in data2["outputs"]}
        self.assertFalse(outs2["DP-1"]["is_aligned"])
        self.assertEqual(outs2["DP-1"]["delta_y"], -32)
        # 300mm / 1920px * (-32px) = -5.0 mm
        self.assertAlmostEqual(outs2["DP-1"]["delta_mm"], -5.0, places=1)
        self.assertIn("mm", outs2["DP-1"]["label"])

    def test_physical_edge_alignment_24portrait_27landscape(self):
        """Verify that 24" portrait and 27" landscape align physically to avoid DPI mismatch."""
        from nirimod.pages.outputs import OutputsPage

        dp_left = {
            "name": "DP-Left",
            "physical_size": [299, 531],
            "logical": {"x": 0, "y": 0, "width": 1080, "height": 1920},
        }
        dp_right = {
            "name": "DP-Right",
            "physical_size": [598, 336],
            "logical": {"x": 1080, "y": 0, "width": 2560, "height": 1440},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp_left, dp_right]
        page._custom_physical = {}
        page._set_output_pos = lambda name, x, y: next(
            o for o in page._outputs if o["name"] == name
        )["logical"].update({"x": x, "y": y})
        page._send_overlay_update = lambda: None
        page._canvas = None

        # Bottom Align (Physical)
        page._align_outputs("DP-Left", "bottom")
        # 168mm from bottom on DP-Right (336 / 2 = 168mm)
        # On DP-Left (531mm / 1920px), 168mm is 168 * 1920 / 531 = 607.46px from bottom
        # local_y = 1920 - 607.46 = 1312.54px -> y = 720 - 1313 = -593
        self.assertEqual(dp_left["logical"]["y"], -593)

        # Top Align (Physical)
        page._align_outputs("DP-Left", "top")
        # 168mm from top on DP-Right
        # On DP-Left, 168mm from top is 607.46px -> y = 720 - 607 = 113
        self.assertEqual(dp_left["logical"]["y"], 113)

        # Center Align
        page._align_outputs("DP-Left", "center")
        # (1440 - 1920) / 2 = -240
        self.assertEqual(dp_left["logical"]["y"], -240)

    def test_adjust_red_line(self):
        """Verify _adjust_red_line directly raises or lowers the red line on screen."""
        from nirimod.pages.outputs import OutputsPage

        dp = {
            "name": "DP-1",
            "logical": {"x": 0, "y": -593, "width": 1080, "height": 1920},
        }
        page = object.__new__(OutputsPage)
        page._outputs = [dp]
        page._set_output_pos = lambda name, x, y: dp["logical"].update({"x": x, "y": y})
        page._send_overlay_update = lambda: None
        page._canvas = None

        # Lower line by 10px on physical screen: y must decrease by 10
        page._adjust_red_line("DP-1", 10)
        self.assertEqual(dp["logical"]["y"], -603)

        # Raise line by 1px on physical screen: y must increase by 1
        page._adjust_red_line("DP-1", -1)
        self.assertEqual(dp["logical"]["y"], -602)

    def test_overlay_badges_for_all_alignment_targets(self):
        """Verify overlay produces PERFECTLY ALIGNED badges for Bottom, Center, and Top."""
        import io
        import json
        from unittest.mock import MagicMock
        from nirimod.pages.outputs import OutputsPage

        dp_left = {
            "name": "DP-Left",
            "physical_size": [299, 531],
            "logical": {"x": 0, "y": -593, "width": 1080, "height": 1920},
        }
        dp_right = {
            "name": "DP-Right",
            "physical_size": [598, 336],
            "logical": {"x": 1080, "y": 0, "width": 2560, "height": 1440},
        }

        page = object.__new__(OutputsPage)
        page._outputs = [dp_left, dp_right]
        page._current_out = dp_left
        page._drag_output = "DP-Left"
        page._custom_physical = {}

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_stdin = io.BytesIO()
        mock_proc.stdin = mock_stdin
        page._overlay_proc = mock_proc

        # Bottom Aligned (-593)
        page._send_overlay_update()
        data = json.loads(mock_stdin.getvalue().decode().strip())
        self.assertTrue(data["is_aligned"])
        outs = {o["name"]: o for o in data["outputs"]}
        self.assertIn("PERFECTLY ALIGNED: Bottom", outs["DP-Left"]["label"])

        # Top Aligned (113)
        dp_left["logical"]["y"] = 113
        mock_stdin.seek(0)
        mock_stdin.truncate(0)
        page._send_overlay_update()
        data_top = json.loads(mock_stdin.getvalue().decode().strip())
        self.assertTrue(data_top["is_aligned"])
        outs_top = {o["name"]: o for o in data_top["outputs"]}
        self.assertIn("PERFECTLY ALIGNED: Top", outs_top["DP-Left"]["label"])

        # Center Aligned (-240)
        dp_left["logical"]["y"] = -240
        mock_stdin.seek(0)
        mock_stdin.truncate(0)
        page._send_overlay_update()
        data_ctr = json.loads(mock_stdin.getvalue().decode().strip())
        self.assertTrue(data_ctr["is_aligned"])
        outs_ctr = {o["name"]: o for o in data_ctr["outputs"]}
        self.assertIn("PERFECTLY ALIGNED: Center", outs_ctr["DP-Left"]["label"])


if __name__ == "__main__":
    unittest.main()
