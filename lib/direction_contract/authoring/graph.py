"""Internal execution graph (guide N8): computed to check references and cycles, never written to 40."""

from __future__ import annotations

from typing import Any


def scene_edges(scene: dict[str, Any]) -> list[tuple[str, str]]:
    """BEAT->ACTION, STATE->ACTION (from), ACTION->STATE (to), EVENT->ACTION, plus action ordering dependencies."""
    edges: list[tuple[str, str]] = []
    for b in scene.get("beats") or []:
        edges += [(b["beat_id"], a) for a in b.get("linked_actions") or []]
    for a in scene.get("actions") or []:
        aid = a["action_id"]
        edges.append((a["from_state_id"], aid))
        edges.append((aid, a["to_state_id"]))
        dep = a.get("dependency") or {}
        edges += [(d["action"], aid) for d in dep.get("after") or []]
        edges += [(aid, other) for other in dep.get("before") or []]
    for e in scene.get("events") or []:
        edges += [(e["event_id"], a) for a in e.get("actions") or []]
    return edges


def find_cycle(edges: list[tuple[str, str]]) -> list[str] | None:
    """A cycle as a node path (first == last), or None. Deterministic: nodes in first-seen order."""
    graph: dict[str, list[str]] = {}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        graph.setdefault(dst, [])
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None
