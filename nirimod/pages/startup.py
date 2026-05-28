"""Startup Programs page."""

from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from nirimod.kdl_parser import KdlNode
from nirimod.pages.base import BasePage
from nirimod.startup_entries import make_startup_node, startup_values_from_node


class StartupPage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, header, _, content = self._make_toolbar_page("Startup Programs")
        self._content = content



        self.refresh()
        return tb

    def refresh(self):
        self._rebuild()

    def _get_entries(self) -> list[KdlNode]:
        return [
            n
            for n in self._nodes
            if n.name in ("spawn-at-startup", "spawn-sh-at-startup")
        ]

    def _rebuild(self):
        # Clear existing content
        while True:
            child = self._content.get_first_child()
            if child is None:
                break
            self._content.remove(child)

        entries = self._get_entries()

        if not entries:
            status = Adw.StatusPage(
                title="No Startup Programs",
                description="Programs added here will launch automatically when niri starts.",
                icon_name="applications-system-symbolic",
            )

            add_btn = Gtk.Button(label="Add Program")
            add_btn.add_css_class("pill")
            add_btn.add_css_class("suggested-action")
            add_btn.set_halign(Gtk.Align.CENTER)
            add_btn.connect("clicked", self._on_add)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_valign(Gtk.Align.CENTER)
            box.set_vexpand(True)
            box.append(status)
            box.append(add_btn)

            self._content.append(box)
        else:
            grp = Adw.PreferencesGroup(
                title="Startup Programs",
                description=f"{len(entries)} program{'s' if len(entries) != 1 else ''} configured to launch",
            )
            for i, entry in enumerate(entries):
                row = self._make_row(entry, i)
                grp.add(row)

            self._content.append(grp)
            
            # Also add a convenient button at the bottom
            add_btn = Gtk.Button(label="Add Another Program")
            add_btn.add_css_class("pill")
            add_btn.set_halign(Gtk.Align.CENTER)
            add_btn.set_margin_top(16)
            add_btn.connect("clicked", self._on_add)
            self._content.append(add_btn)

    def _make_row(self, node: KdlNode, idx: int) -> Adw.ActionRow:
        cmd, is_sh, delay = startup_values_from_node(node)
        cmd_str = GLib.markup_escape_text(cmd) if cmd else "(empty)"
        subtitle_parts = []
        if delay > 0:
            subtitle_parts.append(f"Delay: {delay}s")
        subtitle_parts.append(
            "Via shell (spawn-sh-at-startup)" if is_sh else "Launched directly"
        )

        row = Adw.ActionRow(
            title=cmd_str or "(empty)",
            subtitle=" | ".join(subtitle_parts),
        )
        row.set_activatable(True)
        row.connect("activated", lambda *_, i=idx: self._on_edit(i))

        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.add_css_class("flat")
        del_btn.add_css_class("error")
        del_btn.set_tooltip_text("Remove startup entry")
        del_btn.connect("clicked", lambda *_, i=idx: self._on_delete(i))
        row.add_suffix(del_btn)
        return row

    def _on_add(self, *_):
        self._show_dialog(None, -1)

    def _on_edit(self, idx: int):
        entries = self._get_entries()
        if 0 <= idx < len(entries):
            self._show_dialog(entries[idx], idx)

    def _on_delete(self, idx: int):
        entries = self._get_entries()
        if 0 <= idx < len(entries):
            self._nodes.remove(entries[idx])
            self._commit("remove startup entry")
            self._rebuild()

    def _show_dialog(self, node: KdlNode | None, idx: int):
        dialog = Adw.AlertDialog(
            heading="Startup Program", body="Enter the command to launch at startup."
        )
        cmd_entry = Adw.EntryRow(title="Command")
        sh_switch = Adw.SwitchRow(title="Use shell (spawn-sh-at-startup)")
        delay_adj = Gtk.Adjustment(
            value=0, lower=0, upper=3600, step_increment=1, page_increment=10
        )
        delay_row = Adw.SpinRow(
            title="Delay",
            subtitle="Seconds to wait before launching",
            adjustment=delay_adj,
            digits=0,
        )
        if node:
            command, is_sh, delay = startup_values_from_node(node)
            cmd_entry.set_text(command)
            sh_switch.set_active(is_sh)
            delay_row.set_value(delay)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        grp = Adw.PreferencesGroup()
        grp.add(cmd_entry)
        grp.add(delay_row)
        grp.add(sh_switch)
        box.append(grp)
        dialog.set_extra_child(box)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def _on_resp(d, r):
            if r != "save":
                return
            cmd = cmd_entry.get_text().strip()
            if not cmd:
                return
            is_sh = sh_switch.get_active()
            delay = int(delay_row.get_value())
            new_node = make_startup_node(cmd, is_sh, delay)
            entries = self._get_entries()
            if idx >= 0 and 0 <= idx < len(entries):
                i = self._nodes.index(entries[idx])
                self._nodes[i] = new_node
            else:
                self._nodes.append(new_node)
            self._commit("startup entry")
            self._rebuild()

        dialog.connect("response", _on_resp)
        dialog.present(self._win)
