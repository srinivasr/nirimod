"""Wrappers around `niri msg` C. Low-level IPC operations."""

from __future__ import annotations

import json
from typing import Callable




# Internal: synchronous helper


def _run_sync(args: list[str], timeout: float = 5.0) -> tuple[str, str, int]:
    import subprocess

    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return "", "niri: command not found", 1
    except subprocess.TimeoutExpired:
        return "", "niri msg timed out", 1


# Internal: non-blocking async dispatch


def _run_async(
    args: list[str],
    callback: Callable[[str, str, int], None],
) -> None:
    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    try:
        proc = Gio.Subprocess.new(
            args,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
        )
    except GLib.Error:
        GLib.idle_add(lambda: callback("", "niri: command not found", 1) or False)
        return

    def _on_done(source: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            ok, stdout_bytes, stderr_bytes = source.communicate_finish(result)
            stdout = stdout_bytes.get_data().decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.get_data().decode("utf-8", errors="replace") if stderr_bytes else ""
            if not ok:
                rc = 1
            else:
                rc = 0 if source.get_exit_status() == 0 else 1
        except GLib.Error as exc:
            stdout, stderr, rc = "", str(exc), 1
        callback(stdout, stderr, rc)

    proc.communicate_async(None, None, _on_done)


# IPC Getters


def is_niri_running() -> bool:
    """Return True if `niri msg version` succeeds. Called once at startup."""
    stdout, _, rc = _run_sync(["niri", "msg", "version"])
    return rc == 0 and bool(stdout.strip())


def get_version() -> str:
    stdout, _, rc = _run_sync(["niri", "--version"])
    return stdout.strip() if rc == 0 else "unknown"


_touchpad_cache: bool | None = None


def has_touchpad() -> bool:
    import os

    global _touchpad_cache
    if _touchpad_cache is not None:
        return _touchpad_cache

    result = False
    try:
        for dev in os.listdir("/sys/class/input"):
            name_file = f"/sys/class/input/{dev}/device/name"
            if os.path.exists(name_file):
                with open(name_file) as fh:
                    name = fh.read().lower()
                if "touchpad" in name or "trackpad" in name:
                    result = True
                    break
    except Exception:
        pass

    _touchpad_cache = result
    return result


def validate_config(config_path: str | None = None) -> tuple[bool, str]:
    cmd = ["niri", "validate"]
    if config_path:
        cmd += ["--config", config_path]
    stdout, stderr, rc = _run_sync(cmd, timeout=10.0)
    if rc == 0:
        return True, stdout.strip() or "Config is valid."
    return False, stderr.strip() or stdout.strip() or "Unknown validation error."


def load_config_file() -> tuple[bool, str]:
    stdout, stderr, rc = _run_sync(
        ["niri", "msg", "action", "load-config-file"], timeout=10.0
    )
    if rc == 0:
        return True, stdout.strip() or "Config applied."
    return False, stderr.strip() or stdout.strip() or "Config reload failed."


def get_outputs(callback: Callable[[list[dict]], None]) -> None:
    def _done(stdout: str, _stderr: str, rc: int) -> None:
        if rc != 0:
            callback([])
            return
        try:
            data = json.loads(stdout)
            callback(list(data.values()) if isinstance(data, dict) else data)
        except json.JSONDecodeError:
            callback([])

    _run_async(["niri", "msg", "--json", "outputs"], _done)


def get_workspaces(callback: Callable[[list[dict]], None]) -> None:
    def _done(stdout: str, _stderr: str, rc: int) -> None:
        if rc != 0:
            callback([])
            return
        try:
            callback(json.loads(stdout))
        except json.JSONDecodeError:
            callback([])

    _run_async(["niri", "msg", "--json", "workspaces"], _done)


def get_windows(callback: Callable[[list[dict]], None]) -> None:
    def _done(stdout: str, _stderr: str, rc: int) -> None:
        if rc != 0:
            callback([])
            return
        try:
            callback(json.loads(stdout))
        except json.JSONDecodeError:
            callback([])

    _run_async(["niri", "msg", "--json", "windows"], _done)


def get_focused_window(callback: Callable[[dict | None], None]) -> None:
    def _done(stdout: str, _stderr: str, rc: int) -> None:
        if rc != 0:
            callback(None)
            return
        try:
            callback(json.loads(stdout))
        except json.JSONDecodeError:
            callback(None)

    _run_async(["niri", "msg", "--json", "focused-window"], _done)


def action(action_name: str, *args: str, callback: Callable[[bool], None] | None = None) -> None:
    cmd = ["niri", "msg", "action", action_name] + list(args)

    def _done(_stdout: str, _stderr: str, rc: int) -> None:
        if callback is not None:
            callback(rc == 0)

    _run_async(cmd, _done)


# Legacy thread shims


def run_in_thread(fn: Callable, callback: Callable | None = None):

    import threading

    import gi
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    def _worker():
        result = fn()
        if callback is not None:
            GLib.idle_add(lambda: callback(result) or False)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
