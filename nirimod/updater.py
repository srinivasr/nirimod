import json
import os
import shlex
import shutil
import subprocess
import tempfile
import urllib.request
import stat
import threading
from gi.repository import GLib

API_URL = "https://api.github.com/repos/srinivasr/nirimod/commits/main"
INSTALL_DIR = os.path.expanduser("~/.local/share/nirimod")
FALLBACK_TERMINALS = [
    "xdg-terminal-exec",
    "gnome-terminal",
    "kgx",  # GNOME Console
    "kitty",
    "ghostty",
    "alacritty",
    "konsole",
    "foot",
    "xterm",
]


def check_for_updates(callback):
    # Runs in a background thread so the UI stays responsive.
    # Calls callback(sha, message) if there's something new, or callback(None, None) otherwise.
    def _do_check():
        try:
            if not os.path.isdir(os.path.join(INSTALL_DIR, ".git")):
                # not a git install, nothing we can do
                GLib.idle_add(callback, None, None)
                return

            local_hash = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=INSTALL_DIR,
                text=True,
            ).strip()

            req = urllib.request.Request(
                API_URL, headers={"User-Agent": "NiriMod-Updater"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                remote_hash = data.get("sha")
                commit_msg = data.get("commit", {}).get(
                    "message", "New update available"
                )

            if remote_hash and remote_hash != local_hash:
                GLib.idle_add(callback, remote_hash, commit_msg)
            else:
                GLib.idle_add(callback, None, None)

        except Exception as e:
            print(f"Update check failed: {e}")
            GLib.idle_add(callback, None, None)

    threading.Thread(target=_do_check, daemon=True).start()


def _terminal_candidates():
    terminal = os.environ.get("TERMINAL", "").strip()
    if terminal:
        yield terminal
    yield from FALLBACK_TERMINALS


def _build_terminal_command(terminal: str, script_path: str) -> list[str] | None:
    try:
        parts = shlex.split(terminal)
    except ValueError:
        return None

    if not parts:
        return None

    if os.path.basename(parts[0]) == "xdg-terminal-exec":
        return [*parts, script_path]

    if parts[-1] in {"-e", "--execute", "-x"}:
        return [*parts, script_path]

    return [*parts, "-e", script_path]


def launch_updater_in_terminal():
    # Write a tiny installer script to /tmp and open it in whatever terminal is around.
    script_content = """#!/usr/bin/env bash
echo "Starting NiriMod update..."
curl -sSL https://raw.githubusercontent.com/srinivasr/nirimod/main/install.sh | bash -s -- --install
echo ""
echo "Update complete! Press Enter to close this window."
read
"""
    script_path = os.path.join(tempfile.gettempdir(), "nirimod_update.sh")
    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, stat.S_IRWXU)

    for term in _terminal_candidates():
        command = _build_terminal_command(term, script_path)
        if command is None or shutil.which(command[0]) is None:
            continue

        try:
            subprocess.Popen(command)
            return
        except Exception:
            continue

    print("Could not find a suitable terminal to launch the update.")
