"""Execution binding (43): where each locked contract id is realized, per production scene × runtime layer (D16).

``bind`` never copies ids as proof. For every runtime_stack layer that
declares a locked id (explicitly or by running the action that implies it,
D10) it finds the production scenes the id lands in and produces one binding
per (production scene, layer):

- CODE: the layer has a raw trace (``traces[layer]``: atelier source scan,
  HyperFrames OM.at scan) and every timeline operation of the consumed ids in
  that scene is implemented there;
- ASSET: a source layer (factual_source, base_visual, generated_media) and an
  edit_decisions cut of that scene places the object's source (SOURCE_IDENTITY_V1);
- otherwise ``not_executed_by_engine``.

It also records ``scene_windows``: the program time of every production scene
as rendered (primary cuts in order, like video_compose), the scene end that
ACTIVE_AT_SCENE_END, LAST_FRAME and minimum_hold use.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from lib.direction_contract.authority import canonical_json_sha256, source_identical
from lib.direction_contract.contract_v12 import ASSET_LAYERS, LOCKED, Contract
from schemas.direction_contract import validate as validate_schema

_REF_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+) (?P<symbol>\S+) \((?P<via>[^)]+)\)$")
_EVENT_RE = re.compile(r"\bev-[\w.-]+")
_VIA = {"element": "useElement", "model": "useModelState", "measures": "useMeasures", "view": "useView"}


def program_windows(edit_decisions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Production scene -> {start, end, cuts}: primary cuts laid end to end, each (out - in) / speed long."""
    out: dict[str, dict[str, Any]] = {}
    cursor = 0.0
    for cut in edit_decisions.get("cuts") or []:
        if (cut.get("layer") or "primary") != "primary":
            continue
        try:
            duration = max(0.0, (float(cut["out_seconds"]) - float(cut["in_seconds"])) / max(float(cut.get("speed", 1.0)), 0.1))
        except (KeyError, TypeError, ValueError):
            continue
        start, end = cursor, cursor + duration
        cursor = end
        sid = cut.get("scene_id")
        if not sid:
            continue
        w = out.setdefault(sid, {"start": start, "end": end, "cuts": []})
        w["start"], w["end"] = min(w["start"], start), max(w["end"], end)
        w["cuts"].append({"cut": cut, "start": round(start, 6), "end": round(end, 6)})
    return out


def scene_runtime(edit_decisions: dict[str, Any], cut: dict[str, Any] | None) -> str:
    override = (cut or {}).get("runtime")
    if override in ("hyperframes", "footage"):
        return override
    base = edit_decisions.get("render_runtime") or "remotion"
    if base == "hyperframes":
        return "hyperframes"
    return "remotion_atelier" if edit_decisions.get("composition_mode") == "atelier" else "remotion_templated"


def _family(runtime: str) -> str:
    return "remotion" if runtime.startswith("remotion") else runtime


