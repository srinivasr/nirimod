"""Layout settings page."""

from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from nirimod.kdl_parser import KdlNode, find_or_create, set_child_arg, remove_child
from nirimod.column_display import (
    COLUMN_DISPLAY_LABELS,
    column_display_index,
    column_display_value,
)
from nirimod.pages.base import BasePage


CENTER_OPTIONS = ["never", "always", "on-overflow"]


class LayoutPage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, _, _, content = self._make_toolbar_page("Layout")
        self._content = content
        self._build_content()
        return tb

    def _build_content(self):
        content = self._content
        nodes = self._nodes
        layout = find_or_create(nodes, "layout")

        basic_grp = Adw.PreferencesGroup(title="General")

        gaps_val = int(layout.child_arg("gaps") or 16)
        gaps_adj = Gtk.Adjustment(value=gaps_val, lower=0, upper=200, step_increment=2)
        gaps_row = Adw.SpinRow(title="Window Gaps (px)", adjustment=gaps_adj, digits=0)

        gaps_row._last_val = gaps_val

        def _on_gaps_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_layout("gaps", new_val)

        gaps_row.connect("notify::value", _on_gaps_changed)
        basic_grp.add(gaps_row)

        cfc_model = Gtk.StringList.new(CENTER_OPTIONS)
        cfc_row = Adw.ComboRow(title="Center Focused Column", model=cfc_model)
        cur_cfc = layout.child_arg("center-focused-column") or "never"
        if cur_cfc in CENTER_OPTIONS:
            cfc_row.set_selected(CENTER_OPTIONS.index(cur_cfc))
        cfc_row.connect(
            "notify::selected",
            lambda r, _: self._set_layout(
                "center-focused-column", CENTER_OPTIONS[r.get_selected()]
            ),
        )
        basic_grp.add(cfc_row)

        display_model = Gtk.StringList.new(COLUMN_DISPLAY_LABELS)
        display_row = Adw.ComboRow(
            title="Default Column Display",
            subtitle="How new columns open",
            model=display_model,
        )
        display_row.set_selected(
            column_display_index(layout.child_arg("default-column-display"))
        )
        display_row.connect(
            "notify::selected",
            lambda r, _: self._set_layout(
                "default-column-display", column_display_value(r.get_selected())
            ),
        )
        basic_grp.add(display_row)

        prefer_csd_row = Adw.SwitchRow(
            title="Prefer No CSD", subtitle="Ask apps to omit client-side decorations"
        )
        prefer_csd_row.set_active(any(n.name == "prefer-no-csd" for n in nodes))
        prefer_csd_row.connect(
            "notify::active",
            lambda r, _: self._toggle_top("prefer-no-csd", r.get_active()),
        )
        basic_grp.add(prefer_csd_row)

        bg_color_val = str(layout.child_arg("background-color") or "transparent")
        bg_row = Adw.EntryRow(title="Background Color (e.g. transparent, #000000)")
        bg_row.set_text(bg_color_val)
        bg_row.set_show_apply_button(True)
        bg_row.connect(
            "apply",
            lambda r: self._set_layout("background-color", r.get_text().strip()),
        )
        basic_grp.add(bg_row)

        content.append(basic_grp)

        dcw_grp = Adw.PreferencesGroup(title="Default Column Width")
        dcw_node = layout.get_child("default-column-width")

        prop_val = 0.5
        fixed_val = 800
        use_fixed = False

        if dcw_node:
            fc = dcw_node.get_child("fixed")
            pc = dcw_node.get_child("proportion")
            if fc and fc.args:
                fixed_val = int(fc.args[0])
                use_fixed = True
            elif pc and pc.args:
                prop_val = float(pc.args[0])

        mode_model = Gtk.StringList.new(["Proportion", "Fixed (px)"])
        mode_row = Adw.ComboRow(title="Mode", model=mode_model)
        mode_row.set_selected(1 if use_fixed else 0)
        dcw_grp.add(mode_row)

        prop_adj = Gtk.Adjustment(value=prop_val, lower=0.05, upper=1.0, step_increment=0.05)
        prop_spin = Gtk.SpinButton(adjustment=prop_adj, digits=2, climb_rate=1)
        prop_spin.set_valign(Gtk.Align.CENTER)
        prop_spin.connect("value-changed", lambda s: self._set_dcw_proportion(s.get_value()))
        prop_row = Adw.ActionRow(title="Proportion")
        prop_row.add_suffix(prop_spin)
        prop_row.set_visible(not use_fixed)
        dcw_grp.add(prop_row)

        fixed_adj = Gtk.Adjustment(value=fixed_val, lower=100, upper=7680, step_increment=10)
        fixed_spin = Gtk.SpinButton(adjustment=fixed_adj, digits=0, climb_rate=1)
        fixed_spin.set_valign(Gtk.Align.CENTER)
        fixed_spin.connect("value-changed", lambda s: self._set_dcw_fixed(int(s.get_value())))
        fixed_row = Adw.ActionRow(title="Fixed Width (px)")
        fixed_row.add_suffix(fixed_spin)
        fixed_row.set_visible(use_fixed)
        dcw_grp.add(fixed_row)

        def _on_mode_changed(r, _):
            is_fixed = r.get_selected() == 1
            prop_row.set_visible(not is_fixed)
            fixed_row.set_visible(is_fixed)
            if is_fixed:
                self._set_dcw_fixed(int(fixed_spin.get_value()))
            else:
                self._set_dcw_proportion(prop_spin.get_value())

        mode_row.connect("notify::selected", _on_mode_changed)
        content.append(dcw_grp)

        pw_grp = Adw.PreferencesGroup(title="Preset Column Widths (proportions)")
        pw_grp.set_description("Cycled through by Mod+R")
        pcw_node = layout.get_child("preset-column-widths")
        presets = []
        if pcw_node:
            for c in pcw_node.children:
                if c.name == "proportion" and c.args:
                    presets.append(float(c.args[0]))
        self._preset_spins: list[Gtk.SpinButton] = []

        for val in presets or [0.333, 0.5, 0.667]:
            self._add_preset_row(pw_grp, val)
        add_preset_btn = Gtk.Button(label="Add Preset")
        add_preset_btn.add_css_class("flat")
        add_preset_btn.connect("clicked", lambda *_: self._add_preset_row(pw_grp, 0.5))
        pw_grp.set_header_suffix(add_preset_btn)
        content.append(pw_grp)

        struts_grp = Adw.PreferencesGroup(title="Struts (outer gaps, px)")
        struts_node = layout.get_child("struts")
        for side in ["left", "right", "top", "bottom"]:
            val = int(struts_node.child_arg(side) or 0) if struts_node else 0
            adj = Gtk.Adjustment(value=val, lower=0, upper=500, step_increment=4)
            row = Adw.SpinRow(title=side.capitalize(), adjustment=adj, digits=0)

            row._last_val = val

            def _on_strut_changed(r, _, s=side):
                new_val = int(r.get_value())
                if new_val != getattr(r, "_last_val", None):
                    r._last_val = new_val
                    self._set_strut(s, new_val)

            row.connect("notify::value", _on_strut_changed)
            struts_grp.add(row)
        content.append(struts_grp)

    def _add_preset_row(self, grp: Adw.PreferencesGroup, val: float):
        spin_adj = Gtk.Adjustment(value=val, lower=0.05, upper=1.0, step_increment=0.05)
        spin = Gtk.SpinButton(adjustment=spin_adj, digits=3, climb_rate=1)
        spin.set_valign(Gtk.Align.CENTER)
        self._preset_spins.append(spin)

        row = Adw.ActionRow(title=f"Proportion {val:.3f}")
        spin.connect(
            "value-changed",
            lambda s, r=row: (
                r.set_title(f"Proportion {s.get_value():.3f}"),
                self._save_presets(),
            ),
        )

        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.add_css_class("flat")
        del_btn.add_css_class("error")

        def _on_delete(s=spin):
            self._preset_spins.remove(s)
            grp.remove(row)
            self._save_presets()

        del_btn.connect("clicked", lambda *_: _on_delete())
        row.add_suffix(spin)
        row.add_suffix(del_btn)
        grp.add(row)

    def _save_presets(self):
        layout = find_or_create(self._nodes, "layout")
        pcw = layout.get_child("preset-column-widths")
        if pcw is None:
            pcw = KdlNode("preset-column-widths")
            layout.children.append(pcw)
        new_children = []
        for i, s in enumerate(self._preset_spins):
            if i < len(pcw.children):
                child = pcw.children[i]
                child.name = "proportion"
                child.args = [round(s.get_value(), 5)]
                new_children.append(child)
            else:
                new_children.append(KdlNode("proportion", args=[round(s.get_value(), 5)]))
                
        salvaged = ""
        for i in range(len(self._preset_spins), len(pcw.children)):
            salvaged += pcw.children[i].leading_trivia
        if salvaged and new_children:
            new_children[-1].trailing_trivia += salvaged
            
        pcw.children = new_children
        self._commit("preset column widths")

    def _set_layout(self, key: str, value):
        layout = find_or_create(self._nodes, "layout")
        set_child_arg(layout, key, value)
        self._commit(f"layout {key}")

    def _set_dcw_proportion(self, val: float):
        layout = find_or_create(self._nodes, "layout")
        dcw = layout.get_child("default-column-width")
        if dcw is None:
            dcw = KdlNode("default-column-width")
            layout.children.append(dcw)
        dcw.children = [KdlNode("proportion", args=[round(val, 4)])]
        self._commit("default column width proportion")

    def _set_dcw_fixed(self, px: int):
        layout = find_or_create(self._nodes, "layout")
        dcw = layout.get_child("default-column-width")
        if dcw is None:
            dcw = KdlNode("default-column-width")
            layout.children.append(dcw)
        dcw.children = [KdlNode("fixed", args=[px])]
        self._commit("default column width fixed")

    def _set_strut(self, side: str, val: int):
        layout = find_or_create(self._nodes, "layout")
        struts = layout.get_child("struts")
        if struts is None:
            struts = KdlNode("struts")
            layout.children.append(struts)
        if val > 0:
            set_child_arg(struts, side, val)
        else:
            remove_child(struts, side)
        self._commit(f"strut {side}")

    def _toggle_top(self, key: str, enabled: bool):
        nodes = self._nodes
        existing = next((n for n in reversed(nodes) if n.name == key), None)
        
        app_state = self._win.app_state
        if enabled and not existing:
            cache = getattr(app_state, "_removed_top_nodes", {})
            if key in cache:
                idx, node = cache[key]
                nodes.insert(min(idx, len(nodes)), node)
            else:
                nodes.append(KdlNode(key))
        elif not enabled and existing:
            if not hasattr(app_state, "_removed_top_nodes"):
                app_state._removed_top_nodes = {}
            app_state._removed_top_nodes[key] = (nodes.index(existing), existing)
            nodes.remove(existing)
            
        self._commit(f"toggle {key}")

    def refresh(self):
        for child in list(self._content):
            self._content.remove(child)
        self._build_content()
