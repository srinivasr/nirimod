"""Animations page with bezier curve editor and Nirimation preset browser."""

from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import urllib.error
import urllib.request

import gi
import logging

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from nirimod.kdl_parser import (
    KdlNode,
    find_or_create,
    parse_kdl,
    set_child_arg,
    set_node_flag,
)
from nirimod.pages.base import BasePage

_NIRIMATION_API = "https://api.github.com/repos/XansiVA/nirimation/contents/animations"
_NIRIMATION_RAW = (
    "https://raw.githubusercontent.com/XansiVA/nirimation/main/animations/{name}"
)
_NIRIMATION_HTML = "https://github.com/XansiVA/nirimation/blob/main/animations/{name}"

_JGARZA_API = "https://api.github.com/repos/jgarza9788/niri-animation-collection/contents/animations"
_JGARZA_RAW = "https://raw.githubusercontent.com/jgarza9788/niri-animation-collection/main/animations/{name}"
_JGARZA_HTML = "https://github.com/jgarza9788/niri-animation-collection/blob/main/animations/{name}"

# In-memory cache: None = not fetched, list = fetched entries, Exception = error
_nirimation_cache: list[dict] | Exception | None = None
_jgarza_cache: list[dict] | Exception | None = None

# Local presets directory
_LOCAL_PRESETS_DIR = Path("~/.config/nirimod/presets").expanduser()

# Slug used as subdirectory name for each source
_SOURCE_SLUGS = {
    "XansiVA/nirimation": "nirimation",
    "jgarza9788/niri-animation-collection": "niri-animation-collection",
}


ANIM_GROUPS = [
    (
        "Window Management",
        [
            ("window-open", "Window Open", "window-new-symbolic"),
            ("window-close", "Window Close", "window-close-symbolic"),
            ("window-movement", "Window Movement", "transform-move-symbolic"),
            ("window-resize", "Window Resize", "view-fullscreen-symbolic"),
        ],
    ),
    (
        "Workspace",
        [
            ("workspace-switch", "Workspace Switch", "video-display-symbolic"),
            (
                "horizontal-view-movement",
                "Horizontal View Movement",
                "pan-end-symbolic",
            ),
        ],
    ),
    (
        "Interface",
        [
            ("overview-open-close", "Overview Open/Close", "view-app-grid-symbolic"),
            ("overview-screenshot", "Overview Screenshot", "camera-photo-symbolic"),
            ("screenshot-ui-open", "Screenshot UI Open", "camera-photo-symbolic"),
            (
                "config-notification-open-close",
                "Config Notification",
                "preferences-system-symbolic",
            ),
        ],
    ),
]

PRESET_CURVES = {
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
    "linear": (0.0, 0.0, 1.0, 1.0),
    "spring": (0.17, 0.67, 0.83, 0.67),
}


