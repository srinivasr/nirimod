from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nirimod.kdl_parser import (
    NIRI_CONFIG,
    KdlNode,
    load_niri_config_multi,
    parse_kdl,
    save_niri_config,
    save_niri_config_multi,
    write_kdl,
)
from nirimod.undo import UndoEntry, UndoManager

if TYPE_CHECKING:
    pass


@dataclass
class RuntimeInfo:
    niri_running: bool = False
    has_touchpad: bool = False


class AppState:
    def __init__(self) -> None:
        self._nodes: list[KdlNode] = []
        self._saved_kdl: str = ""
        self._undo: UndoManager = UndoManager()
        self._runtime: RuntimeInfo = RuntimeInfo()
        self._dirty: bool = False
        self._include_slots: list[tuple[KdlNode, Path]] = []
        self._source_files: set[Path] = set()
        self._saved_nodes: list[KdlNode] = []
        self._current_nodes: list[KdlNode] = []

    def load(self) -> None:
        from nirimod import niri_ipc

        self._runtime = RuntimeInfo(
            niri_running=niri_ipc.is_niri_running(),
            has_touchpad=niri_ipc.has_touchpad(),
        )
        self._nodes, self._include_slots = load_niri_config_multi()
        self._source_files = {NIRI_CONFIG}
        for _, path in self._include_slots:
            if path.exists():
                self._source_files.add(path)
        self._saved_kdl = write_kdl(self._nodes) if self._nodes else ""
        self._saved_nodes = copy.deepcopy(self._nodes)
        self._current_nodes = copy.deepcopy(self._nodes)
        self._dirty = False

    @property
    def nodes(self) -> list[KdlNode]:
        return self._nodes

    @nodes.setter
    def nodes(self, value: list[KdlNode]) -> None:
        self._nodes = value
        self._current_nodes = copy.deepcopy(value)

    @property
    def saved_kdl(self) -> str:
        return self._saved_kdl

    @property
    def source_files(self) -> set[Path]:
        return self._source_files

    @property
    def include_slots(self) -> list[tuple[KdlNode, Path]]:
        return self._include_slots

    @property
    def is_multi_file(self) -> bool:
        return bool(self._include_slots)

    @property
    def niri_running(self) -> bool:
        return self._runtime.niri_running

    @property
    def has_touchpad(self) -> bool:
        return self._runtime.has_touchpad

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False

    @property
    def undo(self) -> UndoManager:
        return self._undo

    def push_undo(self, description: str, before: str, after: str) -> None:
        nodes_before = None
        if self._current_nodes and write_kdl(self._current_nodes) == before:
            nodes_before = copy.deepcopy(self._current_nodes)
        elif write_kdl(self._nodes) == before:
            nodes_before = copy.deepcopy(self._nodes)

        nodes_after = None
        if write_kdl(self._nodes) == after:
            nodes_after = copy.deepcopy(self._nodes)

        if nodes_after is not None:
            self._current_nodes = copy.deepcopy(nodes_after)
        else:
            self._current_nodes = self._restore_nodes_from_snapshot(after)

        entry = UndoEntry(
            description=description,
            snapshot_before=before,
            snapshot_after=after,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )
        self._undo.push(entry)

    def _restore_nodes_from_snapshot(self, snapshot: str) -> list[KdlNode]:
        nodes = parse_kdl(snapshot) if snapshot else []
        if self._include_slots:
            name_counts: dict[str, int] = {}
            seq_map: dict[tuple[str, int], tuple[Path, int]] = {}
            ref = self._saved_nodes or self._current_nodes
            for n in ref:
                if n.source_file is not None:
                    idx = name_counts.get(n.name, 0)
                    name_counts[n.name] = idx + 1
                    seq_map[(n.name, idx)] = (
                        n.source_file,
                        getattr(n, "_primary_order", 0),
                    )

            restore_counts: dict[str, int] = {}
            for n in nodes:
                if n.source_file is None:
                    idx = restore_counts.get(n.name, 0)
                    restore_counts[n.name] = idx + 1
                    if (n.name, idx) in seq_map:
                        n.source_file, n._primary_order = seq_map[(n.name, idx)]
                    elif (n.name, 0) in seq_map:
                        n.source_file, n._primary_order = seq_map[(n.name, 0)]
        return nodes

    def apply_undo(self) -> UndoEntry | None:
        entry = self._undo.pop_undo()
        if entry is None:
            return None
        self._nodes = (
            copy.deepcopy(entry.nodes_before)
            if entry.nodes_before is not None
            else self._restore_nodes_from_snapshot(entry.snapshot_before)
        )
        self._current_nodes = copy.deepcopy(self._nodes)
        self._dirty = entry.snapshot_before != self._saved_kdl
        return entry

    def apply_redo(self) -> UndoEntry | None:
        entry = self._undo.pop_redo()
        if entry is None:
            return None
        self._nodes = (
            copy.deepcopy(entry.nodes_after)
            if entry.nodes_after is not None
            else self._restore_nodes_from_snapshot(entry.snapshot_after)
        )
        self._current_nodes = copy.deepcopy(self._nodes)
        self._dirty = entry.snapshot_after != self._saved_kdl
        return entry

    def discard(self) -> None:
        if self._saved_nodes:
            self._nodes = copy.deepcopy(self._saved_nodes)
        elif self._saved_kdl:
            self._nodes = self._restore_nodes_from_snapshot(self._saved_kdl)
        else:
            self._nodes = []
        self._current_nodes = copy.deepcopy(self._nodes)
        self._undo.clear()
        self._dirty = False

    def commit_save(self, new_kdl: str) -> None:
        self._saved_kdl = new_kdl
        self._saved_nodes = copy.deepcopy(self._nodes)
        self._current_nodes = copy.deepcopy(self._nodes)
        self._undo.clear()
        self._dirty = False

    def reload_from_disk(self) -> None:
        self._nodes, self._include_slots = load_niri_config_multi()
        self._source_files = {NIRI_CONFIG}
        for _, path in self._include_slots:
            if path.exists():
                self._source_files.add(path)
        self._saved_kdl = write_kdl(self._nodes) if self._nodes else ""
        self._saved_nodes = copy.deepcopy(self._nodes)
        self._current_nodes = copy.deepcopy(self._nodes)

    def write_current_kdl(self) -> str:
        return write_kdl(self._nodes)

    def write_to_path(self, path: Path | None = None) -> None:
        if path is not None:
            # Explicit path (e.g. validation temp file) — single file write
            save_niri_config(self._nodes, path=path)
        elif self._include_slots:
            save_niri_config_multi(self._nodes, self._include_slots)
        else:
            save_niri_config(self._nodes)
