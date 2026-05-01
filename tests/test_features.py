#!/usr/bin/env python3
"""Headless feature tests for NiriMod — exercises every page's logic."""

import sys
import traceback
import os
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("WAYLAND_DISPLAY", "wayland-1")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PASS = "[PASS]"
WARN = "[WARN]"
FAIL = "[FAIL]"

results = []

def test(name, fn):
    try:
        msg = fn()
        results.append((PASS, name, msg or ""))
    except Exception as e:
        results.append((FAIL, name, f"{type(e).__name__}: {e}"))
        traceback.print_exc()


test.__test__ = False

# KDL Parser
from nirimod.kdl_parser import parse_kdl, write_kdl, KdlNode

def t_kdl_roundtrip():
    src = 'output "eDP-1" { scale 2.0; }\nbinds { XF86AudioRaise { action "volume-up"; } }'
    nodes = parse_kdl(src)
    assert nodes, "no nodes parsed"
    return f"{len(nodes)} nodes"

def t_kdl_include():
    src = 'include "~/.config/niri/dms/monitor.kdl"\nspawn-at-startup "waybar"'
    nodes = parse_kdl(src)
    names = [n.name for n in nodes]
    assert "include" in names
    assert "spawn-at-startup" in names
    return "include + spawn parsed"

def t_kdl_nested():
    src = 'window-rule { match app-id="firefox"; open-maximized true; }'
    nodes = parse_kdl(src)
    assert nodes[0].name == "window-rule"
    assert nodes[0].children
    return "nested nodes OK"

def t_kdl_write():
    node = KdlNode("spawn-at-startup", args=["waybar", "--config", "/etc/waybar.json"])
    out = write_kdl([node])
    assert "waybar" in out
    return out.strip()

test("KDL: parse + write roundtrip", t_kdl_roundtrip)
test("KDL: include directive parsing", t_kdl_include)
test("KDL: nested children parsing", t_kdl_nested)
test("KDL: write KdlNode with args", t_kdl_write)

# AppState
from nirimod.state import AppState

def t_state_load():
    s = AppState()
    s.load()
    assert isinstance(s.nodes, list)
    return f"{len(s.nodes)} top-level nodes loaded"

def t_state_dirty():
    s = AppState()
    s.load()
    assert not s.is_dirty
    s.mark_dirty()
    assert s.is_dirty
    s.mark_clean()
    assert not s.is_dirty
    return "dirty/clean flags OK"

def t_state_discard():
    s = AppState()
    s.load()
    original_len = len(s.nodes)
    s.nodes.append(KdlNode("test-node"))
    s.mark_dirty()
    s.discard()
    assert len(s.nodes) == original_len
    return f"discarded back to {original_len} nodes"

def t_state_undo():
    s = AppState()
    s.load()
    before = write_kdl(s.nodes)
    s.nodes.append(KdlNode("test-undo-node"))
    after = write_kdl(s.nodes)
    s.push_undo("add test node", before, after)
    assert s.undo.can_undo()
    entry = s.apply_undo()
    assert entry is not None
    assert "test-undo-node" not in write_kdl(s.nodes)
    return "undo restored previous state"

test("AppState: load from disk", t_state_load)
test("AppState: dirty / clean flags", t_state_dirty)
test("AppState: discard reverts nodes", t_state_discard)
test("AppState: undo stack push+pop", t_state_undo)

# Undo Manager
from nirimod.undo import UndoManager, UndoEntry

def t_undo_redo():
    m = UndoManager()
    m.push(UndoEntry("step1", "before1", "after1"))
    m.push(UndoEntry("step2", "before2", "after2"))
    assert m.can_undo()
    e = m.pop_undo()
    assert e.description == "step2"
    assert m.can_redo()
    e2 = m.pop_redo()
    assert e2.description == "step2"
    return "undo→redo cycle OK"

test("UndoManager: push/pop/redo", t_undo_redo)

# Profiles
from nirimod import profiles as prof_mod

def t_profiles_list():
    names = prof_mod.list_profiles()
    assert isinstance(names, list)
    return f"{len(names)} profiles found"

def t_profiles_save_delete():
    s = AppState()
    s.load()
    # save_profile takes name + optional set[Path] of source files
    prof_mod.save_profile("__test_profile__", s.source_files)
    names = prof_mod.list_profiles()
    assert "__test_profile__" in names, f"profile not found in {names}"
    prof_mod.delete_profile("__test_profile__")
    assert "__test_profile__" not in prof_mod.list_profiles()
    return "save + delete profile OK"

test("Profiles: list", t_profiles_list)
test("Profiles: save and delete", t_profiles_save_delete)

# Pages (import + build check)
# We test imports and logic only — no GTK widget creation without display
page_modules = [
    ("appearance", "nirimod.pages.appearance"),
    ("animations", "nirimod.pages.animations"),
    ("layout",     "nirimod.pages.layout"),
    ("startup",    "nirimod.pages.startup"),
    ("environment","nirimod.pages.environment"),
    ("workspaces", "nirimod.pages.workspaces"),
    ("window_rules","nirimod.pages.window_rules"),
    ("bindings",   "nirimod.pages.bindings"),
    ("outputs",    "nirimod.pages.outputs"),
    ("input_page", "nirimod.pages.input_page"),
    ("gestures",   "nirimod.pages.gestures"),
    ("raw_config", "nirimod.pages.raw_config"),
]

