"""Raw Config page — editable view of the full merged config."""

from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango, GLib

from pathlib import Path

from nirimod import niri_ipc
from nirimod.kdl_parser import NIRI_CONFIG, replace_config_file
from nirimod.pages.base import BasePage


class RawConfigPage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, header, _, content = self._make_toolbar_page("Raw Config")
        self._content = content

        self._scroll_positions: dict[Path, tuple[float, float]] = {}
        self._buffer_modified = False
        self._original_text = ""

        self._current_files: list[Path] = []
        self._file_dropdown = Gtk.DropDown()
        self._file_dropdown.set_valign(Gtk.Align.CENTER)
        self._file_dropdown.connect("notify::selected-item", self._on_file_selected)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box.set_halign(Gtk.Align.CENTER)
        title_box.set_valign(Gtk.Align.CENTER)

        title_label = Gtk.Label(label="Config File")
        title_label.add_css_class("title")
        title_box.append(title_label)
        title_box.append(self._file_dropdown)

        header.pack_start(title_box)
        title_box.set_margin_start(12)

        # Header actions
        validate_btn = Gtk.Button(label="Validate")
        validate_btn.add_css_class("suggested-action")
        validate_btn.connect("clicked", self._on_validate)
        header.pack_end(validate_btn)

        self._save_btn = Gtk.Button(label="Save")
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.set_tooltip_text("Save this file and reload niri (Ctrl+S)")
        self._save_btn.connect("clicked", self._on_save_raw)
        self._save_btn.set_sensitive(False)
        header.pack_end(self._save_btn)

        self._discard_btn = Gtk.Button(label="Discard")
        self._discard_btn.add_css_class("destructive-action")
        self._discard_btn.add_css_class("flat")
        self._discard_btn.set_tooltip_text("Discard unsaved changes")
        self._discard_btn.connect("clicked", self._on_discard_raw)
        self._discard_btn.set_sensitive(False)
        header.pack_end(self._discard_btn)

        # Editor
        self._textview = Gtk.TextView()
        self._textview.set_editable(True)
        self._textview.set_monospace(True)
        self._textview.set_wrap_mode(Gtk.WrapMode.NONE)
        self._textview.set_left_margin(16)
        self._textview.set_right_margin(16)
        self._textview.set_top_margin(16)
        self._textview.set_bottom_margin(16)
        self._textview.add_css_class("code-editor")

        self._buf = self._textview.get_buffer()
        self._buf.connect("changed", self._on_buffer_changed)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.add_css_class("card")
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        self._scroll.set_hexpand(True)
        self._scroll.set_child(self._textview)
        content.append(self._scroll)

        self.refresh()
        return tb


    # Scroll position helpers

    def _save_scroll_position(self):
        """Persist the current scroll position for the active file."""
        idx = self._file_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._current_files):
            return
        path = self._current_files[idx]
        hadj = self._scroll.get_hadjustment()
        vadj = self._scroll.get_vadjustment()
        self._scroll_positions[path] = (hadj.get_value(), vadj.get_value())

    def _restore_scroll_position(self, path: Path):
        """Restore the saved scroll position for a given file, if any."""
        if path not in self._scroll_positions:
            return
        hval, vval = self._scroll_positions[path]

        def _apply():
            hadj = self._scroll.get_hadjustment()
            vadj = self._scroll.get_vadjustment()
            hadj.set_value(hval)
            vadj.set_value(vval)
            return False  # don't repeat

        # Defer one frame so the buffer is fully laid out before scrolling
        GLib.idle_add(_apply)


    # Page lifecycle

    def on_shown(self):
        """Called every time the user navigates back to this page."""
        # Restore scroll for whichever file is currently selected
        idx = self._file_dropdown.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION and idx < len(self._current_files):
            self._restore_scroll_position(self._current_files[idx])

    def refresh(self):
        state = self._win.app_state

        if state.is_multi_file:
            self._current_files = sorted(list(state.source_files))
            if NIRI_CONFIG in self._current_files:
                self._current_files.remove(NIRI_CONFIG)
                self._current_files.insert(0, NIRI_CONFIG)
        else:
            self._current_files = [NIRI_CONFIG]

        strings = [p.name for p in self._current_files]
        self._file_dropdown.set_model(Gtk.StringList.new(strings))

        self._load_selected_file()

    def _reload_from_disk(self):
        """Re-read the file from disk, discarding any edits."""
        self._load_selected_file(force=True)


    # File loading

    def _on_file_selected(self, dropdown, param):
        self._save_scroll_position()
        self._load_selected_file()

    def _load_selected_file(self, force: bool = False):
        idx = self._file_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._current_files):
            return

        if self._buffer_modified and not force:
            self._confirm_discard_then(lambda: self._do_load_file(idx))
            return

        self._do_load_file(idx)

    def _do_load_file(self, idx: int):
        path = self._current_files[idx]
        text = path.read_text() if path.exists() else f"// File not found: {path}"

        self._buf.handler_block_by_func(self._on_buffer_changed)
        self._buf.set_text(text)
        self._original_text = text
        self._apply_syntax_highlighting(self._buf, text)
        self._buf.handler_unblock_by_func(self._on_buffer_changed)

        self._set_modified(False)
        self._restore_scroll_position(path)


    # Buffer modification tracking

    def _on_buffer_changed(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        is_changed = (text != self._original_text)
        if is_changed != self._buffer_modified:
            self._set_modified(is_changed)

    def _set_modified(self, modified: bool):
        self._buffer_modified = modified
        self._save_btn.set_sensitive(modified)
        self._discard_btn.set_sensitive(modified)


    # Save / Discard

    def _on_save_raw(self, *_):
        idx = self._file_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._current_files):
            return

        path = self._current_files[idx]
        text = self._buf.get_text(self._buf.get_start_iter(), self._buf.get_end_iter(), False)

        from nirimod import app_settings
        if app_settings.get("auto_backup", True):
            from nirimod.backup import backup_all_sources
            limit = app_settings.get("backup_limit", 10)
            backup_all_sources(self._win.app_state.source_files, limit=limit)

        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(text)
        except Exception as e:
            self.show_toast(f"Write error: {e}", timeout=6)
            return

        self.show_toast("Validating…", timeout=2)

        def _on_validated(result):
            ok, msg = result
            if not ok:
                tmp.unlink(missing_ok=True)
                self.show_toast(f"Validation error: {msg[:120]}", timeout=8)
                return
            try:
                replace_config_file(tmp, path)
            except Exception as e:
                self.show_toast(f"Save error: {e}", timeout=6)
                return

            self._set_modified(False)
            self._original_text = text
            self._apply_syntax_highlighting(self._buf, text)
            niri_ipc.run_in_thread(niri_ipc.load_config_file, self._on_reloaded)

        niri_ipc.run_in_thread(
            lambda: niri_ipc.validate_config(str(tmp)), _on_validated
        )

    def _on_reloaded(self, result):
        ok, msg = result
        if ok:
            self.show_toast("Config saved and applied ✓", timeout=3)
        else:
            self.show_toast(f"Saved, but reload failed: {msg[:80]}", timeout=8)
        self._win.app_state.reload_from_disk()
        self._win._build_search_index()

    def _on_discard_raw(self, *_):
        self._confirm_discard_then(self._reload_from_disk)

    def _confirm_discard_then(self, callback):
        import gi
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        dialog = Adw.AlertDialog(
            heading="Discard changes?",
            body="Your unsaved edits to this file will be lost.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def _on_response(dlg, response):
            if response == "discard":
                self._set_modified(False)
                callback()

        dialog.connect("response", _on_response)
        dialog.present(self._win)


    # Syntax highlighting

    def _apply_syntax_highlighting(self, buf: Gtk.TextBuffer, text: str):
        tag_table = buf.get_tag_table()

        def _get_or_create_tag(name, **props):
            t = tag_table.lookup(name)
            if t is None:
                t = buf.create_tag(name, **props)
            return t

        comment_tag = _get_or_create_tag(
            "comment", foreground="#6a9955", style=Pango.Style.ITALIC
        )
        string_tag = _get_or_create_tag("string", foreground="#ce9178")
        node_tag = _get_or_create_tag("node", foreground="#9cdcfe")
        keyword_tag = _get_or_create_tag("keyword", foreground="#c586c0")

        import re

        def _apply(pattern, tag, group=0):
            for m in re.finditer(pattern, text, re.MULTILINE):
                s = buf.get_iter_at_offset(m.start(group))
                e = buf.get_iter_at_offset(m.end(group))
                buf.apply_tag(tag, s, e)

        _apply(r"//[^\n]*", comment_tag)
        _apply(r'"[^"\\]*(?:\\.[^"\\]*)*"', string_tag)
        _apply(r"\b(true|false|null)\b", keyword_tag)
        _apply(r"^(\s*)([a-zA-Z][\w\-]*)", node_tag, group=2)


    # Copy / Validate



    def _on_validate(self, *_):
        self.show_toast("Validating...")

        def _on_validated(result):
            ok, msg = result
            self.show_toast(msg[:120], timeout=5)

        niri_ipc.run_in_thread(
            lambda: niri_ipc.validate_config(str(NIRI_CONFIG)), _on_validated
        )
