"""Lightweight KDL parser and writer for Niri config.kdl.

Handles the subset of KDL used by niri's config format. For complex
cases (nested nodes, attributes) we store raw KDL text and do targeted
find/replace rather than a full AST round-trip.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NIRI_CONFIG = Path.home() / ".config" / "niri" / "config.kdl"
PROFILES_DIR = Path.home() / ".config" / "niri" / "profiles"
BACKUP_DIR = Path.home() / ".config" / "niri" / "backup"


class KdlRawString(str):
    """Marker class for strings that should be serialized as raw string literals r"..."."""

    pass


@dataclass
class KdlNode:
    name: str
    args: list[Any] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)
    children: list["KdlNode"] = field(default_factory=list)
    leading_trivia: str = ""
    trailing_trivia: str = ""
    children_trailing_trivia: str = ""
    source_file: Path | None = field(default=None, compare=False, repr=False)
    _removed_children: dict[str, tuple[int, "KdlNode"]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def get_child(self, name: str) -> "KdlNode | None":
        for c in reversed(self.children):
            if c.name == name:
                return c
        return None

    def get_children(self, name: str) -> list["KdlNode"]:
        return [c for c in self.children if c.name == name]

    def child_arg(self, name: str, default=None):
        c = self.get_child(name)
        if c and c.args:
            return c.args[0]
        return default

    def __repr__(self):
        return f"KdlNode({self.name!r}, args={self.args}, props={self.props}, children={len(self.children)})"


# Tokenizer

# Token types
_TOK_NEWLINE = "NL"  # statement-terminating newline
_TOK_SEMICOLON = "SC"  # ; statement terminator
_TOK_LBRACE = "LB"  # {
_TOK_RBRACE = "RB"  # }
_TOK_STRING = "STR"  # "..."
_TOK_RAW_STRING = "RSTR"  # r#"..."#
_TOK_PLAIN = "PL"  # identifier / number / keyword
_TOK_SLASHDASH = "SD"  # /- (next node/arg suppressed)
_TOK_WS = "WS"  # whitespace or comment
_TOK_EOF = "EOF"


def _lex(text: str) -> list[tuple[str, str]]:
    """Return list of (token_type, token_value) from KDL source."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    in_node = False  # True after we've seen a non-WS token on this line

    while i < n:
        # whitespace (spaces/tabs only — NOT newlines)
        if text[i] in " \t":
            j = i
            while j < n and text[j] in " \t":
                j += 1
            tokens.append((_TOK_WS, text[i:j]))
            i = j
            continue

        # line comment
        if text[i : i + 2] == "//":
            j = i
            while j < n and text[j] != "\n":
                j += 1
            tokens.append((_TOK_WS, text[i:j]))
            i = j
            continue

        # block comment
        if text[i : i + 2] == "/*":
            end = text.find("*/", i + 2)
            j = end + 2 if end != -1 else n
            tokens.append((_TOK_WS, text[i:j]))
            i = j
            continue

        # backslash line continuation — \ before \n keeps node open
        if text[i] == "\\" and i + 1 < n and text[i + 1] in "\r\n":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            tokens.append((_TOK_WS, text[i:j]))
            i = j
            continue

        # newline(s) — act as statement terminator
        if text[i] in "\r\n":
            j = i
            while j < n and text[j] in "\r\n":
                j += 1
            nl_str = text[i:j]
            if in_node:
                tokens.append((_TOK_NEWLINE, nl_str))
                in_node = False
            else:
                tokens.append((_TOK_WS, nl_str))
            i = j
            continue

        # semicolon — explicit terminator
        if text[i] == ";":
            if in_node:
                tokens.append((_TOK_SEMICOLON, ";"))
                in_node = False
            else:
                tokens.append((_TOK_WS, ";"))
            i += 1
            continue

        # /- (node/arg comment)
        if text[i : i + 2] == "/-":
            tokens.append((_TOK_SLASHDASH, "/-"))
            i += 2
            in_node = True
            continue

        # braces
        if text[i] == "{":
            tokens.append((_TOK_LBRACE, "{"))
            in_node = False  # children block resets line context
            i += 1
            continue
        if text[i] == "}":
            tokens.append((_TOK_RBRACE, "}"))
            in_node = False
            i += 1
            continue

        # raw string r#"..."# (handle r#, r##, etc.)
        if text[i] == "r" and i + 1 < n and text[i + 1] in '#"':
            j = i + 1
            while j < n and text[j] == "#":
                j += 1
            num_hashes = j - i - 1
            if j < n and text[j] == '"':
                start = j + 1
                end_delim = '"' + "#" * num_hashes
                end = text.find(end_delim, start)
                if end == -1:
                    raw = text[start:]
                    i = n
                else:
                    raw = text[start:end]
                    i = end + len(end_delim)
                tokens.append((_TOK_RAW_STRING, raw))
                in_node = True
                continue
            # Not a raw string — fall through to identifier parsing

        # quoted string
        if text[i] == '"':
            j = i + 1
            s = ""
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                    esc = {
                        "n": "\n",
                        "t": "\t",
                        "r": "\r",
                        '"': '"',
                        "\\": "\\",
                        "b": "\b",
                        "f": "\f",
                    }.get(text[j], text[j])
                    s += esc
                else:
                    s += text[j]
                j += 1
            tokens.append((_TOK_STRING, s))
            in_node = True
            i = j + 1
            continue

        # plain token (identifier, number, keyword)
        j = i
        while j < n and text[j] not in ' \t\r\n;{}"\\':
            # Property values can be written as raw strings, e.g.
            # title=r#"^notificationtoasts_\d+_desktop$"#. Stop after the
            # '=' so the raw-string lexer below can preserve backslashes.
            if text[j] == "=" and j + 1 < n and text[j + 1] == "r":
                k = j + 2
                while k < n and text[k] == "#":
                    k += 1
                if k < n and text[k] == '"':
                    j += 1
                    break
            if text[j] == "/" and j + 1 < n and text[j + 1] in "-/*":
                break
            j += 1
        tok = text[i:j]
        if tok:
            tokens.append((_TOK_PLAIN, tok))
            in_node = True
        i = j

    if in_node:
        tokens.append((_TOK_EOF, ""))
    tokens.append((_TOK_EOF, ""))
    return tokens


