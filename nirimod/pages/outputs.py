"""Outputs / Monitors page with interactive canvas."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from typing import TYPE_CHECKING

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


from gi.repository import Adw, Gdk, Gtk

from nirimod import niri_ipc
from nirimod.kdl_parser import KdlNode, set_child_arg, safe_switch_connect
from nirimod.pages.base import BasePage

if TYPE_CHECKING:
    from nirimod.window import NiriModWindow

TRANSFORMS = [
    "normal",
    "90",
    "180",
    "270",
    "flipped",
    "flipped-90",
    "flipped-180",
    "flipped-270",
]

PHYSICAL_SIZE_PRESETS = [
    ("detected", "Detected (EDID)"),
    ("24_16_9", '24" 16:9 (531×299 mm)'),
    ("27_16_9", '27" 16:9 (598×336 mm)'),
    ("32_16_9", '32" 16:9 (708×398 mm)'),
    ("custom", "Custom Dimensions..."),
]

PRESET_DIMENSIONS: dict[str, tuple[int, int]] = {
    "24_16_9": (531, 299),
    "27_16_9": (598, 336),
    "32_16_9": (708, 398),
}


def get_output_physical_size(
    output: dict,
    custom_overrides: dict | None = None,
    respect_transform: bool = True,
) -> tuple[float, float, str]:
    """Return (width_mm, height_mm, label_string) for an output."""
    name = output.get("name", "")
    override = (custom_overrides or {}).get(name, {})
    preset = override.get("preset")

    if preset == "custom":
        w = float(override.get("width_mm", 0))
        h = float(override.get("height_mm", 0))
        return w, h, f"{int(round(w))}×{int(round(h))} mm (Custom)"
    elif preset in PRESET_DIMENSIONS:
        w, h = PRESET_DIMENSIONS[preset]
        return float(w), float(h), f"{w}×{h} mm"

    phys = output.get("physical_size")
    if phys and len(phys) == 2 and phys[0] > 0 and phys[1] > 0:
        w, h = float(phys[0]), float(phys[1])
        t = (output.get("logical") or {}).get("transform", "normal")
        t_str = str(t).lower().replace("_", "-")
        if respect_transform and t_str in ["90", "270", "flipped-90", "flipped-270"]:
            w, h = h, w
        return w, h, f"{int(round(w))}×{int(round(h))} mm"

    # Fallback using 96 DPI
    mode_idx = output.get("current_mode", 0)
    modes = output.get("modes", [])
    m = (
        modes[mode_idx]
        if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
        else {}
    )
    pw = m.get("width", 1920)
    ph = m.get("height", 1080)
    t = (output.get("logical") or {}).get("transform", "normal")
    t_str = str(t).lower().replace("_", "-")
    if respect_transform and t_str in ["90", "270", "flipped-90", "flipped-270"]:
        pw, ph = ph, pw
    w = round(pw / 96.0 * 25.4)
    h = round(ph / 96.0 * 25.4)
    return float(w), float(h), f"{int(w)}×{int(h)} mm"


def get_physical_canvas_rects(
    outputs: list[dict],
    custom_overrides: dict | None = None,
    reference_name: str | None = None,
    reference_origin: tuple[float, float] | None = None,
) -> list[tuple[float, float, float, float, dict]]:
    """Compute physical (bx, by, bw, bh, output) for drawing canvas."""
    if not outputs:
        return []

    anchor = None
    if reference_name:
        anchor = next(
            (o for o in outputs if o.get("name") == reference_name), None
        )
    if anchor is None:
        anchor = min(outputs, key=lambda o: (o.get("logical") or {}).get("x", 0))

    a_pos = anchor.get("logical") or {}
    ax, ay = a_pos.get("x", 0), a_pos.get("y", 0)
    aw, ah = a_pos.get("width", 1920), a_pos.get("height", 1080)
    apw, aph, _ = get_output_physical_size(anchor, custom_overrides)
    abx, aby = reference_origin if reference_origin is not None else (0.0, 0.0)

    rects = []
    for o in outputs:
        pw, ph, _ = get_output_physical_size(o, custom_overrides)
        if o == anchor:
            rects.append((abx, aby, pw, ph, o))
        else:
            pos = o.get("logical") or {}
            x, y = pos.get("x", 0), pos.get("y", 0)
            lw, lh = pos.get("width", 1920), pos.get("height", 1080)

            if x >= ax:
                dx = x - (ax + aw)
                bx = abx + apw + dx * (pw / max(lw, 1))
            else:
                dx = x + lw - ax
                bx = abx - pw + dx * (pw / max(lw, 1))

            if ah != lh:
                t = (y - ay) / (ah - lh)
                by = aby + t * (aph - ph)
            else:
                by = aby + (y - ay) * (ph / max(lh, 1))
            rects.append((bx, by, pw, ph, o))
    return rects


def _snap_axis_origin(
    other_edge: float,
    dragged_size: float,
    dragged_at_start: bool,
    other_at_start: bool,
) -> int:
    """Round a snapped origin without moving opposing edges into each other."""
    if dragged_at_start:
        if other_at_start:
            return round(other_edge)
        return math.ceil(other_edge)

    origin = other_edge - dragged_size
    if other_at_start:
        return math.floor(origin)
    return round(origin)


class OutputsPage(BasePage):
    def __init__(self, window: "NiriModWindow"):
        super().__init__(window)
        self._outputs: list[dict] = []
        self._current_out: dict | None = None

        self._canvas: Gtk.DrawingArea | None = None
        self._drag_output: str | None = None
        self._drag_offset: tuple[float, float] = (0, 0)
        self._view_mode: str = "physical"
        self._custom_physical: dict[str, dict] = {}
        self._overlay_proc: subprocess.Popen | None = None
        self._show_canvas_line: bool = True

    def build(self) -> Gtk.Widget:
        tb, header, scroll, content = self._make_toolbar_page("Outputs")

        add_fake_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_fake_btn.set_tooltip_text("Add fake monitor for testing")
        add_fake_btn.add_css_class("flat")
        add_fake_btn.connect("clicked", lambda *_: self._add_fake_monitor())
        header.pack_end(add_fake_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Reload outputs from niri")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh_btn)

        # Toggle between Physical Size (mm) and Logical Size (px)
        self._view_mode_btn = Gtk.ToggleButton(label="Physical")
        self._view_mode_btn.set_active(self._view_mode == "physical")
        self._view_mode_btn.set_tooltip_text(
            "Toggle between physical dimensions (mm) and logical pixels (px)"
        )
        self._view_mode_btn.add_css_class("flat")
        self._view_mode_btn.connect("toggled", self._on_view_mode_toggled)
        header.pack_end(self._view_mode_btn)

        # Toggle Desktop Alignment Overlay guide line
        self._overlay_btn = Gtk.ToggleButton(icon_name="video-display-symbolic")
        self._overlay_btn.set_tooltip_text(
            "Toggle real-time red alignment line across desktop displays"
        )
        self._overlay_btn.add_css_class("flat")
        self._overlay_btn.connect(
            "toggled", lambda b: self._toggle_desktop_overlay(b.get_active())
        )
        header.pack_end(self._overlay_btn)

        # Toggle Canvas Alignment Guide Line
        self._canvas_line_btn = Gtk.ToggleButton(icon_name="view-grid-symbolic")
        self._canvas_line_btn.set_active(getattr(self, "_show_canvas_line", True))
        self._canvas_line_btn.set_tooltip_text(
            "Toggle canvas alignment guide line"
        )
        self._canvas_line_btn.add_css_class("flat")
        self._canvas_line_btn.connect("toggled", self._on_canvas_line_toggled)
        header.pack_end(self._canvas_line_btn)

        canvas_frame = Gtk.Frame()
        canvas_frame.add_css_class("card")
        canvas_frame.set_margin_bottom(8)

        self._canvas = Gtk.DrawingArea()
        self._canvas.set_content_height(350)
        self._canvas.set_draw_func(self._draw_canvas)
        self._canvas.set_focusable(True)
        canvas_frame.set_child(self._canvas)
        content.append(canvas_frame)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_canvas_click)
        self._canvas.add_controller(click)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_canvas_key_pressed)
        self._canvas.add_controller(key_ctrl)

        self._out_combo = Adw.ComboRow(title="Monitor")
        self._out_combo.connect("notify::selected", self._on_output_selected)
        sel_group = Adw.PreferencesGroup()
        sel_group.add(self._out_combo)
        content.append(sel_group)

        self._detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.append(self._detail_box)

        tb.connect("destroy", lambda *_: self._toggle_desktop_overlay(False))

        self.refresh()
        return tb

    def _on_view_mode_toggled(self, btn: Gtk.ToggleButton):
        self._view_mode = "physical" if btn.get_active() else "logical"
        btn.set_label("Physical" if self._view_mode == "physical" else "Logical")
        if self._canvas:
            self._canvas.queue_draw()

    def _on_canvas_line_toggled(self, btn: Gtk.ToggleButton):
        self._show_canvas_line = btn.get_active()
        if self._canvas:
            self._canvas.queue_draw()

    def _get_active_and_ref_outputs(self) -> tuple[dict | None, dict | None]:
        """Return (active_output, reference_output).

        Active output is the one being dragged or selected in the detail panel.
        Reference output is the stationary monitor used as the alignment baseline.
        """
        if not self._outputs:
            return None, None
        if len(self._outputs) == 1:
            return self._outputs[0], self._outputs[0]

        active_name = getattr(self, "_drag_output", None)
        if not active_name and self._current_out:
            active_name = self._current_out.get("name")

        active_o = next(
            (o for o in self._outputs if o.get("name") == active_name), None
        )
        if active_o is None:
            active_o = self._outputs[0]

        others = [
            o for o in self._outputs if o.get("name") != active_o.get("name")
        ]
        ref_o = others[0] if others else active_o

        return active_o, ref_o

    def _get_alignment_reference_y(self) -> float:
        """Return the stable vertical center reference height across outputs."""
        _, ref_o = self._get_active_and_ref_outputs()
        if not ref_o:
            return 0.0
        pos = ref_o.get("logical") or {}
        ry = pos.get("y", 0)
        rh = pos.get("height", 1080)
        return float(ry + rh / 2.0)

    def _align_outputs(self, name: str, mode: str):
        """Align output `name` relative to other outputs: 'center', 'top', or 'bottom'.

        When physical dimensions are available, uses physical millimeter alignment
        so monitor boundaries/centers match in physical space regardless of DPI differences.
        """
        cur_o = next((o for o in self._outputs if o.get("name") == name), None)
        if not cur_o:
            return
        others = [o for o in self._outputs if o.get("name") != name]
        if not others:
            return
        other = min(others, key=lambda o: (o.get("logical") or {}).get("x", 0))

        other_pos = other.get("logical") or {}
        other_y = other_pos.get("y", 0)
        other_h = other_pos.get("height", 1080)

        cur_pos = cur_o.get("logical") or {}
        cur_x = cur_pos.get("x", 0)
        cur_h = cur_pos.get("height", 1080)

        cur_pw, cur_ph, _ = get_output_physical_size(
            cur_o, getattr(self, "_custom_physical", {})
        )
        other_pw, other_ph, _ = get_output_physical_size(
            other, getattr(self, "_custom_physical", {})
        )

        has_physical = cur_ph > 0 and other_ph > 0

        if mode == "center":
            new_y = int(round(other_y + (other_h - cur_h) / 2.0))
        elif mode == "top":
            new_y = int(round(other_y))
        elif mode == "bottom":
            new_y = int(round(other_y + other_h - cur_h))
        else:
            return

        self._set_output_pos(name, cur_x, new_y)
        if hasattr(self, "_pos_y_adj"):
            self._pos_y_adj.set_value(new_y)
        if self._canvas:
            self._canvas.queue_draw()
        self._send_overlay_update()

    def _adjust_red_line(self, name: str, delta_screen_px: int):
        """Directly adjust the red line position on the screen by delta_screen_px.

        Positive delta_screen_px moves the red line DOWN on the physical screen.
        Negative delta_screen_px moves the red line UP on the physical screen.

        Because local_y = ref_y - y, moving the red line DOWN (increasing local_y)
        requires DECREASING y: new_y = cur_y - delta_screen_px.
        """
        cur_o = next((o for o in self._outputs if o.get("name") == name), None)
        if not cur_o:
            return
        pos = cur_o.get("logical") or {}
        cur_x = pos.get("x", 0)
        cur_y = pos.get("y", 0)

        new_y = cur_y - delta_screen_px
        self._set_output_pos(name, cur_x, new_y)
        if hasattr(self, "_pos_y_adj"):
            self._pos_y_adj.set_value(new_y)
        if self._canvas:
            self._canvas.queue_draw()
        self._send_overlay_update()

    def _toggle_desktop_overlay(self, active: bool):
        proc = getattr(self, "_overlay_proc", None)
        if not active:
            self._overlay_global_y = None
            if proc is not None:
                try:
                    if proc.stdin:
                        proc.stdin.write(b'{"action": "quit"}\n')
                        proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.terminate()
                except Exception:
                    pass
                self._overlay_proc = None
            return

        if proc is None:
            self._overlay_global_y = None
            cmd = [sys.executable, "-m", "nirimod.alignment_overlay"]
            try:
                self._overlay_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._send_overlay_update()
            except Exception as e:
                print(f"Failed to start alignment overlay: {e}", file=sys.stderr)

    def _send_overlay_update(self):
        proc = getattr(self, "_overlay_proc", None)
        if proc is None or proc.poll() is not None:
            return
        try:
            active_o, ref_o = self._get_active_and_ref_outputs()
            if not active_o or not ref_o:
                return

            active_name = active_o.get("name", "")
            ref_name = ref_o.get("name", "")

            act_pos = (active_o.get("logical") or {})
            act_y = act_pos.get("y", 0)
            act_h = act_pos.get("height", 1080)

            ref_pos = (ref_o.get("logical") or {})
            ref_y_val = float(ref_pos.get("y", 0))
            ref_h = float(ref_pos.get("height", 1080))

            if self._drag_output:
                # During mouse drag: baseline is stationary monitor fixed at its vertical center
                ref_y = ref_y_val + ref_h / 2.0
                self._overlay_global_y = ref_y
            else:
                # During static/key adjustment: anchor to stable global level so line never jumps on clicks
                if getattr(self, "_overlay_global_y", None) is None:
                    base = self._outputs[0]
                    b_pos = base.get("logical") or {}
                    self._overlay_global_y = float(b_pos.get("y", 0) + b_pos.get("height", 1080) / 2.0)
                ref_y = self._overlay_global_y

            # Canonical alignment targets for active_o relative to ref_o
            y_center = ref_y_val + (ref_h - act_h) / 2.0
            loc_center = float(ref_y - y_center)

            y_bottom = ref_y_val + ref_h - act_h
            loc_bottom = float(ref_y - y_bottom)

            y_top = ref_y_val
            loc_top = float(ref_y - y_top)

            targets = [
                ("Center", y_center, loc_center),
                ("Bottom", y_bottom, loc_bottom),
                ("Top", y_top, loc_top),
            ]

            aligned_target = None
            for t_name, t_y, t_loc in targets:
                if abs(act_y - t_y) <= 1:
                    aligned_target = t_name
                    break

            is_globally_aligned = (aligned_target is not None) and (len(self._outputs) > 1)

            best_target_name, best_y, best_loc = min(
                targets, key=lambda t: abs(act_y - t[1])
            )
            delta_y = int(round(best_y - act_y))
            _, act_ph, _ = get_output_physical_size(
                active_o, getattr(self, "_custom_physical", {})
            )
            delta_mm = (delta_y / max(act_h, 1)) * act_ph

            outs_info = []
            for o in self._outputs:
                pos = o.get("logical") or {}
                name = o.get("name", "")
                oy = pos.get("y", 0)
                oh = pos.get("height", 1080)
                is_ref = (name == ref_name) and (len(self._outputs) > 1)
                is_active = (name == active_name) and (len(self._outputs) > 1)

                pw, ph, _ = get_output_physical_size(
                    o, getattr(self, "_custom_physical", {})
                )

                if self._drag_output:
                    if not is_active:
                        out_local_y = float(oh / 2.0)
                    else:
                        out_local_y = float(ref_y - oy)
                else:
                    out_local_y = float(ref_y - oy)

                if is_active:
                    item_aligned = is_globally_aligned
                    item_delta_y = delta_y
                    item_delta_mm = round(delta_mm, 1)
                    if item_aligned:
                        label = f"{name} [PERFECTLY ALIGNED: {aligned_target}]"
                    else:
                        label = f"{name} (ΔY={delta_y:+d}px / {item_delta_mm:+.1f}mm vs {best_target_name})"
                else:
                    item_aligned = is_globally_aligned
                    item_delta_y = 0
                    item_delta_mm = 0.0
                    if item_aligned:
                        label = f"{name} [Reference - ALIGNED: {aligned_target}]"
                    else:
                        label = f"{name} [Reference Baseline]"

                outs_info.append(
                    {
                        "name": name,
                        "model": o.get("model", ""),
                        "y": oy,
                        "x": pos.get("x", 0),
                        "local_y": out_local_y,
                        "label": label,
                        "is_active": is_active,
                        "is_aligned": item_aligned,
                        "delta_y": item_delta_y,
                        "delta_mm": item_delta_mm,
                    }
                )
            msg = (
                json.dumps(
                    {
                        "action": "update",
                        "ref_y": ref_y,
                        "active_name": active_name,
                        "is_aligned": is_globally_aligned,
                        "outputs": outs_info,
                    }
                )
                + "\n"
            )
            if proc.stdin:
                proc.stdin.write(msg.encode("utf-8"))
                proc.stdin.flush()
        except Exception:
            pass

    def _supply_offline_outputs(self):
        for o in self._outputs:
            if o.get("logical") is not None:
                continue
            name = o.get("name")
            if not name:
                continue
            out_node = next(
                (
                    n
                    for n in self._nodes
                    if n.name == "output" and n.args and n.args[0] == name
                ),
                None,
            )
            if out_node is None:
                continue

            mode_str = out_node.child_arg("mode")
            scale_val = out_node.child_arg("scale")
            t_val = out_node.child_arg("transform")
            pos_node = out_node.get_child("position")

            modes = o.get("modes", [])
            mode_idx = None
            if mode_str and modes:
                try:
                    w_str = mode_str.split("@")[0].split("x")[0]
                    h_str = mode_str.split("@")[0].split("x")[1]
                    w = int(w_str)
                    h = int(h_str)
                    for i, m in enumerate(modes):
                        if m.get("width") == w and m.get("height") == h:
                            mode_idx = i
                            break
                except (ValueError, IndexError):
                    pass

            if mode_idx is not None:
                o["current_mode"] = mode_idx

            m = (
                modes[mode_idx]
                if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
                else {}
            )
            pw = m.get("width", 1920)
            ph = m.get("height", 1080)

            scale = float(scale_val) if scale_val is not None else 1.0
            t = str(t_val).lower().replace("_", "-") if t_val else "normal"
            if t in ["90", "270", "flipped-90", "flipped-270"]:
                pw, ph = ph, pw

            px = 0
            py = 0
            if pos_node:
                px = pos_node.props.get("x", 0)
                py = pos_node.props.get("y", 0)

            o["logical"] = {
                "x": px,
                "y": py,
                "width": round(pw / scale),
                "height": round(ph / scale),
                "scale": scale,
                "transform": t,
            }

    def refresh(self):
        def _on_got_outputs(outputs):
            self._outputs = outputs
            self._supply_offline_outputs()
            names = [o.get("name", "?") for o in self._outputs]
            model = Gtk.StringList.new(names)
            self._out_combo.set_model(model)
            if self._outputs:
                self._load_output_detail(self._outputs[0])
            if self._canvas:
                self._canvas.queue_draw()
            # Rebuild search index as the detail rows are now populated
            if hasattr(self._win, "_build_search_index"):
                self._win._build_search_index()

        niri_ipc.get_outputs(_on_got_outputs)

    def _add_fake_monitor(self):
        idx = 1
        while any(o.get("name") == f"fake-{idx}" for o in self._outputs):
            idx += 1
        name = f"fake-{idx}"

        o = {
            "name": name,
            "modes": [{"width": 1920, "height": 1080, "refresh_rate": 60000}],
            "current_mode": 0,
            "logical": {
                "x": 0,
                "y": 0,
                "width": 1920,
                "height": 1080,
                "scale": 1.0,
                "transform": "normal",
            },
        }
        self._outputs.append(o)

        names = [out.get("name", "?") for out in self._outputs]
        model = Gtk.StringList.new(names)
        self._out_combo.set_model(model)
        self._out_combo.set_selected(len(self._outputs) - 1)

        if self._canvas:
            self._canvas.queue_draw()
        if hasattr(self._win, "_build_search_index"):
            self._win._build_search_index()

    # Canvas drawing

    def _draw_canvas(self, area, cr, width, height):
        if not self._outputs:
            cr.set_source_rgba(0.05, 0.05, 0.05, 0.4)
            cr.rectangle(0, 0, width, height)
            cr.fill()
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.8)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            cr.move_to(width / 2 - 80, height / 2)
            cr.show_text("No outputs detected")
            return

        is_physical = getattr(self, "_view_mode", "logical") == "physical"
        rect_map = {}
        if is_physical:
            phys_rects = get_physical_canvas_rects(
                self._outputs,
                getattr(self, "_custom_physical", {}),
                reference_name=getattr(self, "_drag_ref_name", None),
                reference_origin=getattr(self, "_drag_ref_origin", None),
            )
            for r in phys_rects:
                rect_map[r[4].get("name")] = r

        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for o in self._outputs:
            if is_physical and o.get("name") in rect_map:
                bx, by, bw, bh, _ = rect_map[o.get("name")]
                lx, ly, lw, lh = bx, by, bw, bh
            else:
                pos = o.get("logical") or {}
                lx = pos.get("x", 0)
                ly = pos.get("y", 0)
                lw = pos.get("width", 1920)
                lh = pos.get("height", 1080)
            min_x = min(min_x, lx)
            min_y = min(min_y, ly)
            max_x = max(max_x, lx + lw)
            max_y = max(max_y, ly + lh)

        if min_x == float("inf"):
            min_x = min_y = 0
            max_x = 1920
            max_y = 1080

        total_w = max_x - min_x
        total_h = max_y - min_y

        scale = min(width / max(total_w, 1), height / max(total_h, 1)) * 0.9
        off_x = (width - total_w * scale) / 2 - min_x * scale
        off_y = (height - total_h * scale) / 2 - min_y * scale

        if self._drag_output and hasattr(self, "_drag_start_scale"):
            scale = self._drag_start_scale
            off_x, off_y = self._drag_start_offset

        self._canvas_scale = scale
        self._canvas_offset = (off_x, off_y)
        self._canvas_pixel_w = width
        self._canvas_pixel_h = height

        # grid background
        cr.set_source_rgba(1, 1, 1, 0.03)
        cr.set_line_width(1)
        grid_size = 40
        for gx in range(0, int(width), grid_size):
            cr.move_to(gx, 0)
            cr.line_to(gx, height)
        for gy in range(0, int(height), grid_size):
            cr.move_to(0, gy)
            cr.line_to(width, gy)
        cr.stroke()

        canvas_min_x = float("inf")
        canvas_max_x = float("-inf")

        for i, o in enumerate(self._outputs):
            if is_physical and o.get("name") in rect_map:
                bx, by, bw, bh, _ = rect_map[o.get("name")]
                x = off_x + bx * scale
                y = off_y + by * scale
                w = bw * scale
                h = bh * scale
            else:
                pos = o.get("logical") or {}
                x = off_x + pos.get("x", 0) * scale
                y = off_y + pos.get("y", 0) * scale
                w = pos.get("width", 1920) * scale
                h = pos.get("height", 1080) * scale

            canvas_min_x = min(canvas_min_x, x)
            canvas_max_x = max(canvas_max_x, x + w)

            is_sel = o.get("name") == (
                self._current_out.get("name") if self._current_out else None
            )

            if is_sel:
                cr.set_source_rgba(155 / 255, 109 / 255, 1.0, 1.0)
            else:
                cr.set_source_rgba(0.2, 0.2, 0.2, 1.0)
            cr.rectangle(x, y, w, h)
            cr.fill_preserve()

            # border
            cr.set_line_width(1.5)
            if is_sel:
                cr.set_source_rgba(0.7, 0.7, 0.75, 0.9)
            else:
                cr.set_source_rgba(0.4, 0.4, 0.45, 0.6)
            cr.stroke()

            name = o.get("name", f"Output {i}")
            mode_idx = o.get("current_mode")
            modes = o.get("modes", [])
            mode = (
                modes[mode_idx]
                if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
                else {}
            )
            out_scale = (o.get("logical") or {}).get("scale", 1.0)
            res = f"{mode.get('width', '?')}×{mode.get('height', '?')}"
            scale_text = f"Scale: {out_scale}x"
            _, _, phys_label = get_output_physical_size(
                o, getattr(self, "_custom_physical", {})
            )
            phys_text = phys_label.split(" (")[0]

            cr.set_source_rgba(1, 1, 1, 0.95 if is_sel else 0.7)

            cr.select_font_face("Sans", 0, 1)
            font_size = max(10, min(16, w / 10))
            cr.set_font_size(font_size)
            te = cr.text_extents(name)
            cr.move_to(x + w / 2 - te.width / 2, y + h / 2 - font_size * 0.7)
            cr.show_text(name)

            cr.select_font_face("Sans", 0, 0)
            res_size = max(8, min(12, w / 15))
            cr.set_font_size(res_size)
            te2 = cr.text_extents(res)
            cr.move_to(x + w / 2 - te2.width / 2, y + h / 2 + res_size * 0.6)
            cr.show_text(res)

            cr.set_source_rgba(0.6, 0.6, 0.65, 0.9 if is_sel else 0.6)
            scale_size = max(7, min(11, w / 18))
            cr.set_font_size(scale_size)
            info_text = f"{scale_text} • {phys_text}"
            te3 = cr.text_extents(info_text)
            cr.move_to(
                x + w / 2 - te3.width / 2,
                y + h / 2 + res_size * 0.6 + scale_size * 1.3,
            )
            cr.show_text(info_text)

        # Red alignment guide line across screens
        if getattr(self, "_show_canvas_line", True) and len(self._outputs) >= 2 and canvas_min_x < canvas_max_x:
            active_o, ref_o = self._get_active_and_ref_outputs()
            if getattr(self, "_overlay_global_y", None) is not None:
                line_y = off_y + self._overlay_global_y * scale
            elif is_physical and rect_map and ref_o:
                ref_rect = rect_map.get(ref_o.get("name"))
                if ref_rect:
                    line_y = off_y + (ref_rect[1] + ref_rect[3] / 2.0) * scale
                else:
                    ref_pos = ref_o.get("logical") or {}
                    line_y = (
                        off_y
                        + (ref_pos.get("y", 0) + ref_pos.get("height", 1080) / 2.0)
                        * scale
                    )
            elif ref_o:
                ref_pos = ref_o.get("logical") or {}
                line_y = (
                    off_y
                    + (ref_pos.get("y", 0) + ref_pos.get("height", 1080) / 2.0)
                    * scale
                )
            else:
                line_y = off_y + self._get_alignment_reference_y() * scale

            line_start_x = max(12.0, canvas_min_x - 30.0)
            line_end_x = min(float(width) - 12.0, canvas_max_x + 30.0)

            # Dark outline for crisp contrast
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.5)
            cr.set_line_width(3.5)
            cr.move_to(line_start_x, line_y)
            cr.line_to(line_end_x, line_y)
            cr.stroke()

            active_pos = (active_o.get("logical") or {}) if active_o else {}
            act_y = active_pos.get("y", 0)
            act_h = active_pos.get("height", 1080)
            ref_pos = (ref_o.get("logical") or {}) if ref_o else {}
            ref_y_val = float(ref_pos.get("y", 0))
            ref_h = float(ref_pos.get("height", 1080))
            ref_global_y = ref_y_val + ref_h / 2.0

            act_pw, act_ph, _ = (
                get_output_physical_size(
                    active_o, getattr(self, "_custom_physical", {})
                )
                if active_o
                else (0.0, 0.0, "")
            )
            ref_pw, ref_ph, _ = (
                get_output_physical_size(
                    ref_o, getattr(self, "_custom_physical", {})
                )
                if ref_o
                else (0.0, 0.0, "")
            )
            has_phys = act_ph > 0 and ref_ph > 0

            y_center = ref_y_val + (ref_h - act_h) / 2.0
            y_bottom = ref_y_val + ref_h - act_h
            y_top = ref_y_val

            canvas_aligned_target = None
            for t_name, t_y in [("Center", y_center), ("Bottom", y_bottom), ("Top", y_top)]:
                if abs(act_y - t_y) <= 1:
                    canvas_aligned_target = t_name
                    break

            is_canvas_aligned = (canvas_aligned_target is not None) and (len(self._outputs) > 1)

            if is_canvas_aligned:
                line_color = (46 / 255, 204 / 255, 113 / 255, 0.95)
                badge_text = f"{canvas_aligned_target} [Aligned]"
            else:
                line_color = (235 / 255, 55 / 255, 55 / 255, 0.95)
                nearest_name, nearest_y = min(
                    [("Center", y_center), ("Bottom", y_bottom), ("Top", y_top)],
                    key=lambda t: abs(act_y - t[1]),
                )
                delta_y = int(round(nearest_y - act_y))
                badge_text = f"{nearest_name} ({delta_y:+d}px)"

            # Crisp alignment line
            cr.set_source_rgba(*line_color)
            cr.set_line_width(2.0)
            cr.move_to(line_start_x, line_y)
            cr.line_to(line_end_x, line_y)
            cr.stroke()

            # Small "Center" badge at start
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(9.0)
            te_b = cr.text_extents(badge_text)
            bw = te_b.width + 10.0
            bh = 15.0
            bx = line_start_x
            by = line_y - bh / 2.0

            cr.set_source_rgba(*line_color)
            cr.rectangle(bx, by, bw, bh)
            cr.fill()

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
            cr.move_to(bx + 5.0, by + bh - 4.0)
            cr.show_text(badge_text)

    def _on_drag_begin(self, gesture, sx, sy):
        if not hasattr(self, "_canvas_scale"):
            return
        scale = self._canvas_scale
        ox, oy = self._canvas_offset
        is_physical = getattr(self, "_view_mode", "logical") == "physical"
        rect_map = {}
        if is_physical:
            phys_rects = get_physical_canvas_rects(
                self._outputs, getattr(self, "_custom_physical", {})
            )
            for r in phys_rects:
                rect_map[r[4].get("name")] = r

        for o in reversed(self._outputs):
            if is_physical and o.get("name") in rect_map:
                bx, by, bw, bh, _ = rect_map[o.get("name")]
                x = ox + bx * scale
                y = oy + by * scale
                w = bw * scale
                h = bh * scale
            else:
                pos = o.get("logical") or {}
                x = ox + pos.get("x", 0) * scale
                y = oy + pos.get("y", 0) * scale
                w = pos.get("width", 1920) * scale
                h = pos.get("height", 1080) * scale

            if x <= sx <= x + w and y <= sy <= y + h:
                pos = o.get("logical") or {}
                self._drag_output = o["name"]
                self._last_dx = 0
                self._last_dy = 0
                self._drag_start_lx = pos.get("x", 0)
                self._drag_start_ly = pos.get("y", 0)
                self._drag_current_lx = pos.get("x", 0)
                self._drag_current_ly = pos.get("y", 0)
                self._drag_start_scale = scale
                self._drag_start_offset = (ox, oy)

                others = [
                    out for out in self._outputs if out.get("name") != o.get("name")
                ]
                ref_out = others[0] if others else None
                if ref_out:
                    self._drag_ref_name = ref_out.get("name")
                    if is_physical and rect_map and self._drag_ref_name in rect_map:
                        r_rect = rect_map[self._drag_ref_name]
                        self._drag_ref_origin = (r_rect[0], r_rect[1])
                    else:
                        self._drag_ref_origin = (0.0, 0.0)
                else:
                    self._drag_ref_name = None
                    self._drag_ref_origin = (0.0, 0.0)
                return

    def _on_drag_update(self, gesture, dx, dy):
        if not self._drag_output or not hasattr(self, "_canvas_scale"):
            return

        scale = getattr(self, "_drag_start_scale", self._canvas_scale)
        delta_dx = dx - getattr(self, "_last_dx", 0)
        delta_dy = dy - getattr(self, "_last_dy", 0)
        self._last_dx = dx
        self._last_dy = dy

        if not hasattr(self, "_drag_current_lx") and hasattr(
            self, "_drag_start_lx"
        ):
            self._drag_current_lx = self._drag_start_lx
        if not hasattr(self, "_drag_current_ly") and hasattr(
            self, "_drag_start_ly"
        ):
            self._drag_current_ly = self._drag_start_ly

        drag_o = next(
            (o for o in self._outputs if o.get("name") == self._drag_output),
            None,
        )
        if not drag_o:
            return

        is_physical = getattr(self, "_view_mode", "logical") == "physical"

        monitor_scale = (drag_o.get("logical") or {}).get("scale", 1.0)
        mode_idx = drag_o.get("current_mode")
        modes = drag_o.get("modes", [])
        mode = (
            modes[mode_idx]
            if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
            else {}
        )
        pixel_w = mode.get("width", 1920)
        pixel_h = mode.get("height", 1080)

        transform = (
            str((drag_o.get("logical") or {}).get("transform", "normal"))
            .lower()
            .replace("_", "-")
        )
        if transform in ["90", "270", "flipped-90", "flipped-270"]:
            pixel_w, pixel_h = pixel_h, pixel_w

        logical_w = pixel_w / monitor_scale
        logical_h = pixel_h / monitor_scale

        if is_physical and (delta_dx != 0 or delta_dy != 0):
            pw_m, ph_m, _ = get_output_physical_size(
                drag_o, getattr(self, "_custom_physical", {})
            )
            self._drag_current_lx += (delta_dx / scale) * (
                logical_w / max(pw_m, 1.0)
            )

            ref_name = getattr(self, "_drag_ref_name", None)
            if not ref_name:
                others = [
                    o for o in self._outputs if o.get("name") != self._drag_output
                ]
                ref_o = others[0] if others else None
            else:
                ref_o = next(
                    (o for o in self._outputs if o.get("name") == ref_name), None
                )

            if ref_o:
                ref_pos = ref_o.get("logical") or {}
                ref_lh = ref_pos.get("height", 1080)
                _, ref_ph, _ = get_output_physical_size(
                    ref_o, getattr(self, "_custom_physical", {})
                )
            else:
                ref_lh = 1080
                ref_ph = 300.0

            if ref_lh != logical_h and ref_ph != ph_m:
                factor_y = (ref_lh - logical_h) / (ref_ph - ph_m)
            else:
                factor_y = logical_h / max(ph_m, 1.0)

            self._drag_current_ly += (delta_dy / scale) * factor_y
        else:
            self._drag_current_lx += delta_dx / scale
            self._drag_current_ly += delta_dy / scale

        if hasattr(self, "_drag_start_ly") and (delta_dx == 0 and delta_dy == 0):
            self._drag_current_ly = self._drag_start_ly
        if hasattr(self, "_drag_start_lx") and (delta_dx == 0 and delta_dy == 0):
            self._drag_current_lx = self._drag_start_lx

        new_lx = self._drag_current_lx
        new_ly = self._drag_current_ly

        # edge snapping & center snapping
        SNAP_THRESHOLD = 30
        snapped_x = new_lx
        snapped_y = new_ly
        closest_x = SNAP_THRESHOLD + 1
        closest_y = SNAP_THRESHOLD + 1

        dragged_left = new_lx
        dragged_right = new_lx + logical_w
        dragged_top = new_ly
        dragged_bottom = new_ly + logical_h

        for other in self._outputs:
            if other.get("name") == self._drag_output:
                continue

            other_pos = other.get("logical") or {}
            other_x = other_pos.get("x", 0)
            other_y = other_pos.get("y", 0)

            other_scale = other_pos.get("scale", 1.0)
            other_mode_idx = other.get("current_mode")
            other_modes = other.get("modes", [])
            other_mode = (
                other_modes[other_mode_idx]
                if isinstance(other_mode_idx, int)
                and 0 <= other_mode_idx < len(other_modes)
                else {}
            )
            other_pixel_w = other_mode.get("width", 1920)
            other_pixel_h = other_mode.get("height", 1080)

            other_transform = (
                str(other_pos.get("transform", "normal"))
                .lower()
                .replace("_", "-")
            )
            if other_transform in ["90", "270", "flipped-90", "flipped-270"]:
                other_pixel_w, other_pixel_h = other_pixel_h, other_pixel_w

            other_logical_w = other_pixel_w / other_scale
            other_logical_h = other_pixel_h / other_scale

            other_left = other_x
            other_right = other_x + other_logical_w
            other_top = other_y
            other_bottom = other_y + other_logical_h

            vertical_spans_are_near = not (
                dragged_bottom < other_top - SNAP_THRESHOLD
                or other_bottom + SNAP_THRESHOLD < dragged_top
            )
            horizontal_spans_are_near = not (
                dragged_right < other_left - SNAP_THRESHOLD
                or other_right + SNAP_THRESHOLD < dragged_left
            )

            if vertical_spans_are_near:
                for dragged_edge, is_left_edge in [
                    (dragged_left, True),
                    (dragged_right, False),
                ]:
                    for other_edge, is_other_left_edge in [
                        (other_left, True),
                        (other_right, False),
                    ]:
                        dist = abs(dragged_edge - other_edge)
                        if dist < closest_x:
                            closest_x = dist
                            snapped_x = _snap_axis_origin(
                                other_edge,
                                logical_w,
                                is_left_edge,
                                is_other_left_edge,
                            )

            if horizontal_spans_are_near:
                for dragged_edge, is_top_edge in [
                    (dragged_top, True),
                    (dragged_bottom, False),
                ]:
                    for other_edge, is_other_top_edge in [
                        (other_top, True),
                        (other_bottom, False),
                    ]:
                        dist = abs(dragged_edge - other_edge)
                        if dist < closest_y:
                            closest_y = dist
                            snapped_y = _snap_axis_origin(
                                other_edge,
                                logical_h,
                                is_top_edge,
                                is_other_top_edge,
                            )

                # Center-to-center snapping (active in physical alignment mode)
                if is_physical:
                    dragged_center = new_ly + logical_h / 2.0
                    other_center = other_y + other_logical_h / 2.0
                    dist_center = abs(dragged_center - other_center)
                    if dist_center < closest_y:
                        closest_y = dist_center
                        snapped_y = round(other_center - logical_h / 2.0)

        if closest_x <= SNAP_THRESHOLD:
            new_lx = snapped_x
        if closest_y <= SNAP_THRESHOLD:
            new_ly = snapped_y

        if not drag_o.get("logical"):
            drag_o["logical"] = {}
        drag_o["logical"]["x"] = new_lx
        drag_o["logical"]["y"] = new_ly

        if self._canvas:
            self._canvas.queue_draw()
        self._send_overlay_update()

    def _on_drag_end(self, gesture, dx, dy):
        if self._drag_output:
            if self._canvas:
                self._canvas.queue_draw()

            moved = False
            if hasattr(self, "_drag_current_lx") and hasattr(self, "_drag_start_lx"):
                if (
                    self._drag_current_lx != self._drag_start_lx
                    or self._drag_current_ly != self._drag_start_ly
                ):
                    moved = True

            if moved:
                for o in self._outputs:
                    self._apply_position(o["name"])

                if self._current_out:
                    cur_pos = self._current_out.get("logical") or {}
                    if hasattr(self, "_pos_x_adj"):
                        self._pos_x_adj.set_value(cur_pos.get("x", 0))
                    if hasattr(self, "_pos_y_adj"):
                        self._pos_y_adj.set_value(cur_pos.get("y", 0))

            self._drag_output = None
            self._drag_ref_name = None
            self._drag_ref_origin = None
            self._send_overlay_update()

    def _on_canvas_click(self, gesture, n_press, x, y):
        if not hasattr(self, "_canvas_scale"):
            return

        scale = self._canvas_scale
        ox, oy = self._canvas_offset
        is_physical = getattr(self, "_view_mode", "logical") == "physical"
        rect_map = {}
        if is_physical:
            phys_rects = get_physical_canvas_rects(
                self._outputs, getattr(self, "_custom_physical", {})
            )
            for r in phys_rects:
                rect_map[r[4].get("name")] = r

        for i, o in reversed(list(enumerate(self._outputs))):
            if is_physical and o.get("name") in rect_map:
                bx, by, bw, bh, _ = rect_map[o.get("name")]
                mx = ox + bx * scale
                my = oy + by * scale
                mw = bw * scale
                mh = bh * scale
            else:
                pos = o.get("logical") or {}
                mx = ox + pos.get("x", 0) * scale
                my = oy + pos.get("y", 0) * scale
                mw = pos.get("width", 1920) * scale
                mh = pos.get("height", 1080) * scale

            if mx <= x <= mx + mw and my <= y <= my + mh:
                self._out_combo.set_selected(i)
                if self._canvas:
                    self._canvas.grab_focus()
                return

    def _on_canvas_key_pressed(
        self, controller, keyval: int, keycode: int, state: Gdk.ModifierType
    ) -> bool:
        if not self._current_out:
            return False
        name = self._current_out.get("name")
        if not name:
            return False

        pos = self._current_out.get("logical") or {}
        cur_x = pos.get("x", 0)
        cur_y = pos.get("y", 0)

        step = 10 if (state & Gdk.ModifierType.SHIFT_MASK) else 1

        if keyval == Gdk.KEY_Up:
            new_y = cur_y - step
            self._set_output_pos(name, cur_x, new_y)
            if hasattr(self, "_pos_y_adj"):
                self._pos_y_adj.set_value(new_y)
            return True
        elif keyval == Gdk.KEY_Down:
            new_y = cur_y + step
            self._set_output_pos(name, cur_x, new_y)
            if hasattr(self, "_pos_y_adj"):
                self._pos_y_adj.set_value(new_y)
            return True
        elif keyval == Gdk.KEY_Left:
            new_x = cur_x - step
            self._set_output_pos(name, new_x, cur_y)
            if hasattr(self, "_pos_x_adj"):
                self._pos_x_adj.set_value(new_x)
            return True
        elif keyval == Gdk.KEY_Right:
            new_x = cur_x + step
            self._set_output_pos(name, new_x, cur_y)
            if hasattr(self, "_pos_x_adj"):
                self._pos_x_adj.set_value(new_x)
            return True

        return False

    def _apply_position(self, name: str):
        o = next((x for x in self._outputs if x["name"] == name), None)
        if not o:
            return
        pos = o.get("logical") or {}

        nx = int(round(pos.get("x", 0)))
        ny = int(round(pos.get("y", 0)))

        out_node = self._get_or_create_out_node(name)
        pos_node = out_node.get_child("position")
        if pos_node is not None:
            if pos_node.props.get("x") == nx and pos_node.props.get("y") == ny:
                return
        else:
            pos_node = KdlNode(name="position")
            out_node.children.append(pos_node)

        pos_node.props["x"] = nx
        pos_node.props["y"] = ny

        if self._current_out and self._current_out.get("name") == name:
            if hasattr(self, "_pos_x_adj") and int(self._pos_x_adj.get_value()) != nx:
                self._pos_x_adj.set_value(nx)
            if hasattr(self, "_pos_y_adj") and int(self._pos_y_adj.get_value()) != ny:
                self._pos_y_adj.set_value(ny)

        self._commit("output position")

    def _on_output_selected(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self._outputs):
            self._load_output_detail(self._outputs[idx])
            # Rebuild search index as the detail rows have changed
            if hasattr(self._win, "_build_search_index"):
                self._win._build_search_index()

    def _load_output_detail(self, output: dict):
        self._current_out = output
        for child in list(self._detail_box):
            self._detail_box.remove(child)

        name = output.get("name", "?")
        nodes = self._nodes
        out_node = next(
            (n for n in nodes if n.name == "output" and n.args and n.args[0] == name),
            None,
        )

        modes = output.get("modes", [])
        mode_strs = [
            f"{m.get('width', 0)}×{m.get('height', 0)}@{m.get('refresh_rate', 0) / 1000:.3f}"
            for m in modes
        ]
        mode_model = Gtk.StringList.new(mode_strs)
        mode_row = Adw.ComboRow(title="Resolution &amp; Refresh Rate")
        mode_row.set_model(mode_model)
        mode_idx = output.get("current_mode")
        cur_mode = (
            modes[mode_idx]
            if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
            else {}
        )
        cur_str = f"{cur_mode.get('width', 0)}×{cur_mode.get('height', 0)}@{cur_mode.get('refresh_rate', 0) / 1000:.3f}"
        if cur_str in mode_strs:
            mode_row.set_selected(mode_strs.index(cur_str))
        mode_row.connect(
            "notify::selected",
            lambda r, _: self._on_mode_changed(name, modes, r.get_selected()),
        )

        scale_val = round((output.get("logical") or {}).get("scale", 1.0), 3)
        scale_adj = Gtk.Adjustment(
            value=scale_val,
            lower=0.01,
            upper=100.0,
            step_increment=0.05,
        )
        scale_row = Adw.SpinRow(title="Scale", adjustment=scale_adj, digits=2)
        scale_row.connect(
            "notify::value",
            lambda r, _: self._set_output_prop(name, "scale", r.get_value()),
        )

        t_model = Gtk.StringList.new(TRANSFORMS)
        transform_row = Adw.ComboRow(title="Transform", model=t_model)
        cur_t = (output.get("logical") or {}).get("transform", "normal")
        cur_t_norm = str(cur_t).lower().replace("_", "-") if cur_t else "normal"
        if cur_t_norm in TRANSFORMS:
            transform_row.set_selected(TRANSFORMS.index(cur_t_norm))
        transform_row.connect(
            "notify::selected",
            lambda r, _: self._set_output_prop(
                name, "transform", TRANSFORMS[r.get_selected()]
            ),
        )

        px = (output.get("logical") or {}).get("x", 0)
        py = (output.get("logical") or {}).get("y", 0)
        px_adj = Gtk.Adjustment(
            value=px, lower=-1000000, upper=1000000, step_increment=1
        )
        py_adj = Gtk.Adjustment(
            value=py, lower=-1000000, upper=1000000, step_increment=1
        )
        self._pos_x_adj = px_adj
        self._pos_y_adj = py_adj
        pos_x_row = Adw.SpinRow(title="Position X", adjustment=px_adj, digits=0)
        pos_y_row = Adw.SpinRow(title="Position Y", adjustment=py_adj, digits=0)
        pos_x_row.connect(
            "notify::value",
            lambda r, _: self._set_output_pos(
                name, int(r.get_value()), int(py_adj.get_value())
            ),
        )
        pos_y_row.connect(
            "notify::value",
            lambda r, _: self._set_output_pos(
                name, int(px_adj.get_value()), int(r.get_value())
            ),
        )

        vrr_row = Adw.SwitchRow(title="Variable Refresh Rate (VRR)")
        vrr_val = (
            (out_node.get_child("variable-refresh-rate") is not None)
            if out_node
            else False
        )
        vrr_row.set_active(vrr_val)
        safe_switch_connect(
            vrr_row,
            vrr_val,
            lambda enabled: self._set_output_flag(
                name, "variable-refresh-rate", enabled
            ),
        )

        off_row = Adw.SwitchRow(title="Disable Output")
        off_val = (out_node.get_child("off") is not None) if out_node else False
        off_row.set_active(off_val)
        safe_switch_connect(
            off_row,
            off_val,
            lambda enabled: self._set_output_flag(name, "off", enabled),
        )

        grp = Adw.PreferencesGroup(title=f"Output: {name}")
        for r in [
            mode_row,
            scale_row,
            transform_row,
            pos_x_row,
            pos_y_row,
            vrr_row,
            off_row,
        ]:
            grp.add(r)

        # Quick Align buttons
        if len(self._outputs) >= 2:
            align_row = Adw.ActionRow(
                title="Quick Alignment",
                subtitle="Align physical centers, top edges, or bottom edges",
            )
            align_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            align_box.set_valign(Gtk.Align.CENTER)

            btn_center = Gtk.Button(label="Center")
            btn_center.set_tooltip_text("Align monitor physical center lines")
            btn_center.add_css_class("suggested-action")
            btn_center.connect(
                "clicked", lambda *_: self._align_outputs(name, "center")
            )
            align_box.append(btn_center)

            btn_top = Gtk.Button(label="Top")
            btn_top.set_tooltip_text("Align monitor physical top edges")
            btn_top.connect(
                "clicked", lambda *_: self._align_outputs(name, "top")
            )
            align_box.append(btn_top)

            btn_bottom = Gtk.Button(label="Bottom")
            btn_bottom.set_tooltip_text("Align monitor physical bottom edges")
            btn_bottom.connect(
                "clicked", lambda *_: self._align_outputs(name, "bottom")
            )
            align_box.append(btn_bottom)

            align_row.add_suffix(align_box)
            grp.add(align_row)

            # Red line micro-adjustment row
            line_row = Adw.ActionRow(
                title="Fine-Tune Red Line",
                subtitle="Directly raise or lower the red line on this screen",
            )
            line_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            line_box.set_valign(Gtk.Align.CENTER)

            btn_dn_10 = Gtk.Button(label="▼ 10px")
            btn_dn_10.set_tooltip_text("Lower red line by 10px on this screen")
            btn_dn_10.connect(
                "clicked", lambda *_: self._adjust_red_line(name, 10)
            )
            line_box.append(btn_dn_10)

            btn_dn_1 = Gtk.Button(label="▼ 1px")
            btn_dn_1.set_tooltip_text("Lower red line by 1px on this screen")
            btn_dn_1.connect(
                "clicked", lambda *_: self._adjust_red_line(name, 1)
            )
            line_box.append(btn_dn_1)

            btn_up_1 = Gtk.Button(label="▲ 1px")
            btn_up_1.set_tooltip_text("Raise red line by 1px on this screen")
            btn_up_1.connect(
                "clicked", lambda *_: self._adjust_red_line(name, -1)
            )
            line_box.append(btn_up_1)

            btn_up_10 = Gtk.Button(label="▲ 10px")
            btn_up_10.set_tooltip_text("Raise red line by 10px on this screen")
            btn_up_10.connect(
                "clicked", lambda *_: self._adjust_red_line(name, -10)
            )
            line_box.append(btn_up_10)

            line_row.add_suffix(line_box)
            grp.add(line_row)

        self._detail_box.append(grp)

        # Physical Dimensions preferences group
        phys_w, phys_h, phys_label = get_output_physical_size(
            output, getattr(self, "_custom_physical", {})
        )
        phys_grp = Adw.PreferencesGroup(title="Physical Dimensions")

        cur_override = getattr(self, "_custom_physical", {}).get(name, {})
        cur_preset = cur_override.get("preset", "detected")

        preset_names = [p[1] for p in PHYSICAL_SIZE_PRESETS]
        preset_keys = [p[0] for p in PHYSICAL_SIZE_PRESETS]
        preset_model = Gtk.StringList.new(preset_names)
        preset_row = Adw.ComboRow(
            title="Physical Size Preset", model=preset_model
        )
        if cur_preset in preset_keys:
            preset_row.set_selected(preset_keys.index(cur_preset))

        custom_w_adj = Gtk.Adjustment(
            value=phys_w, lower=50, upper=3000, step_increment=1
        )
        custom_h_adj = Gtk.Adjustment(
            value=phys_h, lower=50, upper=3000, step_increment=1
        )
        custom_w_row = Adw.SpinRow(
            title="Width (mm)", adjustment=custom_w_adj, digits=0
        )
        custom_h_row = Adw.SpinRow(
            title="Height (mm)", adjustment=custom_h_adj, digits=0
        )

        is_custom = cur_preset == "custom"
        custom_w_row.set_visible(is_custom)
        custom_h_row.set_visible(is_custom)

        def _on_preset_changed(combo, _):
            idx = combo.get_selected()
            if 0 <= idx < len(preset_keys):
                pkey = preset_keys[idx]
                if not hasattr(self, "_custom_physical"):
                    self._custom_physical = {}
                if name not in self._custom_physical:
                    self._custom_physical[name] = {}
                self._custom_physical[name]["preset"] = pkey
                custom_w_row.set_visible(pkey == "custom")
                custom_h_row.set_visible(pkey == "custom")
                if self._canvas:
                    self._canvas.queue_draw()

        def _on_custom_dim_changed(*_):
            if not hasattr(self, "_custom_physical"):
                self._custom_physical = {}
            if name not in self._custom_physical:
                self._custom_physical[name] = {}
            self._custom_physical[name]["width_mm"] = custom_w_adj.get_value()
            self._custom_physical[name]["height_mm"] = custom_h_adj.get_value()
            if self._canvas:
                self._canvas.queue_draw()

        preset_row.connect("notify::selected", _on_preset_changed)
        custom_w_row.connect("notify::value", _on_custom_dim_changed)
        custom_h_row.connect("notify::value", _on_custom_dim_changed)

        phys_grp.add(preset_row)
        phys_grp.add(custom_w_row)
        phys_grp.add(custom_h_row)
        self._detail_box.append(phys_grp)

        if self._canvas:
            self._canvas.queue_draw()
        self._send_overlay_update()

    def _ensure_output_fields(self, out_node: KdlNode, name: str):
        manual_out = None
        if self._nodes:
            manual_out = next(
                (
                    n
                    for n in self._nodes
                    if n.name == "output" and n.args and n.args[0] == name
                ),
                None,
            )

        if manual_out:
            if out_node.get_child("mode") is None:
                m = manual_out.child_arg("mode")
                if m:
                    set_child_arg(out_node, "mode", m)
            if out_node.get_child("scale") is None:
                s = manual_out.child_arg("scale")
                if s is not None:
                    set_child_arg(out_node, "scale", s)
            if out_node.get_child("transform") is None:
                t = manual_out.child_arg("transform")
                if t:
                    set_child_arg(out_node, "transform", t)
            if out_node.get_child("position") is None:
                pos_node = manual_out.get_child("position")
                if pos_node:
                    new_pos = KdlNode(name="position", props=pos_node.props.copy())
                    out_node.children.append(new_pos)

        o = next((x for x in self._outputs if x.get("name") == name), None)
        if o:
            if out_node.get_child("mode") is None:
                mode_idx = o.get("current_mode")
                modes = o.get("modes", [])
                if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes):
                    m = modes[mode_idx]
                    mode_str = f"{m.get('width', 0)}x{m.get('height', 0)}@{m.get('refresh_rate', 0) / 1000:.3f}"
                    set_child_arg(out_node, "mode", mode_str)
            if out_node.get_child("scale") is None:
                set_child_arg(
                    out_node, "scale", (o.get("logical") or {}).get("scale", 1.0)
                )
            if out_node.get_child("transform") is None:
                t = (o.get("logical") or {}).get("transform", "normal")
                t = str(t).lower().replace("_", "-") if t else "normal"
                if t not in TRANSFORMS:
                    t = "normal"
                set_child_arg(out_node, "transform", t)
            pos_node = out_node.get_child("position")
            if pos_node is None:
                pos_node = KdlNode(name="position")
                out_node.children.append(pos_node)
                pos_node.props["x"] = (o.get("logical") or {}).get("x", 0)
                pos_node.props["y"] = (o.get("logical") or {}).get("y", 0)

    def _get_or_create_out_node(self, name: str) -> KdlNode:
        nodes = self._nodes
        out_node = next(
            (n for n in nodes if n.name == "output" and n.args and n.args[0] == name),
            None,
        )
        is_new = out_node is None
        if out_node is None:
            out_node = KdlNode(name="output", args=[name])
            nodes.append(out_node)

        assert out_node is not None

        if is_new:
            self._ensure_output_fields(out_node, name)

        order = {"mode": 0, "scale": 1, "transform": 2, "position": 3}
        out_node.children.sort(key=lambda c: order.get(c.name, 999))

        return out_node

    def _update_logical_dims(self, o: dict):
        if not o.get("logical"):
            o["logical"] = {}
        mode_idx = o.get("current_mode")
        modes = o.get("modes", [])
        m = (
            modes[mode_idx]
            if isinstance(mode_idx, int) and 0 <= mode_idx < len(modes)
            else {}
        )
        pw = m.get("width", 1920)
        ph = m.get("height", 1080)

        scale = o["logical"].get("scale", 1.0)
        if scale <= 0:
            scale = 1.0

        t = o["logical"].get("transform", "normal")
        t_str = str(t).lower().replace("_", "-")
        if t_str in ["90", "270", "flipped-90", "flipped-270"]:
            pw, ph = ph, pw

        o["logical"]["width"] = round(pw / scale)
        o["logical"]["height"] = round(ph / scale)

    def _on_mode_changed(self, name: str, modes: list, idx: int):
        if not (0 <= idx < len(modes)):
            return
        m = modes[idx]
        mode_str = f"{m.get('width', 0)}x{m.get('height', 0)}@{m.get('refresh_rate', 0) / 1000:.3f}"
        out_node = self._get_or_create_out_node(name)
        set_child_arg(out_node, "mode", mode_str)

        o = next((x for x in self._outputs if x.get("name") == name), None)
        if o:
            o["current_mode"] = idx
            self._update_logical_dims(o)

        self._commit("output mode")
        if self._canvas:
            self._canvas.queue_draw()

    def _set_output_prop(self, name: str, prop: str, value):
        if prop == "scale" and isinstance(value, float):
            value = round(value, 3)

        out_node = self._get_or_create_out_node(name)
        set_child_arg(out_node, prop, value)

        o = next((x for x in self._outputs if x.get("name") == name), None)
        if o:
            if not o.get("logical"):
                o["logical"] = {}
            if prop == "scale":
                o["logical"]["scale"] = value
            elif prop == "transform":
                o["logical"]["transform"] = value
            self._update_logical_dims(o)

        self._commit(f"output {prop}")
        if self._canvas:
            self._canvas.queue_draw()

    def _set_output_pos(self, name: str, x: int, y: int):
        nx = int(round(x))
        ny = int(round(y))

        out_node = self._get_or_create_out_node(name)
        pos_node = out_node.get_child("position")
        if pos_node is not None:
            if pos_node.props.get("x") == nx and pos_node.props.get("y") == ny:
                return
        else:
            pos_node = KdlNode(name="position")
            out_node.children.append(pos_node)

        pos_node.props["x"] = nx
        pos_node.props["y"] = ny

        o = next((out for out in self._outputs if out.get("name") == name), None)
        if o:
            if not o.get("logical"):
                o["logical"] = {}
            o["logical"]["x"] = nx
            o["logical"]["y"] = ny

        self._commit("output position")
        if self._canvas:
            self._canvas.queue_draw()
        self._send_overlay_update()

    def _set_output_flag(self, name: str, flag: str, enabled: bool):
        from nirimod.kdl_parser import set_node_flag

        out_node = self._get_or_create_out_node(name)
        set_node_flag(out_node, flag, enabled)
        if flag == "off" and not enabled:
            self._supply_offline_outputs()
        self._commit(f"output {flag}")
        if self._canvas:
            self._canvas.queue_draw()
