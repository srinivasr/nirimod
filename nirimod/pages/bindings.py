"""Key Bindings page — list editor + keyboard map visualizer.

Tab 1: "Bindings List"    — the original Adw row-based editor (unchanged logic).
Tab 2: "Keyboard Map"     — Cairo keyboard visualizer ported from omer-biz/visu.
"""

from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from nirimod.kdl_parser import KdlNode
from nirimod.pages.base import BasePage
from nirimod.widgets import KeyboardVisualizer, normalize_key_id


MODIFIERS = ["Super", "Ctrl", "Alt", "Shift"]

NIRI_ACTIONS = [
    "close-window",
    "focus-column-left",
    "focus-column-right",
    "focus-column-first",
    "focus-column-last",
    "focus-window-down",
    "focus-window-up",
    "move-column-left",
    "move-column-right",
    "move-column-to-first",
    "move-column-to-last",
    "move-window-down",
    "move-window-up",
    "focus-workspace-down",
    "focus-workspace-up",
    "focus-workspace",
    "move-column-to-workspace",
    "move-column-to-workspace-down",
    "move-column-to-workspace-up",
    "move-workspace-down",
    "move-workspace-up",
    "focus-monitor-left",
    "focus-monitor-right",
    "focus-monitor-up",
    "focus-monitor-down",
    "move-column-to-monitor-left",
    "move-column-to-monitor-right",
    "move-column-to-monitor-down",
    "move-column-to-monitor-up",
    "maximize-column",
    "fullscreen-window",
    "maximize-window-to-edges",
    "switch-preset-column-width",
    "switch-preset-window-height",
    "set-column-width",
    "set-window-height",
    "set-dynamic-cast-window",
    "set-dynamic-cast-monitor",
    "clear-dynamic-cast-target",
    "reset-window-height",
    "center-column",
    "center-visible-columns",
    "screenshot",
    "screenshot-screen",
    "screenshot-window",
    "spawn",
    "spawn-sh",
    "quit",
    "power-off-monitors",
    "toggle-window-floating",
    "switch-focus-between-floating-and-tiling",
    "toggle-column-tabbed-display",
    "toggle-overview",
    "consume-or-expel-window-left",
    "consume-or-expel-window-right",
    "consume-window-into-column",
    "expel-window-from-column",
    "expand-column-to-available-width",
    "show-hotkey-overlay",
    "toggle-keyboard-shortcuts-inhibit",
    "toggle-windowed-fullscreen",
]


_KNOWN_BIND_PROPS = {"allow-when-locked", "repeat"}


def _make_bind(
    keysym: str,
    action: str,
    action_args: list | None = None,
    allow_when_locked: bool = False,
    repeat: bool = True,
    extra_props: dict | None = None,
) -> dict:
    return {
        "keysym": keysym,
        "action": action,
        "action_args": action_args or [],
        "allow_when_locked": allow_when_locked,
        "repeat": repeat,
        "extra_props": extra_props or {},
    }


def _parse_binds_from_nodes(nodes: list[KdlNode]) -> list[dict]:
    """Parse all bind nodes from the binds block."""
    binds_node = next((n for n in nodes if n.name == "binds"), None)
    if not binds_node:
        return []
    result = []
    for child in binds_node.children:
        keysym = child.name
        action = ""
        action_args: list = []
        allow_locked = child.props.get("allow-when-locked", False)
        repeat = child.props.get("repeat", True)
        extra_props = {
            k: v for k, v in child.props.items() if k not in _KNOWN_BIND_PROPS
        }
        for sub in child.children:
            action = sub.name
            action_args = list(sub.args)
        result.append(
            _make_bind(
                keysym,
                action,
                action_args,
                bool(allow_locked),
                bool(repeat),
                extra_props,
            )
        )
    return result