def _parse_value(tok_type: str, tok_val: str) -> Any:
    if tok_type == _TOK_STRING:
        return tok_val
    if tok_type == _TOK_RAW_STRING:
        return KdlRawString(tok_val)
    v = tok_val
    if v == "true":
        return True
    if v == "false":
        return False
    if v == "null":
        return None
    try:
        return int(v, 0)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_nodes(
    tokens: list[tuple[str, str]], pos: int, is_top_level: bool = False
) -> tuple[list[KdlNode], int, str]:
    nodes: list[KdlNode] = []
    n = len(tokens)
    skip_next = False

    current_trivia = ""

    while pos < n:
        tt, tv = tokens[pos]

        if tt in (_TOK_WS, _TOK_NEWLINE, _TOK_SEMICOLON):
            current_trivia += tv
            pos += 1
            continue

        if tt == _TOK_EOF:
            break

        if tt == _TOK_RBRACE:
            if is_top_level:
                current_trivia += tv
                pos += 1
                continue
            break

        if tt == _TOK_SLASHDASH:
            current_trivia += tv
            skip_next = True
            pos += 1
            continue

        if tt not in (_TOK_PLAIN, _TOK_STRING):
            current_trivia += tv
            pos += 1
            continue

        name = tv
        pos += 1
        node = KdlNode(name=name)
        node.leading_trivia = current_trivia
        current_trivia = ""

        accumulated_ws = ""

        while pos < n:
            tt2, tv2 = tokens[pos]

            if tt2 in (_TOK_NEWLINE, _TOK_SEMICOLON, _TOK_EOF):
                node.trailing_trivia += accumulated_ws + tv2
                pos += 1
                break

            if tt2 == _TOK_WS:
                accumulated_ws += tv2
                pos += 1
                continue

            if tt2 == _TOK_RBRACE:
                node.trailing_trivia += accumulated_ws
                break

            if tt2 == _TOK_LBRACE:
                node.trailing_trivia += accumulated_ws
                accumulated_ws = ""
                pos += 1
                node.children, pos, node.children_trailing_trivia = _parse_nodes(
                    tokens, pos
                )
                if pos < n and tokens[pos][0] == _TOK_RBRACE:
                    pos += 1
                break

            if tt2 == _TOK_SLASHDASH:
                accumulated_ws += tv2
                pos += 1
                while pos < n and tokens[pos][0] == _TOK_WS:
                    accumulated_ws += tokens[pos][1]
                    pos += 1
                if pos < n and tokens[pos][0] not in (
                    _TOK_NEWLINE,
                    _TOK_SEMICOLON,
                    _TOK_EOF,
                    _TOK_RBRACE,
                    _TOK_LBRACE,
                ):
                    accumulated_ws += tokens[pos][1]
                    pos += 1
                continue

            if "/*" in accumulated_ws or "//" in accumulated_ws:
                node.trailing_trivia += accumulated_ws
            accumulated_ws = ""

            if tt2 == _TOK_PLAIN and "=" in tv2 and not tv2.startswith("-"):
                k, _, vraw = tv2.partition("=")
                if not vraw:
                    pos += 1
                    while pos < n and tokens[pos][0] == _TOK_WS:
                        pos += 1
                    if pos < n and tokens[pos][0] not in (
                        _TOK_NEWLINE,
                        _TOK_SEMICOLON,
                        _TOK_EOF,
                        _TOK_RBRACE,
                        _TOK_LBRACE,
                    ):
                        vtt, vtv = tokens[pos]
                        node.props[k] = _parse_value(vtt, vtv)
                        pos += 1
                elif vraw == "r" or (
                    vraw.startswith("r") and all(c == "#" for c in vraw[1:])
                ):
                    num_hashes = len(vraw) - 1
                    pos += 1
                    while pos < n and tokens[pos][0] == _TOK_WS:
                        pos += 1
                    if pos < n and tokens[pos][0] == _TOK_STRING:
                        node.props[k] = KdlRawString(tokens[pos][1])
                        pos += 1
                        while (
                            num_hashes > 0
                            and pos < n
                            and tokens[pos] == (_TOK_PLAIN, "#")
                        ):
                            pos += 1
                            num_hashes -= 1
                    else:
                        node.props[k] = _parse_value(_TOK_PLAIN, vraw)
                else:
                    node.props[k] = _parse_value(_TOK_PLAIN, vraw)
                    pos += 1
            else:
                node.args.append(_parse_value(tt2, tv2))
                pos += 1

        if skip_next:
            current_trivia += _write_node(node)
            skip_next = False
        else:
            nodes.append(node)

    return nodes, pos, current_trivia


