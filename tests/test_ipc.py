"""Unit tests for the niri IPC wrappers.

Tests the synchronous helpers and validates that the non-blocking async
dispatch functions are wired correctly, using mocks to avoid requiring
a live niri compositor.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestRunSync(unittest.TestCase):
    """Tests for the internal _run_sync helper."""

    def test_command_not_found(self):
        from nirimod.niri_ipc import _run_sync

        stdout, stderr, rc = _run_sync(["__nonexistent_binary_xyz__"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", stderr)

    def test_successful_command(self):
        from nirimod.niri_ipc import _run_sync

        stdout, stderr, rc = _run_sync(["echo", "hello"])
        self.assertEqual(rc, 0)
        self.assertIn("hello", stdout)

    def test_timeout(self):
        from nirimod.niri_ipc import _run_sync

        stdout, stderr, rc = _run_sync(["sleep", "10"], timeout=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("timed out", stderr)


class TestIsNiriRunning(unittest.TestCase):
    def test_returns_false_when_niri_absent(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("", "not found", 1)):
            self.assertFalse(niri_ipc.is_niri_running())

    def test_returns_true_when_niri_present(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("niri 1.0\n", "", 0)):
            self.assertTrue(niri_ipc.is_niri_running())


class TestValidateConfig(unittest.TestCase):
    def test_valid_config(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("Config is valid.\n", "", 0)):
            ok, msg = niri_ipc.validate_config()
            self.assertTrue(ok)
            self.assertIn("valid", msg.lower())

    def test_invalid_config(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("", "parse error line 3", 1)):
            ok, msg = niri_ipc.validate_config()
            self.assertFalse(ok)
            self.assertIn("parse error", msg)

    def test_with_config_path(self):
        from nirimod import niri_ipc

        captured = {}

        def fake_run(args, timeout=5.0):
            captured["args"] = args
            return ("ok", "", 0)

        with patch.object(niri_ipc, "_run_sync", side_effect=fake_run):
            niri_ipc.validate_config("/tmp/test.kdl")

        self.assertIn("--config", captured["args"])
        self.assertIn("/tmp/test.kdl", captured["args"])


class TestLoadConfigFile(unittest.TestCase):
    def test_load_config_file_calls_niri_action(self):
        from nirimod import niri_ipc

        captured = {}

        def fake_run(args, timeout=5.0):
            captured["args"] = args
            captured["timeout"] = timeout
            return ("", "", 0)

        with patch.object(niri_ipc, "_run_sync", side_effect=fake_run):
            ok, msg = niri_ipc.load_config_file()

        self.assertTrue(ok)
        self.assertEqual(captured["args"], ["niri", "msg", "action", "load-config-file"])
        self.assertEqual(captured["timeout"], 10.0)
        self.assertIn("applied", msg)

    def test_load_config_file_reports_failure(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("", "reload failed", 1)):
            ok, msg = niri_ipc.load_config_file()

        self.assertFalse(ok)
        self.assertIn("reload failed", msg)


class TestHasTouchpad(unittest.TestCase):
    def test_caching(self):
        import nirimod.niri_ipc as ipc_mod

        # Clear any existing cache
        ipc_mod._touchpad_cache = None

        call_count = [0]

        original_listdir = __import__("os").listdir

        def fake_listdir(path):
            if path == "/sys/class/input":
                call_count[0] += 1
                return []
            return original_listdir(path)

        with patch("os.listdir", side_effect=fake_listdir):
            ipc_mod.has_touchpad()
            ipc_mod.has_touchpad()

        # Second call should use cache, so listdir only called once
        self.assertEqual(call_count[0], 1)

        # Clean up for other tests
        ipc_mod._touchpad_cache = None


class TestGetVersion(unittest.TestCase):
    def test_returns_version_string(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("niri 1.2.3\n", "", 0)):
            v = niri_ipc.get_version()
            self.assertEqual(v, "niri 1.2.3")

    def test_returns_unknown_on_failure(self):
        from nirimod import niri_ipc

        with patch.object(niri_ipc, "_run_sync", return_value=("", "error", 1)):
            v = niri_ipc.get_version()
            self.assertEqual(v, "unknown")


class TestRunInThread(unittest.TestCase):
    """Compatibility shim run_in_thread should invoke callback."""

    def test_shim_calls_callback(self):
        from nirimod import niri_ipc

        try:
            import gi
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib
        except (ModuleNotFoundError, Exception):
            self.skipTest("gi (PyGObject) not available in this test environment")

        results = []

        original_idle_add = GLib.idle_add

        def sync_idle_add(fn, *args):
            fn(*args)
            return 0

        GLib.idle_add = sync_idle_add
        try:
            t = niri_ipc.run_in_thread(lambda: 42, lambda r: results.append(r))
            t.join(timeout=2.0)
        finally:
            GLib.idle_add = original_idle_add

        self.assertEqual(results, [42])



if __name__ == "__main__":
    unittest.main()
