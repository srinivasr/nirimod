from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UndoEntry:
    description: str
    snapshot_before: str
    snapshot_after: str
    nodes_before: list[Any] | None = None
    nodes_after: list[Any] | None = None


class UndoManager:
    def __init__(self, max_depth: int = 100):
        self._stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._max = max_depth

    def push(self, entry: UndoEntry) -> None:
        self._stack.append(entry)
        if len(self._stack) > self._max:
            self._stack.pop(0)
        self._redo_stack.clear()

    @property
    def last_snapshot(self) -> str | None:
        if self._stack:
            return self._stack[-1].snapshot_after
        return None

    @property
    def last_description(self) -> str | None:
        if self._stack:
            return self._stack[-1].description
        return None

    def pop_undo(self) -> UndoEntry | None:
        if not self._stack:
            return None
        entry = self._stack.pop()
        self._redo_stack.append(entry)
        return entry

    def pop_redo(self) -> UndoEntry | None:
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        self._stack.append(entry)
        return entry

    def can_undo(self) -> bool:
        return bool(self._stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def clear(self) -> None:
        self._stack.clear()
        self._redo_stack.clear()