def parse_kdl(text: str) -> list[KdlNode]:
    tokens = _lex(text)
    nodes, _, eof_trivia = _parse_nodes(tokens, 0, is_top_level=True)
    if nodes and eof_trivia:
        setattr(nodes[-1], "eof_trivia", eof_trivia)
    return nodes


def load_niri_config() -> list[KdlNode]:
    if not NIRI_CONFIG.exists():
        return []
    return parse_kdl(NIRI_CONFIG.read_text())


def _resolve_includes(
    nodes: list[KdlNode],
    base: Path,
    depth: int = 0,
) -> tuple[list[KdlNode], list[tuple[KdlNode, Path]]]:
    # Flatten all included files into a single node list, tracking which file
    # each node came from (source_file) and its original position in the primary
    # config (_primary_order) so we can put it back in the right place on save.
    flat: list[KdlNode] = []
    slots: list[tuple[KdlNode, Path]] = []

    for i, node in enumerate(nodes):
        if node.name != "include" or depth > 5:
            node.source_file = base
            if depth == 0:
                node._primary_order = i  # type: ignore[attr-defined]
            flat.append(node)
            continue

        optional = node.props.get("optional", False)
        if not node.args:
            node.source_file = base
            if depth == 0:
                node._primary_order = i  # type: ignore[attr-defined]
            flat.append(node)
            continue

        node.source_file = base
        if depth == 0:
            node._primary_order = i  # type: ignore[attr-defined]
        target = base.parent / node.args[0]
        slots.append((node, target))

        if not target.exists():
            if not optional:
                import warnings

                warnings.warn(f"nirimod: included file not found: {target}")
            continue

        included = parse_kdl(target.read_text())
        child_flat, child_slots = _resolve_includes(included, target, depth + 1)
        flat.extend(child_flat)
        slots.extend(child_slots)

    return flat, slots


def load_niri_config_multi() -> tuple[list[KdlNode], list[tuple[KdlNode, Path]]]:
    if not NIRI_CONFIG.exists():
        return [], []
    raw = parse_kdl(NIRI_CONFIG.read_text())
    return _resolve_includes(raw, NIRI_CONFIG)


def _atomic_write(path: Path, content: str) -> None:
    # Skip if nothing changed — avoids triggering niri's config watcher
    # for files that we touched but didn't actually modify.
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".nirimod_tmp_")
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.close(fd)
        os.unlink(tmp)
        raise


