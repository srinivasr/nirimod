from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from nirimod import niri_ipc
from nirimod.kdl_parser import (
    KdlNode,
    find_or_create,
    remove_child,
    set_child_arg,
    set_node_flag,
    safe_switch_connect,
)
from nirimod.pages.base import BasePage

ACCEL_PROFILES = ["default", "flat", "adaptive"]
SCROLL_METHODS_TP = ["two-finger", "edge", "on-button-down", "no-scroll"]
SCROLL_METHODS_MOUSE = ["default", "no-scroll", "on-button-down"]
CLICK_METHODS = ["button-areas", "clickfinger"]


class InputPage(BasePage):
    def build(self) -> Gtk.Widget:
        tb, _, _, content = self._make_toolbar_page("Input")
        self._content = content
        self._build_content()
        return tb

    def _build_content(self):
        content = self._content
        nodes = self._nodes

        kb_expander = Adw.ExpanderRow(
            title="Keyboard", subtitle="XKB options &amp; key repeat"
        )
        kb_expander.add_css_class("nm-expander")

        kb_node = find_or_create(nodes, "input", "keyboard")
        xkb_node = kb_node.get_child("xkb") or KdlNode("xkb")

        fields = [
            ("layout", "Layout", "e.g. us,ru"),
            ("variant", "Variant", "e.g. dvorak"),
            ("model", "Model", ""),
            ("options", "Options", "e.g. grp:win_space_toggle"),
            ("rules", "Rules", ""),
        ]
        self._xkb_entries: dict[str, Adw.EntryRow] = {}
        for key, title, ph in fields:
            row = Adw.EntryRow(title=title)
            row.set_show_apply_button(True)
            val = xkb_node.child_arg(key) if xkb_node else None
            if val:
                row.set_text(str(val))
            row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
            row.connect("apply", lambda r, k=key: self._set_xkb(k, r.get_text()))
            kb_expander.add_row(row)
            self._xkb_entries[key] = row

        delay_adj = Gtk.Adjustment(
            value=int(kb_node.child_arg("repeat-delay", 600)),
            lower=100,
            upper=3000,
            step_increment=50,
        )
        delay_row = Adw.SpinRow(
            title="Repeat Delay (ms)", adjustment=delay_adj, digits=0
        )
        delay_row.connect(
            "notify::value",
            lambda r, _: self._set_kb("repeat-delay", int(r.get_value())),
        )
        kb_expander.add_row(delay_row)

        rate_adj = Gtk.Adjustment(
            value=int(kb_node.child_arg("repeat-rate", 25)),
            lower=1,
            upper=200,
            step_increment=1,
        )
        rate_row = Adw.SpinRow(
            title="Repeat Rate (keys/sec)", adjustment=rate_adj, digits=0
        )
        rate_row.connect(
            "notify::value",
            lambda r, _: self._set_kb("repeat-rate", int(r.get_value())),
        )
        kb_expander.add_row(rate_row)

        numlock_row = Adw.SwitchRow(title="Enable Num Lock on Startup")
        nl_init = kb_node.get_child("numlock") is not None
        numlock_row.set_active(nl_init)
        safe_switch_connect(numlock_row, nl_init, self._toggle_numlock)
        kb_expander.add_row(numlock_row)

        kb_grp = Adw.PreferencesGroup()
        kb_grp.add(kb_expander)
        content.append(kb_grp)

        # focus / pointer
        focus_grp = Adw.PreferencesGroup(title="Pointer Behavior")
        input_node = find_or_create(nodes, "input")

        ffm_row = Adw.SwitchRow(title="Focus Follows Mouse")
        ffm_node = input_node.get_child("focus-follows-mouse")
        ffm_row._last_active = ffm_node is not None
        ffm_row.set_active(ffm_node is not None)

        def _on_ffm_toggled(r, _):
            new_val = r.get_active()
            if new_val != getattr(r, "_last_active", None):
                r._last_active = new_val
                self._toggle_ffm(new_val)

        ffm_row.connect("notify::active", _on_ffm_toggled)
        focus_grp.add(ffm_row)

        scroll_val = 33
        if ffm_node:
            vRaw = ffm_node.props.get("max-scroll-amount")
            if vRaw is not None:
                try:
                    scroll_val = int(float(str(vRaw).replace("%", "").strip()))
                except ValueError:
                    pass
        self._last_scroll_val = scroll_val
        scroll_adj = Gtk.Adjustment(
            value=scroll_val, lower=0, upper=100, step_increment=1
        )
        scroll_pct_row = Adw.SpinRow(
            title="Max Scroll Amount (%)",
            subtitle="0% = only fully visible windows",
            adjustment=scroll_adj,
            digits=0,
        )
        scroll_pct_row.set_sensitive(ffm_node is not None)
        self._scroll_pct_row = scroll_pct_row
        scroll_pct_row._last_val = scroll_val

        def _on_scroll_pct_changed(r, _):
            new_val = int(r.get_value())
            if new_val != getattr(r, "_last_val", None):
                r._last_val = new_val
                self._set_ffm_scroll(new_val)

        scroll_pct_row.connect("notify::value", _on_scroll_pct_changed)
        focus_grp.add(scroll_pct_row)

        warp_init = input_node.get_child("warp-mouse-to-focus") is not None
        warp_row = Adw.SwitchRow(title="Warp Mouse to Focus")
        warp_row.set_active(warp_init)
        safe_switch_connect(
            warp_row,
            warp_init,
            lambda enabled: self._toggle_input_flag("warp-mouse-to-focus", enabled),
        )
        focus_grp.add(warp_row)

        wabf_init = input_node.get_child("workspace-auto-back-and-forth") is not None
        wabf_row = Adw.SwitchRow(
            title="Workspace Auto Back-and-Forth",
            subtitle="Switching to current workspace switches back to previous",
        )
        wabf_row.set_active(wabf_init)
        safe_switch_connect(
            wabf_row,
            wabf_init,
            lambda enabled: self._toggle_input_flag(
                "workspace-auto-back-and-forth", enabled
            ),
        )
        focus_grp.add(wabf_row)
        content.append(focus_grp)

        # touchpad
        tp_expander = Adw.ExpanderRow(title="Touchpad")
        tp_expander.add_css_class("nm-expander")
        has_tp = niri_ipc.has_touchpad()
        if not has_tp:
            tp_expander.set_subtitle("No touchpad detected")
            tp_expander.set_sensitive(False)

        tp_node = find_or_create(nodes, "input", "touchpad")

        def tp_switch(key, label, subtitle=""):
            r = Adw.SwitchRow(title=label, subtitle=subtitle)
            ini = tp_node.get_child(key) is not None
            r.set_active(ini)
            safe_switch_connect(
                r, ini, lambda enabled, k=key: self._set_tp_flag(k, enabled)
            )
            return r

        def tp_bool_switch(key, label, default_active=True, subtitle=""):
            r = Adw.SwitchRow(title=label, subtitle=subtitle)
            node = tp_node.get_child(key)
            if node is not None and node.args:
                ini = bool(node.args[0])
            else:
                ini = default_active
            r.set_active(ini)
            safe_switch_connect(r, ini, lambda enabled, k=key: self._set_tp(k, enabled))
            return r

        tp_expander.add_row(tp_switch("tap", "Tap to Click"))
        tp_expander.add_row(tp_switch("dwt", "Disable While Typing"))
        tp_expander.add_row(tp_switch("dwtp", "Disable While Trackpointing"))
        tp_expander.add_row(tp_switch("natural-scroll", "Natural Scroll"))
        tp_expander.add_row(tp_switch("left-handed", "Left Handed"))
        tp_expander.add_row(tp_switch("middle-emulation", "Middle Click Emulation"))
        tp_expander.add_row(tp_bool_switch("drag", "Tap Drag"))
        tp_expander.add_row(tp_switch("drag-lock", "Tap Drag Lock"))
        tp_expander.add_row(
            tp_switch("disabled-on-external-mouse", "Disable on External Mouse")
        )

        spd_adj = Gtk.Adjustment(
            value=float(tp_node.child_arg("accel-speed") or 0.0),
            lower=-1.0,
            upper=1.0,
            step_increment=0.05,
        )
        spd_row = Adw.SpinRow(title="Accel Speed", adjustment=spd_adj, digits=2)
        spd_row.connect(
            "notify::value", lambda r, _: self._set_tp("accel-speed", r.get_value())
        )
        tp_expander.add_row(spd_row)

        ap_model = Gtk.StringList.new(ACCEL_PROFILES)
        ap_row = Adw.ComboRow(title="Accel Profile", model=ap_model)
        cur_ap = tp_node.child_arg("accel-profile") or "default"
        if cur_ap in ACCEL_PROFILES:
            ap_row.set_selected(ACCEL_PROFILES.index(cur_ap))
        ap_row.connect(
            "notify::selected",
            lambda r, _: self._set_tp(
                "accel-profile", ACCEL_PROFILES[r.get_selected()]
            ),
        )
        tp_expander.add_row(ap_row)

        sm_model = Gtk.StringList.new(SCROLL_METHODS_TP)
        sm_row = Adw.ComboRow(title="Scroll Method", model=sm_model)
        cur_sm = tp_node.child_arg("scroll-method") or "two-finger"
        if cur_sm in SCROLL_METHODS_TP:
            sm_row.set_selected(SCROLL_METHODS_TP.index(cur_sm))
        sm_row.connect(
            "notify::selected",
            lambda r, _: self._set_tp(
                "scroll-method", SCROLL_METHODS_TP[r.get_selected()]
            ),
        )
        tp_expander.add_row(sm_row)

        cm_model = Gtk.StringList.new(CLICK_METHODS)
        cm_row = Adw.ComboRow(title="Click Method", model=cm_model)
        cur_cm = tp_node.child_arg("click-method") or "button-areas"
        if cur_cm in CLICK_METHODS:
            cm_row.set_selected(CLICK_METHODS.index(cur_cm))
        cm_row.connect(
            "notify::selected",
            lambda r, _: self._set_tp("click-method", CLICK_METHODS[r.get_selected()]),
        )
        tp_expander.add_row(cm_row)

        tp_grp = Adw.PreferencesGroup()
        tp_grp.add(tp_expander)
        content.append(tp_grp)

        # mouse
        m_expander = Adw.ExpanderRow(title="Mouse")
        m_expander.add_css_class("nm-expander")
        m_node = find_or_create(nodes, "input", "mouse")

        m_nat = Adw.SwitchRow(title="Natural Scroll")
        mn_init = m_node.get_child("natural-scroll") is not None
        m_nat.set_active(mn_init)
        safe_switch_connect(
            m_nat, mn_init, lambda enabled: self._set_m_flag("natural-scroll", enabled)
        )
        m_expander.add_row(m_nat)

        m_lh = Adw.SwitchRow(title="Left Handed")
        mlh_init = m_node.get_child("left-handed") is not None
        m_lh.set_active(mlh_init)
        safe_switch_connect(
            m_lh, mlh_init, lambda enabled: self._set_m_flag("left-handed", enabled)
        )
        m_expander.add_row(m_lh)

        m_me = Adw.SwitchRow(title="Middle Click Emulation")
        mme_init = m_node.get_child("middle-emulation") is not None
        m_me.set_active(mme_init)
        safe_switch_connect(
            m_me,
            mme_init,
            lambda enabled: self._set_m_flag("middle-emulation", enabled),
        )
        m_expander.add_row(m_me)

        m_spd_adj = Gtk.Adjustment(
            value=float(m_node.child_arg("accel-speed") or 0.0),
            lower=-1.0,
            upper=1.0,
            step_increment=0.05,
        )
        m_spd_row = Adw.SpinRow(title="Accel Speed", adjustment=m_spd_adj, digits=2)
        m_spd_row.connect(
            "notify::value", lambda r, _: self._set_m("accel-speed", r.get_value())
        )
        m_expander.add_row(m_spd_row)

        m_ap_model = Gtk.StringList.new(ACCEL_PROFILES)
        m_ap_row = Adw.ComboRow(title="Accel Profile", model=m_ap_model)
        cur_m_ap = m_node.child_arg("accel-profile") or "default"
        if cur_m_ap in ACCEL_PROFILES:
            m_ap_row.set_selected(ACCEL_PROFILES.index(cur_m_ap))
        m_ap_row.connect(
            "notify::selected",
            lambda r, _: self._set_m("accel-profile", ACCEL_PROFILES[r.get_selected()]),
        )
        m_expander.add_row(m_ap_row)

        m_sm_model = Gtk.StringList.new(SCROLL_METHODS_MOUSE)
        m_sm_row = Adw.ComboRow(title="Scroll Method", model=m_sm_model)
        cur_m_sm = m_node.child_arg("scroll-method") or "default"
        if cur_m_sm in SCROLL_METHODS_MOUSE:
            m_sm_row.set_selected(SCROLL_METHODS_MOUSE.index(cur_m_sm))
        m_sm_row.connect(
            "notify::selected",
            lambda r, _: self._set_m(
                "scroll-method", SCROLL_METHODS_MOUSE[r.get_selected()]
            ),
        )
        m_expander.add_row(m_sm_row)

        m_btn_val = int(m_node.child_arg("scroll-button", 274))
        m_btn_adj = Gtk.Adjustment(
            value=m_btn_val,
            lower=1,
            upper=1000,
            step_increment=1,
        )
        m_btn_row = Adw.SpinRow(
            title="Scroll Button Code",
            subtitle="274 = middle click (used with 'on-button-down')",
            adjustment=m_btn_adj,
            digits=0,
        )
        m_btn_row.connect(
            "notify::value",
            lambda r, _: self._set_m("scroll-button", int(r.get_value())),
        )
        m_expander.add_row(m_btn_row)

        m_btn_lock = Adw.SwitchRow(
            title="Scroll Button Lock",
            subtitle="Press once to toggle scrolling instead of holding",
        )
        mbl_init = m_node.get_child("scroll-button-lock") is not None
        m_btn_lock.set_active(mbl_init)
        safe_switch_connect(
            m_btn_lock,
            mbl_init,
            lambda enabled: self._set_m_flag("scroll-button-lock", enabled),
        )
        m_expander.add_row(m_btn_lock)

        m_grp = Adw.PreferencesGroup()
        m_grp.add(m_expander)
        content.append(m_grp)

        # trackpoint
        tr_expander = Adw.ExpanderRow(title="Trackpoint")
        tr_expander.add_css_class("nm-expander")
        tr_node = find_or_create(nodes, "input", "trackpoint")

        tr_nat = Adw.SwitchRow(title="Natural Scroll")
        trn_init = tr_node.get_child("natural-scroll") is not None
        tr_nat.set_active(trn_init)
        safe_switch_connect(
            tr_nat,
            trn_init,
            lambda enabled: self._set_tr_flag("natural-scroll", enabled),
        )
        tr_expander.add_row(tr_nat)

        tr_lh = Adw.SwitchRow(title="Left Handed")
        trlh_init = tr_node.get_child("left-handed") is not None
        tr_lh.set_active(trlh_init)
        safe_switch_connect(
            tr_lh, trlh_init, lambda enabled: self._set_tr_flag("left-handed", enabled)
        )
        tr_expander.add_row(tr_lh)

        tr_me = Adw.SwitchRow(title="Middle Click Emulation")
        trme_init = tr_node.get_child("middle-emulation") is not None
        tr_me.set_active(trme_init)
        safe_switch_connect(
            tr_me,
            trme_init,
            lambda enabled: self._set_tr_flag("middle-emulation", enabled),
        )
        tr_expander.add_row(tr_me)

        tr_spd_adj = Gtk.Adjustment(
            value=float(tr_node.child_arg("accel-speed") or 0.0),
            lower=-1.0,
            upper=1.0,
            step_increment=0.05,
        )
        tr_spd_row = Adw.SpinRow(title="Accel Speed", adjustment=tr_spd_adj, digits=2)
        tr_spd_row.connect(
            "notify::value", lambda r, _: self._set_tr("accel-speed", r.get_value())
        )
        tr_expander.add_row(tr_spd_row)

        tr_ap_model = Gtk.StringList.new(ACCEL_PROFILES)
        tr_ap_row = Adw.ComboRow(title="Accel Profile", model=tr_ap_model)
        cur_tr_ap = tr_node.child_arg("accel-profile") or "default"
        if cur_tr_ap in ACCEL_PROFILES:
            tr_ap_row.set_selected(ACCEL_PROFILES.index(cur_tr_ap))
        tr_ap_row.connect(
            "notify::selected",
            lambda r, _: self._set_tr(
                "accel-profile", ACCEL_PROFILES[r.get_selected()]
            ),
        )
        tr_expander.add_row(tr_ap_row)

        tr_sm_model = Gtk.StringList.new(SCROLL_METHODS_TP)
        tr_sm_row = Adw.ComboRow(title="Scroll Method", model=tr_sm_model)
        cur_tr_sm = tr_node.child_arg("scroll-method") or "on-button-down"
        if cur_tr_sm in SCROLL_METHODS_TP:
            tr_sm_row.set_selected(SCROLL_METHODS_TP.index(cur_tr_sm))
        tr_sm_row.connect(
            "notify::selected",
            lambda r, _: self._set_tr(
                "scroll-method", SCROLL_METHODS_TP[r.get_selected()]
            ),
        )
        tr_expander.add_row(tr_sm_row)

        tr_grp = Adw.PreferencesGroup()
        tr_grp.add(tr_expander)
        content.append(tr_grp)

        # cursor
        cursor_grp = Adw.PreferencesGroup(title="Cursor")
        cursor_node = next((n for n in nodes if n.name == "cursor"), None)

        size_val = int(cursor_node.child_arg("xcursor-size", 24)) if cursor_node else 24
        size_adj = Gtk.Adjustment(value=size_val, lower=8, upper=256, step_increment=2)
        size_row = Adw.SpinRow(title="Cursor Size (px)", adjustment=size_adj, digits=0)
        size_row.connect(
            "notify::value",
            lambda r, _: self._set_cursor("xcursor-size", int(r.get_value())),
        )
        cursor_grp.add(size_row)

        hide_val = (
            int(cursor_node.child_arg("hide-after-inactive-ms") or 0)
            if cursor_node
            else 0
        )
        hide_adj = Gtk.Adjustment(
            value=hide_val, lower=0, upper=60000, step_increment=500
        )
        hide_row = Adw.SpinRow(
            title="Hide After Inactive (ms)",
            subtitle="0 = never hide",
            adjustment=hide_adj,
            digits=0,
        )
        hide_row.connect(
            "notify::value",
            lambda r, _: self._set_cursor("hide-after-inactive-ms", int(r.get_value())),
        )
        cursor_grp.add(hide_row)

        theme_val = (
            str(cursor_node.child_arg("xcursor-theme") or "") if cursor_node else ""
        )
        theme_row = Adw.EntryRow(title="Cursor Theme (e.g. Adwaita)")
        theme_row.set_text(theme_val)
        theme_row.set_show_apply_button(True)
        theme_row.connect("apply", lambda r: self._set_cursor_theme(r.get_text()))
        cursor_grp.add(theme_row)
        content.append(cursor_grp)

    def _get_kb_node(self):
        return find_or_create(self._nodes, "input", "keyboard")

    def _get_xkb_node(self):
        kb = self._get_kb_node()
        xkb = kb.get_child("xkb")
        if xkb is None:
            xkb = KdlNode("xkb")
            kb.children.insert(0, xkb)
        return xkb

    def _set_xkb(self, key: str, value: str):
        xkb = self._get_xkb_node()
        if value.strip():
            set_child_arg(xkb, key, value.strip())
        else:
            remove_child(xkb, key)
        self._commit(f"keyboard xkb {key}")

    def _set_kb(self, key: str, value):
        set_child_arg(self._get_kb_node(), key, value)
        self._commit(f"keyboard {key}")

    def _toggle_numlock(self, enabled: bool):
        set_node_flag(self._get_kb_node(), "numlock", enabled)
        self._commit("keyboard numlock")

    def _get_input_node(self):
        return find_or_create(self._nodes, "input")

    def _toggle_ffm(self, enabled: bool):
        inp = self._get_input_node()
        existing = inp.get_child("focus-follows-mouse")
        if enabled:
            if existing is None:
                new_ffm = KdlNode(name="focus-follows-mouse")
                if hasattr(self, "_last_scroll_val"):
                    new_ffm.props["max-scroll-amount"] = f"{self._last_scroll_val}%"
                inp.children.insert(0, new_ffm)
        else:
            if existing is not None:
                inp.children.remove(existing)
        if hasattr(self, "_scroll_pct_row"):
            self._scroll_pct_row.set_sensitive(enabled)
        self._commit("focus-follows-mouse")

    def _set_ffm_scroll(self, pct: int):
        inp = self._get_input_node()
        ffm = inp.get_child("focus-follows-mouse")
        if ffm is None:
            ffm = KdlNode("focus-follows-mouse")
            inp.children.append(ffm)
        ffm.props["max-scroll-amount"] = f"{pct}%"
        self._commit("ffm scroll amount")

    def _toggle_input_flag(self, key: str, enabled: bool):
        set_node_flag(self._get_input_node(), key, enabled)
        self._commit(f"input {key}")

    def _get_tp_node(self):
        return find_or_create(self._nodes, "input", "touchpad")

    def _set_tp_flag(self, key: str, enabled: bool):
        set_node_flag(self._get_tp_node(), key, enabled)
        self._commit(f"touchpad {key}")

    def _set_tp(self, key: str, value):
        if key == "accel-profile" and (value == "default" or value is None):
            remove_child(self._get_tp_node(), key)
        else:
            set_child_arg(self._get_tp_node(), key, value)
        self._commit(f"touchpad {key}")

    def _get_m_node(self):
        return find_or_create(self._nodes, "input", "mouse")

    def _set_m_flag(self, key: str, enabled: bool):
        set_node_flag(self._get_m_node(), key, enabled)
        self._commit(f"mouse {key}")

    def _set_m(self, key: str, value):
        if key in ("accel-profile", "scroll-method") and (
            value == "default" or value is None
        ):
            remove_child(self._get_m_node(), key)
        else:
            set_child_arg(self._get_m_node(), key, value)
        self._commit(f"mouse {key}")

    def _get_tr_node(self):
        return find_or_create(self._nodes, "input", "trackpoint")

    def _set_tr_flag(self, key: str, enabled: bool):
        set_node_flag(self._get_tr_node(), key, enabled)
        self._commit(f"trackpoint {key}")

    def _set_tr(self, key: str, value):
        if key == "accel-profile" and (value == "default" or value is None):
            remove_child(self._get_tr_node(), key)
        else:
            set_child_arg(self._get_tr_node(), key, value)
        self._commit(f"trackpoint {key}")

    def _get_cursor_node(self):
        existing = next((n for n in self._nodes if n.name == "cursor"), None)
        if existing is None:
            existing = KdlNode("cursor")
            self._nodes.append(existing)
        return existing

    def _set_cursor(self, key: str, value):
        set_child_arg(self._get_cursor_node(), key, value)
        self._commit(f"cursor {key}")

    def _set_cursor_theme(self, theme: str):
        cur = self._get_cursor_node()
        if theme.strip():
            set_child_arg(cur, "xcursor-theme", theme.strip())
        else:
            remove_child(cur, "xcursor-theme")
        self._commit("cursor xcursor-theme")

    def refresh(self):
        child = self._content.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._content.remove(child)
            child = next_child
        self._build_content()
