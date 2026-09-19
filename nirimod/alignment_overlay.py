"""Desktop alignment overlay for dual/multi-monitor physical alignment.

Runs as a lightweight helper subprocess under GTK3 + GtkLayerShell.
Creates a transparent, click-through overlay window on each monitor and draws
a horizontal red alignment line that live-updates as the user adjusts monitor
positions in nirimod.
"""

from __future__ import annotations

import json
import signal
import sys
from typing import Any

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
import cairo


class MonitorOverlay:
    """Manages an overlay window for a specific monitor."""

    def __init__(self, monitor: Gdk.Monitor, index: int) -> None:
        self.monitor = monitor
        self.index = index

        self.window = Gtk.Window()
        self.window.set_title(f"nirimod-alignment-overlay-{index}")

        # GtkLayerShell configuration
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_monitor(self.window, self.monitor)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)

        # Transparent RGBA visual
        self.window.set_app_paintable(True)
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)

        # Event connections
        self.window.connect("draw", self._on_draw)
        self.window.connect("realize", self._on_realize)
        self.window.connect("size-allocate", self._on_size_allocate)

        self.target_y: float | None = None
        self.target_x: float | None = None
        self.label_text: str = ""
        self.is_aligned: bool = False
        self.is_reference: bool = False
        self.identify_info: dict | None = None
        self.identify_timer_id: int | None = None

        self.window.show_all()

    def _on_realize(self, widget: Gtk.Widget) -> None:
        # Make the window click-through by setting an empty input region
        widget.input_shape_combine_region(cairo.Region())

    def _on_size_allocate(self, widget: Gtk.Widget, allocation: Any) -> None:
        # Re-apply empty input region when size changes
        widget.input_shape_combine_region(cairo.Region())

    def set_line_y(
        self,
        target_y: float | None,
        label: str = "",
        is_aligned: bool = False,
        is_reference: bool = False,
    ) -> None:
        self.target_y = target_y
        self.label_text = label
        self.is_aligned = is_aligned
        self.is_reference = is_reference
        self.window.queue_draw()

    def show_identify(self, info: dict | None, duration_ms: int = 2500) -> None:
        if self.identify_timer_id is not None:
            try:
                GLib.source_remove(self.identify_timer_id)
            except Exception:
                pass
            self.identify_timer_id = None

        self.identify_info = info
        self.window.queue_draw()

        def _on_timeout() -> bool:
            self.identify_info = None
            self.identify_timer_id = None
            self.window.queue_draw()
            return False

        self.identify_timer_id = GLib.timeout_add(duration_ms, _on_timeout)

    def _on_draw(self, widget: Gtk.Widget, cr: cairo.Context) -> bool:
        # Clear completely transparent
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        alloc = widget.get_allocation()
        width = alloc.width
        height = alloc.height
        # Draw real-time alignment line if active
        if self.target_y is not None and (-20 <= self.target_y <= height + 20):
            y = self.target_y

            # Color scheme: emerald green if aligned, vibrant red if adjusting
            if self.is_aligned:
                line_r, line_g, line_b = 46 / 255, 204 / 255, 113 / 255
                tag_bg_r, tag_bg_g, tag_bg_b = 39 / 255, 174 / 255, 96 / 255
            else:
                line_r, line_g, line_b = 1.0, 0.22, 0.22
                tag_bg_r, tag_bg_g, tag_bg_b = 0.0, 0.0, 0.0

            # Black outline / shadow for visibility on light and dark backgrounds
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.65)
            cr.set_line_width(4.5)
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

            # Crisp alignment line
            cr.set_source_rgba(line_r, line_g, line_b, 0.95)
            cr.set_line_width(2.5)
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

            # Left edge alignment arrow marker + Vernier ruler ticks
            cr.set_source_rgba(line_r, line_g, line_b, 0.92)
            cr.move_to(0, y - 9)
            cr.line_to(18, y)
            cr.line_to(0, y + 9)
            cr.close_path()
            cr.fill()

            # Vernier ticks on left edge (+-10px, +-20px)
            cr.set_line_width(1.5)
            for dy in [-20, -10, 10, 20]:
                cr.move_to(0, y + dy)
                cr.line_to(8, y + dy)
                cr.stroke()

            # Right edge alignment arrow marker + Vernier ruler ticks
            cr.move_to(width, y - 9)
            cr.line_to(width - 18, y)
            cr.line_to(width, y + 9)
            cr.close_path()
            cr.fill()

            # Vernier ticks on right edge (+-10px, +-20px)
            for dy in [-20, -10, 10, 20]:
                cr.move_to(width, y + dy)
                cr.line_to(width - 8, y + dy)
                cr.stroke()

            # Label tag (e.g. monitor name and Y coordinate / alignment status)
            if self.label_text:
                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(11.0)
                te = cr.text_extents(self.label_text)
                tag_x = 24.0
                tag_y = y - 26.0 if y >= 30.0 else y + 10.0
                tag_w = max(110.0, te.width + 24.0)
                tag_h = 22.0

                cr.set_source_rgba(tag_bg_r, tag_bg_g, tag_bg_b, 0.88 if self.is_aligned else 0.75)
                cr.rectangle(tag_x, tag_y, tag_w, tag_h)
                cr.fill()

                cr.set_source_rgba(1.0, 1.0, 1.0, 0.98)
                cr.move_to(tag_x + 10.0, tag_y + 15.0)
                cr.show_text(self.label_text)

        # Draw identify card if active
        if self.identify_info is not None:
            self._draw_identify_card(cr, width, height)

        return False

    def _draw_identify_card(self, cr: cairo.Context, width: int, height: int) -> None:
        info = self.identify_info or {}
        num_str = str(info.get("index", self.index + 1))
        name_str = info.get("name", f"Display {num_str}")

        model = info.get("model") or info.get("make") or ""
        res = info.get("res", "")
        refresh = info.get("refresh", "")
        phys = info.get("phys", "")

        sub_parts = []
        if model:
            sub_parts.append(model)
        if res and refresh:
            sub_parts.append(f"{res} @ {refresh}")
        elif res:
            sub_parts.append(res)
        if phys:
            sub_parts.append(phys)
        sub_str = "  •  ".join(sub_parts)

        cx, cy = width / 2.0, height / 2.0

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(14.0)
        te_sub = cr.text_extents(sub_str) if sub_str else None
        sub_w = te_sub.width if te_sub else 0.0

        card_w = max(420.0, min(sub_w + 80.0, width * 0.85))
        card_h = 280.0
        card_x = cx - card_w / 2.0
        card_y = cy - card_h / 2.0
        r = 24.0

        # Drop shadow
        self._rounded_rect(cr, card_x, card_y + 6.0, card_w, card_h, r)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.38)
        cr.fill()

        # Glassmorphic card background
        self._rounded_rect(cr, card_x, card_y, card_w, card_h, r)
        cr.set_source_rgba(18 / 255, 18 / 255, 24 / 255, 0.94)
        cr.fill_preserve()

        # Accent border
        cr.set_source_rgba(155 / 255, 109 / 255, 1.0, 0.75)
        cr.set_line_width(2.2)
        cr.stroke()

        # Large display number
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(92.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.98)
        te_num = cr.text_extents(num_str)
        cr.move_to(cx - (te_num.x_bearing + te_num.width / 2.0), card_y + 115.0)
        cr.show_text(num_str)

        # Subtle divider
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
        cr.set_line_width(1.0)
        cr.move_to(card_x + 36.0, card_y + 145.0)
        cr.line_to(card_x + card_w - 36.0, card_y + 145.0)
        cr.stroke()

        # Connector Name (e.g. DP-1, DP-2)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(24.0)
        cr.set_source_rgba(155 / 255, 109 / 255, 1.0, 1.0)
        te_name = cr.text_extents(name_str)
        cr.move_to(cx - (te_name.x_bearing + te_name.width / 2.0), card_y + 195.0)
        cr.show_text(name_str)

        # Subtitle: model, resolution, refresh, dimensions
        if sub_str and te_sub:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(14.0)
            cr.set_source_rgba(0.85, 0.85, 0.90, 0.88)
            cr.move_to(cx - (te_sub.x_bearing + te_sub.width / 2.0), card_y + 235.0)
            cr.show_text(sub_str)

    @staticmethod
    def _rounded_rect(
        cr: cairo.Context, x: float, y: float, w: float, h: float, r: float
    ) -> None:
        import math

        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def destroy(self) -> None:
        if self.identify_timer_id is not None:
            try:
                GLib.source_remove(self.identify_timer_id)
            except Exception:
                pass
            self.identify_timer_id = None
        self.window.destroy()