def _write_binds_to_node(binds_list: list[dict], binds_node: KdlNode):
    """Rewrite the binds block's children from a list of bind dicts."""
    binds_node.children.clear()
    for b in binds_list:
        child = KdlNode(name=b["keysym"])
        if b["allow_when_locked"]:
            child.props["allow-when-locked"] = True
        if not b["repeat"]:
            child.props["repeat"] = False
        for k, v in b.get("extra_props", {}).items():
            child.props[k] = v
        if b["action"]:
            action_node = KdlNode(name=b["action"])
            args = b.get("action_args") or []
            if not args:
                legacy = b.get("action_arg", "")
                if legacy:
                    args = [legacy]
            action_node.args = list(args)
            child.children.append(action_node)
        binds_node.children.append(child)


def _build_key_bindings_map(binds: list[dict], viz=None) -> dict[str, list[dict]]:
    # bucket binds by their actual physical key ID so the visualizer can highlight them
    result: dict[str, list[dict]] = {}
    for b in binds:
        keysym = b.get("keysym", "")
        raw_key = keysym.split("+")[-1].lower()
        kid = None
        if viz and viz._dynamic_keysym_to_kid:
            kid = viz._dynamic_keysym_to_kid.get(raw_key)
        if not kid:
            kid = normalize_key_id(raw_key)
        result.setdefault(kid, []).append(b)
    return result


# BindingsPage