def save_niri_config_multi(
    nodes: list[KdlNode],
    include_slots: list[tuple[KdlNode, Path]],
) -> None:
    # Figure out which file is the "main" one. Normally config.kdl, but we
    # read it from the slots so we're not hardcoded to a specific path.
    primary = NIRI_CONFIG
    if include_slots and include_slots[0][0].source_file is not None:
        primary = include_slots[0][0].source_file

    # If a node was just created (source_file=None), try to route it to the
    # same file as existing nodes of the same type. That way a new window-rule
    # goes to rules.kdl, a new spawn-at-startup goes to startup.kdl, etc.
    # Genuinely new node types with no existing home fall back to config.kdl.
    name_to_file: dict[str, Path] = {}
    for node in nodes:
        if node.source_file is not None and node.source_file != primary:
            name_to_file.setdefault(node.name, node.source_file)
    for node in nodes:
        if node.source_file is None:
            node.source_file = name_to_file.get(node.name)

    by_file: dict[Path, list[KdlNode]] = {}
    config_nodes: list[KdlNode] = []

    for node in nodes:
        src = node.source_file
        if src is None or src == primary:
            config_nodes.append(node)
        else:
            by_file.setdefault(src, []).append(node)

    for path, file_nodes in by_file.items():
        _atomic_write(path, write_kdl(file_nodes))

    # Rebuild config.kdl in the original node order (include lines stay where
    # the user put them rather than getting hoisted to the top).
    _LARGE = 10**9
    primary_items: list[tuple[int, KdlNode]] = []
    for inc_node, _ in include_slots:
        primary_items.append((getattr(inc_node, "_primary_order", _LARGE), inc_node))
    for node in config_nodes:
        primary_items.append((getattr(node, "_primary_order", _LARGE), node))
    primary_items.sort(key=lambda x: x[0])

    _atomic_write(primary, write_kdl([n for _, n in primary_items]))


# Writer


