"""Appearance page — borders, focus ring, shadows, corner radius."""

from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from nirimod.kdl_parser import KdlNode, find_or_create, set_child_arg, set_node_flag
from nirimod.pages.base import BasePage
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


def _parse_color(color_str: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    if color_str and not rgba.parse(color_str):
        rgba.parse("#7fc8ff")
    return rgba


class AppearancePage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, _, _, content = self._make_toolbar_page("Appearance")
        self._content = content
        self._build_content()
        return tb

    def _build_content(self):
        content = self._content
        nodes = self._nodes
        layout = find_or_create(nodes, "layout")

        fr_node = layout.get_child("focus-ring") or KdlNode("focus-ring")
        fr_group = self._build_border_group("Focus Ring", "focus-ring", fr_node, layout)
        content.append(fr_group)

        b_node = layout.get_child("border") or KdlNode("border")
        b_group = self._build_border_group("Border", "border", b_node, layout)
        content.append(b_group)

        shadow_grp = Adw.PreferencesGroup(title="Shadow")
        shadow_node = layout.get_child("shadow") or KdlNode("shadow")

        shadow_on_row = Adw.SwitchRow(title="Enable Shadows")
        shadow_on_row.set_active(shadow_node.get_child("on") is not None)
        shadow_on_row.connect(
            "notify::active", lambda r, _: self._set_shadow_flag("on", r.get_active())
        )
        shadow_grp.add(shadow_on_row)

        soft_val = int(shadow_node.child_arg("softness") or 30)
        softness_adj = Gtk.Adjustment(
            value=soft_val, lower=0, upper=100, step_increment=1
        )
        softness_row = Adw.SpinRow(
            title="Softness (blur radius)", adjustment=softness_adj, digits=0
        )

        softness_row._last_val = soft_val

        def _on_soft_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_shadow("softness", new_val)

        softness_row.connect("notify::value", _on_soft_changed)
        shadow_grp.add(softness_row)

        spread_val = int(shadow_node.child_arg("spread") or 5)
        spread_adj = Gtk.Adjustment(
            value=spread_val, lower=-50, upper=100, step_increment=1
        )
        spread_row = Adw.SpinRow(title="Spread", adjustment=spread_adj, digits=0)

        spread_row._last_val = spread_val

        def _on_spread_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_shadow("spread", new_val)

        spread_row.connect("notify::value", _on_spread_changed)
        shadow_grp.add(spread_row)

        color_str = shadow_node.child_arg("color") or "#0007"
        color_row = Adw.ActionRow(title="Shadow Color")
        color_btn = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(title="Shadow Color", with_alpha=True)
        )
        color_btn.set_rgba(_parse_color(color_str))
        color_btn.set_valign(Gtk.Align.CENTER)
        color_btn.connect(
            "notify::rgba", lambda b, _: self._set_shadow_color(b.get_rgba())
        )
        color_row.add_suffix(color_btn)
        shadow_grp.add(color_row)

        draw_behind_row = Adw.SwitchRow(
            title="Draw Behind Window",
            subtitle="Fixes corner artifacts with non-CSD apps",
        )
        draw_behind_row.set_active(
            shadow_node.get_child("draw-behind-window") is not None
        )
        draw_behind_row.connect(
            "notify::active",
            lambda r, _: self._set_shadow_flag("draw-behind-window", r.get_active()),
        )
        shadow_grp.add(draw_behind_row)
        content.append(shadow_grp)

        blur_grp = Adw.PreferencesGroup(
            title="Blur (Global)",
            description=(
                "Requires Niri 26.04 or later. Sets blur quality and optional "
                "window blur rules."
            ),
        )
        blur_node = next((n for n in nodes if n.name == "blur"), None)

        blur_enabled_row = Adw.SwitchRow(
            title="Enable Window Blur",
            subtitle="Adds background-effect { blur true } to the global window rule",
        )
        blur_enabled_row.set_active(global_window_blur_enabled(nodes))
        blur_enabled_row.connect(
            "notify::active",
            lambda r, _: self._set_window_blur_enabled(r.get_active()),
        )
        blur_grp.add(blur_enabled_row)

        focused_blur_row = Adw.SwitchRow(
            title="Keep Focused Windows Blurred",
            subtitle="Adds a focused-window rule that forces blur on",
        )
        focused_blur_row.set_active(focused_window_blur_enabled(nodes))
        focused_blur_row.connect(
            "notify::active",
            lambda r, _: self._set_focused_window_blur_enabled(r.get_active()),
        )
        blur_grp.add(focused_blur_row)

        xray_row = Adw.SwitchRow(
            title="Use Xray Wallpaper Blur",
            subtitle="Use wallpaper-only blur; disable for regular background blur",
        )
        xray_row.set_active(global_window_xray_enabled(nodes))
        xray_row.connect(
            "notify::active",
            lambda r, _: self._set_window_blur_xray(r.get_active()),
        )
        blur_grp.add(xray_row)

        opacity_val = get_global_window_opacity(nodes)
        opacity_adj = Gtk.Adjustment(
            value=opacity_val, lower=0.1, upper=1.0, step_increment=0.05
        )
        opacity_row = Adw.SpinRow(
            title="Window Opacity (1 = unset)", adjustment=opacity_adj, digits=2
        )

        opacity_row._last_val = opacity_val

        def _on_opacity_changed(r, _):
            new_val = round(float(r.get_value()), 2)
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_window_opacity(new_val)

        opacity_row.connect("notify::value", _on_opacity_changed)
        blur_grp.add(opacity_row)

        border_bg_row = Adw.SwitchRow(
            title="Draw Border With Background",
            subtitle="Disable to avoid focus colors behind translucent windows",
        )
        border_bg_row.set_active(get_global_draw_border_with_background(nodes))
        border_bg_row.connect(
            "notify::active",
            lambda r, _: self._set_draw_border_with_background(r.get_active()),
        )
        blur_grp.add(border_bg_row)

        passes_val = int(blur_node.child_arg("passes") if blur_node else 0)
        passes_adj = Gtk.Adjustment(
            value=passes_val, lower=0, upper=10, step_increment=1
        )
        passes_row = Adw.SpinRow(
            title="Passes (0 = disabled)", adjustment=passes_adj, digits=0
        )

        passes_row._last_val = passes_val

        def _on_passes_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_blur("passes", new_val)

        passes_row.connect("notify::value", _on_passes_changed)
        blur_grp.add(passes_row)

        offset_val = float(blur_node.child_arg("offset") if blur_node else 2.0)
        offset_adj = Gtk.Adjustment(
            value=offset_val, lower=0.0, upper=20.0, step_increment=0.1
        )
        offset_row = Adw.SpinRow(title="Offset", adjustment=offset_adj, digits=1)

        offset_row._last_val = offset_val

        def _on_offset_changed(r, _):
            new_val = float(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_blur("offset", new_val)

        offset_row.connect("notify::value", _on_offset_changed)
        blur_grp.add(offset_row)

        noise_val = float(blur_node.child_arg("noise") if blur_node else 0.0)
        noise_adj = Gtk.Adjustment(
            value=noise_val, lower=0.0, upper=1.0, step_increment=0.01
        )
        noise_row = Adw.SpinRow(title="Noise", adjustment=noise_adj, digits=2)

        noise_row._last_val = noise_val

        def _on_noise_changed(r, _):
            new_val = float(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_blur("noise", new_val)

        noise_row.connect("notify::value", _on_noise_changed)
        blur_grp.add(noise_row)

        saturation_val = float(blur_node.child_arg("saturation") if blur_node else 1.0)
        saturation_adj = Gtk.Adjustment(
            value=saturation_val, lower=0.0, upper=5.0, step_increment=0.1
        )
        saturation_row = Adw.SpinRow(
            title="Saturation", adjustment=saturation_adj, digits=1
        )

        saturation_row._last_val = saturation_val

        def _on_saturation_changed(r, _):
            new_val = float(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_blur("saturation", new_val)

        saturation_row.connect("notify::value", _on_saturation_changed)
        blur_grp.add(saturation_row)

        content.append(blur_grp)

        misc_grp = Adw.PreferencesGroup(title="Window Geometry")

        cr_val = get_global_corner_radius(nodes)
        cr_adj = Gtk.Adjustment(value=cr_val, lower=0, upper=40, step_increment=1)
        cr_row = Adw.SpinRow(
            title="Corner Radius (px)",
            adjustment=cr_adj,
            digits=0,
        )

        cr_row._last_val = cr_val

        def _on_cr_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_corner_radius(new_val)

        cr_row.connect("notify::value", _on_cr_changed)
        misc_grp.add(cr_row)
        content.append(misc_grp)

    def _build_border_group(
        self, title: str, key: str, node: KdlNode, layout: KdlNode
    ) -> Adw.PreferencesGroup:
        grp = Adw.PreferencesGroup(title=title)

        off_row = Adw.SwitchRow(title="Enable")
        off_row.set_active(node.get_child("off") is None)
        off_row.connect(
            "notify::active",
            lambda r, _, k=key: self._set_layout_border_flag(
                k, "off", not r.get_active()
            ),
        )
        grp.add(off_row)

        width_val = int(node.child_arg("width") or 4)
        width_adj = Gtk.Adjustment(value=width_val, lower=1, upper=20, step_increment=1)
        width_row = Adw.SpinRow(title="Width (px)", adjustment=width_adj, digits=0)

        width_row._last_val = width_val

        def _on_width_changed(r, _, k=key):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_layout_border(k, "width", new_val)

        width_row.connect("notify::value", _on_width_changed)
        grp.add(width_row)

        for color_key, color_label in [
            ("active-color", "Active Color"),
            ("inactive-color", "Inactive Color"),
        ]:
            c_str = node.child_arg(color_key) or (
                "#7fc8ff" if "active" in color_key else "#202020"
            )
            c_row = Adw.ActionRow(title=color_label)
            c_btn = Gtk.ColorDialogButton(
                dialog=Gtk.ColorDialog(title=color_label, with_alpha=True)
            )
            c_btn.set_rgba(_parse_color(c_str))
            c_btn.set_valign(Gtk.Align.CENTER)
            c_btn.connect(
                "notify::rgba",
                lambda b, _, k=key, ck=color_key: self._set_layout_border(
                    k, ck, self._rgba_to_hex(b.get_rgba())
                ),
            )
            c_row.add_suffix(c_btn)
            grp.add(c_row)

        return grp

    @staticmethod
    def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        a = int(rgba.alpha * 255)
        if a == 255:
            return f"#{r:02x}{g:02x}{b:02x}"
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"

    def _get_layout(self):
        return find_or_create(self._nodes, "layout")

    def _get_border_node(self, key: str) -> KdlNode:
        layout = self._get_layout()
        node = layout.get_child(key)
        if node is None:
            node = KdlNode(key)
            layout.children.append(node)
        return node

    def _set_layout_border(self, bkey: str, prop: str, value):
        node = self._get_border_node(bkey)
        set_child_arg(node, prop, value)
        self._commit(f"{bkey} {prop}")

    def _set_layout_border_flag(self, bkey: str, flag: str, enabled: bool):
        node = self._get_border_node(bkey)
        set_node_flag(node, flag, enabled)
        self._commit(f"{bkey} {flag}")

    def _get_shadow_node(self) -> KdlNode:
        layout = self._get_layout()
        node = layout.get_child("shadow")
        if node is None:
            node = KdlNode("shadow")
            layout.children.append(node)
        return node

    def _set_shadow(self, prop: str, value):
        set_child_arg(self._get_shadow_node(), prop, value)
        self._commit(f"shadow {prop}")

    def _set_shadow_flag(self, flag: str, enabled: bool):
        set_node_flag(self._get_shadow_node(), flag, enabled)
        self._commit(f"shadow {flag}")

    def _set_shadow_color(self, rgba: Gdk.RGBA):
        set_child_arg(self._get_shadow_node(), "color", self._rgba_to_hex(rgba))
        self._commit("shadow color")

    def _set_blur(self, prop: str, value):
        # If passes is being set to 0, remove the blur node entirely — it's
        # a Niri 26.04+ feature and an empty/zero block causes a validation
        # error on older versions.
        if prop == "passes" and int(value) == 0:
            blur_node = next((n for n in self._nodes if n.name == "blur"), None)
            if blur_node is not None:
                self._nodes.remove(blur_node)
            self._commit("blur removed")
            return
        blur_node = find_or_create(self._nodes, "blur")
        set_child_arg(blur_node, prop, value)
        self._commit(f"blur {prop}")

    def _set_window_blur_enabled(self, enabled: bool):
        set_global_window_blur(self._nodes, enabled)
        self._commit("window blur")

    def _set_focused_window_blur_enabled(self, enabled: bool):
        set_focused_window_blur(self._nodes, enabled)
        self._commit("focused window blur")

    def _set_window_blur_xray(self, enabled: bool):
        set_global_window_xray(self._nodes, enabled)
        self._commit("window blur xray")

    def _set_window_opacity(self, opacity: float):
        set_global_window_opacity(self._nodes, opacity)
        self._commit("window opacity")

    def _set_draw_border_with_background(self, enabled: bool):
        set_global_draw_border_with_background(self._nodes, enabled)
        self._commit("draw border with background")

    def _set_corner_radius(self, radius: int):
        set_global_corner_radius(self._nodes, radius)
        self._commit("corner radius")

    def refresh(self):
        for child in list(self._content):
            self._content.remove(child)
        self._build_content()