class BindingsPage(BasePage):
    def __init__(self, window):
        super().__init__(window)
        self._binds: list[dict] = []
        self._search_query = ""
        self._kb_search_query = ""
        self._file_monitor: Gio.FileMonitor | None = None
        self._viz: KeyboardVisualizer | None = None

    def build(self) -> Gtk.Widget:
        # Create a custom ToolbarView layout to match "Workspace View" aesthetic
        tb = Adw.ToolbarView()

        # Custom Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_start(24)
        header_box.set_margin_end(24)
        header_box.set_margin_top(20)
        header_box.set_margin_bottom(12)

        # Title/Subtitle Group
        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_vbox.set_hexpand(True)
        
        self._main_title = Gtk.Label(label="Keybindings")
        self._main_title.set_xalign(0.0)
        self._main_title.add_css_class("title-1")
        title_vbox.append(self._main_title)

        self._kb_stats_header = Gtk.Label(label="Detecting bindings...")
        self._kb_stats_header.set_xalign(0.0)
        self._kb_stats_header.add_css_class("dim-label")
        self._kb_stats_header.add_css_class("caption")
        title_vbox.append(self._kb_stats_header)
        header_box.append(title_vbox)

        # Layout Selector (shown only on Keyboard tab)
        from nirimod import app_settings
        from nirimod.xkb_helper import XkbHelper
        
        self._layouts = XkbHelper.get_available_layouts()
        layout_names = [d for _, d in self._layouts]
        self._layout_model = Gtk.StringList.new(layout_names)
        self._layout_combo = Gtk.DropDown(model=self._layout_model)
        self._layout_combo.set_valign(Gtk.Align.CENTER)
        self._layout_combo.set_enable_search(True)
        
        # Priority: Settings > Niri Config > US
        saved_layout = app_settings.get("kb_layout")
        if not saved_layout:
            saved_layout = self._get_current_niri_layout() or "us"
            
        selected_idx = 0
        for i, (lid, _) in enumerate(self._layouts):
            if lid == saved_layout:
                selected_idx = i
                break
        self._layout_combo.set_selected(selected_idx)
            
        self._layout_combo.connect("notify::selected", self._on_layout_changed)
        header_box.append(self._layout_combo)

        # Add Button (hidden by default, shown on List tab)
        self._add_btn = Gtk.Button(icon_name="list-add-symbolic")
        self._add_btn.set_tooltip_text("Add binding")
        self._add_btn.add_css_class("flat")
        self._add_btn.add_css_class("circular")
        self._add_btn.set_valign(Gtk.Align.CENTER)
        self._add_btn.set_visible(False)
        self._add_btn.connect("clicked", self._on_add_clicked)
        header_box.append(self._add_btn)

        # View Switcher (Styled as Physical/List View buttons)
        self._view_stack = Adw.ViewStack()
        
        switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        switcher_box.add_css_class("linked")
        switcher_box.set_valign(Gtk.Align.CENTER)
        
        self._btn_physical = Gtk.ToggleButton(label="Physical")
        self._btn_list = Gtk.ToggleButton(label="List View")
        self._btn_list.set_group(self._btn_physical)
        
        self._btn_physical.connect("toggled", self._on_view_toggle)
        self._btn_list.connect("toggled", self._on_view_toggle)
        
        switcher_box.append(self._btn_physical)
        switcher_box.append(self._btn_list)
        header_box.append(switcher_box)
        
        tb.add_top_bar(header_box)

        list_page_widget = self._build_list_tab()
        self._view_stack.add_named(list_page_widget, "list")

        kb_page_widget = self._build_keyboard_tab()
        self._view_stack.add_named(kb_page_widget, "keyboard")

        # Default to keyboard (Physical)
        self._view_stack.set_visible_child_name("keyboard")
        self._btn_physical.set_active(True)

        tb.set_content(self._view_stack)

        self.refresh()
        self._start_file_monitor()
        return tb

    def _get_current_niri_layout(self):
        try:
            from nirimod import kdl_parser
            nodes = kdl_parser.load_niri_config()
            for node in nodes:
                if node.name == "input":
                    kb = node.get_child("keyboard")
                    if kb:
                        xkb = kb.get_child("xkb")
                        if xkb:
                            l = xkb.child_arg("layout")
                            v = xkb.child_arg("variant")
                            if l:
                                return f"{l}:{v}" if v else l
        except Exception:
            pass
        return None

    def _on_layout_changed(self, dropdown, param):
        from nirimod import app_settings
        idx = dropdown.get_selected()
        if idx < len(self._layouts):
            layout_id = self._layouts[idx][0]
            app_settings.set("kb_layout", layout_id)
            if self._viz:
                self._viz.set_layout(layout_id)

    def _on_view_toggle(self, btn):
        if not btn.get_active():
            return
        is_list = btn == self._btn_list
        self._view_stack.set_visible_child_name("list" if is_list else "keyboard")
        self._add_btn.set_visible(is_list)
        if hasattr(self, "_layout_combo"):
            self._layout_combo.set_visible(not is_list)

    def _build_list_tab(self) -> Gtk.Widget:
        """Return the scrollable list editor widget (original UI)."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_start(32)
        content.set_margin_end(32)
        content.set_margin_top(24)
        content.set_margin_bottom(32)
        scroll.set_child(content)

        # Search

        # Search
        search = Gtk.SearchEntry(placeholder_text="Filter bindings…")
        search.set_margin_start(0)
        search.set_margin_end(0)
        search.connect("search-changed", self._on_filter_changed)
        content.append(search)

        # Binds Grid
        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_valign(Gtk.Align.START)
        self._flowbox.set_max_children_per_line(3)
        self._flowbox.set_min_children_per_line(1)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.set_column_spacing(16)
        self._flowbox.set_row_spacing(16)
        self._flowbox.set_homogeneous(True)
        content.append(self._flowbox)

        self._list_content = content
        return scroll

    def _build_keyboard_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        outer.set_margin_top(20)
        outer.set_margin_bottom(24)
        scroll.set_child(outer)

        # Search bar
        kb_search = Gtk.SearchEntry(
            placeholder_text="Filter by action… (e.g. spawn, focus)"
        )
        kb_search.connect("search-changed", self._on_kb_search_changed)
        outer.append(kb_search)

        # Search bar
        self._kb_stats = Gtk.Label(label="") # kept for reference if needed, but we use header now
        self._kb_stats.set_visible(False)

        # Keyboard visualizer
        self._viz = KeyboardVisualizer()
        self._viz.connect("key-selected", self._on_kb_key_selected)
        self._viz.connect("edit-binding", self._on_kb_edit_binding)
        self._viz.connect("add-binding", self._on_kb_add_binding)
        outer.append(self._viz)

        return scroll

    # Tab switching

    def _on_tab_changed(self, stack, _param):
        child = stack.get_visible_child_name()
        # Show add-button only on list tab
        if hasattr(self, "_add_btn_in_header"):
            self._add_btn_in_header.set_visible(child == "list")

    # Refresh / sync

    def refresh(self):
        self._binds = _parse_binds_from_nodes(self._nodes)
        self._rebuild_list()
        self._refresh_visualizer()

    def on_shown(self):
        self._refresh_visualizer()

    def _refresh_visualizer(self):
        if self._viz is None:
            return
        from nirimod import app_settings
        layout_id = app_settings.get("kb_layout")
        if not layout_id:
            layout_id = self._get_current_niri_layout() or "us"
        self._viz.set_layout(layout_id)
        
        binds_map = _build_key_bindings_map(self._binds, self._viz)
        self._viz.set_bindings(binds_map)
        self._viz.set_search(self._kb_search_query)
        n_total = len(self._binds)
        self._kb_stats_header.set_label(
            f"{n_total} active bindings detected"
        )

    # List editor helpers (unchanged from original)

    def _rebuild_list(self):
        if not hasattr(self, "_flowbox"):
            return

        # Clear existing children
        while True:
            child = self._flowbox.get_first_child()
            if child is None:
                break
            self._flowbox.remove(child)

        q = self._search_query.lower()
        visible_count = 0
        for i, b in enumerate(self._binds):
            if q and q not in b["keysym"].lower() and q not in b["action"].lower():
                continue
            card = self._make_bind_card(b, i)
            self._flowbox.append(card)
            visible_count += 1

    def _make_bind_card(self, b: dict, idx: int) -> Gtk.Widget:
        keysym = b["keysym"]
        action = b["action"]
        action_args = b.get("action_args") or []
        action_arg_display = " ".join(str(a) for a in action_args)

        full_action = f"{action} {action_arg_display}".strip()
        if not full_action:
            full_action = "(unassigned)"

        # Card container
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.set_size_request(240, 140)
        card.add_css_class("nm-binding-card")
        # Custom styling for the card
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b".nm-binding-card { "
            b"  background: rgba(30, 30, 35, 0.6); "
            b"  border: 1px solid rgba(255, 255, 255, 0.08); "
            b"  border-radius: 12px; "
            b"  padding: 16px; "
            b"  transition: all 200ms ease; "
            b"} "
            b".nm-binding-card:hover { "
            b"  background: rgba(45, 45, 50, 0.8); "
            b"  border-color: rgba(147, 51, 234, 0.4); "
            b"}"
            b".nm-binding-actions-label { "
            b"  color: rgba(255, 255, 255, 0.4); "
            b"  font-weight: 800; "
            b"  letter-spacing: 0.05em; "
            b"  font-size: 0.7rem; "
            b"} "
            b".nm-binding-action-name { "
            b"  color: rgba(192, 132, 252, 1.0); "
            b"  font-weight: 600; "
            b"  font-size: 1.0rem; "
            b"} "
            b".nm-keycap-purple { "
            b"  background: #581c87; "
            b"  color: white; "
            b"  border-radius: 6px; "
            b"  padding: 2px 8px; "
            b"  font-weight: bold; "
            b"  font-size: 0.8rem; "
            b"}"
        )
        card.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # 1. Keycaps Row
        keys_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        parts = keysym.split("+")
        _labels = {
            "mod": "MOD",
            "super": "SUP",
            "ctrl": "CTL",
            "control": "CTL",
            "shift": "SHFT",
            "alt": "ALT",
        }

        for i, part in enumerate(parts):
            label_text = part
            is_mod = i < len(parts) - 1
            if is_mod:
                label_text = _labels.get(part.lower(), part.upper()[:4])
            else:
                label_text = label_text.upper() if len(label_text) == 1 else label_text

            cap = Gtk.Label(label=label_text)
            cap.add_css_class("nm-keycap-purple")
            keys_box.append(cap)
            
            if i < len(parts) - 1:
                plus = Gtk.Label(label="+")
                plus.add_css_class("dim-label")
                keys_box.append(plus)

        card.append(keys_box)

        # 2. "ACTIONS" Label
        actions_header = Gtk.Label(label="ACTIONS")
        actions_header.set_xalign(0.0)
        actions_header.add_css_class("nm-binding-actions-label")
        actions_header.set_margin_top(12)
        card.append(actions_header)

        # 3. Action Name
        action_lbl = Gtk.Label(label=full_action)
        action_lbl.set_xalign(0.0)
        action_lbl.set_ellipsize(3) # pango.EllipsizeMode.END
        action_lbl.add_css_class("nm-binding-action-name")
        card.append(action_lbl)

        # Spacer to push action buttons to the bottom
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        card.append(spacer)

        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom_row.set_halign(Gtk.Align.END)

        if b.get("allow_when_locked"):
            lock = Gtk.Label(label="🔒")
            lock.set_opacity(0.6)
            bottom_row.append(lock)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
        edit_btn.add_css_class("flat")
        edit_btn.add_css_class("circular")
        edit_btn.connect("clicked", lambda *_, i=idx: self._on_edit_clicked(i))
        bottom_row.append(edit_btn)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.add_css_class("error")
        del_btn.connect("clicked", lambda *_, i=idx: self._on_delete_clicked(i))
        bottom_row.append(del_btn)

        card.append(bottom_row)

        return card

    def _on_filter_changed(self, entry):
        self._search_query = entry.get_text().strip()
        self._rebuild_list()

    def _on_kb_search_changed(self, entry):
        self._kb_search_query = entry.get_text().strip()
        if self._viz:
            self._viz.set_search(self._kb_search_query)

    def _on_kb_key_selected(self, viz, key_id: str):
        pass

    def _on_kb_edit_binding(self, viz, bind_dict):
        try:
            idx = self._binds.index(bind_dict)
            self._show_bind_dialog(bind_dict, idx)
        except ValueError:
            pass

    def _on_kb_add_binding(self, viz, key_id: str):

        if len(key_id) == 1:
            display_key = key_id.upper()
        else:
            display_key = key_id.capitalize()

        new_bind = {
            "keysym": f"Mod+{display_key}",
            "action": "",
            "action_args": [],
            "allow_when_locked": False,
            "repeat": True,
            "extra_props": {}
        }
        self._show_bind_dialog(new_bind, -1)

    def _on_delete_clicked(self, idx: int):
        if 0 <= idx < len(self._binds):
            del self._binds[idx]
            self._save_binds()
            self._rebuild_list()
            self._refresh_visualizer()

    def _on_add_clicked(self, *_):
        self._show_bind_dialog(None, -1)

    def _on_edit_clicked(self, idx: int):
        if 0 <= idx < len(self._binds):
            self._show_bind_dialog(self._binds[idx], idx)

    def _show_bind_dialog(self, bind: dict | None, idx: int):
        dialog = Adw.Dialog(title="Edit Binding" if bind else "Add Binding")
        dialog.set_content_width(440)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=dialog.get_title()))
        box.append(header)

        prefs = Adw.PreferencesPage()
        prefs.set_vexpand(True)

        # Keysym group
        keys_grp = Adw.PreferencesGroup(title="Key Combination")

        mod_row = Adw.ActionRow(title="Modifiers")
        mod_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mod_box.set_valign(Gtk.Align.CENTER)
        mod_checks: dict[str, Gtk.CheckButton] = {}
        cur_keysym = bind["keysym"] if bind else ""
        for mod in MODIFIERS:
            cb = Gtk.CheckButton(label=mod)
            cb.set_active(
                mod.lower() in cur_keysym.lower()
                or ("mod" in cur_keysym.lower() and mod == "Super")
            )
            mod_box.append(cb)
            mod_checks[mod] = cb
        mod_row.add_suffix(mod_box)
        keys_grp.add(mod_row)

        key_entry = Adw.EntryRow(title="Key (e.g. T, F1, Return)")
        bare = cur_keysym.split("+")[-1] if bind else ""
        key_entry.set_text(bare)
        keys_grp.add(key_entry)
        prefs.add(keys_grp)

        # Action group
        act_grp = Adw.PreferencesGroup(title="Action")
        act_model = Gtk.StringList.new(NIRI_ACTIONS)
        act_combo = Adw.ComboRow(title="Action", model=act_model)
        cur_action = bind["action"] if bind else ""
        if cur_action in NIRI_ACTIONS:
            act_combo.set_selected(NIRI_ACTIONS.index(cur_action))
        act_grp.add(act_combo)

        arg_row = Adw.EntryRow(title="Argument (for spawn, focus-workspace, etc.)")
        cur_args = (bind.get("action_args") or []) if bind else []
        arg_row.set_text(" ".join(str(a) for a in cur_args) if cur_args else "")
        act_grp.add(arg_row)
        prefs.add(act_grp)

        # Options
        opt_grp = Adw.PreferencesGroup(title="Options")
        locked_row = Adw.SwitchRow(title="Allow When Locked")
        locked_row.set_active(bind["allow_when_locked"] if bind else False)
        opt_grp.add(locked_row)

        repeat_row = Adw.SwitchRow(title="Repeat")
        repeat_row.set_active(bind["repeat"] if bind else True)
        opt_grp.add(repeat_row)
        prefs.add(opt_grp)

        box.append(prefs)

        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        save_row.set_halign(Gtk.Align.END)
        save_row.set_margin_start(16)
        save_row.set_margin_end(16)
        save_row.set_margin_top(8)
        save_row.set_margin_bottom(16)
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.add_css_class("pill")

        def _do_save(*_):
            mods = [m for m, cb in mod_checks.items() if cb.get_active()]
            key = key_entry.get_text().strip()
            if not key:
                return
            mod_parts = []
            for m in mods:
                mod_parts.append("Mod" if m == "Super" else m)
            keysym = "+".join(mod_parts + [key])
            action_idx = act_combo.get_selected()
            action = NIRI_ACTIONS[action_idx] if action_idx < len(NIRI_ACTIONS) else ""
            arg_text = arg_row.get_text().strip()
            new_args = arg_text.split() if arg_text else []
            new_bind = _make_bind(
                keysym,
                action,
                new_args,
                locked_row.get_active(),
                repeat_row.get_active(),
                bind.get("extra_props", {}) if bind else {},
            )
            if idx >= 0:
                self._binds[idx] = new_bind
            else:
                self._binds.append(new_bind)
            self._save_binds()
            self._rebuild_list()
            self._refresh_visualizer()
            dialog.close()

        save_btn.connect("clicked", _do_save)
        save_row.append(save_btn)
        box.append(save_row)

        dialog.set_child(box)
        dialog.present(self._win)

    def _save_binds(self):
        nodes = self._nodes
        binds_node = next((n for n in nodes if n.name == "binds"), None)
        if binds_node is None:
            binds_node = KdlNode("binds")
            nodes.append(binds_node)
        _write_binds_to_node(self._binds, binds_node)
        self._commit("keybindings")

    # File monitor (live-sync)

    def _start_file_monitor(self):
        try:
            from nirimod.kdl_parser import NIRI_CONFIG

            gfile = Gio.File.new_for_path(str(NIRI_CONFIG))
            monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            monitor.connect("changed", self._on_config_file_changed)
            self._file_monitor = monitor
        except Exception:
            pass

    def _on_config_file_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGED, Gio.FileMonitorEvent.CREATED):
            GLib.timeout_add(400, self._reload_from_disk)

    def _reload_from_disk(self):
        self._win.notify_nodes_changed()
        return False  # don't repeat
