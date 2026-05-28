"""Helpers for reading and writing startup program entries."""

from __future__ import annotations

import re
import shlex

from nirimod.kdl_parser import KdlNode


_DELAY_PREFIX_RE = re.compile(
    r"^\s*sleep\s+(?P<seconds>\d+)\s*(?:&&|;)\s*(?P<command>.+?)\s*$"
)


def strip_startup_delay(command: str) -> tuple[str, int]:
    match = _DELAY_PREFIX_RE.match(command)
    if match is None:
        return command, 0

    command = match.group("command").strip()
    if command.startswith("exec "):
        command = command[5:].strip()
    return command, int(match.group("seconds"))


def startup_values_from_node(node: KdlNode) -> tuple[str, bool, int]:
    is_sh = "sh" in node.name
    if is_sh:
        command = str(node.args[0]) if node.args else ""
        command, delay = strip_startup_delay(command)
        return command, True, delay

    command = shlex.join(str(arg) for arg in node.args)
    return command, False, 0


def make_startup_node(command: str, is_sh: bool, delay: int) -> KdlNode:
    if delay > 0:
        if is_sh:
            delayed_command = f"sleep {delay} && {command}"
        else:
            try:
                args = shlex.split(command)
            except ValueError:
                args = command.split()
            delayed_command = f"sleep {delay} && exec {shlex.join(args)}"
        return KdlNode("spawn-sh-at-startup", args=[delayed_command])

    if is_sh:
        return KdlNode("spawn-sh-at-startup", args=[command])

    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    return KdlNode("spawn-at-startup", args=args)
