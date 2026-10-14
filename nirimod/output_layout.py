"""Rect helpers for keeping an output layout non-overlapping."""

from __future__ import annotations

import math


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


def touches(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["w"] < b["x"]
        or b["x"] + b["w"] < a["x"]
        or a["y"] + a["h"] < b["y"]
        or b["y"] + b["h"] < a["y"]
    )


def separation(a: dict, b: dict) -> float:
    dx = max(b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"]), 0)
    dy = max(b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"]), 0)
    return math.hypot(dx, dy)


def contact_shifts(a: dict, b: dict) -> list[tuple[int, int]]:
    shifts = [
        (b["x"] - a["w"] - a["x"], b["y"] - a["y"]),
        (b["x"] + b["w"] - a["x"], b["y"] - a["y"]),
        (b["x"] - a["x"], b["y"] - a["h"] - a["y"]),
        (b["x"] - a["x"], b["y"] + b["h"] - a["y"]),
        (b["x"] - a["w"] - a["x"], b["y"] - a["h"] - a["y"]),
        (b["x"] + b["w"] - a["x"], b["y"] - a["h"] - a["y"]),
        (b["x"] - a["w"] - a["x"], b["y"] + b["h"] - a["y"]),
        (b["x"] + b["w"] - a["x"], b["y"] + b["h"] - a["y"]),
    ]
    if h_overlap(a, b):
        shifts.append((0, b["y"] - (a["y"] + a["h"])))
        shifts.append((0, b["y"] + b["h"] - a["y"]))
    if v_overlap(a, b):
        shifts.append((b["x"] - (a["x"] + a["w"]), 0))
        shifts.append((b["x"] + b["w"] - a["x"], 0))
    return shifts


def adjacency_graph(rects: list[dict]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {r["name"]: set() for r in rects}
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            if touches(a, b):
                graph[a["name"]].add(b["name"])
                graph[b["name"]].add(a["name"])
    return graph


def adjacency_clusters(rects: list[dict]) -> list[list[dict]]:
    graph = adjacency_graph(rects)
    by_name = {r["name"]: r for r in rects}
    clusters: list[list[dict]] = []
    seen: set[str] = set()
    for start in rects:
        if start["name"] in seen:
            continue
        cluster = [start]
        seen.add(start["name"])
        stack = [start]
        while stack:
            for other in graph[stack.pop()["name"]]:
                if other in seen:
                    continue
                seen.add(other)
                cluster.append(by_name[other])
                stack.append(by_name[other])
        clusters.append(cluster)
    return clusters


def shift_is_clear(cluster: list[dict], rects: list[dict], dx: int, dy: int) -> bool:
    members = {id(r) for r in cluster}
    for r in cluster:
        moved = {**r, "x": r["x"] + dx, "y": r["y"] + dy}
        for other in rects:
            if id(other) in members:
                continue
            if overlaps(moved, other):
                return False
    return True


def pack_axis(rects: list[dict], axis: str) -> bool:
    size = "w" if axis == "x" else "h"
    perpendicular = v_overlap if axis == "x" else h_overlap
    changed = False
    for r in sorted(rects, key=lambda rect: rect[axis]):
        edges = [
            o[axis] + o[size]
            for o in rects
            if o is not r and perpendicular(o, r) and o[axis] + o[size] <= r[axis]
        ]
        if not edges:
            continue
        anchor = max(edges)
        if r[axis] - anchor > 1:
            r[axis] = anchor
            changed = True
    return changed


def pack_rects(rects: list[dict]) -> list[str]:
    before = {r["name"]: (r["x"], r["y"]) for r in rects}
    for _ in range(len(rects) + 2):
        if not (pack_axis(rects, "x") | pack_axis(rects, "y")):
            break
    return [r["name"] for r in rects if before[r["name"]] != (r["x"], r["y"])]


def layout_is_sound(rects: list[dict]) -> bool:
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            if overlaps(a, b):
                return False
    return len(adjacency_clusters(rects)) == 1


def attach_stray_clusters(rects: list[dict]) -> list[str]:
    clusters = adjacency_clusters(rects)
    if len(clusters) < 2:
        return []

    primary = max(clusters, key=len)
    moved: list[str] = []
    for cluster in clusters:
        if cluster is primary:
            continue
        best: tuple[int, int, int] | None = None
        fallback: tuple[int, int, int] | None = None
        for a in cluster:
            target = min(primary, key=lambda b: separation(a, b))
            for dx, dy in contact_shifts(a, target):
                cost = abs(dx) + abs(dy)
                if fallback is None or cost < fallback[0]:
                    fallback = (cost, dx, dy)
                if shift_is_clear(cluster, rects, dx, dy) and (
                    best is None or cost < best[0]
                ):
                    best = (cost, dx, dy)
        if best is None:
            best = fallback
        if best is None or best[0] == 0:
            primary.extend(cluster)
            continue
        for r in cluster:
            r["x"] += best[1]
            r["y"] += best[2]
        primary.extend(cluster)
        moved.extend(r["name"] for r in cluster)
    return moved
