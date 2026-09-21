"""Scene runtime override v1: one main runtime per scene.

The project keeps its default ``render_runtime`` (the master assembly). A scene
may override the runtime of its main picture:

- ``inherit``     — use the project default (same as leaving it out)
- ``remotion``    — structured graphics in the Remotion assembly
- ``hyperframes`` — a HyperFrames/GSAP clip rendered per scene, then placed in
                    the Remotion assembly as an ordinary video cut
- ``footage``     — a real video/still cut

This is not a layer compositor: a scene has one main runtime; the existing
caption/audio/overlay paths still apply on top of the assembly.

HyperFrames scenes keep the visual-direction contract. Before the clip renders,
``write_bridge`` writes ``om-direction.js`` into the scene workspace with the
scene's visual_timeline events in scene-local seconds, and ``trace_workspace``
requires that every event is placed by the authored GSAP code
(``OM.at("<event id>")`` or ``data-om-event="<event id>"``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

SCENE_RUNTIMES = ("inherit", "remotion", "hyperframes", "footage")
COMPOSITION_RUNTIMES = ("remotion", "hyperframes")  # need approval at proposal

BRIDGE_JS = "om-direction.js"
BRIDGE_JSON = "om-direction.json"
_REF_RE = re.compile(r"""OM\.at\(\s*["']([^"']+)["']\s*\)|data-om-event\s*=\s*["']([^"']+)["']""")
_SCRIPT_RE = re.compile(r"""<script[^>]+src\s*=\s*["'](?:\./)?om-direction\.js["']""", re.I)
_DURATION_RE = re.compile(r"""data-composition-id\s*=\s*["']root["'][^>]*?data-duration\s*=\s*["']([\d.]+)["']"""
                          r"""|data-duration\s*=\s*["']([\d.]+)["'][^>]*?data-composition-id\s*=\s*["']root["']""", re.S)


# ---------------------------------------------------------------- resolution

def approved_runtimes(edit_or_plan: dict[str, Any], project_runtime: Optional[str]) -> set[str]:
    """Runtimes approved at proposal. Default: only the project runtime."""
    approved = edit_or_plan.get("approved_runtimes")
    out = {str(r).lower() for r in approved} if approved else set()
    if project_runtime:
        out.add(project_runtime.lower())
    return out


def resolve_scene_runtimes(
    scenes: Iterable[dict[str, Any]],
    project_runtime: str,
    approved: Iterable[str],
    unavailable: Iterable[str] = (),
) -> dict[str, Any]:
    """Compact per-scene runtime list for downstream stages.

    ``scenes`` are scene_plan scenes (``id``, optional ``runtime`` /
    ``runtime_reason``). A requested composition runtime that was not approved,
    or is unavailable on this machine, falls back to the project default with a
    warning — never silently.
    """
    approved_set = {a.lower() for a in approved}
    unavailable_set = {u.lower() for u in unavailable}
    out: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for scene in scenes:
        sid = scene.get("id") or scene.get("scene_id")
        requested = (scene.get("runtime") or "inherit").lower()
        reason = scene.get("runtime_reason") or ""
        runtime = project_runtime if requested == "inherit" else requested
        if requested not in SCENE_RUNTIMES:
            warnings.append({"code": "UNKNOWN_SCENE_RUNTIME", "scene_id": sid,
                             "message": f"scene {sid}: unknown runtime {requested!r}; using {project_runtime}"})
            runtime = project_runtime
        elif runtime in COMPOSITION_RUNTIMES and runtime not in approved_set:
            warnings.append({"code": "RUNTIME_NOT_APPROVED", "scene_id": sid, "runtime": runtime,
                             "message": f"scene {sid} fits {runtime} ({reason or 'no reason given'}) but {runtime} "
                                        f"was not approved at proposal; using {project_runtime}. Present it to "
                                        f"the user or record why it is excluded."})
            runtime = project_runtime
        elif runtime in unavailable_set:
            warnings.append({"code": "RUNTIME_UNAVAILABLE", "scene_id": sid, "runtime": runtime,
                             "message": f"scene {sid}: {runtime} is not available on this machine; using "
                                        f"{project_runtime}"})
            runtime = project_runtime
        row = {"scene_id": sid, "runtime": runtime, "reason": reason}
        if requested not in ("inherit", runtime):
            row["requested"] = requested
        out.append(row)
    return {"project_runtime": project_runtime, "scenes": out, "warnings": warnings}


# ---------------------------------------------------------------- hyperframes bridge

def scene_events(timeline: Optional[dict[str, Any]], cut: dict[str, Any]) -> list[dict[str, Any]]:
    """visual_timeline events executed by this scene cut, in scene-local seconds."""
    if not timeline:
        return []
    start, end = float(cut["in_seconds"]), float(cut["out_seconds"])
    sid = cut.get("scene_id")
    out = []
    for ev in timeline.get("events") or []:
        t = float(ev["time_seconds"])
        mine = ev.get("scene_id") == sid if sid else start - 1e-3 <= t < end
        if not mine:
            continue
        out.append({
            "id": ev["id"],
            "t": round(max(0.0, t - start), 3),
            "duration": float(ev.get("duration_seconds") or 0.0),
            "operation": ev.get("operation"),
            "target": ev.get("target"),
            "model_id": ev.get("model_id"),
            "params": ev.get("params") or {},
            "anchor": (ev.get("anchor") or {}).get("text"),
        })
    return sorted(out, key=lambda e: (e["t"], e["id"]))


def write_bridge(workspace: Path, cut: dict[str, Any], events: list[dict[str, Any]]) -> Path:
    """Write the generated ``om-direction.js`` (and .json) into the scene workspace."""
    data = {
        "scene_id": cut.get("scene_id"),
        "cut_id": cut.get("id"),
        "duration": round(float(cut["out_seconds"]) - float(cut["in_seconds"]), 3),
        "events": events,
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    (workspace / BRIDGE_JSON).write_text(payload, encoding="utf-8")
    js = (
        "// Generated by OpenMontage video_compose from visual_timeline. Do not edit.\n"
        "// Place every event with OM.at(\"<event id>\") (scene-local seconds) on your GSAP timeline.\n"
        f"window.OM_DIRECTION = {payload};\n"
        "window.OM = {\n"
        "  direction: window.OM_DIRECTION,\n"
        "  at: function (id) {\n"
        "    var ev = window.OM_DIRECTION.events.find(function (e) { return e.id === id; });\n"
        "    if (!ev) { throw new Error('OpenMontage: unknown direction event ' + id); }\n"
        "    return ev.t;\n"
        "  },\n"
        "  event: function (id) {\n"
        "    return window.OM_DIRECTION.events.find(function (e) { return e.id === id; }) || null;\n"
        "  }\n"
        "};\n"
    )
    path = workspace / BRIDGE_JS
    path.write_text(js, encoding="utf-8")
    return path


def root_duration(workspace: Path) -> Optional[float]:
    entry = workspace / "index.html"
    if not entry.is_file():
        return None
    m = _DURATION_RE.search(entry.read_text(encoding="utf-8", errors="ignore"))
    return float(m.group(1) or m.group(2)) if m else None


def trace_workspace(workspace: Path, events: list[dict[str, Any]], expected_duration: Optional[float] = None
                    ) -> dict[str, Any]:
    """Map every scene event to the authored HyperFrames code that places it."""
    hard: list[str] = []
    refs: dict[str, list[str]] = {}
    entry = workspace / "index.html"
    if not entry.is_file():
        return {"hard_failures": [f"no index.html in {workspace}"], "events": [], "implemented": 0}
    html = entry.read_text(encoding="utf-8", errors="ignore")
    if events and not _SCRIPT_RE.search(html):
        hard.append(f'{entry.name} does not load {BRIDGE_JS}: add <script src="{BRIDGE_JS}"></script> before '
                    f"your timeline script")
    for path in sorted(workspace.rglob("*")):
        if (path.suffix.lower() not in (".html", ".js") or path.name == BRIDGE_JS
                or "node_modules" in path.parts or "renders" in path.parts):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for m in _REF_RE.finditer(line):
                eid = m.group(1) or m.group(2)
                refs.setdefault(eid, []).append(f"{path.relative_to(workspace).as_posix()}:{lineno}")
    known = {e["id"] for e in events}
    rows = []
    for ev in events:
        where = refs.get(ev["id"], [])
        rows.append({"event_id": ev["id"], "t": ev["t"], "implemented": bool(where), "where": where})
        if not where:
            hard.append(f"{ev['id']} ({ev['operation']} {ev['target']}) at scene time {ev['t']}s is not placed in "
                        f"the HyperFrames code (use OM.at(\"{ev['id']}\"))")
    for eid in sorted(set(refs) - known):
        hard.append(f"code references direction event {eid!r} that this scene does not have ({refs[eid][0]})")
    if expected_duration is not None:
        dur = root_duration(workspace)
        if dur is None:
            hard.append("root composition has no data-duration")
        elif abs(dur - expected_duration) > 0.05:
            hard.append(f"root data-duration {dur}s does not match the scene cut ({expected_duration:.3f}s)")
    return {"hard_failures": hard, "events": rows, "implemented": sum(r["implemented"] for r in rows)}


def hyperframes_cuts(edit_decisions: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in edit_decisions.get("cuts") or [] if (c.get("runtime") or "").lower() == "hyperframes"]


def without_scene_events(timeline: Optional[dict[str, Any]], cuts: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The timeline minus the events that HyperFrames scene cuts execute."""
    if not timeline or not cuts:
        return timeline
    owned = {e["id"] for c in cuts for e in scene_events(timeline, c)}
    return {**timeline, "events": [e for e in timeline.get("events") or [] if e["id"] not in owned]}


def planned_runtime_gaps(scenes: Iterable[dict[str, Any]], cuts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soft warning: scenes planned as HyperFrames whose cuts render without it."""
    cuts = list(cuts)
    out: list[dict[str, Any]] = []
    for scene in scenes:
        if (scene.get("runtime") or "").lower() != "hyperframes":
            continue
        sid = scene.get("id") or scene.get("scene_id")
        mine = [c for c in cuts if c.get("scene_id") == sid]
        if not mine and scene.get("start_seconds") is not None and scene.get("end_seconds") is not None:
            lo, hi = float(scene["start_seconds"]), float(scene["end_seconds"])
            mine = [c for c in cuts if lo - 1e-3 <= float(c.get("in_seconds", -1)) < hi]
        if not any((c.get("runtime") or "").lower() == "hyperframes" for c in mine):
            out.append({"code": "PLANNED_RUNTIME_DROPPED", "scene_id": sid, "runtime": "hyperframes",
                        "message": f"scene {sid} was planned with runtime 'hyperframes' but its cuts render without it; "
                                   f"record the decision in decision_log or restore the HyperFrames scene"})
    return out
