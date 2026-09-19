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

    def _on_draw(self, widget: Gtk.Widget, cr: cairo.Context) -> bool:
        # Clear completely transparent
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if self.target_y is None:
            return False

        alloc = widget.get_allocation()
        width = alloc.width
        height = alloc.height
        y = self.target_y

        # Only draw if within reasonable bounds of screen
        if not (-20 <= y <= height + 20):
            return False

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

        return False

    def destroy(self) -> None:
        self.window.destroy()


class OverlayApp:
    """Manages overlay windows and handles JSON command streaming from stdin."""

    def __init__(self) -> None:
        self.display = Gdk.Display.get_default()
        if not self.display:
            sys.exit(1)

        self.overlays: list[MonitorOverlay] = []
        self._init_overlays()

        # Listen for updates via stdin
        GLib.io_add_watch(
            sys.stdin.fileno(),
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            self._on_stdin_data,
        )

        self.display.connect("monitor-added", lambda *_: self._init_overlays())
        self.display.connect("monitor-removed", lambda *_: self._init_overlays())

    def _init_overlays(self) -> None:
        for ov in self.overlays:
            ov.destroy()
        self.overlays.clear()

        n_monitors = self.display.get_n_monitors()
        for i in range(n_monitors):
            mon = self.display.get_monitor(i)
            if mon:
                self.overlays.append(MonitorOverlay(mon, i))

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
        except Exception:
            pass

        return True

    def _handle_update(self, cmd: dict) -> None:
        ref_y = cmd.get("ref_y")
        outputs_info = cmd.get("outputs", [])

        for i, ov in enumerate(self.overlays):
            geom = ov.monitor.get_geometry()
            model = ov.monitor.get_model() or ""
            make = ov.monitor.get_manufacturer() or ""

            matched = None
            if i < len(outputs_info):
                matched = outputs_info[i]

            for o in outputs_info:
                name = o.get("name", "")
                if model and (name.lower() in model.lower() or model in name):
                    matched = o
                    break
                if o.get("model") and o.get("model") == model:
                    matched = o
                    break

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


def main() -> None:
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    OverlayApp()
    Gtk.main()


if __name__ == "__main__":
    main()