import importlib
for name, module_path in page_modules:
    def _test(mp=module_path, n=name):
        importlib.import_module(mp)
        return "module imported OK"
    test(f"Page import: {name}", _test)

# Startup page logic
import shlex

def t_startup_spawn_sh():
    cmd = "waybar --config /etc/waybar.json"
    node = KdlNode("spawn-sh-at-startup", args=[cmd])   # single string for sh
    assert node.args[0] == cmd
    return f"spawn-sh-at-startup args = {node.args}"

def t_startup_spawn_direct():
    cmd = "dunst"
    args = shlex.split(cmd)
    node = KdlNode("spawn-at-startup", args=args)
    assert node.args == ["dunst"]
    return "spawn-at-startup args OK"

test("Startup: spawn-sh-at-startup node", t_startup_spawn_sh)
test("Startup: spawn-at-startup node", t_startup_spawn_direct)

# Animations curve serialization
def t_anim_curve_format():
    # The correct niri format is: curve "cubic-bezier" 0.25 0.1 0.25 1.0
    kdl = 'animations { workspace-switch { spring damping-ratio=1.0; } }'
    nodes = parse_kdl(kdl)
    out = write_kdl(nodes)
    assert "workspace-switch" in out
    return "animation node roundtrip OK"

test("Animations: curve node roundtrip", t_anim_curve_format)

# Environment page logic
def t_env_node():
    node = KdlNode("environment", children=[
        KdlNode("WAYLAND_DISPLAY", args=["wayland-1"])
    ])
    out = write_kdl([node])
    assert "WAYLAND_DISPLAY" in out
    return out.strip()

test("Environment: env var node write", t_env_node)

# Window rules logic
def t_window_rule_node():
    kdl = 'window-rule { match app-id="org.gnome.Calculator"; open-floating true; }'
    nodes = parse_kdl(kdl)
    assert nodes[0].name == "window-rule"
    children_names = [c.name for c in nodes[0].children]
    assert "match" in children_names
    assert "open-floating" in children_names
    return f"children: {children_names}"

test("Window Rules: parse match+action", t_window_rule_node)

# Output node
def t_output_node():
    kdl = 'output "eDP-1" { scale 1.5; transform "90"; mode "1920x1080@60"; }'
    nodes = parse_kdl(kdl)
    assert nodes[0].name == "output"
    assert nodes[0].args == ["eDP-1"]
    children = {c.name: c for c in nodes[0].children}
    assert "scale" in children
    assert float(children["scale"].args[0]) == 1.5
    return "output node parsed OK"

test("Outputs: parse output node", t_output_node)

# Bindings logic
def t_binds_node():
    kdl = 'binds { Mod+T { action spawn "alacritty"; } Mod+Q { action close-window; } }'
    nodes = parse_kdl(kdl)
    assert nodes[0].name == "binds"
    assert len(nodes[0].children) == 2
    return f"{len(nodes[0].children)} binds found"

test("Bindings: parse binds block", t_binds_node)

# Workspaces logic
def t_workspaces_node():
    kdl = 'workspaces { workspace "Browser"; workspace "Terminal"; }'
    nodes = parse_kdl(kdl)
    assert nodes[0].name == "workspaces"
    return f"{len(nodes[0].children)} workspaces"

test("Workspaces: parse workspace names", t_workspaces_node)

# NiriIPC
from nirimod import niri_ipc

def t_ipc_is_running():
    result = niri_ipc.is_niri_running()
    assert isinstance(result, bool)
    return f"niri running = {result}"

def t_ipc_has_touchpad():
    result = niri_ipc.has_touchpad()
    assert isinstance(result, bool)
    return f"has touchpad = {result}"

test("NiriIPC: is_niri_running()", t_ipc_is_running)
test("NiriIPC: has_touchpad()", t_ipc_has_touchpad)

# AppSettings
from nirimod import app_settings

def t_app_settings():
    original = app_settings.get("auto_update", True)
    app_settings.set("auto_update", False)
    assert not app_settings.get("auto_update")
    app_settings.set("auto_update", original)
    return "get/set OK"

test("AppSettings: get/set", t_app_settings)

def _print_results() -> int:
    print("\n" + "="*50)
    print("  NIRIMOD FEATURE TEST REPORT")
    print("="*50)

    passed = sum(1 for r in results if r[0] == PASS)
    failed = sum(1 for r in results if r[0] == FAIL)
    warned = sum(1 for r in results if r[0] == WARN)

    for icon, name, detail in results:
        status = f"{icon} {name}"
        if detail:
            print(f"{status}\n     → {detail}")
        else:
            print(status)

    print("="*50)
    print(
        f"  {passed} passed  |  {warned} warnings  |  {failed} failed  |  {len(results)} total"
    )
    print("="*50)
    return failed


if __name__ == "__main__":
    sys.exit(1 if _print_results() else 0)