def _code_refs(entry: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for text in entry.get("implementation_reference") or []:
        m = _REF_RE.match(str(text))
        if not m:
            continue
        via = _VIA.get(m["via"], m["via"])
        refs.append({"file": m["file"], "line": int(m["line"]), "symbol": m["symbol"], "via": via})
    return refs


def _trace(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict) and "trace" in raw:
        return raw["trace"], raw.get("source")
    return raw or {}, None


def _overlap(span: tuple[float, float] | None, windows: dict[str, dict[str, Any]]) -> list[str]:
    if span is None:
        return []
    lo, hi = span
    return [sid for sid, w in windows.items() if min(hi, w["end"]) - max(lo, w["start"]) > 1e-6]


def _at(t: float, windows: dict[str, dict[str, Any]]) -> list[str]:
    return [sid for sid, w in windows.items() if w["start"] - 1e-6 <= t < w["end"] - 1e-6][:1]


def bind(contract: Contract, timeline: dict[str, Any], edit_decisions: dict[str, Any], traces: dict[str, Any]) -> dict[str, Any]:
    """Generate 43 from the compiled timeline, the edit decisions and one raw trace per traced layer."""
    contract.check_ref("visual_timeline", timeline.get("contract"))
    windows = program_windows(edit_decisions)
    events = timeline.get("events") or []
    resolved = {r["anchor_id"]: r for r in (timeline.get("anchor_resolution") or {}).get("resolved_anchors") or []}
    event_ids = {e["id"] for e in events}

    traced = {layer: _trace(raw) for layer, raw in (traces or {}).items()}
    entry_of: dict[str, dict[str, dict[str, Any]]] = {
        layer: {e["event_id"]: e for e in t.get("events") or []} for layer, (t, _) in traced.items()}
    # failures about one event (implemented or not, known to the timeline or not) count against that event only;
    # the rest (no DirectionProvider, no runtime import) make every CODE binding of the layer unbound
    global_failures = {
        layer: [h for h in t.get("hard_failures") or [] if not _EVENT_RE.search(h) and not any(eid in h for eid in event_ids)]
        for layer, (t, _) in traced.items()}

    def span_of(start_anchor: str | None, end_anchor: str | None) -> tuple[float, float] | None:
        a, b = resolved.get(start_anchor or ""), resolved.get(end_anchor or "")
        if not a or not b:
            return None
        return a["start_time"], b["end_time"]

    rows: dict[tuple[str, str], dict[str, Any]] = {}

    def row(psid: str, layer: str, scene_id: str) -> dict[str, Any]:
        key = (psid, layer)
        if key not in rows:
            rows[key] = {"scene_id": scene_id, "production_scene_id": psid, "layer": layer,
                         "consumes": {"action_ids": [], "event_ids": [], "state_ids": []}}
        return rows[key]

    for sid, scene in contract.scenes.items():
        if scene.get("importance") != LOCKED:
            continue
        span = scene.get("narration_span") or {}
        scene_prods = _overlap(span_of(span.get("start_anchor"), span.get("end_anchor")), windows)
        actions = {a["action_id"]: a for a in scene.get("actions") or []}
        action_prods: dict[str, list[str]] = {}
        for aid, a in actions.items():
            # where its operations run; an action with none belongs where its start anchor is spoken
            prods = sorted({e["scene_id"] for e in events if e.get("action_id") == aid})
            if not prods:
                start = resolved.get(a.get("start_anchor") or "")
                prods = _at(start["start_time"], windows) if start else []
            action_prods[aid] = prods
        first_action = next(iter(actions), None)
        for layer, ids in (contract.layer_consumes.get(sid) or {}).items():
            for cid in ids:
                kind = contract.kind(cid)
                if kind == "action":
                    prods = action_prods.get(cid, [])
                elif kind == "event":
                    prods = sorted({e["scene_id"] for e in events if e.get("contract_event_id") == cid})
                    prods = prods or sorted({p for a in (contract.obj(cid) or {}).get("actions") or [] for p in action_prods.get(a, [])})
                elif contract.is_model_state(cid):
                    prods = sorted({e["scene_id"] for e in events if e.get("state_after_id") == cid})
                    entered_by = (contract.obj(cid) or {}).get("entered_by")
                    prods = prods or action_prods.get(entered_by or "", []) or action_prods.get(first_action or "", [])
                else:  # a state outside every model: on screen while the scene's narration plays
                    prods = scene_prods
                for psid in prods or ["unresolved"]:
                    row(psid, layer, sid)["consumes"][f"{kind}_ids"].append(cid)

    bindings: list[dict[str, Any]] = []
    for (psid, layer), r in sorted(rows.items()):
        sid = r["scene_id"]
        consumes = {k: sorted(set(v)) for k, v in r["consumes"].items() if v}
        win = windows.get(psid)
        first_cut = (win or {}).get("cuts", [{}])[0].get("cut") if win else None
        runtime = scene_runtime(edit_decisions, first_cut)
        declared = contract.layer_runtime(sid, layer)
        b: dict[str, Any] = {"binding_id": f"{psid}/{layer}", "production_scene_id": psid, "layer": layer,
                             "runtime": runtime, "consumes": consumes}
        if psid == "unresolved" or win is None:
            b.update(status="unbound", detail=f"no rendered production scene carries {sorted(sum(consumes.values(), []))}")
        elif declared == "none":
            b.update(status="not_executed_by_engine", detail=f"layer {layer} declares runtime none")
        elif _family(runtime) != declared and not (declared == "footage" and runtime == "footage"):
            b.update(status="unbound", detail=f"layer {layer} declares {declared} but {psid} renders as {runtime}")
        elif layer in traced:
            trace, source = traced[layer]
            consumed_actions = consumes.get("action_ids", [])
            ops = [e for e in events if e.get("scene_id") == psid and (
                e.get("action_id") in consumed_actions or e.get("state_after_id") in consumes.get("state_ids", [])
                or e.get("contract_event_id") in consumes.get("event_ids", []))]
            missing_actions = [a for a in consumed_actions if not any(e.get("action_id") == a for e in ops)]
            entries = [entry_of[layer].get(e["id"]) or {} for e in ops]
            unimplemented = [e["id"] for e, t in zip(ops, entries) if not t.get("implemented")]
            refs = [ref for t in entries for ref in _code_refs(t)]
            if ops:
                b["timeline_event_ids"] = [e["id"] for e in ops]
                b["start_seconds"] = round(min(e["time_seconds"] for e in ops), 6)
                b["end_seconds"] = round(max(e["time_seconds"] + e["duration_seconds"] for e in ops), 6)
            if refs:
                symbols = Counter(r["symbol"] for r in refs)
                b["locator"] = {"kind": "CODE", "implementation_path": source or (trace.get("provider_files") or ["."])[0],
                                "component_or_block": symbols.most_common(1)[0][0], "refs": refs}
            problems = []
            if missing_actions:
                problems.append(f"no timeline operation of {missing_actions} in {psid}")
            if unimplemented:
                problems.append(f"operations not implemented in code: {unimplemented}")
            if global_failures.get(layer):
                problems.append("; ".join(global_failures[layer]))
            if not ops and not missing_actions:
                problems.append(f"no timeline operation realizes {sorted(sum(consumes.values(), []))} in {psid}")
            b["status"] = "unbound" if problems or not refs else "bound"
            if problems:
                b["detail"] = "; ".join(problems)
        elif layer in ASSET_LAYERS:
            cuts = win["cuts"]
            needs: list[tuple[str, str]] = []  # (state id, source asset)
            other: list[str] = []
            for st in consumes.get("state_ids", []):
                if contract.is_model_state(st):
                    other.append(st)
                    continue
                for oid in (contract.obj(st) or {}).get("visible_objects") or []:
                    asset = (contract.obj(oid) or {}).get("source_asset")
                    if asset:
                        needs.append((st, asset))
            other += consumes.get("action_ids", [])
            match = None
            for c in cuts:
                if needs and all(source_identical(asset, str(c["cut"].get("source") or "")) for _, asset in needs):
                    match = c
                    break
            shown = match or next((c for c in cuts if c["cut"].get("source")), cuts[0])
            cut = shown["cut"]
            b["locator"] = {"kind": "ASSET", "cut_id": str(cut.get("id")), "source_asset_ref": str(cut.get("source") or ""),
                            "via": "edit_decisions.cut", "in_seconds": shown["start"], "out_seconds": shown["end"]}
            b["start_seconds"], b["end_seconds"] = shown["start"], shown["end"]
            if other:
                b.update(status="unbound", detail=f"an asset layer cannot realize model actions/states {other}")
            elif needs and match is None:
                b.update(status="unbound", detail=f"no cut of {psid} places {sorted({a for _, a in needs})} (cut {cut.get('id')} shows {cut.get('source')!r})")
            elif not needs and not cut.get("source"):
                b.update(status="unbound", detail=f"no cut of {psid} places a source asset")
            else:
                b["status"] = "bound"
        else:
            b.update(status="not_executed_by_engine", detail=f"layer {layer} has no trace and is not a source-asset layer")
        bindings.append(b)

    event_rows = []
    for e in events:
        layer = next((l for l in traced if e["id"] in entry_of[l]), None)
        entry = entry_of[layer][e["id"]] if layer else {}
        win = windows.get(e.get("scene_id"))
        row_ = {"event_id": e["id"], "production_scene_id": e.get("scene_id"),
                "runtime": scene_runtime(edit_decisions, win["cuts"][0]["cut"] if win else None),
                "time_seconds": e["time_seconds"], "implemented": bool(entry.get("implemented")), "refs": _code_refs(entry)}
        for k in ("action_id", "contract_event_id"):
            if e.get(k):
                row_[k] = e[k]
        if layer:
            row_["layer"] = layer
        event_rows.append(row_)

    trace_sources = []
    for layer, (t, source) in traced.items():
        trace_sources.append({"layer": layer, "runtime": scene_runtime(edit_decisions, None),
                              "source": source or ",".join(t.get("provider_files") or []) or "trace",
                              "hard_failures": list(t.get("hard_failures") or [])})
    if any(b["locator"]["kind"] == "ASSET" for b in bindings if b.get("locator")):
        trace_sources.append({"layer": "factual_source", "runtime": scene_runtime(edit_decisions, None), "source": "edit_decisions"})

    out = {
        "version": "1.2",
        "contract": contract.ref,
        "timeline_sha256": canonical_json_sha256(timeline),
        "edit_decisions_sha256": canonical_json_sha256(edit_decisions),
        "scene_windows": [{"production_scene_id": sid, "start_seconds": round(w["start"], 6), "end_seconds": round(w["end"], 6),
                           "cut_ids": [str(c["cut"].get("id")) for c in w["cuts"]]} for sid, w in windows.items()],
        "bindings": bindings,
        "events": event_rows,
        "trace_sources": trace_sources,
    }
    validate_schema("execution_binding", out)
    return out


def bound_ids(binding: dict[str, Any]) -> dict[str, dict[str, str]]:
    """contract id -> {layer: worst status across the production scenes that carry it}."""
    rank = {"bound": 0, "deviated": 1, "not_executed_by_engine": 2, "unbound": 3}
    out: dict[str, dict[str, str]] = {}
    for b in binding.get("bindings") or []:
        for ids in (b.get("consumes") or {}).values():
            for cid in ids:
                cur = out.setdefault(cid, {}).get(b["layer"])
                if cur is None or rank[b["status"]] > rank[cur]:
                    out[cid][b["layer"]] = b["status"]
    return out