class BezierEditor(Gtk.DrawingArea):
    """Interactive cubic Bézier curve editor with animated preview ball."""

    def __init__(self, on_changed=None):
        super().__init__()
        self._cp = [0.25, 0.1, 0.25, 1.0]  # x1,y1,x2,y2
        self._on_changed = on_changed
        self._dragging: int | None = None  # 0=p1, 1=p2
        self._ball_t = 0.0
        self._ball_dir = 1
        self._anim_id: int | None = None

        self.set_content_width(220)
        self.set_content_height(180)
        self.set_draw_func(self._draw)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self.add_controller(click)

        self.add_tick_callback(self._on_tick)

    def set_curve(self, x1, y1, x2, y2):
        self._cp = [x1, y1, x2, y2]
        self.queue_draw()

    def get_curve(self):
        return tuple(self._cp)

    def _on_tick(self, widget, frame_clock):
        current_time = frame_clock.get_frame_time()
        if not hasattr(self, "_last_time"):
            self._last_time = current_time
            return True

        dt = (current_time - self._last_time) / 1_000_000.0
        self._last_time = current_time

        # Move at a constant speed of ~0.75 units per second
        speed = 0.75
        self._ball_t += (dt * speed) * self._ball_dir

        if self._ball_t >= 1.0:
            self._ball_t = 1.0
            self._ball_dir = -1
        elif self._ball_t <= 0.0:
            self._ball_t = 0.0
            self._ball_dir = 1

        self.queue_draw()
        return True

    def _bezier_pt(self, t):
        x1, y1, x2, y2 = self._cp
        # Cubic bezier from (0,0) to (1,1) with controls (x1,y1), (x2,y2)
        mt = 1 - t
        bx = 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t * t * t
        by = 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t * t * t
        return bx, by

    def _canvas_to_cp(self, cx, cy, W, H, pad=20):
        """Convert canvas coords to bezier control point (0-1 range)."""
        x = (cx - pad) / (W - 2 * pad)
        y = 1.0 - (cy - pad) / (H - 2 * pad)
        return max(0.0, min(1.0, x)), max(-0.5, min(1.5, y))

    def _cp_to_canvas(self, x, y, W, H, pad=20):
        cx = pad + x * (W - 2 * pad)
        cy = pad + (1.0 - y) * (H - 2 * pad)
        return cx, cy

    def _draw(self, area, cr, W, H):
        pad = 20

        cr.set_source_rgba(0.08, 0.08, 0.08, 1.0)
        cr.rectangle(0, 0, W, H)
        cr.fill()
        cr.set_source_rgba(0.2, 0.2, 0.22, 0.4)
        cr.set_line_width(0.5)
        for i in range(5):
            gx = pad + i * (W - 2 * pad) / 4
            gy = pad + i * (H - 2 * pad) / 4
            cr.move_to(gx, pad)
            cr.line_to(gx, H - pad)
            cr.stroke()
            cr.move_to(pad, gy)
            cr.line_to(W - pad, gy)
            cr.stroke()

        x1, y1, x2, y2 = self._cp
        px1, py1 = self._cp_to_canvas(x1, y1, W, H, pad)
        px2, py2 = self._cp_to_canvas(x2, y2, W, H, pad)
        start = self._cp_to_canvas(0, 0, W, H, pad)
        end = self._cp_to_canvas(1, 1, W, H, pad)

        cr.set_source_rgba(0.2, 0.2, 0.25, 0.4)
        cr.set_line_width(1.0)
        cr.move_to(*start)
        cr.line_to(px1, py1)
        cr.stroke()
        cr.move_to(*end)
        cr.line_to(px2, py2)
        cr.stroke()

        # Bezier path
        cr.set_source_rgba(0.3, 0.7, 1.0, 0.9)
        cr.set_line_width(2.5)
        cr.move_to(*start)
        cr.curve_to(px1, py1, px2, py2, *end)
        cr.stroke()

        bx_01, by_01 = self._bezier_pt(self._ball_t)
        bx_c, by_c = self._cp_to_canvas(bx_01, by_01, W, H, pad)
        cr.set_source_rgba(1.0, 0.6, 0.2, 0.95)
        cr.arc(bx_c, by_c, 5, 0, 2 * math.pi)
        cr.fill()

        for px, py, color in [
            (px1, py1, (0.4, 1.0, 0.5, 1.0)),
            (px2, py2, (1.0, 0.4, 0.5, 1.0)),
        ]:
            cr.set_source_rgba(*color)
            cr.arc(px, py, 6, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.5)
            cr.set_line_width(1.5)
            cr.arc(px, py, 6, 0, 2 * math.pi)
            cr.stroke()

    def _hit_cp(self, cx, cy, W, H, pad=20):
        x1, y1, x2, y2 = self._cp
        px1, py1 = self._cp_to_canvas(x1, y1, W, H, pad)
        px2, py2 = self._cp_to_canvas(x2, y2, W, H, pad)
        if math.hypot(cx - px1, cy - py1) < 12:
            return 0
        if math.hypot(cx - px2, cy - py2) < 12:
            return 1
        return None

    def _on_press(self, gesture, _n, x, y):
        W = self.get_width()
        H = self.get_height()
        self._dragging = self._hit_cp(x, y, W, H)

    def _on_release(self, gesture, _n, x, y):
        self._dragging = None

    def _on_motion(self, controller, x, y):
        if self._dragging is None:
            return
        W = self.get_width()
        H = self.get_height()
        cpx, cpy = self._canvas_to_cp(x, y, W, H)
        if self._dragging == 0:
            self._cp[0] = cpx
            self._cp[1] = cpy
        else:
            self._cp[2] = cpx
            self._cp[3] = cpy
        self.queue_draw()
        if self._on_changed:
            self._on_changed(*self._cp)


def _fetch_presets_from_github(api_url, raw_tmpl, html_tmpl, cache_attr, callback):
    """Generic preset fetcher for any GitHub contents API endpoint."""
    import sys

    mod = sys.modules[__name__]
    cached = getattr(mod, cache_attr)
    if cached is not None:
        GLib.idle_add(callback, cached)
        return

    def _worker():
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "nirimod/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            entries = []
            for item in data:
                if item.get("type") != "file":
                    continue
                n = item["name"]
                if not n.endswith(".kdl"):
                    continue
                stem = n[:-4]  # strip .kdl
                display = stem.replace("-", " ").replace("_", " ").title()
                entries.append(
                    {
                        "name": n,
                        "display_name": display,
                        "download_url": item.get(
                            "download_url",
                            raw_tmpl.format(name=n),
                        ),
                        "html_url": item.get(
                            "html_url",
                            html_tmpl.format(name=n),
                        ),
                    }
                )
            entries.sort(key=lambda e: e["display_name"])
            setattr(mod, cache_attr, entries)
            GLib.idle_add(callback, entries)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            setattr(mod, cache_attr, exc)
            GLib.idle_add(callback, exc)

    threading.Thread(target=_worker, daemon=True).start()


def _fetch_nirimation_presets(callback):
    """Fetch preset list from XansiVA/nirimation in a background thread."""
    _fetch_presets_from_github(
        _NIRIMATION_API,
        _NIRIMATION_RAW,
        _NIRIMATION_HTML,
        "_nirimation_cache",
        callback,
    )


def _fetch_jgarza_presets(callback):
    """Fetch preset list from jgarza9788/niri-animation-collection in a background thread."""
    _fetch_presets_from_github(
        _JGARZA_API,
        _JGARZA_RAW,
        _JGARZA_HTML,
        "_jgarza_cache",
        callback,
    )


