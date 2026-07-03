"""Main application window — sidebar + content NavigationSplitView."""

from __future__ import annotations

import hashlib
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from nirimod import kdl_parser
from nirimod import niri_ipc
from nirimod import profiles as prof_mod
from nirimod.state import AppState
from nirimod.theme import CSS

# Grouped sidebar structure: (section_title, [(page_id, icon, label), ...])
SIDEBAR_GROUPS = [
    ("Input", [
        ("input", "input-keyboard-symbolic", "Input"),
        ("bindings", "preferences-desktop-keyboard-shortcuts-symbolic", "Key Bindings"),
    ]),
    ("Display", [
        ("outputs", "video-display-symbolic", "Outputs"),
        ("appearance", "preferences-desktop-appearance-symbolic", "Appearance"),
        ("animations", "applications-multimedia-symbolic", "Animations"),
    ]),
    ("Workspace", [
        ("layout", "view-grid-symbolic", "Layout"),
        ("workspaces", "view-paged-symbolic", "Workspaces"),
        ("window_rules", "preferences-system-symbolic", "Window Rules"),
    ]),
    ("System", [
        ("startup", "system-run-symbolic", "Startup"),
        ("environment", "preferences-other-symbolic", "Environment"),
        ("gestures", "input-touchpad-symbolic", "Gestures & Misc"),
    ]),
    ("Advanced", [
        ("raw_config", "text-x-generic-symbolic", "Raw Config"),
    ]),
]

# Flat list for backward compat (select_page, search index, etc.)
SIDEBAR_PAGES = [entry for _, group in SIDEBAR_GROUPS for entry in group]


class NiriModWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("NiriMod")
        self.set_default_size(1060, 720)

        self.app_state = AppState()
        self.app_state.load()

        self._current_page_id = ""
        self._pages: dict[str, Gtk.Widget] = {}
        self._sidebar_rows: dict[str, Gtk.ListBoxRow] = {}
        self._sidebar_listboxes: dict[str, Gtk.ListBox] = {}


        self._load_css()
        self._build_ui()
        self._check_onboarding()
        self._check_for_updates()
        self._check_kofi()

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_ui(self):
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast_overlay.set_child(root_box)

        self._niri_banner = Gtk.Label(
            label="⚠  niri is not running — changes will be saved but not applied live",
            xalign=0,
        )
        self._niri_banner.add_css_class("nm-niri-banner")
        self._niri_banner.set_visible(not self.app_state.niri_running)
        root_box.append(self._niri_banner)

        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_vexpand(True)
        root_box.append(self._split_view)

        self._split_view.set_sidebar(self._build_sidebar_nav())
        self._split_view.set_content(self._build_content_nav())

        self._setup_shortcuts()

        # Navigate to first page
        if SIDEBAR_PAGES:
            self._select_page(SIDEBAR_PAGES[0][0])

    def _build_sidebar_nav(self) -> Adw.NavigationPage:
        nav = Adw.NavigationPage(title="NiriMod")

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_box.add_css_class("nm-sidebar-bg")

        # Header with app title and a menu button for profiles
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="NiriMod")
        header.set_title_widget(title_widget)

        sidebar_box.append(header)

        # Search bar
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search settings\u2026")
        self._search_entry.add_css_class("nm-search-entry")
        self._search_entry.set_margin_start(10)
        self._search_entry.set_margin_end(10)
        self._search_entry.set_margin_top(10)
        self._search_entry.set_margin_bottom(0)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("stop-search", self._on_stop_search)
        # Enter key navigates to the highlighted result
        self._search_entry.connect("activate", self._on_search_activate)
        # Up/Down keys move the selection without stealing focus
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_search_key_pressed)
        self._search_entry.add_controller(key_ctrl)
        sidebar_box.append(self._search_entry)


        self._search_revealer = Gtk.Revealer()
        self._search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._search_revealer.set_transition_duration(120)
        self._search_revealer.set_reveal_child(False)
        self._search_revealer.set_margin_start(8)
        self._search_revealer.set_margin_end(8)
        self._search_revealer.set_margin_top(4)
        self._search_revealer.set_margin_bottom(4)
        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.set_max_content_height(300)
        results_scroll.set_propagate_natural_height(True)
        self._search_results_listbox = Gtk.ListBox()
        self._search_results_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._search_results_listbox.add_css_class("nm-search-results")
        self._search_results_listbox.connect("row-activated", self._on_search_result_activated)
        results_scroll.set_child(self._search_results_listbox)
        self._search_revealer.set_child(results_scroll)
        sidebar_box.append(self._search_revealer)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        nav_box.set_margin_top(8)
        nav_box.set_margin_bottom(16)

        for section_title, pages in SIDEBAR_GROUPS:
            # Section header label
            section_lbl = Gtk.Label(label=section_title.upper())
            section_lbl.set_xalign(0.0)
            section_lbl.set_margin_start(16)
            section_lbl.set_margin_end(16)
            section_lbl.set_margin_top(16)
            section_lbl.set_margin_bottom(4)
            section_lbl.add_css_class("nm-sidebar-section-label")
            nav_box.append(section_lbl)

            # Page rows for this section
            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            listbox.add_css_class("navigation-sidebar")
            listbox.add_css_class("nm-sidebar-listbox")
            listbox.set_margin_start(8)
            listbox.set_margin_end(8)
            listbox.connect("row-selected", self._on_row_selected)

            for page_id, icon, label in pages:
                row = self._make_sidebar_row(page_id, icon, label)
                listbox.append(row)
                self._sidebar_rows[page_id] = row
                self._sidebar_listboxes[page_id] = listbox

            nav_box.append(listbox)

        scroll.set_child(nav_box)
        sidebar_box.append(scroll)

        nav.set_child(sidebar_box)
        return nav

    def _make_sidebar_row(self, page_id: str, icon: str, label: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.page_id = page_id  # type: ignore[attr-defined]

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        icon_img = Gtk.Image(icon_name=icon)
        icon_img.add_css_class("nm-sidebar-icon")
        box.append(icon_img)

        text_lbl = Gtk.Label(label=label, xalign=0)
        text_lbl.set_hexpand(True)
        box.append(text_lbl)



        row.set_child(box)
        return row

    def _build_content_nav(self) -> Adw.NavigationPage:
        self._content_nav = Adw.NavigationPage(title="")

        content_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)
        self._stack.set_vexpand(True)
        content_root.append(self._stack)


        self._build_all_pages()
        self._build_search_index()

        self._dirty_bar = self._build_dirty_bar()
        content_root.append(self._dirty_bar)

        self._content_nav.set_child(content_root)
        return self._content_nav

    def _build_dirty_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("nm-dirty-bar")
        bar.set_visible(False)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)

        self._dirty_label = Gtk.Label(label="Unsaved changes")
        self._dirty_label.set_hexpand(True)
        self._dirty_label.set_xalign(0.0)
        self._dirty_label.set_opacity(0.7)
        bar.append(self._dirty_label)

        self._undo_btn = Gtk.Button(label="Undo")
        self._undo_btn.add_css_class("flat")
        self._undo_btn.set_tooltip_text("Undo last change (Ctrl+Z)")
        self._undo_btn.connect("clicked", lambda *_: self._do_undo())
        bar.append(self._undo_btn)

        self._redo_btn = Gtk.Button(label="Redo")
        self._redo_btn.add_css_class("flat")
        self._redo_btn.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        self._redo_btn.set_sensitive(False)
        self._redo_btn.connect("clicked", lambda *_: self._do_redo())
        bar.append(self._redo_btn)

        discard_btn = Gtk.Button(label="Discard")
        discard_btn.add_css_class("destructive-action")
        discard_btn.add_css_class("flat")
        discard_btn.set_tooltip_text("Revert all unsaved changes")
        discard_btn.connect("clicked", lambda *_: self._on_discard())
        bar.append(discard_btn)

        save_btn = Gtk.Button(label="Save & Apply")
        save_btn.add_css_class("suggested-action")
        save_btn.set_tooltip_text("Save to config.kdl and reload niri (Ctrl+S)")
        save_btn.connect("clicked", lambda *_: self._on_save())
        bar.append(save_btn)

        return bar

    def _build_all_pages(self):
        from nirimod.pages import (
            outputs,
            input_page,
            layout,
            appearance,
            animations,
            bindings,
            window_rules,
            startup,
            workspaces,
            environment,
            gestures,
            raw_config,
        )

        page_builders = {
            "outputs": outputs.OutputsPage,
            "input": input_page.InputPage,
            "layout": layout.LayoutPage,
            "appearance": appearance.AppearancePage,
            "animations": animations.AnimationsPage,
            "bindings": bindings.BindingsPage,
            "window_rules": window_rules.WindowRulesPage,
            "startup": startup.StartupPage,
            "workspaces": workspaces.WorkspacesPage,
            "environment": environment.EnvironmentPage,
            "gestures": gestures.GesturesPage,
            "raw_config": raw_config.RawConfigPage,
        }
        for page_id, _, title in SIDEBAR_PAGES:
            cls = page_builders.get(page_id)
            if cls:
                page_obj = cls(window=self)
                widget = page_obj.build()
                self._pages[page_id] = page_obj
                self._stack.add_named(widget, page_id)

    def _on_row_selected(self, _lb, row):
        if row is None:
            return
        pid = getattr(row, "page_id", None)
        if pid:

            for other_pid, lb in self._sidebar_listboxes.items():
                if lb is not _lb:
                    lb.unselect_all()
            self._select_page(pid)

    def _select_page(self, page_id: str):
        self._current_page_id = page_id
        self._stack.set_visible_child_name(page_id)
        for pid, _, title in SIDEBAR_PAGES:
            if pid == page_id:
                self._content_nav.set_title(title)
                break
        # Select the right sidebar row, deselect others
        for pid, lb in self._sidebar_listboxes.items():
            row = self._sidebar_rows.get(pid)
            if row:
                if pid == page_id:
                    lb.select_row(row)


        # Notify page of visibility
        page = self._pages.get(page_id)
        if page and hasattr(page, "on_shown"):
            page.on_shown()

    def _build_search_index(self):
        self._search_index: list[dict] = []

        def traverse(widget, pid, p_title):

            if isinstance(widget, Adw.PreferencesRow):
                title = widget.get_title()
                if title:
                    subtitle = widget.get_subtitle() if hasattr(widget, "get_subtitle") else ""
                    self._search_index.append({
                        "page_id": pid,
                        "page_title": p_title,
                        "title": title,
                        "subtitle": subtitle,
                        "widget": widget,
                    })


            if isinstance(widget, Adw.PreferencesGroup):
                title = widget.get_title()
                if title:
                    self._search_index.append({
                        "page_id": pid,
                        "page_title": p_title,
                        "title": title,
                        "subtitle": "(Group)",
                        "widget": widget,
                    })

            # Recurse into all children to find nested elements
            child = widget.get_first_child()
            while child:
                traverse(child, pid, p_title)
                child = child.get_next_sibling()

        for pid, _icon, p_title in SIDEBAR_PAGES:
            stack_child = self._stack.get_child_by_name(pid)
            if stack_child:
                traverse(stack_child, pid, p_title)

    def _on_search_changed(self, entry):
        query = entry.get_text().strip().lower()
        if not query or len(query) < 2:
            self._search_revealer.set_reveal_child(False)
            return

        matches = [
            r for r in self._search_index
            if query in r["title"].lower()
            or query in r["subtitle"].lower()
            or query in r["page_title"].lower()
        ]

        child = self._search_results_listbox.get_first_child()
        while child:
            self._search_results_listbox.remove(child)
            child = self._search_results_listbox.get_first_child()

        if matches:
            for m in matches:
                row = Gtk.ListBoxRow()
                row.search_match = m
                row.set_focusable(False)
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                box.set_margin_start(8)
                box.set_margin_end(8)
                box.set_margin_top(6)
                box.set_margin_bottom(6)
                title_lbl = Gtk.Label(label=m["title"], xalign=0)
                title_lbl.add_css_class("heading")
                title_lbl.set_focusable(False)
                title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                box.append(title_lbl)
                sub_text = m["page_title"]
                if m["subtitle"]:
                    sub_text += f" \u2022 {m['subtitle']}"
                sub_lbl = Gtk.Label(label=sub_text, xalign=0)
                sub_lbl.add_css_class("dim-label")
                sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                sub_lbl.set_focusable(False)
                box.append(sub_lbl)
                row.set_child(box)
                self._search_results_listbox.append(row)
            first = self._search_results_listbox.get_row_at_index(0)
            if first:
                self._search_results_listbox.select_row(first)
            self._search_revealer.set_reveal_child(True)
        else:
            self._search_revealer.set_reveal_child(False)

    def _on_search_key_pressed(self, controller, keyval, keycode, state):
        if not self._search_revealer.get_reveal_child():
            return False
        lb = self._search_results_listbox
        sel = lb.get_selected_row()
        if keyval == Gdk.KEY_Down:
            idx = (sel.get_index() + 1) if sel else 0
            nxt = lb.get_row_at_index(idx)
            if nxt:
                lb.select_row(nxt)
            return True
        if keyval == Gdk.KEY_Up:
            if sel and sel.get_index() > 0:
                lb.select_row(lb.get_row_at_index(sel.get_index() - 1))
            return True
        return False

    def _on_search_activate(self, entry):
        if not self._search_revealer.get_reveal_child():
            return
        sel = self._search_results_listbox.get_selected_row()
        if sel:
            self._on_search_result_activated(self._search_results_listbox, sel)

    def _on_stop_search(self, entry):
        entry.set_text("")
        self._search_revealer.set_reveal_child(False)

    def _on_search_result_activated(self, listbox, row):
        if not hasattr(row, "search_match"):
            return

        m = row.search_match
        self._search_revealer.set_reveal_child(False)
        self._search_entry.set_text("")

        # Navigate to the page
        self._select_page(m["page_id"])

        # Highlight the widget
        widget = m["widget"]
        widget.add_css_class("nm-pulse-highlight")

        def remove_class():
            widget.remove_css_class("nm-pulse-highlight")
            return False

        GLib.timeout_add(1500, remove_class)

    # Shortcuts

    def _setup_shortcuts(self):
        app = self.get_application()
        if not app:
            return
        shortcuts = [
            ("save", self._on_save, ["<Control>s"]),
            ("undo", self._do_undo, ["<Control>z"]),
            ("redo", self._do_redo, ["<Control><Shift>z"]),
            ("search", lambda: self._search_entry.grab_focus(), ["<Control>f"]),
        ]
        for name, fn, accels in shortcuts:
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, f=fn: f())
            self.add_action(a)
            app.set_accels_for_action(f"win.{name}", accels)

        # Menu actions
        open_profiles_action = Gio.SimpleAction.new("open_profiles", None)
        open_profiles_action.connect("activate", lambda *_: self._on_profiles_clicked())
        self.add_action(open_profiles_action)

        open_prefs_action = Gio.SimpleAction.new("open_preferences", None)
        open_prefs_action.connect("activate", lambda *_: self._open_preferences())
        self.add_action(open_prefs_action)

        reset_config_action = Gio.SimpleAction.new("reset_config", None)
        reset_config_action.connect("activate", lambda *_: self._on_reset_config_clicked())
        self.add_action(reset_config_action)

        open_kofi_action = Gio.SimpleAction.new("open_kofi", None)
        open_kofi_action.connect("activate", lambda *_: self._show_kofi_dialog())
        self.add_action(open_kofi_action)

    def get_nodes(self):
        return self.app_state.nodes

    def mark_dirty(self):
        self.app_state.mark_dirty()
        self._dirty_bar.set_visible(True)
        self._undo_btn.set_sensitive(self.app_state.undo.can_undo())
        self._redo_btn.set_sensitive(self.app_state.undo.can_redo())
        desc = self.app_state.undo.last_description
        self._dirty_label.set_label(f"Unsaved: {desc}" if desc else "Unsaved changes")
        self._build_search_index()

    def mark_clean(self):
        self.app_state.mark_clean()
        self._dirty_bar.set_visible(False)
        self._dirty_label.set_label("Unsaved changes")
        self._redo_btn.set_sensitive(False)

    def push_undo(self, description: str, before: str, after: str):
        self.app_state.push_undo(description, before, after)
        self._undo_btn.set_sensitive(True)

    def notify_nodes_changed(self):
        self.app_state.reload_from_disk()
        page = self._pages.get(self._current_page_id)
        if page and hasattr(page, "refresh"):
            page.refresh()
            self._build_search_index()

    def _on_save(self):
        from nirimod import app_settings
        if app_settings.get("auto_backup", True):
            from nirimod.backup import backup_all_sources
            limit = app_settings.get("backup_limit", 10)
            backup_all_sources(self.app_state.source_files, limit=limit)

        new_kdl = self.app_state.write_current_kdl()

        def _finish_save(reload_result):
            reload_ok, reload_msg = reload_result
            self.app_state.commit_save(new_kdl)
            out = self._pages.get("outputs")
            if out and hasattr(out, "refresh"):
                out.refresh()
            raw = self._pages.get("raw_config")
            if raw and hasattr(raw, "refresh"):
                raw.refresh()
                self._build_search_index()
            self.mark_clean()
            if reload_ok:
                self.show_toast("Config saved and applied ✓", timeout=3)
            else:
                self.show_toast(
                    f"Config saved, but reload failed: {reload_msg}", timeout=8
                )

        if self.app_state.is_multi_file:
            # Snapshot all source files before touching them
            snapshots = {
                p: p.read_text() for p in self.app_state.source_files if p.exists()
            }
            self.app_state.write_to_path()

            def _on_validated(result):
                ok, msg = result
                if not ok:
                    # Restore all files from snapshots
                    for p, text in snapshots.items():
                        p.write_text(text)
                    self.show_toast(f"Validation error: {msg}", timeout=8)
                    return
                niri_ipc.run_in_thread(niri_ipc.load_config_file, _finish_save)

            niri_ipc.run_in_thread(
                lambda: niri_ipc.validate_config(), _on_validated
            )
        else:
            tmp_kdl = kdl_parser.NIRI_CONFIG.with_name(".config.kdl.tmp")
            self.app_state.write_to_path(tmp_kdl)

            def _on_validated(result):
                ok, msg = result
                if not ok:
                    self.show_toast(f"Validation error: {msg}", timeout=8)
                    tmp_kdl.unlink(missing_ok=True)
                    return
                shutil.move(tmp_kdl, kdl_parser.NIRI_CONFIG)
                niri_ipc.run_in_thread(niri_ipc.load_config_file, _finish_save)

            niri_ipc.run_in_thread(
                lambda: niri_ipc.validate_config(str(tmp_kdl)), _on_validated
            )

    def _on_discard(self):
        self.app_state.discard()
        self.mark_clean()
        self.notify_nodes_changed()

    def _raw_config_textview_focused(self) -> bool:
        """Return True if the raw-config text editor currently has keyboard focus."""
        raw_page = self._pages.get("raw_config")
        if raw_page is None:
            return False
        tv = getattr(raw_page, "_textview", None)
        if tv is None:
            return False
        return tv.has_focus()

    def _do_undo(self):
        if self._raw_config_textview_focused():
            raw_page = self._pages.get("raw_config")
            buf = raw_page._textview.get_buffer()  # type: ignore[union-attr]
            if buf.get_can_undo():
                buf.undo()
            return

        entry = self.app_state.apply_undo()
        if entry is None:
            return

        if not self.app_state.undo.can_undo():
            self._undo_btn.set_sensitive(False)

        if self.app_state.is_dirty:
            self.mark_dirty()
        else:
            self.mark_clean()

        self.notify_nodes_changed()

    def _do_redo(self):
        if self._raw_config_textview_focused():
            raw_page = self._pages.get("raw_config")
            buf = raw_page._textview.get_buffer()
            if buf.get_can_redo():
                buf.redo()
            return

        entry = self.app_state.apply_redo()
        if entry is None:
            return

        self._redo_btn.set_sensitive(self.app_state.undo.can_redo())
        self._undo_btn.set_sensitive(True)
        self.mark_dirty()
        self.notify_nodes_changed()

    def show_toast(self, message: str, timeout: int = 3, copy_text: str | None = None):
        toast = Adw.Toast(title=message, timeout=timeout)
        if copy_text is not None:
            toast.set_button_label("Copy")
            toast.connect("button-clicked", lambda *_: self.get_clipboard().set(copy_text))
        elif "error" in message.lower() or "failed" in message.lower():
            toast.set_button_label("Copy")
            toast.connect("button-clicked", lambda *_: self.get_clipboard().set(message))

        self._toast_overlay.add_toast(toast)

    def _get_baseline_dir(self):
        from pathlib import Path
        path_str = str(kdl_parser.NIRI_CONFIG.resolve())
        path_hash = hashlib.md5(path_str.encode()).hexdigest()[:8]
        return Path.home() / ".config" / "nirimod" / "baseline" / f"{kdl_parser.NIRI_CONFIG.name}_{path_hash}"

    def _check_onboarding(self):
        baseline_dir = self._get_baseline_dir()
        sentinel = baseline_dir / kdl_parser.NIRI_CONFIG.name
        if sentinel.exists():
            return

        source_files = sorted(self.app_state.source_files)
        filenames = "\n".join(f"  • <tt>{p.name}</tt>" for p in source_files)
        body = (
            f"NiriMod will back up your original config files to\n"
            f"<tt>{baseline_dir}</tt>:\n\n"
            f"{filenames}\n"
        )

        dialog = Adw.AlertDialog(heading="Welcome to NiriMod", body=body)
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", "Not Now")
        dialog.add_response("accept", "Create Backup")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("accept")
        dialog.connect("response", self._on_onboarding_response)
        dialog.present(self)

    def _check_kofi(self):
        from nirimod import app_settings

        if app_settings.get("kofi_v3_dont_show", False):
            return
        self._show_kofi_dialog()

    def _show_kofi_dialog(self):
        from nirimod import app_settings

        dialog = Adw.AlertDialog(
            heading="Enjoying NiriMod? ☕",
            body=(
                "NiriMod is a passion project built entirely in my free time to make customizing Niri easier for everyone.\n\n"
                "If it has improved your workflow, please consider supporting its development with a small tip on Ko-fi! "
                "Your support directly fuels new features and keeps the project alive."
            ),
        )
        dialog.add_response("dismiss", "Maybe Later")
        dialog.add_response("kofi", "Support on Ko-fi")
        dialog.set_response_appearance("kofi", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("kofi")

        dont_show_check = Gtk.CheckButton(label="Don't show this again on startup")
        dont_show_check.set_active(app_settings.get("kofi_v3_dont_show", False))
        dont_show_check.set_halign(Gtk.Align.CENTER)
        dont_show_check.set_margin_top(4)
        dialog.set_extra_child(dont_show_check)

        def _on_kofi_response(dlg, response):
            app_settings.set("kofi_v3_dont_show", dont_show_check.get_active())
            if response == "kofi":
                Gio.AppInfo.launch_default_for_uri("https://ko-fi.com/srinivasr", None)

        dialog.connect("response", _on_kofi_response)
        dialog.present(self)

    def _check_for_updates(self):
        from nirimod import app_settings, updater
        if app_settings.get("auto_update", True):
            updater.check_for_updates(self._on_update_check_result)

    def _on_update_check_result(self, remote_sha: str | None, commit_msg: str | None):
        if remote_sha is None:
            return

        dialog = Adw.AlertDialog(
            heading="Update Available",
            body=f"A new version of NiriMod is available on GitHub!\n\n<b>Latest Commit:</b>\n{GLib.markup_escape_text(commit_msg or '')}",
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", "Later")
        dialog.add_response("update", "Update in Terminal")
        dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)

        def _on_response(dlg, response):
            if response == "update":
                from nirimod import updater
                updater.launch_updater_in_terminal()
                app = self.get_application()
                if app:
                    app.quit()
        dialog.connect("response", _on_response)
        dialog.present(self)

    def _on_onboarding_response(self, dialog, response):
        if response != "accept":
            return
        baseline_dir = self._get_baseline_dir()
        try:
            baseline_dir.mkdir(parents=True, exist_ok=True)
            for p in self.app_state.source_files:
                if p.exists():
                    try:
                        rel = p.relative_to(kdl_parser.NIRI_CONFIG.parent)
                        dest = baseline_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, dest)
                    except ValueError:
                        shutil.copy2(p, baseline_dir / p.name)
            self.show_toast("Baseline backup created ✓")
        except Exception as e:
            self.show_toast(f"Backup failed: {e}", timeout=6)

    def _on_reset_config_clicked(self, _btn=None):
        baseline_dir = self._get_baseline_dir()

        backups = []
        if kdl_parser.BACKUP_DIR.exists():
            for p in kdl_parser.BACKUP_DIR.iterdir():
                if p.is_dir():
                    backups.append((p.stat().st_mtime, p, p.name))
        
        backups.sort(key=lambda x: x[0], reverse=True)
        
        if baseline_dir.exists():
            backups.append((baseline_dir.stat().st_mtime, baseline_dir, "Original Baseline"))
            
        if not backups:
            self.show_toast("No backups available to restore.")
            return

        prefs_win = Adw.PreferencesWindow()
        prefs_win.set_title("Restore Backup")
        prefs_win.set_modal(True)
        prefs_win.set_transient_for(self)
        prefs_win.set_default_size(500, 400)

        page = Adw.PreferencesPage()
        grp = Adw.PreferencesGroup(
            title="Available Backups",
            description="Select a backup to restore your configuration from."
        )

        for _, path, name in backups:
            row = Adw.ActionRow(title=name)
            if name == "Original Baseline":
                row.set_subtitle("Taken on first launch")
                
            restore_btn = Gtk.Button(label="Restore")
            restore_btn.set_valign(Gtk.Align.CENTER)
            restore_btn.add_css_class("flat")
            restore_btn.add_css_class("suggested-action")
            restore_btn.connect("clicked", lambda _b, p=path: self._confirm_restore(p, prefs_win))
            row.add_suffix(restore_btn)
            grp.add(row)
            
        page.add(grp)
        prefs_win.add(page)
        prefs_win.present()

    def _confirm_restore(self, backup_dir, parent_dialog):
        parent_dialog.close()
        dialog = Adw.AlertDialog(
            heading="Confirm Restore",
            body="Your current configuration will be replaced by this backup. You may want to manually save your current work first."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("restore", "Restore")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda dlg, r: self._perform_restore(backup_dir) if r == "restore" else None)
        dialog.present(self)

    def _perform_restore(self, backup_dir):
        try:
            shutil.copytree(backup_dir, kdl_parser.NIRI_CONFIG.parent, dirs_exist_ok=True)
            self.app_state.reload_from_disk()
            self.notify_nodes_changed()
            self.mark_clean()
            self.show_toast("Config restored from backup ✓")
        except Exception as e:
            self.show_toast(f"Restore failed: {e}", timeout=6)

    def _open_preferences(self):
        from nirimod import app_settings

        prefs_win = Adw.PreferencesWindow()
        prefs_win.set_title("NiriMod Preferences")
        prefs_win.set_modal(True)
        prefs_win.set_transient_for(self)
        prefs_win.set_default_size(500, 400)

        page = Adw.PreferencesPage(
            title="General", icon_name="emblem-system-symbolic"
        )

        updates_grp = Adw.PreferencesGroup(
            title="Updates",
            description="Control how NiriMod checks for new versions",
        )

        auto_update_row = Adw.SwitchRow(
            title="Check for Updates Automatically",
            subtitle="Checks the GitHub repository for new commits on launch",
        )
        auto_update_row.set_active(app_settings.get("auto_update", True))
        auto_update_row.connect(
            "notify::active",
            lambda row, _: app_settings.set("auto_update", row.get_active()),
        )
        updates_grp.add(auto_update_row)
        page.add(updates_grp)

        config_grp = Adw.PreferencesGroup(
            title="Configuration File",
            description="Manage Niri configuration paths and backups",
        )

        config_path_row = Adw.ActionRow(title="Config Path")
        current_path = app_settings.get("config_path", "")
        config_path_row.set_subtitle(current_path if current_path else "Default (~/.config/niri/config.kdl)")
        
        browse_btn = Gtk.Button(label="Browse...")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", lambda _b: self._on_browse_config(prefs_win, config_path_row))
        config_path_row.add_suffix(browse_btn)

        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_btn.set_valign(Gtk.Align.CENTER)
        clear_btn.set_tooltip_text("Reset to default")
        clear_btn.connect("clicked", lambda _b: self._on_clear_config(config_path_row))
        config_path_row.add_suffix(clear_btn)

        config_grp.add(config_path_row)

        backup_path_row = Adw.ActionRow(title="Backup Directory")
        current_backup = app_settings.get("backup_path", "")
        backup_path_row.set_subtitle(current_backup if current_backup else "Default (~/.config/nirimod/backups)")
        
        browse_backup_btn = Gtk.Button(label="Browse...")
        browse_backup_btn.set_valign(Gtk.Align.CENTER)
        browse_backup_btn.connect("clicked", lambda _b: self._on_browse_backup_dir(prefs_win, backup_path_row))
        backup_path_row.add_suffix(browse_backup_btn)

        clear_backup_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_backup_btn.set_valign(Gtk.Align.CENTER)
        clear_backup_btn.set_tooltip_text("Reset to default")
        clear_backup_btn.connect("clicked", lambda _b: self._on_clear_backup_dir(backup_path_row))
        backup_path_row.add_suffix(clear_backup_btn)

        config_grp.add(backup_path_row)

        auto_backup_row = Adw.SwitchRow(
            title="Automatic Backups",
            subtitle="Create a timestamped backup before saving",
        )
        auto_backup_row.set_active(app_settings.get("auto_backup", True))
        auto_backup_row.connect(
            "notify::active",
            lambda row, _: app_settings.set("auto_backup", row.get_active()),
        )
        config_grp.add(auto_backup_row)

        backup_limit_row = Adw.SpinRow(
            title="Backup Limit",
            subtitle="Maximum number of backups to keep per file (0 = unlimited)",
            digits=0,
        )
        backup_limit_row.set_adjustment(Gtk.Adjustment(value=app_settings.get("backup_limit", 10), lower=0, upper=1000, step_increment=1))
        backup_limit_row.connect(
            "notify::value",
            lambda row, _: app_settings.set("backup_limit", int(row.get_value())),
        )
        
        def _on_auto_backup_changed(switch_row, _param):
            backup_limit_row.set_sensitive(switch_row.get_active())
            
        auto_backup_row.connect("notify::active", _on_auto_backup_changed)
        backup_limit_row.set_sensitive(auto_backup_row.get_active())

        config_grp.add(backup_limit_row)
        page.add(config_grp)

        prefs_win.add(page)
        prefs_win.present()

    def _on_browse_config(self, parent_win, row):
        from nirimod import app_settings
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Niri Config")
        f = Gtk.FileFilter()
        f.set_name("KDL files")
        f.add_pattern("*.kdl")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)

        def _on_response(dialog, result):
            try:
                f = dialog.open_finish(result)
                if f:
                    path = f.get_path()
                    app_settings.set("config_path", path)
                    row.set_subtitle(path)
                    self.show_toast("Restart NiriMod to use the new config path.", timeout=5)
            except GLib.Error:
                pass

        dialog.open(parent_win, None, _on_response)
        
    def _on_browse_backup_dir(self, parent_win, row):
        from nirimod import app_settings
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Backup Directory")
        
        def _on_response(dialog, result):
            try:
                f = dialog.select_folder_finish(result)
                if f:
                    path = f.get_path()
                    app_settings.set("backup_path", path)
                    row.set_subtitle(path)
                    kdl_parser.set_paths(
                        config_path=app_settings.get("config_path", ""),
                        backup_path=path
                    )
                    self.show_toast("Backup directory updated.", timeout=3)
            except GLib.Error:
                pass

        dialog.select_folder(parent_win, None, _on_response)

    def _on_clear_backup_dir(self, row):
        from nirimod import app_settings
        app_settings.set("backup_path", "")
        row.set_subtitle("Default (~/.config/nirimod/backups)")
        kdl_parser.set_paths(
            config_path=app_settings.get("config_path", ""),
            backup_path=""
        )
        self.show_toast("Backup directory reset to default.", timeout=3)

    def _on_clear_config(self, row):
        from nirimod import app_settings
        app_settings.set("config_path", "")
        row.set_subtitle("Default (~/.config/niri/config.kdl)")
        self.show_toast("Restart NiriMod to use the default config path.", timeout=5)

    def _on_profiles_clicked(self, _btn=None):
        dialog = Adw.AlertDialog(heading="Profiles")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(4)
        box.set_margin_end(4)

        names = prof_mod.list_profiles()
        if names:
            grp = Adw.PreferencesGroup(title="Saved Profiles")
            for name in names:
                row = Adw.ActionRow(title=name)
                load_btn = Gtk.Button(label="Load")
                load_btn.set_valign(Gtk.Align.CENTER)
                load_btn.add_css_class("flat")
                load_btn.connect(
                    "clicked", lambda _b, n=name: self._load_profile(n, dialog)
                )
                del_btn = Gtk.Button(icon_name="user-trash-symbolic")
                del_btn.set_valign(Gtk.Align.CENTER)
                del_btn.add_css_class("flat")
                del_btn.add_css_class("error")
                del_btn.connect(
                    "clicked", lambda _b, n=name: self._delete_profile(n, dialog)
                )
                row.add_suffix(load_btn)
                row.add_suffix(del_btn)
                grp.add(row)
            box.append(grp)

        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_row.set_margin_top(8)
        entry = Gtk.Entry(placeholder_text="New profile name…")
        entry.set_hexpand(True)
        save_btn = Gtk.Button(label="Save Current")
        save_btn.add_css_class("suggested-action")
        save_btn.connect(
            "clicked", lambda _b: self._save_profile(entry.get_text(), dialog)
        )
        save_row.append(entry)
        save_row.append(save_btn)
        box.append(save_row)

        dialog.set_extra_child(box)
        dialog.add_response("close", "Close")
        dialog.present(self)

    def _save_profile(self, name: str, dialog):
        name = name.strip()
        if not name:
            return
        prof_mod.save_profile(name, source_files=self.app_state.source_files)
        self.show_toast(f"Profile '{name}' saved ✓")

    def _load_profile(self, name: str, dialog):
        if prof_mod.load_profile(name):
            self.notify_nodes_changed()
            self.mark_dirty()
            self.show_toast(f"Profile '{name}' loaded")
        dialog.close()

    def _delete_profile(self, name: str, dialog):
        prof_mod.delete_profile(name)
        self.show_toast(f"Profile '{name}' deleted")

        extra = dialog.get_extra_child()
        if extra:
            dialog.set_extra_child(None)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(4)
        box.set_margin_end(4)
        names = prof_mod.list_profiles()
        if names:
            grp = Adw.PreferencesGroup(title="Saved Profiles")
            for n in names:
                row = Adw.ActionRow(title=n)
                load_btn = Gtk.Button(label="Load")
                load_btn.set_valign(Gtk.Align.CENTER)
                load_btn.add_css_class("flat")
                load_btn.connect("clicked", lambda _b, nm=n: self._load_profile(nm, dialog))
                del_btn = Gtk.Button(icon_name="user-trash-symbolic")
                del_btn.set_valign(Gtk.Align.CENTER)
                del_btn.add_css_class("flat")
                del_btn.add_css_class("error")
                del_btn.connect("clicked", lambda _b, nm=n: self._delete_profile(nm, dialog))
                row.add_suffix(load_btn)
                row.add_suffix(del_btn)
                grp.add(row)
            box.append(grp)
        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_row.set_margin_top(8)
        entry = Gtk.Entry(placeholder_text="New profile name\u2026")
        entry.set_hexpand(True)
        save_btn = Gtk.Button(label="Save Current")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda _b: self._save_profile(entry.get_text(), dialog))
        save_row.append(entry)
        save_row.append(save_btn)
        box.append(save_row)
        dialog.set_extra_child(box)

