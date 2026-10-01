"""Unit tests for the AppState manager.

Tests state initialization, dirty tracking, undo/redo integration,
commit_save, discard, and node serialization helpers — without requiring
a live GTK session or filesystem access.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from nirimod.kdl_parser import KdlNode, KdlRawString, parse_kdl, write_kdl
from nirimod.state import AppState


class TestAppStateInit(unittest.TestCase):
    """AppState starts in a clean, non-dirty state."""

    def test_initial_state(self):
        state = AppState()
        self.assertEqual(state.nodes, [])
        self.assertEqual(state.saved_kdl, "")
        self.assertFalse(state.is_dirty)
        self.assertFalse(state.niri_running)
        self.assertFalse(state.has_touchpad)

    def test_initial_undo_empty(self):
        state = AppState()
        self.assertFalse(state.undo.can_undo())
        self.assertFalse(state.undo.can_redo())


class TestDirtyTracking(unittest.TestCase):
    def test_mark_dirty(self):
        state = AppState()
        self.assertFalse(state.is_dirty)
        state.mark_dirty()
        self.assertTrue(state.is_dirty)

    def test_mark_clean(self):
        state = AppState()
        state.mark_dirty()
        state.mark_clean()
        self.assertFalse(state.is_dirty)


class TestUndoRedo(unittest.TestCase):
    def _make_state_with_nodes(self, kdl: str) -> AppState:
        state = AppState()
        state.nodes = parse_kdl(kdl)
        state._saved_kdl = kdl
        return state

    def test_push_and_apply_undo(self):
        state = self._make_state_with_nodes("gaps 8\n")
        before = "gaps 8\n"
        after = "gaps 16\n"
        state.push_undo("change gaps", before, after)
        self.assertTrue(state.undo.can_undo())

        entry = state.apply_undo()
        self.assertIsNotNone(entry)
        self.assertEqual(
            state.nodes[0].get_child("gaps")
            if state.nodes and state.nodes[0].children
            else None,
            None,
        )
        # After undo, nodes should be from the 'before' snapshot
        kdl_out = write_kdl(state.nodes)
        self.assertIn("8", kdl_out)

    def test_apply_undo_empty_returns_none(self):
        state = AppState()
        result = state.apply_undo()
        self.assertIsNone(result)

    def test_apply_redo_empty_returns_none(self):
        state = AppState()
        result = state.apply_redo()
        self.assertIsNone(result)

    def test_undo_sets_dirty(self):
        state = self._make_state_with_nodes("gaps 8\n")
        state.push_undo("x", "gaps 16\n", "gaps 24\n")
        state.apply_undo()
        self.assertTrue(state.is_dirty)

    def test_redo_after_undo(self):
        state = self._make_state_with_nodes("gaps 8\n")
        state.push_undo("x", "gaps 8\n", "gaps 16\n")
        state.apply_undo()
        self.assertTrue(state.undo.can_redo())
        entry = state.apply_redo()
        self.assertIsNotNone(entry)
        kdl_out = write_kdl(state.nodes)
        self.assertIn("16", kdl_out)


class TestCommitSave(unittest.TestCase):
    def test_commit_save_clears_undo_and_dirty(self):
        state = AppState()
        state.push_undo("x", "a", "b")
        state.mark_dirty()
        state.commit_save("new kdl\n")
        self.assertEqual(state.saved_kdl, "new kdl\n")
        self.assertFalse(state.is_dirty)
        self.assertFalse(state.undo.can_undo())


class TestDiscard(unittest.TestCase):
    def test_discard_restores_saved_kdl(self):
        state = AppState()
        state._saved_kdl = "gaps 8\n"
        state.nodes = parse_kdl("gaps 16\n")
        state.mark_dirty()
        state.push_undo("x", "gaps 8\n", "gaps 16\n")

        state.discard()

        self.assertFalse(state.is_dirty)
        self.assertFalse(state.undo.can_undo())
        kdl_out = write_kdl(state.nodes)
        self.assertIn("8", kdl_out)

    def test_discard_empty_saved_kdl(self):
        state = AppState()
        state._saved_kdl = ""
        state.discard()
        self.assertEqual(state.nodes, [])


class TestWriteCurrentKdl(unittest.TestCase):
    def test_write_current_kdl(self):
        state = AppState()
        state.nodes = [KdlNode("prefer-no-csd")]
        out = state.write_current_kdl()
        self.assertIn("prefer-no-csd", out)

    def test_write_raw_string(self):
        # A string containing a double-quote forces the hash-delimited raw form
        node = KdlNode("env", args=[KdlRawString('has "double" quotes')])
        out = write_kdl([node])
        self.assertIn('r#"', out)


class TestLoad(unittest.TestCase):
    def test_load_detects_runtime(self):
        state = AppState()
        # state.py does: from nirimod import niri_ipc
        # We patch at the canonical module location so all references see the mock.
        with (
            patch("nirimod.niri_ipc.is_niri_running", return_value=True),
            patch("nirimod.niri_ipc.has_touchpad", return_value=True),
            patch("nirimod.kdl_parser.NIRI_CONFIG") as mock_cfg,
        ):
            mock_cfg.exists.return_value = False
            state.load()

        self.assertTrue(state.niri_running)
        self.assertTrue(state.has_touchpad)
        self.assertFalse(state.is_dirty)


class TestMultiFileUndo(unittest.TestCase):
    def test_undo_preserves_source_files_and_prevents_duplicate_blocks(self):
        from pathlib import Path
        import tempfile
        import shutil
        from nirimod import kdl_parser as K

        tmp = Path(tempfile.mkdtemp())
        try:
            main = tmp / "config.kdl"
            inputs = tmp / "inputs.kdl"
            main.write_text(
                'include "inputs.kdl"\n\nbinds {\n  Mod4+Q { close-window }\n}\n'
            )
            inputs.write_text("touchpad {\n  tap\n}\n")

            K.set_paths(config_path=main, backup_path=tmp / "backups")
            state = AppState()
            state.load()

            self.assertTrue(state.is_multi_file)
            tp_node = next(n for n in state.nodes if n.name == "touchpad")
            self.assertEqual(tp_node.source_file, inputs)

            before = state.write_current_kdl()
            K.set_child_arg(tp_node, "tap", False)
            after = state.write_current_kdl()
            state.push_undo("change tap", before, after)
            state.mark_dirty()

            state.apply_undo()
            tp_after_undo = next(n for n in state.nodes if n.name == "touchpad")
            self.assertEqual(tp_after_undo.source_file, inputs)

            state.write_to_path()
            self.assertIn("touchpad", inputs.read_text())
            self.assertNotIn("touchpad", main.read_text())
            self.assertIn('include "inputs.kdl"', main.read_text())

            state.apply_redo()
            tp_after_redo = next(n for n in state.nodes if n.name == "touchpad")
            self.assertEqual(tp_after_redo.source_file, inputs)
            state.write_to_path()
            self.assertNotIn("touchpad", main.read_text())
        finally:
            shutil.rmtree(tmp)
            K.set_paths()


class TestZeroValueDefaults(unittest.TestCase):
    def test_gaps_zero_preserved(self):
        from nirimod.kdl_parser import parse_kdl

        nodes = parse_kdl("layout {\n  gaps 0\n}\n")
        self.assertEqual(nodes[0].child_arg("gaps", 16), 0)

    def test_shadow_softness_and_spread_zero_preserved(self):
        from nirimod.kdl_parser import parse_kdl

        nodes = parse_kdl("shadow {\n  softness 0\n  spread 0\n}\n")
        self.assertEqual(nodes[0].child_arg("softness", 30), 0)
        self.assertEqual(nodes[0].child_arg("spread", 5), 0)

    def test_repeat_delay_and_rate_zero_preserved(self):
        from nirimod.kdl_parser import parse_kdl

        nodes = parse_kdl("keyboard {\n  repeat-delay 0\n  repeat-rate 0\n}\n")
        self.assertEqual(nodes[0].child_arg("repeat-delay", 600), 0)
        self.assertEqual(nodes[0].child_arg("repeat-rate", 25), 0)

    def test_slowdown_zero_preserved(self):
        from nirimod.kdl_parser import parse_kdl

        nodes = parse_kdl("animations {\n  slowdown 0.0\n}\n")
        self.assertEqual(nodes[0].child_arg("slowdown", 1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