def _val_to_kdl(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, KdlRawString):
        num_hashes = 0
        delim = ""
        while f'"{delim}' in v:
            num_hashes += 1
            delim = "#" * num_hashes
        return f'r{delim}"{v}"{delim}'
    if isinstance(v, str):
        escaped = (
            v.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if v is None:
        return "null"
    return str(v)


def _is_inline_node(node: KdlNode) -> bool:
    # True if the node was originally written as a one-liner: `name { child; }`
    # We detect this by checking that nothing inside the block has a newline.
    if not node.children:
        return False
    if "\n" in node.trailing_trivia:
        return False
    for child in node.children:
        if "\n" in child.leading_trivia or "\n" in child.trailing_trivia:
            return False
        if child.children and not _is_inline_node(child):
            return False
    if "\n" in node.children_trailing_trivia:
        return False
    return True


def _write_node_inline(node: KdlNode) -> str:
    # Renders a node as a compact one-liner with no trivia or indentation.
    if isinstance(node.name, KdlRawString):
        name_str = _val_to_kdl(node.name)
    else:
        name_str = f'"{node.name}"' if " " in node.name else node.name

    parts = [name_str]
    for a in node.args:
        parts.append(_val_to_kdl(a))
    for k, v in node.props.items():
        parts.append(f"{k}={_val_to_kdl(v)}")

    res = " ".join(parts)
    if node.children:
        children_str = " ".join(f"{_write_node_inline(c)};" for c in node.children)
        res += f" {{ {children_str} }}"
    return res


def _write_node(node: KdlNode, indent: int = 0) -> str:
    res = node.leading_trivia

    pad = "    " * indent
    if not node.leading_trivia:
        res += pad
    elif node.leading_trivia.endswith("\n"):
        res += pad

    if isinstance(node.name, KdlRawString):
        name_str = _val_to_kdl(node.name)
    else:
        name_str = f'"{node.name}"' if " " in node.name else node.name

    parts = [name_str]
    for a in node.args:
        parts.append(_val_to_kdl(a))
    for k, v in node.props.items():
        parts.append(f"{k}={_val_to_kdl(v)}")

    res += " ".join(parts)

    if node.children:
        if _is_inline_node(node):
            # Keep the original pre-brace spacing (e.g. `Mod+B      {`) so
            # any column-aligned keybind blocks stay aligned.
            pre_brace = node.trailing_trivia if node.trailing_trivia else " "
            if not pre_brace[0].isspace():
                pre_brace = " " + pre_brace
            children_str = " ".join(f"{_write_node_inline(c)};" for c in node.children)
            res += f"{pre_brace}{{ {children_str} }}"
        else:
            if not res.endswith(" "):
                res += " "
            res += "{"

            tt = node.trailing_trivia
            # trailing_trivia here is the space that was *before* the '{', not after.
            # Re-emitting it after the brace created `cursor { ` (trailing space).
            # Only emit if it has real content like a comment or newline.
            if tt and (not tt.isspace() or "\n" in tt):
                if not tt[0].isspace() and not tt.startswith("\n"):
                    res += " "
                res += tt

            for child in node.children:
                child_str = _write_node(child, indent + 1)
                if (
                    res
                    and not res.endswith("\n")
                    and child_str
                    and not child_str.startswith("\n")
                ):
                    res += "\n"
                res += child_str

            # children_trailing_trivia is usually just indentation whitespace before '}'.
            # We reconstruct that ourselves via pad, so only emit it when it has
            # real content (e.g. a trailing comment).
            ctt = node.children_trailing_trivia
            if ctt and (not ctt.isspace() or "\n" in ctt):
                lines = ctt.splitlines(keepends=True)
                while lines and lines[-1].strip() == "":
                    lines.pop()
                ctt_trimmed = "".join(lines)
                if ctt_trimmed:
                    res += ctt_trimmed
                    if not res.endswith("\n"):
                        res += "\n"
            if not res.endswith("\n"):
                res += "\n"
            res += pad
            res += "}"

        # Don't tack on a '\n' — the next node's leading_trivia starts with one.
        return res

    elif node.trailing_trivia:
        if not node.trailing_trivia[
            0
        ].isspace() and not node.trailing_trivia.startswith("\n"):
            res += " "
        res += node.trailing_trivia

    if not res.endswith("\n"):
        res += "\n"

    return res


def write_kdl(nodes: list[KdlNode]) -> str:
    if not nodes:
        return "// NiriMod configuration\n"

    res = ""
    for n in nodes:
        node_str = _write_node(n)
        if getattr(n, "eof_trivia", None):
            node_str += getattr(n, "eof_trivia")

        if (
            res
            and not res.endswith("\n")
            and node_str
            and not node_str.startswith("\n")
        ):
            res += "\n"
        res += node_str

    if res and not res.endswith("\n"):
        res += "\n"

    return res


def save_niri_config(nodes: list[KdlNode], path: Path | None = None) -> None:
    target = path or NIRI_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(write_kdl(nodes))


# Config mutation helpers


def find_or_create(nodes: list[KdlNode], *path: str) -> KdlNode:
    """Navigate/create nested nodes by path, operating on a list of nodes."""
    current_list = nodes
    node: KdlNode | None = None
    for name in path:
        node = next((n for n in reversed(current_list) if n.name == name), None)
        if node is None:
            node = KdlNode(name=name)
            # give it a blank line so it doesn't get concatenated to
            # whatever node came before it in the serialized output
            node.leading_trivia = "\n"
            current_list.append(node)
        current_list = node.children
    return node  # type: ignore[return-value]


def set_child_arg(parent: KdlNode, child_name: str, value: Any) -> None:
    child = parent.get_child(child_name)
    if child is None:
        cache = getattr(parent, "_removed_children", {})
        if child_name in cache:
            idx, node = cache[child_name]
            parent.children.insert(min(idx, len(parent.children)), node)
            child = node
        else:
            child = KdlNode(name=child_name)
            # Ensure it formats nicely if created from scratch
            child.leading_trivia = "\n"
            parent.children.append(child)
    child.args = [value]
    child.props = {}


def remove_child(parent: KdlNode, child_name: str) -> None:
    existing = parent.get_child(child_name)
    if existing:
        if not hasattr(parent, "_removed_children"):
            parent._removed_children = {}
        parent._removed_children[child_name] = (
            parent.children.index(existing),
            existing,
        )
        parent.children.remove(existing)


def set_node_flag(parent: KdlNode, flag_name: str, enabled: bool) -> None:
    existing = parent.get_child(flag_name)
    if enabled and existing is None:
        cache = getattr(parent, "_removed_children", {})
        if flag_name in cache:
            idx, node = cache[flag_name]
            parent.children.insert(min(idx, len(parent.children)), node)
        else:
            new_node = KdlNode(name=flag_name)
            new_node.leading_trivia = "\n"
            parent.children.insert(0, new_node)
    elif not enabled and existing is not None:
        if not hasattr(parent, "_removed_children"):
            parent._removed_children = {}
        parent._removed_children[flag_name] = (
            parent.children.index(existing),
            existing,
        )
        parent.children.remove(existing)


def get_nodes_section(nodes: list[KdlNode], name: str) -> KdlNode | None:
    return next((n for n in reversed(nodes) if n.name == name), None)


def safe_switch_connect(switch_row, initial_value: bool, callback) -> None:
    switch_row._last_active = initial_value

    def _guarded(r, _):
        new_val = r.get_active()
        if new_val != getattr(r, "_last_active", None):
            r._last_active = new_val
            callback(new_val)

    switch_row.connect("notify::active", _guarded)