class AnimationsPage(BasePage):
    def __init__(self, window):
        super().__init__(window)
        self._prev_anim_snapshot = None
        self._active_preset_name = None
        self._state_file = Path("~/.config/nirimod/animations.json").expanduser()
        self._load_state()

    def _load_state(self):
        try:
            if self._state_file.exists():
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._prev_anim_snapshot = data.get("prev_anim_snapshot")
                    self._active_preset_name = data.get("active_preset_name")
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load animations state: {e}")

    def _save_state(self):
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "prev_anim_snapshot": self._prev_anim_snapshot,
                        "active_preset_name": self._active_preset_name,
                    },
                    f,
                )
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save animations state: {e}")

    def build(self) -> Gtk.Widget:
        tb, header, _, _ = self._make_toolbar_page("")
        header.set_title_widget(Gtk.Box())  # hide the default title

        # Custom Header (matches Workspace View / Keybindings aesthetic)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_start(24)
        header_box.set_margin_end(24)
        header_box.set_margin_top(20)
        header_box.set_margin_bottom(12)

        # Title/Subtitle Group
        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_vbox.set_hexpand(True)

        self._main_title = Gtk.Label(label="Animations")
        self._main_title.set_xalign(0.0)
        self._main_title.add_css_class("title-1")
        title_vbox.append(self._main_title)

        self._active_preset_lbl = Gtk.Label(label="Using custom animations")
        self._active_preset_lbl.set_xalign(0.0)
        self._active_preset_lbl.add_css_class("dim-label")
        self._active_preset_lbl.add_css_class("caption")
        title_vbox.append(self._active_preset_lbl)
        header_box.append(title_vbox)

        # View Switcher (Styled as Custom/Presets buttons)
        self._view_stack = Adw.ViewStack()

        switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        switcher_box.add_css_class("linked")
        switcher_box.set_valign(Gtk.Align.START)

        self._btn_custom = Gtk.ToggleButton(label="Custom")
        self._btn_presets = Gtk.ToggleButton(label="Presets")
        self._btn_presets.set_group(self._btn_custom)

        self._btn_custom.connect("toggled", self._on_view_toggle)
        self._btn_presets.connect("toggled", self._on_view_toggle)

        switcher_box.append(self._btn_custom)
        switcher_box.append(self._btn_presets)
        header_box.append(switcher_box)

        # Custom Header (matches Workspace View / Keybindings aesthetic)
        self._view_stack = Adw.ViewStack()
        self._view_stack.set_vexpand(True)

        # Tabs
        custom_widget = self._build_custom_tab()
        self._view_stack.add_named(custom_widget, "custom")

        presets_widget = self._build_presets_tab()
        self._view_stack.add_named(presets_widget, "presets")

        # Default to Custom
        self._view_stack.set_visible_child_name("custom")
        self._btn_custom.set_active(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(header_box)
        main_box.append(self._view_stack)

        tb.set_content(main_box)

        self._update_header()
        return tb

    def _on_view_toggle(self, btn):
        if not btn.get_active():
            return
        is_custom = btn == self._btn_custom
        self._view_stack.set_visible_child_name("custom" if is_custom else "presets")

    def _update_header(self):
        if self._active_preset_name:
            self._active_preset_lbl.set_label(
                f"Active preset: <b>{GLib.markup_escape_text(self._active_preset_name)}</b>"
            )
            self._active_preset_lbl.set_use_markup(True)
        else:
            self._active_preset_lbl.set_label("Using custom animations")
            self._active_preset_lbl.set_use_markup(False)

        if hasattr(self, "_custom_switch_grp"):
            self._custom_switch_grp.set_visible(self._prev_anim_snapshot is not None)

    def _build_custom_tab(self) -> Gtk.Widget:
        """Return the custom animations tab (global toggles, bezier editor, and categories)."""
        if not hasattr(self, "_custom_scroll"):
            self._custom_scroll = Gtk.ScrolledWindow()
            self._custom_scroll.set_policy(
                Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC
            )
            self._custom_scroll.set_vexpand(True)
            self._custom_content = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=20
            )
            self._custom_content.set_hexpand(True)
            self._custom_content.set_margin_start(24)
            self._custom_content.set_margin_end(24)
            self._custom_content.set_margin_top(24)
            self._custom_content.set_margin_bottom(24)
            self._custom_scroll.set_child(self._custom_content)
        else:
            while child := self._custom_content.get_first_child():
                self._custom_content.remove(child)

        content = self._custom_content
        anim_node = find_or_create(self._nodes, "animations")

        # ── Switch to Custom Banner ──────────────────────────────────────────
        self._custom_switch_grp = Adw.PreferencesGroup()
        self._custom_switch_grp.set_hexpand(True)
        self._custom_switch_row = Adw.ActionRow(
            title="Community Preset Active",
            subtitle="You are currently using a preset. Switch back to use your custom animation settings.",
        )
        self._custom_switch_row.add_css_class("property")
        self._custom_switch_row.set_icon_name("emblem-important-symbolic")
        switch_btn = Gtk.Button(label="Switch to Custom")
        switch_btn.add_css_class("suggested-action")
        switch_btn.add_css_class("pill")
        switch_btn.set_valign(Gtk.Align.CENTER)
        switch_btn.set_margin_top(8)
        switch_btn.set_margin_bottom(8)
        switch_btn.connect("clicked", self._on_restore_previous)
        self._custom_switch_row.add_suffix(switch_btn)
        self._custom_switch_grp.add(self._custom_switch_row)
        self._custom_switch_grp.set_visible(self._prev_anim_snapshot is not None)
        content.append(self._custom_switch_grp)

        # ── Global Settings ──────────────────────────────────────────────────
        off_grp = Adw.PreferencesGroup(
            title="Global Settings",
            description="These apply to all animations universally.",
        )
        off_grp.set_hexpand(True)
        off_row = Adw.SwitchRow(
            title="Enable Animations",
            subtitle="Toggle all desktop animations on or off",
        )
        off_row.set_icon_name("media-playback-start-symbolic")
        off_row.set_active(anim_node.get_child("off") is None)
        off_row.connect(
            "notify::active", lambda r, _: self._toggle_all(not r.get_active())
        )
        off_grp.add(off_row)

        slowdown_val = float(anim_node.child_arg("slowdown", 1.0))
        slowdown_adj = Gtk.Adjustment(
            value=slowdown_val, lower=0.1, upper=10.0, step_increment=0.1
        )
        slowdown_row = Adw.SpinRow(
            title="Global Slowdown Factor",
            subtitle="Multiply all animation durations by this factor",
            adjustment=slowdown_adj,
            digits=1,
        )
        slowdown_row.set_icon_name("preferences-system-time-symbolic")
        slowdown_row._last_val = slowdown_val

        def _on_slowdown_changed(r, _):
            new_val = float(r.get_value())
            if abs(new_val - getattr(r, "_last_val", 0.0)) > 0.01:
                r._last_val = new_val
                self._set_anim("slowdown", new_val)

        slowdown_row.connect("notify::value", _on_slowdown_changed)
        off_grp.add(slowdown_row)
        content.append(off_grp)

        # ── Easing Curve Editor ──────────────────────────────────────────────
        bezier_grp = Adw.PreferencesGroup(
            title="Easing Curve Editor",
            description="Design a custom easing curve to apply to any animation below.",
        )
        bezier_grp.set_hexpand(True)

        editor_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=48)
        editor_row.set_margin_start(12)
        editor_row.set_margin_end(12)
        editor_row.set_margin_top(20)
        editor_row.set_margin_bottom(20)
        editor_row.set_halign(Gtk.Align.CENTER)

        # Left: bezier canvas
        edit_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        edit_vbox.set_valign(Gtk.Align.CENTER)
        self._bezier_editor = BezierEditor(on_changed=self._on_bezier_changed)
        self._bezier_editor.set_halign(Gtk.Align.CENTER)
        edit_vbox.append(self._bezier_editor)

        coords_lbl = Gtk.Label(label="0.25, 0.1, 0.25, 1.0")
        coords_lbl.add_css_class("monospace")
        coords_lbl.add_css_class("dim-label")
        coords_lbl.set_selectable(True)
        coords_lbl.set_halign(Gtk.Align.CENTER)
        self._coords_lbl = coords_lbl
        edit_vbox.append(coords_lbl)
        editor_row.append(edit_vbox)

        # Right: quick presets
        presets_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        presets_vbox.set_valign(Gtk.Align.CENTER)
        preset_title = Gtk.Label(label="Quick Presets", xalign=0)
        preset_title.add_css_class("heading")
        presets_vbox.append(preset_title)

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(2)
        flow.set_min_children_per_line(2)
        flow.set_valign(Gtk.Align.START)
        flow.set_column_spacing(6)
        flow.set_row_spacing(6)
        for name, curve in PRESET_CURVES.items():
            btn = Gtk.Button(label=name)
            btn.connect("clicked", lambda b, c=curve, n=name: self._apply_preset(c, n))
            flow.append(btn)
        presets_vbox.append(flow)
        editor_row.append(presets_vbox)

        bezier_grp.add(editor_row)
        content.append(bezier_grp)

        # ── Per-animation groups ─────────────────────────────────────────────
        for group_title, anims in ANIM_GROUPS:
            grp = Adw.PreferencesGroup(title=group_title)
            grp.set_hexpand(True)
            for anim_key, anim_label, icon_name in anims:
                row = self._build_anim_row(anim_key, anim_label, icon_name, anim_node)
                grp.add(row)
            content.append(grp)

        return self._custom_scroll

    def _build_presets_tab(self) -> Gtk.Widget:
        """Return the community presets tab (downloaded + online sources)."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_hexpand(True)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        scroll.set_child(content)

        # Downloaded / offline section — always shown first
        self._presets_content = content
        self._local_presets_grp: Adw.PreferencesGroup | None = None
        self._refresh_local_presets_group()

        nim_grp = self._build_nirimation_group()
        nim_grp.set_hexpand(True)
        content.append(nim_grp)

        jgarza_grp = self._build_jgarza_group()
        jgarza_grp.set_hexpand(True)
        content.append(jgarza_grp)

        return scroll

    # ------------------------------------------------------------------ local

    def _local_preset_dir(self, source_label: str) -> Path:
        slug = _SOURCE_SLUGS.get(source_label, source_label.replace("/", "-"))
        return _LOCAL_PRESETS_DIR / slug

    def _list_local_presets(self) -> list[dict]:
        """Return all downloaded presets sorted by display name."""
        entries: list[dict] = []
        if not _LOCAL_PRESETS_DIR.exists():
            return entries
        for source_dir in sorted(_LOCAL_PRESETS_DIR.iterdir()):
            if not source_dir.is_dir():
                continue
            # Reverse-map slug → label
            slug_to_label = {v: k for k, v in _SOURCE_SLUGS.items()}
            source_label = slug_to_label.get(source_dir.name, source_dir.name)
            for kdl_file in sorted(source_dir.glob("*.kdl")):
                stem = kdl_file.stem
                display = stem.replace("-", " ").replace("_", " ").title()
                entries.append(
                    {
                        "name": kdl_file.name,
                        "display_name": display,
                        "source_label": source_label,
                        "local_path": kdl_file,
                    }
                )
        return entries

    def _refresh_local_presets_group(self):
        """Rebuild the Downloaded Presets group from the filesystem."""
        # Remove the old group widget from the content box if present
        if self._local_presets_grp is not None and hasattr(self, "_presets_content"):
            try:
                self._presets_content.remove(self._local_presets_grp)
            except (TypeError, ValueError):
                pass

        entries = self._list_local_presets()

        grp = Adw.PreferencesGroup(
            title="Downloaded Presets",
            description="Locally saved presets — apply these without an internet connection.",
        )
        grp.set_hexpand(True)
        grp.set_header_suffix(self._make_open_folder_btn())
        self._local_presets_grp = grp

        if not entries:
            empty_row = Adw.ActionRow(
                title="No presets downloaded yet",
                subtitle="Use the download button (\u2193) next to any online preset below.",
            )
            empty_row.add_prefix(
                Gtk.Image.new_from_icon_name("folder-download-symbolic")
            )
            grp.add(empty_row)
        else:
            for entry in entries:
                row = self._make_local_preset_row(entry)
                grp.add(row)

        # Prepend at the top of the presets content box
        if hasattr(self, "_presets_content"):
            # Insert before the first child (nirimation group)
            first = self._presets_content.get_first_child()
            if first:
                self._presets_content.insert_child_after(grp, None)  # prepend
            else:
                self._presets_content.append(grp)

    def _make_open_folder_btn(self) -> Gtk.Button:
        btn = Gtk.Button(icon_name="folder-open-symbolic")
        btn.set_tooltip_text("Open presets folder")
        btn.add_css_class("flat")
        btn.add_css_class("circular")
        btn.connect(
            "clicked",
            lambda _b: Gtk.show_uri(None, _LOCAL_PRESETS_DIR.as_uri(), 0),
        )
        return btn

    def _make_local_preset_row(self, entry: dict) -> Adw.ActionRow:
        """Row for a locally-downloaded preset (Apply + Delete)."""
        row = Adw.ActionRow(
            title=entry["display_name"],
            subtitle=f"{entry['source_label']}  ·  {entry['name']}",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))

        # Delete button
        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.set_tooltip_text("Delete local copy")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.connect(
            "clicked",
            lambda _b, e=entry: self._delete_local_preset(e),
        )
        row.add_suffix(del_btn)

        # Apply button
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.add_css_class("pill")
        apply_btn.set_valign(Gtk.Align.CENTER)
        apply_btn.connect(
            "clicked",
            lambda _b, e=entry, r=row: self._confirm_apply_local_preset(e, r),
        )
        row.add_suffix(apply_btn)

        return row

    def _confirm_apply_local_preset(self, entry: dict, row: Adw.ActionRow):
        try:
            dialog = Adw.AlertDialog(
                heading=f'Apply "{entry["display_name"]}"?',
                body=(
                    "This will fully replace your current animations block with the locally saved "
                    f'"{entry["display_name"]}" preset.\n\n'
                    "Your existing bezier curves and per-animation settings will be overwritten. "
                    "You can undo this with Ctrl+Z."
                ),
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("apply", "Apply Preset")
            dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def _on_response(d, resp):
                if resp == "apply":
                    self._apply_local_preset(entry, row)

            dialog.connect("response", _on_response)
            dialog.present(self._win)
        except AttributeError:
            self._apply_local_preset(entry, row)

    def _apply_local_preset(self, entry: dict, row: Adw.ActionRow):
        """Apply a locally-saved .kdl file (no network required)."""
        try:
            kdl_text = entry["local_path"].read_text(encoding="utf-8")
            self._do_apply_kdl_preset(kdl_text, entry["display_name"], row)
        except OSError as exc:
            self.show_toast(f"Failed to read local preset: {exc}")

    def _delete_local_preset(self, entry: dict):
        try:
            entry["local_path"].unlink(missing_ok=True)
            # Clean up empty source dir
            parent = entry["local_path"].parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            self.show_toast(f"{entry['display_name']} deleted")
            self._refresh_local_presets_group()
        except OSError as exc:
            self.show_toast(f"Delete failed: {exc}")

    def _on_restore_previous(self, _btn):
        """Restore the animations block that was saved before the last preset apply."""
        if self._prev_anim_snapshot is None:
            return
        try:
            snap_nodes = parse_kdl(self._prev_anim_snapshot)
            snap_anim = next((n for n in snap_nodes if n.name == "animations"), None)
            user_nodes = self._nodes
            user_anim = next(
                (n for n in reversed(user_nodes) if n.name == "animations"), None
            )
            if user_anim is None:
                user_anim = KdlNode(name="animations")
                user_anim.leading_trivia = "\n"
                user_nodes.append(user_anim)
            if snap_anim is not None:
                user_anim.children = list(snap_anim.children)
                user_anim.args = list(snap_anim.args)
                user_anim.props = dict(snap_anim.props)
            else:
                user_anim.children = []
                user_anim.args = []
                user_anim.props = {}
            self._prev_anim_snapshot = None
            self._active_preset_name = None
            self._save_state()
            self._commit("restore previous animations")
            self.show_toast("↩ Previous animations restored")
            self._update_header()
            self._build_custom_tab()  # Refresh UI components
        except (OSError, ValueError, IndexError, TypeError) as exc:
            self.show_toast(f"Restore failed: {exc}")

    def _build_preset_group(
        self,
        title: str,
        description: str,
        fetch_fn,
        bust_cache_attr: str,
        rows_attr: str,
        source_label: str,
        repo_url: str,
    ) -> Adw.PreferencesGroup:
        """Generic builder for a community-preset PreferencesGroup."""
        import sys

        mod = sys.modules[__name__]

        header_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        repo_btn = Gtk.Button(icon_name="web-browser-symbolic")
        repo_btn.set_tooltip_text("View repository on GitHub")
        repo_btn.add_css_class("flat")
        repo_btn.add_css_class("circular")
        repo_btn.connect("clicked", lambda _b: Gtk.show_uri(None, repo_url, 0))
        header_btns.append(repo_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh preset list from GitHub")
        refresh_btn.add_css_class("flat")
        refresh_btn.add_css_class("circular")
        header_btns.append(refresh_btn)

        grp = Adw.PreferencesGroup(title=title, description=description)
        grp.set_header_suffix(header_btns)

        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(8)
        spinner.set_margin_bottom(8)
        spinner_row = Adw.ActionRow(title="Fetching presets…")
        spinner_row.add_prefix(spinner)
        grp.add(spinner_row)

        rows: list[Adw.ActionRow] = []
        setattr(self, rows_attr, rows)

        def _on_result(result):
            grp.remove(spinner_row)
            spinner.stop()
            if isinstance(result, Exception):
                err_row = Adw.ActionRow(
                    title="Unable to fetch presets",
                    subtitle=str(result),
                )
                err_row.add_prefix(
                    Gtk.Image.new_from_icon_name("network-error-symbolic")
                )
                grp.add(err_row)
                rows.append(err_row)
                return
            for entry in result:
                row = self._make_preset_row(entry, source_label)
                grp.add(row)
                rows.append(row)

        def _on_refresh_clicked(_btn):
            setattr(mod, bust_cache_attr, None)
            for row in list(rows):
                grp.remove(row)
            rows.clear()
            sp2 = Gtk.Spinner()
            sp2.start()
            sp2.set_margin_top(8)
            sp2.set_margin_bottom(8)
            wait_row = Adw.ActionRow(title="Fetching presets…")
            wait_row.add_prefix(sp2)
            grp.add(wait_row)

            def _on_result2(result):
                grp.remove(wait_row)
                sp2.stop()
                if isinstance(result, Exception):
                    err_row = Adw.ActionRow(
                        title="Unable to fetch presets",
                        subtitle=str(result),
                    )
                    err_row.add_prefix(
                        Gtk.Image.new_from_icon_name("network-error-symbolic")
                    )
                    grp.add(err_row)
                    rows.append(err_row)
                    return
                for entry in result:
                    row = self._make_preset_row(entry, source_label)
                    grp.add(row)
                    rows.append(row)

            fetch_fn(_on_result2)

        refresh_btn.connect("clicked", _on_refresh_clicked)
        fetch_fn(_on_result)
        return grp

    def _build_nirimation_group(self) -> Adw.PreferencesGroup:
        """Build the XansiVA/nirimation presets section."""
        return self._build_preset_group(
            title="Nirimation Community Presets",
            description="GLSL shader animations from XansiVA/nirimation — replaces your current animations block.",
            fetch_fn=_fetch_nirimation_presets,
            bust_cache_attr="_nirimation_cache",
            rows_attr="_nirimation_rows",
            source_label="XansiVA/nirimation",
            repo_url="https://github.com/XansiVA/nirimation",
        )

    def _build_jgarza_group(self) -> Adw.PreferencesGroup:
        """Build the jgarza9788/niri-animation-collection presets section."""
        return self._build_preset_group(
            title="Niri Animation Collection",
            description="Community GLSL shader presets from jgarza9788/niri-animation-collection — replaces your current animations block.",
            fetch_fn=_fetch_jgarza_presets,
            bust_cache_attr="_jgarza_cache",
            rows_attr="_jgarza_rows",
            source_label="jgarza9788/niri-animation-collection",
            repo_url="https://github.com/jgarza9788/niri-animation-collection",
        )

    def _make_preset_row(self, entry: dict, source_label: str) -> Adw.ActionRow:
        """Create a single preset row for any community-preset group."""
        row = Adw.ActionRow(
            title=entry["display_name"],
            subtitle=entry["name"],
        )

        # Download-to-disk button
        dl_btn = Gtk.Button(icon_name="folder-download-symbolic")
        dl_btn.set_tooltip_text("Download preset for offline use")
        dl_btn.add_css_class("flat")
        dl_btn.add_css_class("circular")
        dl_btn.set_valign(Gtk.Align.CENTER)
        dl_btn.connect(
            "clicked",
            lambda _b, e=entry, r=row, sl=source_label, b=dl_btn: (
                self._download_preset_locally(e, r, sl, b)
            ),
        )
        row.add_suffix(dl_btn)

        # Apply button
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.add_css_class("pill")
        apply_btn.set_valign(Gtk.Align.CENTER)
        apply_btn.connect(
            "clicked",
            lambda _b, e=entry, r=row, sl=source_label: self._confirm_apply_preset(
                e, r, sl
            ),
        )
        row.add_suffix(apply_btn)

        return row

    def _download_preset_locally(self, entry, row, source_label, dl_btn):
        # download the preset KDL to disk
        dest_dir = self._local_preset_dir(source_label)
        dest_file = dest_dir / entry["name"]

        dl_btn.set_sensitive(False)
        self.show_toast(f"Downloading {entry['display_name']}…", timeout=5)

        def _worker():
            try:
                req = urllib.request.Request(
                    entry["download_url"],
                    headers={"User-Agent": "nirimod/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    kdl_bytes = resp.read()
                GLib.idle_add(_on_done, kdl_bytes, None)
            except urllib.error.URLError as exc:
                GLib.idle_add(_on_done, None, exc)

        def _on_done(kdl_bytes, error):
            dl_btn.set_sensitive(True)
            if error:
                self.show_toast(f"Download failed: {error}")
                return
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file.write_bytes(kdl_bytes)
                self.show_toast(f"{entry['display_name']} saved locally")
                # Update the download button to show it's already saved
                dl_btn.set_icon_name("emblem-ok-symbolic")
                dl_btn.set_tooltip_text("Already downloaded")
                dl_btn.set_sensitive(False)
                self._refresh_local_presets_group()
            except OSError as exc:
                self.show_toast(f"Save failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _confirm_apply_preset(self, entry, row, source_label="community"):
        try:
            dialog = Adw.AlertDialog(
                heading=f'Apply "{entry["display_name"]}"?',
                body=(
                    "This will fully replace your current animations block with the "
                    f'"{entry["display_name"]}" preset from {source_label}.\n\n'
                    "Your existing bezier curves and per-animation settings will be overwritten. "
                    "You can undo this with Ctrl+Z."
                ),
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("apply", "Apply Preset")
            dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def _on_response(d, resp):
                if resp == "apply":
                    self._apply_nirimation_preset(entry, row)

            dialog.connect("response", _on_response)
            dialog.present(self._win)
        except AttributeError:
            self._apply_nirimation_preset(entry, row)

    def _apply_nirimation_preset(self, entry, row):
        row.set_sensitive(False)
        self.show_toast(f"Downloading {entry['display_name']}...", timeout=5)

        def _worker():
            try:
                req = urllib.request.Request(
                    entry["download_url"],
                    headers={"User-Agent": "nirimod/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    kdl_text = resp.read().decode()
                GLib.idle_add(_on_downloaded, kdl_text, None)
            except urllib.error.URLError as exc:
                GLib.idle_add(_on_downloaded, None, exc)

        def _on_downloaded(kdl_text, error):
            row.set_sensitive(True)
            if error:
                self.show_toast(f"Failed to download preset: {error}")
                return
            self._do_apply_kdl_preset(kdl_text, entry["display_name"], row)

        threading.Thread(target=_worker, daemon=True).start()

    def _do_apply_kdl_preset(self, kdl_text, display_name, row):
        try:
            preset_nodes = parse_kdl(kdl_text)
            preset_anim = next(
                (n for n in preset_nodes if n.name == "animations"), None
            )
            if preset_anim is None:
                self.show_toast("Preset has no animations block — nothing applied.")
                return

            user_nodes = self._nodes
            user_anim = next(
                (n for n in reversed(user_nodes) if n.name == "animations"), None
            )

            if self._prev_anim_snapshot is None:
                from nirimod.kdl_parser import write_kdl

                if user_anim is not None:
                    snap_node = KdlNode(name="animations")
                    snap_node.children = list(user_anim.children)
                    snap_node.args = list(user_anim.args)
                    snap_node.props = dict(user_anim.props)
                    self._prev_anim_snapshot = write_kdl([snap_node])
                else:
                    self._prev_anim_snapshot = write_kdl([])

            if user_anim is None:
                user_anim = KdlNode(name="animations")
                user_anim.leading_trivia = "\n"
                user_nodes.append(user_anim)

            user_anim.children = list(preset_anim.children)
            user_anim.args = list(preset_anim.args)
            user_anim.props = dict(preset_anim.props)

            self._active_preset_name = display_name
            self._save_state()
            self._commit(f"preset: {display_name}")
            self._update_header()
            self.show_toast(f"\u2728 {display_name} preset applied!")
        except (OSError, ValueError, IndexError, TypeError) as exc:
            self.show_toast(f"Error applying preset: {exc}")

    def _apply_preset(self, curve: tuple, name: str):
        self._bezier_editor.set_curve(*curve)
        self._update_coords_label()

    def _on_bezier_changed(self, x1, y1, x2, y2):
        self._update_coords_label()

    def _update_coords_label(self):
        x1, y1, x2, y2 = self._bezier_editor.get_curve()
        self._coords_lbl.set_label(f"{x1:.3f}, {y1:.3f}, {x2:.3f}, {y2:.3f}")

    def _build_anim_row(
        self, key: str, label: str, icon_name: str, anim_node: KdlNode
    ) -> Adw.ExpanderRow:
        grp = Adw.ExpanderRow(title=label)
        grp.set_icon_name(icon_name)
        grp.add_css_class("nm-expander")
        an = anim_node.get_child(key)

        enabled_row = Adw.SwitchRow(title="Enabled")
        enabled_row.set_active(an is not None and an.get_child("off") is None)
        enabled_row.connect(
            "notify::active",
            lambda r, _, k=key: self._set_anim_enabled(k, r.get_active()),
        )
        grp.add_row(enabled_row)

        duration = an.child_arg("duration-ms") if an else 250
        dur_val = int(duration) if duration else 250
        dur_adj = Gtk.Adjustment(value=dur_val, lower=10, upper=2000, step_increment=10)
        dur_row = Adw.SpinRow(title="Duration (ms)", adjustment=dur_adj, digits=0)

        dur_row._last_val = dur_val

        def _on_dur_changed(r, _, k=key):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_anim_prop(k, "duration-ms", new_val)

        dur_row.connect("notify::value", _on_dur_changed)
        grp.add_row(dur_row)

        # Apply bezier button
        apply_btn = Gtk.Button(label="Apply Editor Curve")
        apply_btn.add_css_class("flat")
        apply_btn.set_valign(Gtk.Align.CENTER)

        # Determine current curve for subtitle

        curve_node = an.get_child("curve") if an else None
        easing = an.get_child("easing") if an else None
        current_curve = ""
        if curve_node and len(curve_node.args) >= 5:
            vals = " ".join(str(v) for v in curve_node.args[1:])
            current_curve = f"cubic-bezier {vals}"
        elif easing and easing.child_arg("bezier"):
            current_curve = f"bezier {easing.child_arg('bezier')}"
        elif easing and easing.args:
            current_curve = str(easing.args[0])

        apply_row = Adw.ActionRow(
            title="Easing Curve", subtitle=current_curve if current_curve else "Default"
        )
        apply_btn.connect(
            "clicked", lambda *_, k=key, ar=apply_row: self._apply_bezier_to_anim(k, ar)
        )
        apply_row.add_suffix(apply_btn)
        grp.add_row(apply_row)

        return grp

    def _toggle_all(self, off: bool):
        anim = find_or_create(self._nodes, "animations")
        set_node_flag(anim, "off", off)
        self._commit("animations off")

    def _set_anim(self, key: str, value):
        anim = find_or_create(self._nodes, "animations")
        set_child_arg(anim, key, value)
        self._commit(f"animations {key}")

    def _set_anim_enabled(self, anim_key: str, enabled: bool):
        anim = find_or_create(self._nodes, "animations")
        an = anim.get_child(anim_key)
        if not enabled:
            if an is None:
                an = KdlNode(anim_key)
                anim.children.append(an)
            set_node_flag(an, "off", True)
        else:
            if an:
                from nirimod.kdl_parser import remove_child

                remove_child(an, "off")
        self._commit(f"animation {anim_key} enabled")

    def _set_anim_prop(self, anim_key: str, prop: str, value):
        anim = find_or_create(self._nodes, "animations")
        an = anim.get_child(anim_key)
        if an is None:
            an = KdlNode(anim_key)
            anim.children.append(an)

        if prop == "duration-ms":
            from nirimod.kdl_parser import remove_child

            remove_child(an, "spring")

        set_child_arg(an, prop, value)
        self._commit(f"animation {anim_key} {prop}")

    def _apply_bezier_to_anim(self, anim_key: str, apply_row: Adw.ActionRow = None):
        x1, y1, x2, y2 = self._bezier_editor.get_curve()
        anim = find_or_create(self._nodes, "animations")
        an = anim.get_child(anim_key)
        if an is None:
            an = KdlNode(anim_key)
            anim.children.append(an)

        # Remove legacy easing block if present
        old_easing = an.get_child("easing")
        if old_easing is not None:
            an.children.remove(old_easing)

        from nirimod.kdl_parser import remove_child

        remove_child(an, "spring")

        curve_node = an.get_child("curve")
        if curve_node is None:
            curve_node = KdlNode("curve")
            an.children.append(curve_node)
        curve_node.args = [
            "cubic-bezier",
            round(x1, 3),
            round(y1, 3),
            round(x2, 3),
            round(y2, 3),
        ]

        curve_str = f"{x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}"
        self._commit(f"animation {anim_key} bezier")
        self.show_toast(f"Bezier applied to {anim_key}")

        if apply_row:
            apply_row.set_subtitle(f"cubic-bezier {curve_str}")
