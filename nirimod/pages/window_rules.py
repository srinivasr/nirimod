"""Window Rules page — redesigned for usability."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from nirimod.kdl_parser import KdlNode, KdlRawString
from nirimod.pages.base import BasePage


# ── Human-readable labels ────────────────────────────────────────────────────

SCREENCAST_BLOCK_KEY = "block-out-from"

BOOL_MATCH_LABELS = {
    "is-active": "Is Active",
    "is-floating": "Is Floating",
    "is-focused": "Is Focused",
    "at-startup": "At Startup",
}

BOOL_ACTION_LABELS = {
    "open-maximized": "Open Maximized",
    "open-fullscreen": "Open Fullscreen",
    "open-floating": "Open Floating",
    SCREENCAST_BLOCK_KEY: "Block from Screencast",
    "draw-border-with-background": "Draw Border with Background",
    "clip-to-geometry": "Clip to Geometry",
    "prefer-no-csd": "Prefer No CSD",
}

NUM_ACTION_LABELS = {
    "opacity": ("Opacity", 0.0, 1.0, 0.05, 2),
    "geometry-corner-radius": ("Corner Radius (px)", 0, 40, 1, 0),
    "min-width": ("Min Width (px)", 0, 7680, 1, 0),
    "min-height": ("Min Height (px)", 0, 7680, 1, 0),
    "max-width": ("Max Width (px)", 0, 7680, 1, 0),
    "max-height": ("Max Height (px)", 0, 7680, 1, 0),
    "default-window-height": ("Default Window Height (px)", 0, 7680, 1, 0),
}

STR_ACTION_LABELS = {
    "open-on-workspace": "Open on Workspace",
    "open-on-output": "Open on Output",
    "default-column-width": "Default Column Width",
}

LAYER_BOOL_ACTION_LABELS = {
    "place-within-backdrop": "Place Within Backdrop",
    SCREENCAST_BLOCK_KEY: "Block from Screencast",
}


def _bool_action_active(rule: KdlNode | None, key: str) -> bool:
    if rule is None:
        return False
    if key != SCREENCAST_BLOCK_KEY:
        return rule.get_child(key) is not None

    legacy = rule.get_child("block-out-from-screencast")
    if legacy is not None:
        return True

    node = rule.get_child(SCREENCAST_BLOCK_KEY)
    return node is not None and bool(node.args) and node.args[0] == "screencast"


def _bool_action_node(key: str) -> KdlNode:
    if key == SCREENCAST_BLOCK_KEY:
        return KdlNode(SCREENCAST_BLOCK_KEY, args=["screencast"])
    return KdlNode(key, args=[True])


def _rule_summary(rule: KdlNode) -> tuple[str, str]:
    """Return (title, subtitle) for a window-rule row."""
    matches = rule.get_children("match")
    if not matches:
        title = "Global Rule"
    else:
        parts = []
        for m in matches:
            for k, v in m.props.items():
                parts.append(f"{k}: {v}")
            for a in m.args:
                parts.append(str(a))
        title = "  •  ".join(parts) if parts else "(any)"

    badges = []
    for c in rule.children:
        if c.name == "match":
            continue
        if c.name == "opacity" and c.args:
            badges.append(f"opacity {c.args[0]}")
        elif c.name == "background-effect":
            badges.append("blur")
        elif c.name == "open-floating":
            badges.append("floating")
        elif c.name == "open-maximized":
            badges.append("maximized")
        elif c.name == "open-fullscreen":
            badges.append("fullscreen")
        elif c.name in ("clip-to-geometry", "geometry-corner-radius"):
            pass  # skip noisy ones
        else:
            badges.append(c.name.replace("-", " "))

    subtitle = ",  ".join(badges[:5]) if badges else "no actions"
    return GLib.markup_escape_text(title), GLib.markup_escape_text(subtitle)


def _layer_rule_summary(rule: KdlNode) -> tuple[str, str]:
    match_node = rule.get_child("match")
    ns = str(match_node.props.get("namespace", "")) if match_node else ""
    title = f"namespace: {ns}" if ns else "(any)"
    actions = [c.name.replace("-", " ") for c in rule.children if c.name != "match"]
    subtitle = ",  ".join(actions) if actions else "no actions"
    return GLib.markup_escape_text(title), GLib.markup_escape_text(subtitle)


# ── Page ─────────────────────────────────────────────────────────────────────


class WindowRulesPage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, header, _, content = self._make_toolbar_page("Window Rules")
        self._content = content

        add_win_btn = Gtk.Button(label="Add Window Rule")
        add_win_btn.add_css_class("flat")
        add_win_btn.set_tooltip_text("Add a new window rule")
        add_win_btn.connect("clicked", self._on_add)
        header.pack_end(add_win_btn)

        add_layer_btn = Gtk.Button(label="Add Layer Rule")
        add_layer_btn.add_css_class("flat")
        add_layer_btn.set_tooltip_text("Add a new layer-shell rule")
        add_layer_btn.connect("clicked", self._on_add_layer)
        header.pack_end(add_layer_btn)

        self._rules_grp = Adw.PreferencesGroup(title="Window Rules")
        content.append(self._rules_grp)

        self._layer_rules_grp = Adw.PreferencesGroup(
            title="Layer Rules",
            description="Rules for layer-shell surfaces (bars, overlays, wallpapers…)",
        )
        content.append(self._layer_rules_grp)

        self.refresh()
        return tb

    def refresh(self):
        self._rebuild()
        self._rebuild_layer()

    # ── Window rules ─────────────────────────────────────────────────────────

    def _get_rules(self) -> list[KdlNode]:
        return [n for n in self._nodes if n.name == "window-rule"]

    def _rebuild(self):
        parent = self._rules_grp.get_parent()
        if parent is None:
            return
        rules = self._get_rules()
        new_grp = Adw.PreferencesGroup(
            title="Window Rules",
            description=f"{len(rules)} rule(s) — click a row to edit",
        )
        for i, rule in enumerate(rules):
            new_grp.add(self._make_rule_row(rule, i))
        parent.remove(self._rules_grp)
        parent.append(new_grp)
        self._rules_grp = new_grp

    def _make_rule_row(self, rule: KdlNode, idx: int) -> Adw.ActionRow:
        title, subtitle = _rule_summary(rule)
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.set_activatable(True)
        row.set_subtitle_lines(1)
        row.add_css_class("monospace")

        # visual badge for blur / opacity
        has_blur = rule.get_child("background-effect") is not None
        op_node = rule.get_child("opacity")
        if has_blur:
            lbl = Gtk.Label(label="blur")
            lbl.add_css_class("tag")
            lbl.add_css_class("accent")
            lbl.set_valign(Gtk.Align.CENTER)
            row.add_suffix(lbl)
        if op_node and op_node.args:
            lbl2 = Gtk.Label(label=f"α {op_node.args[0]}")
            lbl2.add_css_class("tag")
            lbl2.set_valign(Gtk.Align.CENTER)
            row.add_suffix(lbl2)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.add_css_class("flat")
        del_btn.add_css_class("error")
        del_btn.set_tooltip_text("Delete rule")
        del_btn.connect("clicked", lambda *_, i=idx: self._on_delete(i))
        row.add_suffix(del_btn)

        row.connect("activated", lambda *_, i=idx: self._on_edit(i))
        return row

    def _on_add(self, *_):
        self._show_rule_dialog(None, -1)

    def _on_edit(self, idx: int):
        rules = self._get_rules()
        if 0 <= idx < len(rules):
            self._show_rule_dialog(rules[idx], idx)

    def _on_delete(self, idx: int):
        rules = self._get_rules()
        if not (0 <= idx < len(rules)):
            return
        removed = rules[idx]
        self._nodes.remove(removed)
        self._commit("remove window rule")
        self._rebuild()

        # show a quick-undo toast
        t = Adw.Toast(title="Window rule deleted", button_label="Undo", timeout=5)
        t.connect("button-clicked", lambda *_: self._win._do_undo())
        self._win._toast_overlay.add_toast(t)

    def _show_rule_dialog(self, rule: KdlNode | None, rule_idx: int):
        dialog = Adw.Dialog(title="Window Rule")
        dialog.set_content_width(520)
        dialog.set_content_height(680)

        toolbar_view = Adw.ToolbarView()
        hdr = Adw.HeaderBar()
        title_lbl = "Edit Window Rule" if rule else "New Window Rule"
        hdr.set_title_widget(Adw.WindowTitle(title=title_lbl))
        toolbar_view.add_top_bar(hdr)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        prefs = Adw.PreferencesPage()

        # ── Match criteria ────────────────────────────────────────────────
        match_grp = Adw.PreferencesGroup(
            title="Match Criteria",
            description="Leave fields empty to match any window",
        )
        match_node = rule.get_child("match") if rule else None

        app_id_row = Adw.EntryRow(title="App ID (regex, e.g. ^kitty$)")
        app_id_row.set_text(
            str(match_node.props.get("app-id", "")) if match_node else ""
        )
        match_grp.add(app_id_row)

        title_row = Adw.EntryRow(title="Window Title (regex)")
        title_row.set_text(str(match_node.props.get("title", "")) if match_node else "")
        match_grp.add(title_row)

        bool_match_rows: dict[str, Adw.SwitchRow] = {}
        for key, label in BOOL_MATCH_LABELS.items():
            sr = Adw.SwitchRow(title=label)
            val = match_node.props.get(key, False) if match_node else False
            sr.set_active(bool(val))
            match_grp.add(sr)
            bool_match_rows[key] = sr

        prefs.add(match_grp)

        # ── Visibility & layout ───────────────────────────────────────────
        layout_grp = Adw.PreferencesGroup(title="Layout &amp; Visibility")

        bool_rows: dict[str, Adw.SwitchRow] = {}
        for key, label in BOOL_ACTION_LABELS.items():
            sr = Adw.SwitchRow(title=label)
            sr.set_active(_bool_action_active(rule, key))
            layout_grp.add(sr)
            bool_rows[key] = sr

        prefs.add(layout_grp)

        # ── Visual effects ────────────────────────────────────────────────
        fx_grp = Adw.PreferencesGroup(title="Visual Effects")

        op_val = 0.0
        if rule:
            op_node = rule.get_child("opacity")
            if op_node and op_node.args:
                op_val = float(op_node.args[0])
        op_adj = Gtk.Adjustment(value=op_val, lower=0.0, upper=1.0, step_increment=0.05)
        op_row = Adw.SpinRow(
            title="Opacity (0 = unset, 1 = fully opaque)", adjustment=op_adj, digits=2
        )
        fx_grp.add(op_row)

        blur_row = Adw.SwitchRow(
            title="Background Blur",
            subtitle="Adds background-effect { blur true }",
        )
        has_blur = False
        if rule:
            be = rule.get_child("background-effect")
            if be is not None:
                blur_child = be.get_child("blur")
                has_blur = blur_child is not None and (
                    not blur_child.args or blur_child.args[0] is True
                )
        blur_row.set_active(has_blur)
        fx_grp.add(blur_row)

        prefs.add(fx_grp)

        # ── Numeric dimensions ────────────────────────────────────────────
        dim_grp = Adw.PreferencesGroup(title="Dimensions (0 = unset)")
        num_rows: dict[str, Adw.SpinRow] = {}
        for key, (label, lo, hi, step, digits) in NUM_ACTION_LABELS.items():
            if key == "opacity":
                continue  # handled above
            cur = 0
            if rule:
                cn = rule.get_child(key)
                cur = cn.args[0] if cn and cn.args else 0
            adj = Gtk.Adjustment(
                value=float(cur), lower=lo, upper=hi, step_increment=step
            )
            sr = Adw.SpinRow(title=label, adjustment=adj, digits=digits)
            dim_grp.add(sr)
            num_rows[key] = sr

        prefs.add(dim_grp)

        # ── Workspace / output ────────────────────────────────────────────
        place_grp = Adw.PreferencesGroup(title="Placement")
        str_rows: dict[str, Adw.EntryRow] = {}
        for key, label in STR_ACTION_LABELS.items():
            e = Adw.EntryRow(title=label)
            if rule:
                cn = rule.get_child(key)
                e.set_text(str(cn.args[0]) if cn and cn.args else "")
            place_grp.add(e)
            str_rows[key] = e

        prefs.add(place_grp)

        scroll.set_child(prefs)
        toolbar_view.set_content(scroll)

        # ── Save button ───────────────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_start(16)
        btn_box.set_margin_end(16)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(16)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", lambda *_: dialog.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label="Save Rule")
        save_btn.add_css_class("suggested-action")
        save_btn.add_css_class("pill")
        btn_box.append(save_btn)

        toolbar_view.add_bottom_bar(btn_box)

        def _save(*_):
            new_rule = KdlNode("window-rule")
            new_rule.leading_trivia = "\n"

            # match node
            m = KdlNode("match")
            has_match = False
            app_id_text = app_id_row.get_text().strip()
            if app_id_text:
                m.props["app-id"] = KdlRawString(app_id_text)
                has_match = True
            title_text = title_row.get_text().strip()
            if title_text:
                m.props["title"] = KdlRawString(title_text)
                has_match = True
            for key, sr in bool_match_rows.items():
                if sr.get_active():
                    m.props[key] = True
                    has_match = True
            if has_match:
                new_rule.children.append(m)

            # bool actions
            for key, sr in bool_rows.items():
                if sr.get_active():
                    new_rule.children.append(_bool_action_node(key))

            # opacity
            op = op_row.get_value()
            if op > 0.0:
                cn = KdlNode("opacity")
                cn.args = [round(op, 2)]
                new_rule.children.append(cn)

            # blur
            if blur_row.get_active():
                be = KdlNode("background-effect")
                be.children.append(KdlNode("blur", args=[True]))
                new_rule.children.append(be)

            # dimensions
            for key, sr in num_rows.items():
                v = sr.get_value()
                if v > 0:
                    cn = KdlNode(key)
                    cn.args = [int(v)]
                    new_rule.children.append(cn)

            # placement strings
            for key, e in str_rows.items():
                v = e.get_text().strip()
                if v:
                    cn = KdlNode(key)
                    cn.args = [v]
                    new_rule.children.append(cn)

            rules = self._get_rules()
            if rule_idx >= 0 and 0 <= rule_idx < len(rules):
                i = self._nodes.index(rules[rule_idx])
                new_rule.source_file = rules[rule_idx].source_file
                self._nodes[i] = new_rule
            else:
                if rules:
                    new_rule.source_file = rules[-1].source_file
                self._nodes.append(new_rule)

            self._commit("window rule")
            self._rebuild()
            dialog.close()

        save_btn.connect("clicked", _save)
        dialog.set_child(toolbar_view)
        dialog.present(self._win)

    # ── Layer rules ───────────────────────────────────────────────────────────

    def _get_layer_rules(self) -> list[KdlNode]:
        return [n for n in self._nodes if n.name == "layer-rule"]

    def _rebuild_layer(self):
        parent = self._layer_rules_grp.get_parent()
        if parent is None:
            return
        rules = self._get_layer_rules()
        new_grp = Adw.PreferencesGroup(
            title="Layer Rules",
            description=f"{len(rules)} rule(s) — bars, overlays, wallpapers",
        )
        for i, rule in enumerate(rules):
            new_grp.add(self._make_layer_rule_row(rule, i))
        parent.remove(self._layer_rules_grp)
        parent.append(new_grp)
        self._layer_rules_grp = new_grp

    def _make_layer_rule_row(self, rule: KdlNode, idx: int) -> Adw.ActionRow:
        title, subtitle = _layer_rule_summary(rule)
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.set_activatable(True)
        row.add_css_class("monospace")

        has_blur = rule.get_child("background-effect") is not None
        if has_blur:
            lbl = Gtk.Label(label="blur")
            lbl.add_css_class("tag")
            lbl.add_css_class("accent")
            lbl.set_valign(Gtk.Align.CENTER)
            row.add_suffix(lbl)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.add_css_class("flat")
        del_btn.add_css_class("error")
        del_btn.set_tooltip_text("Delete layer rule")
        del_btn.connect("clicked", lambda *_, i=idx: self._on_delete_layer(i))
        row.add_suffix(del_btn)

        row.connect("activated", lambda *_, i=idx: self._on_edit_layer(i))
        return row

    def _on_add_layer(self, *_):
        self._show_layer_dialog(None, -1)

    def _on_edit_layer(self, idx: int):
        rules = self._get_layer_rules()
        if 0 <= idx < len(rules):
            self._show_layer_dialog(rules[idx], idx)

    def _on_delete_layer(self, idx: int):
        rules = self._get_layer_rules()
        if not (0 <= idx < len(rules)):
            return
        self._nodes.remove(rules[idx])
        self._commit("remove layer rule")
        self._rebuild_layer()

        t = Adw.Toast(title="Layer rule deleted", button_label="Undo", timeout=5)
        t.connect("button-clicked", lambda *_: self._win._do_undo())
        self._win._toast_overlay.add_toast(t)

    def _show_layer_dialog(self, rule: KdlNode | None, idx: int):
        dialog = Adw.Dialog(title="Layer Rule")
        dialog.set_content_width(460)

        toolbar_view = Adw.ToolbarView()
        hdr = Adw.HeaderBar()
        hdr.set_title_widget(
            Adw.WindowTitle(title="Edit Layer Rule" if rule else "New Layer Rule")
        )
        toolbar_view.add_top_bar(hdr)

        prefs = Adw.PreferencesPage()

        match_grp = Adw.PreferencesGroup(title="Match")
        match_node = rule.get_child("match") if rule else None
        ns_entry = Adw.EntryRow(title="Namespace (regex, e.g. ^waybar$)")
        ns_entry.set_text(
            str(match_node.props.get("namespace", "")) if match_node else ""
        )
        match_grp.add(ns_entry)
        prefs.add(match_grp)

        act_grp = Adw.PreferencesGroup(title="Actions")
        bool_rows: dict[str, Adw.SwitchRow] = {}
        for key, label in LAYER_BOOL_ACTION_LABELS.items():
            sr = Adw.SwitchRow(title=label)
            sr.set_active(_bool_action_active(rule, key))
            act_grp.add(sr)
            bool_rows[key] = sr

        blur_row = Adw.SwitchRow(title="Background Blur")
        has_blur = False
        if rule:
            be = rule.get_child("background-effect")
            if be:
                bc = be.get_child("blur")
                has_blur = bc is not None and (not bc.args or bc.args[0] is True)
        blur_row.set_active(has_blur)
        act_grp.add(blur_row)

        op_adj = Gtk.Adjustment(value=1.0, lower=0.0, upper=1.0, step_increment=0.05)
        if rule:
            op_node = rule.get_child("opacity")
            if op_node and op_node.args:
                op_adj.set_value(float(op_node.args[0]))
        op_row = Adw.SpinRow(title="Opacity (1 = unset)", adjustment=op_adj, digits=2)
        act_grp.add(op_row)

        prefs.add(act_grp)
        toolbar_view.set_content(prefs)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_start(16)
        btn_box.set_margin_end(16)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(16)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", lambda *_: dialog.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label="Save Rule")
        save_btn.add_css_class("suggested-action")
        save_btn.add_css_class("pill")
        btn_box.append(save_btn)

        toolbar_view.add_bottom_bar(btn_box)

        def _save(*_):
            new_rule = KdlNode("layer-rule")
            new_rule.leading_trivia = "\n"
            ns = ns_entry.get_text().strip()
            if ns:
                m = KdlNode("match")
                m.props["namespace"] = KdlRawString(ns)
                new_rule.children.append(m)
            for key, sr in bool_rows.items():
                if sr.get_active():
                    new_rule.children.append(_bool_action_node(key))
            if blur_row.get_active():
                be = KdlNode("background-effect")
                be.children.append(KdlNode("blur", args=[True]))
                new_rule.children.append(be)
            op = op_row.get_value()
            if op < 1.0:
                op_node = KdlNode("opacity")
                op_node.args = [round(op, 2)]
                new_rule.children.append(op_node)

            rules = self._get_layer_rules()
            if idx >= 0 and 0 <= idx < len(rules):
                i = self._nodes.index(rules[idx])
                new_rule.source_file = rules[idx].source_file
                self._nodes[i] = new_rule
            else:
                if rules:
                    new_rule.source_file = rules[-1].source_file
                elif self._get_rules():
                    new_rule.source_file = self._get_rules()[-1].source_file
                self._nodes.append(new_rule)
            self._commit("layer rule")
            self._rebuild_layer()
            dialog.close()

        save_btn.connect("clicked", _save)
        dialog.set_child(toolbar_view)
        dialog.present(self._win)
