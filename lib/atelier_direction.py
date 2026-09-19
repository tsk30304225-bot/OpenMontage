"""Trace how a bespoke (atelier) composition implements the direction contract.

Atelier compositions are hand-written, so nothing executes visual_timeline
events automatically. They are expected to read contract state through the
direction runtime (``remotion-composer/src/direction``): ``useEventProgress``,
``useElement`` / ``<DirectionElement>``, ``useModelState``, ``useMeasures``,
``useView`` — all keyed by string-literal ids. This module scans the project
source for those calls and maps every timeline event to the code that consumes
it. The trace is derived from the source, not declared by the author, so
"implemented" means a component really reads that event (or the element/model
it changes) at render time.

Runtime-neutral by design: the scan knows ids and call shapes, not Remotion.
HyperFrames workspaces are not scanned yet (reported as unsupported).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lib.visual_direction import is_rail, rail_schedule, replay_model_states

SOURCE_EXTS = {".tsx", ".ts", ".jsx", ".js"}

_Q = r"""["'`]([^"'`]+)["'`]"""
EVENT_RE = re.compile(r"\b(?:useEventProgress|useDirectionEvent)\(\s*" + _Q)
ELEMENT_RE = re.compile(r"\buseElement\(\s*" + _Q + r"\s*,\s*" + _Q)
MODEL_RE = re.compile(r"\buseModelState(?:<[^>()]*>)?\(\s*" + _Q)
MEASURES_RE = re.compile(r"\buseMeasures\(\s*" + _Q)
VIEW_RE = re.compile(r"\buseView\(\s*" + _Q)
DIR_ELEMENT_RE = re.compile(r"<DirectionElement\b([^>]*?)>", re.S)
ATTR_RE = re.compile(r"\b(model|id)\s*=\s*(?:\{\s*)?" + _Q)
PROVIDER_RE = re.compile(r"<DirectionProvider\b[^>]*\btimeline\s*=", re.S)
RUNTIME_IMPORT_RE = re.compile(r"""from\s+["'][^"']*src/direction(?:/[^"']*)?["']""")
LOCAL_FRAME_RE = re.compile(r"\buseCurrentFrame\(")
NAME_RE = re.compile(
    r"(?:function\s+([A-Za-z_]\w*)\s*\(|(?:const|let)\s+([A-Za-z_]\w*)\s*(?::[^=\n]+)?=\s*(?:React\.memo\()?(?:\([^)]*\)|[A-Za-z_]\w*)\s*(?::[^=\n]+)?=>)"
)


def _enclosing_name(text: str, offset: int) -> str:
    name = "<module>"
    for m in NAME_RE.finditer(text, 0, offset):
        name = m.group(1) or m.group(2)
    return name


def scan_project(project_dir: str | Path) -> dict[str, Any]:
    """Collect direction-runtime usage in a bespoke project's source files."""
    root = Path(project_dir)
    refs: dict[str, list[dict[str, Any]]] = {"event": [], "element": [], "model": [], "measures": [], "view": []}
    provider_files: list[str] = []
    runtime_imports: list[str] = []
    local_frame_files: set[str] = set()
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in SOURCE_EXTS or "node_modules" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(root).as_posix()

        def add(kind: str, m: re.Match, **ids: str) -> None:
            line = text.count("\n", 0, m.start()) + 1
            refs[kind].append({"file": rel, "line": line, "component": _enclosing_name(text, m.start()), **ids})

        for m in EVENT_RE.finditer(text):
            add("event", m, event=m.group(1))
        for m in ELEMENT_RE.finditer(text):
            add("element", m, model=m.group(1), element=m.group(2))
        for m in DIR_ELEMENT_RE.finditer(text):
            attrs = {k: v for k, v in ATTR_RE.findall(m.group(1))}
            if "model" in attrs and "id" in attrs:
                add("element", m, model=attrs["model"], element=attrs["id"])
        for m in MODEL_RE.finditer(text):
            add("model", m, model=m.group(1))
        for m in MEASURES_RE.finditer(text):
            add("measures", m, model=m.group(1))
        for m in VIEW_RE.finditer(text):
            add("view", m, model=m.group(1))
        if PROVIDER_RE.search(text):
            provider_files.append(rel)
        if RUNTIME_IMPORT_RE.search(text):
            runtime_imports.append(rel)
        if LOCAL_FRAME_RE.search(text):
            local_frame_files.add(rel)
    return {
        "refs": refs,
        "provider_files": provider_files,
        "runtime_imports": runtime_imports,
        "local_frame_files": sorted(local_frame_files),
    }


def _ref(r: dict[str, Any], via: str) -> str:
    return f"{r['file']}:{r['line']} {r['component']} ({via})"


def _target_state(model: dict[str, Any], state: dict[str, Any], target: str) -> Any:
    if is_rail(model):
        row = rail_schedule(state)["items"].get(target)
        if row is None:
            return {"measures": state.get("measures"), "axis": state.get("axis"), "deadline": state.get("deadline")}
        return {k: row.get(k) for k in ("present", "planned_start", "actual_start", "actual_end", "wait")}
    el = state["elements"].get(target)
    if el is None:
        return {"view": state.get("view"), "measures": state.get("measures")}
    return {k: el.get(k) for k in ("visible", "attrs", "from", "to")}


def build_trace(timeline: dict[str, Any], project_dir: str | Path) -> dict[str, Any]:
    """Map every timeline event to the bespoke code that implements it.

    Hard failures: no <DirectionProvider timeline=…> in the project, no import
    of the direction runtime, an event nothing reads, or a reference to an
    event/model/element the timeline does not contain (the composition and
    the contract disagree).
    """
    scan = scan_project(project_dir)
    refs = scan["refs"]
    models = {m["id"]: m for m in timeline.get("models") or []}
    events = {e["id"]: e for e in timeline.get("events") or []}
    hard: list[str] = []
    warnings: list[str] = []

    if not scan["provider_files"]:
        hard.append("no <DirectionProvider timeline={…}> in the project: bespoke scenes cannot read contract time or state")
    if not scan["runtime_imports"]:
        hard.append("the project never imports the direction runtime (remotion-composer/src/direction)")

    elements_known: dict[str, set[str]] = {}
    for mid, model in models.items():
        if is_rail(model):
            continue
        ids = {str(e["id"]) for e in (model.get("initial_state") or {}).get("elements") or []}
        ids |= {e["target"] for e in events.values() if e["model_id"] == mid}
        elements_known[mid] = ids
    for r in refs["event"]:
        if r["event"] not in events:
            hard.append(f"{_ref(r, 'useEventProgress')} reads event {r['event']!r} that is not in visual_timeline")
    for kind in ("element", "model", "measures", "view"):
        for r in refs[kind]:
            if r["model"] not in models:
                hard.append(f"{_ref(r, kind)} reads model {r['model']!r} that is not in visual_timeline")
            elif kind == "element" and r["element"] not in elements_known.get(r["model"], set()):
                hard.append(f"{_ref(r, 'element')} reads element {r['element']!r} that model {r['model']!r} never has")

    before_after: dict[str, tuple[Any, Any]] = {}
    for mid, model in models.items():
        prev = None
        for ev, state in replay_model_states(timeline, mid):
            if ev is not None:
                before_after[ev["id"]] = (_target_state(model, prev, ev["target"]), _target_state(model, state, ev["target"]))
            prev = state

    entries = []
    for ev in sorted(events.values(), key=lambda e: e["time_seconds"]):
        mid, target, op = ev["model_id"], ev["target"], ev["operation"]
        found = [_ref(r, "useEventProgress") for r in refs["event"] if r["event"] == ev["id"]]
        found += [_ref(r, "useModelState") for r in refs["model"] if r["model"] == mid]
        if op == "MEASURE":
            found += [_ref(r, "useMeasures") for r in refs["measures"] if r["model"] == mid]
        elif op == "SHIFT" and target == "view":
            found += [_ref(r, "useView") for r in refs["view"] if r["model"] == mid]
        else:
            touched = {target} | {str(p) for p in (ev.get("params") or {}).get("path") or []}
            found += [_ref(r, "element") for r in refs["element"] if r["model"] == mid and r["element"] in touched]
        before, after = before_after.get(ev["id"], (None, None))
        entry = {
            "event_id": ev["id"],
            "beat_id": ev.get("beat_id"),
            "scene_id": ev.get("scene_id"),
            "visual_model_id": mid,
            "operation": op,
            "target": target,
            "resolved_time": ev["time_seconds"],
            "implemented": bool(found),
            "implementation_reference": found,
            "state_before": before,
            "state_after": after,
        }
        entries.append(entry)
        if not found:
            hard.append(
                f"{ev['id']} ({op} {target} on {mid} at {ev['time_seconds']}s) is not implemented: no useEventProgress "
                f"for it and no component reads {'the model' if op == 'MEASURE' else repr(target)} through the direction runtime"
            )

    persistent = {}
    for mid in models:
        scenes = sorted({e["scene_id"] for e in events.values() if e["model_id"] == mid})
        persistent[mid] = {"scenes": scenes, "spans_scenes": len(scenes) > 1,
                           "state_source": "direction runtime (absolute time, shared across scenes)"}
    implementers = {r["file"] for rs in refs.values() for r in rs}
    for f in sorted(implementers & set(scan["local_frame_files"])):
        warnings.append(
            f"{f} implements direction events and also calls useCurrentFrame(): make sure event timing comes from the "
            "direction hooks, not from Sequence-local frames"
        )
    return {
        "supported_runtime": "remotion",
        "provider_files": scan["provider_files"],
        "events": entries,
        "implemented": sum(1 for e in entries if e["implemented"]),
        "total": len(entries),
        "persistent_models": persistent,
        "hard_failures": hard,
        "warnings": warnings,
    }