class OverlayApp:
    """Manages overlay windows and handles JSON command streaming from stdin."""

    def __init__(self, one_shot: bool = False) -> None:
        self.one_shot = one_shot
        self.display = Gdk.Display.get_default()
        if not self.display:
            sys.exit(1)

        self.overlays: list[MonitorOverlay] = []
        self._auto_quit_timer: int | None = None
        self._init_overlays()

        # Listen for updates via stdin
        GLib.io_add_watch(
            sys.stdin.fileno(),
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            self._on_stdin_data,
        )

        self.display.connect("monitor-added", lambda *_: self._init_overlays())
        self.display.connect("monitor-removed", lambda *_: self._init_overlays())

        if self.one_shot:
            # Failsafe: quit after 8 seconds if idle/unresponsive
            GLib.timeout_add_seconds(8, Gtk.main_quit)

    def _init_overlays(self) -> None:
        for ov in self.overlays:
            ov.destroy()
        self.overlays.clear()

        n_monitors = self.display.get_n_monitors()
        for i in range(n_monitors):
            mon = self.display.get_monitor(i)
            if mon:
                self.overlays.append(MonitorOverlay(mon, i))

    def _find_output_for_monitor(
        self, ov: MonitorOverlay, outputs_info: list[dict]
    ) -> dict | None:
        if not outputs_info:
            return None
        geom = ov.monitor.get_geometry()
        model = (ov.monitor.get_model() or "").lower()

        # 1. Match by exact coordinate position
        for o in outputs_info:
            if "x" in o and "y" in o and o["x"] == geom.x and o["y"] == geom.y:
                return o

        # 2. Match by model or connector name
        if model:
            for o in outputs_info:
                o_model = (o.get("model") or "").lower()
                o_name = (o.get("name") or "").lower()
                if o_model and (o_model in model or model in o_model):
                    return o
                if o_name and (o_name in model or model in o_name):
                    return o

        # 3. Fallback by monitor index
        if ov.index < len(outputs_info):
            return outputs_info[ov.index]

        return None

    def _on_stdin_data(self, source: int, cond: GLib.IOCondition) -> bool:
        if cond & GLib.IOCondition.HUP:
            Gtk.main_quit()
            return False

        line = sys.stdin.readline()
        if not line:
            Gtk.main_quit()
            return False

        try:
            cmd = json.loads(line)
            action = cmd.get("action")
            if action == "quit":
                Gtk.main_quit()
                return False
            elif action == "update":
                self._handle_update(cmd)
            elif action == "identify":
                self._handle_identify(cmd)
        except Exception:
            pass

        return True

    def _handle_update(self, cmd: dict) -> None:
        ref_y = cmd.get("ref_y")
        outputs_info = cmd.get("outputs", [])

        for i, ov in enumerate(self.overlays):
            geom = ov.monitor.get_geometry()
            matched = self._find_output_for_monitor(ov, outputs_info)

            if ref_y is None:
                ov.set_line_y(None)
                continue

            is_aligned = False
            is_reference = False
            if matched and "local_y" in matched:
                local_y = matched["local_y"]
                label = matched.get(
                    "label",
                    f"{matched.get('name', '')} (Y={int(round(matched.get('y', geom.y)))})",
                )
                is_aligned = matched.get("is_aligned", False)
                is_reference = not matched.get("is_active", True)
            elif matched:
                pos_y = matched.get("y", geom.y)
                local_y = ref_y - pos_y
                label = f"{matched.get('name', '')} (Y={int(round(pos_y))})"
            else:
                local_y = ref_y - geom.y
                label = f"Monitor {i}"

            ov.set_line_y(
                local_y,
                label,
                is_aligned=is_aligned,
                is_reference=is_reference,
            )

    def _handle_identify(self, cmd: dict) -> None:
        outputs_info = cmd.get("outputs", [])
        duration_ms = int(cmd.get("duration_ms", 2500))

        for ov in self.overlays:
            matched = self._find_output_for_monitor(ov, outputs_info)
            ov.show_identify(matched, duration_ms=duration_ms)

        if self.one_shot:
            if self._auto_quit_timer is not None:
                try:
                    GLib.source_remove(self._auto_quit_timer)
                except Exception:
                    pass
            self._auto_quit_timer = GLib.timeout_add(duration_ms + 100, Gtk.main_quit)


def main() -> None:
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    one_shot = "--identify" in sys.argv
    OverlayApp(one_shot=one_shot)
    Gtk.main()


if __name__ == "__main__":
    main()
