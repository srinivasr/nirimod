"""Rect helpers for keeping an output layout non-overlapping."""

from __future__ import annotations


def v_overlap(a: dict, b: dict) -> bool:
    return not (a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def h_overlap(a: dict, b: dict) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"])


def flush_links(
    rects: list[dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    right: dict[str, list[str]] = {r["name"]: [] for r in rects}
    bottom: dict[str, list[str]] = {r["name"]: [] for r in rects}
    for a in rects:
        for b in rects:
            if a is b:
                continue
            if v_overlap(a, b) and b["x"] == a["x"] + a["w"]:
                right[a["name"]].append(b["name"])
            if h_overlap(a, b) and b["y"] == a["y"] + a["h"]:
                bottom[a["name"]].append(b["name"])
    return right, bottom


def reachable(links: dict[str, list[str]], start: str) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        for nxt in links.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen - {start}


def cascade_positions(
    rects: list[dict],
    deltas: dict[str, tuple[int, int]],
    links: tuple[dict[str, list[str]], dict[str, list[str]]] | None = None,
) -> list[str]:
    if not deltas:
        return []
    right, bottom = links if links is not None else flush_links(rects)
    dx: dict[str, int] = {}
    dy: dict[str, int] = {}
    for name, (dw, dh) in deltas.items():
        for other in reachable(right, name):
            dx[other] = dx.get(other, 0) + dw
        for other in reachable(bottom, name):
            dy[other] = dy.get(other, 0) + dh
    before = {r["name"]: (r["x"], r["y"]) for r in rects}
    for r in rects:
        r["x"] += dx.get(r["name"], 0)
        r["y"] += dy.get(r["name"], 0)

    for _ in range(len(rects) + 2):
        snapped = False
        for a in rects:
            for other_name in right.get(a["name"], ()):
                b = next((r for r in rects if r["name"] == other_name), None)
                if b is None or not v_overlap(a, b):
                    continue
                target = a["x"] + a["w"]
                if b["x"] != target and abs(b["x"] - target) <= 1:
                    b["x"] = target
                    snapped = True
            for other_name in bottom.get(a["name"], ()):
                b = next((r for r in rects if r["name"] == other_name), None)
                if b is None or not h_overlap(a, b):
                    continue
                target = a["y"] + a["h"]
                if b["y"] != target and abs(b["y"] - target) <= 1:
                    b["y"] = target
                    snapped = True
        if not snapped:
            break
    return [r["name"] for r in rects if before[r["name"]] != (r["x"], r["y"])]


def overlaps(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def separate_overlaps(
    rects: list[dict], order: dict[str, int]
) -> list[tuple[str, int, int, str]]:
    moved: dict[str, tuple[int, int, str]] = {}
    for _ in range(len(rects) * len(rects) + 8):
        pair = None
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                if overlaps(rects[i], rects[j]):
                    pair = (rects[i], rects[j])
                    break
            if pair:
                break
        if pair is None:
            break
        first, second = pair
        if order.get(second["name"], 0) >= order.get(first["name"], 0):
            mover, other = second, first
        else:
            mover, other = first, second

        candidates = [
            (other["x"] + other["w"], mover["y"]),
            (other["x"] - mover["w"], mover["y"]),
            (mover["x"], other["y"] + other["h"]),
            (mover["x"], other["y"] - mover["h"]),
        ]

        clear = []
        for nx, ny in candidates:
            probe = dict(mover, x=nx, y=ny)
            if not any(overlaps(probe, r) for r in rects if r is not mover):
                clear.append((abs(nx - mover["x"]) + abs(ny - mover["y"]), nx, ny))

        if clear:
            _, mover["x"], mover["y"] = min(clear)
        else:
            _, mover["x"], mover["y"] = min(
                (abs(nx - mover["x"]) + abs(ny - mover["y"]), nx, ny)
                for nx, ny in candidates
            )

        moved[mover["name"]] = (mover["x"], mover["y"], other["name"])
    return [(n, x, y, o) for n, (x, y, o) in moved.items()]
