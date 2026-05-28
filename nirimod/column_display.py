"""Shared helpers for Niri column display config values."""

from __future__ import annotations


COLUMN_DISPLAY_OPTIONS = [
    ("Normal", "normal"),
    ("Tabbed", "tabbed"),
]
COLUMN_DISPLAY_LABELS = [label for label, _ in COLUMN_DISPLAY_OPTIONS]
COLUMN_DISPLAY_RULE_LABELS = ["Use Layout Default", *COLUMN_DISPLAY_LABELS]


def normalize_column_display(value) -> str | None:
    normalized = str(value or "").lower()
    for _, option_value in COLUMN_DISPLAY_OPTIONS:
        if normalized == option_value:
            return option_value
    return None


def column_display_index(value) -> int:
    normalized = normalize_column_display(value)
    for index, (_, option_value) in enumerate(COLUMN_DISPLAY_OPTIONS):
        if normalized == option_value:
            return index
    return 0


def column_display_value(index: int) -> str:
    if 0 <= index < len(COLUMN_DISPLAY_OPTIONS):
        return COLUMN_DISPLAY_OPTIONS[index][1]
    return COLUMN_DISPLAY_OPTIONS[0][1]


def column_display_rule_index(value: str | None) -> int:
    normalized = normalize_column_display(value)
    if normalized is None:
        return 0

    for index, (_, option_value) in enumerate(COLUMN_DISPLAY_OPTIONS, start=1):
        if normalized == option_value:
            return index
    return 0


def column_display_rule_value(index: int) -> str | None:
    option_index = index - 1
    if not (0 <= option_index < len(COLUMN_DISPLAY_OPTIONS)):
        return None
    return COLUMN_DISPLAY_OPTIONS[option_index][1]
