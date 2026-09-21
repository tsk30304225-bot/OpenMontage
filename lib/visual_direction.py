"""Visual direction contract: persistent visual models driven by narration anchors.

The scene director writes ``visual_direction`` (what must change on screen and
why, anchored to narration text, no seconds). After TTS + forced alignment the
edit stage compiles it into ``visual_timeline`` (when each change happens, in
real seconds). Renderers execute the timeline; they do not reinterpret prose.

This module is topic-agnostic. It knows model types, their generic state,
operations, anchors and timing — never what the items mean in a particular
video. Meaning lives in the project's ``visual_direction`` (ids, labels,
grammar, palette, and model configuration such as the queue policy).

A model's ``type`` names what the picture means; ``renderer`` says who draws
it. ``timeline_rail`` has a dedicated reducer and a generic Remotion renderer.
Every other type is an element model (named elements whose visibility and
attributes change) that atelier implements bespoke — renderer support never
decides whether a model exists.

The TypeScript runtime in ``remotion-composer/src/direction/`` and
``remotion-composer/src/components/visual-models/timelineRail.ts`` mirrors the
reducers here; keep them in step (a parity test runs both).
"""

from __future__ import annotations

import copy
import difflib
import re
import unicodedata
from typing import Any

# Operations each model type understands. Operations outside this set are a
# contract error, not something a renderer should improvise. Types without an
# entry here are element models (see ELEMENT_OPERATIONS).
MODEL_OPERATIONS = {
    "timeline_rail": ("ADD", "REMOVE", "EXPAND", "SHIFT", "PROPAGATE", "MEASURE"),
}

DEFAULT_EVENT_SECONDS = {
    "ADD": 0.6,
    "REMOVE": 0.6,
    "REVEAL": 0.8,
    "CONNECT": 1.0,
    "EXPAND": 1.2,
    "SHIFT": 1.0,
    "PROPAGATE": 1.4,
    "MEASURE": 0.5,
}

RAIL_METRICS = ("wait", "idle_before", "duration", "overrun")

# How the actual rail is derived from the plan (timeline_rail.queue.policy):
#   independent  every item happens at its own ready time; no shared resource (Gantt-like)
#   sequential   one shared resource, items in planned order, each starts when ready and the previous one ended
#   ready_first  one shared resource; whenever it frees up it takes, among items already ready,
#                the earliest planned one, and stays idle until the next item is ready
RAIL_POLICIES = ("independent", "sequential", "ready_first")

RAIL_RESERVED_TARGETS = {"slot_interval", "view", "all"}

# Scene roles that show the real world rather than a model or evidence card.
REALITY_ROLES = {"immersion", "breather", "closure", "establish_context", "emotional_beat"}

_STRIP = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Casefold and drop whitespace/punctuation so anchors survive tokenisation."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", str(text)).casefold())


# ---------------------------------------------------------------------------
# Alignment words and anchor matching
# ---------------------------------------------------------------------------


def flatten_alignment(alignment: Any) -> list[dict[str, Any]]:
    """Return ``[{word, start, end}]`` in global seconds from forced-alignment output.

    Accepts ``{"segments": [{"words": [...]}]}`` (qwen3_tts timestamps_path),
    ``{"word_timestamps": [...]}`` (word_timestamps_path) or a plain list of
    either segments or words.
    """
    if isinstance(alignment, dict):
        if "segments" in alignment:
            groups = [seg.get("words") or [] for seg in alignment["segments"]]
        else:
            groups = [alignment.get("word_timestamps") or []]
    elif isinstance(alignment, list):
        if alignment and isinstance(alignment[0], dict) and "words" in alignment[0]:
            groups = [seg.get("words") or [] for seg in alignment]
        else:
            groups = [alignment]
    else:
        return []
    words = []
    for group in groups:
        for w in group:
            if normalize_text(w.get("word", "")):
                words.append({"word": str(w["word"]), "start": float(w["start"]), "end": float(w["end"])})
    words.sort(key=lambda w: w["start"])
    return words


def match_anchor(
    anchor: str,
    words: list[dict[str, Any]],
    *,
    from_index: int = 0,
    min_score: float = 0.8,
) -> dict[str, Any] | None:
    """Find ``anchor`` in the aligned words at or after ``from_index``.

    Exact matching runs over the normalised character stream, so word
    boundaries and punctuation never matter. When the spoken text drifted
    slightly (numbers read out, particles), a fuzzy window match with
    ``SequenceMatcher`` ratio >= ``min_score`` is accepted and reported with
    its score.
    """
    target = normalize_text(anchor)
    if not target or from_index >= len(words):
        return None
    norm = [normalize_text(w["word"]) for w in words]
    stream = ""
    owner: list[int] = []
    for i in range(from_index, len(words)):
        stream += norm[i]
        owner.extend([i] * len(norm[i]))

    pos = stream.find(target)
    if pos >= 0:
        first, last = owner[pos], owner[pos + len(target) - 1]
        return _anchor_result(words, first, last, 1.0)

    best: tuple[float, int, int] | None = None
    n = len(words)
    for i in range(from_index, n):
        text = ""
        for j in range(i, n):
            text += norm[j]
            if len(text) > len(target) * 1.6:
                break
            if len(text) < len(target) * 0.6:
                continue
            score = difflib.SequenceMatcher(None, target, text).ratio()
            if best is None or score > best[0]:
                best = (score, i, j)
    if best and best[0] >= min_score:
        return _anchor_result(words, best[1], best[2], round(best[0], 3))
    return None


def _anchor_result(words: list[dict[str, Any]], first: int, last: int, score: float) -> dict[str, Any]:
    return {
        "word_index": first,
        "last_word_index": last,
        "matched_text": " ".join(w["word"] for w in words[first : last + 1]),
        "start_seconds": round(words[first]["start"], 3),
        "end_seconds": round(words[last]["end"], 3),
        "score": score,
    }


# ---------------------------------------------------------------------------
# timeline_rail state
# ---------------------------------------------------------------------------


def rail_initial_state(model: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(model.get("initial_state") or {})
    state.setdefault("axis", {})
    state.setdefault("slot_interval", 1)
    state.setdefault("items", [])
    state.setdefault("measures", [])
    state.setdefault("frozen", {})
    state.setdefault("show_planned", True)
    state.setdefault("show_actual", True)
    state["policy"] = (model.get("queue") or {}).get("policy", "sequential")
    for item in state["items"]:
        item.setdefault("present", True)
        item.setdefault("ready_offset", 0)
    return state


def _planned_start(state: dict[str, Any], item: dict[str, Any]) -> float:
    if item.get("planned_start") is not None:
        return float(item["planned_start"])
    return float(state["axis"].get("start", 0)) + float(item.get("slot", 0)) * float(state["slot_interval"])


def rail_schedule(state: dict[str, Any]) -> dict[str, Any]:
    """Derive the actual rail from the plan under the model's queue policy.

    Returns per-item planned/ready/actual positions, waits and idle gaps
    (``order`` is the order items start in), plus ``last_end`` and the overrun
    past ``deadline``, both measured on what is visible. Frozen items keep the
    actual position captured when a deferred EXPAND happened, until PROPAGATE
    releases them.
    """
    axis = state["axis"]
    policy = state.get("policy", "sequential")
    if policy not in RAIL_POLICIES:
        raise ValueError(f"timeline_rail queue.policy {policy!r} not in {RAIL_POLICIES}")
    cursor = float(state.get("resource_available_at", axis.get("start", 0)))
    out: dict[str, dict[str, Any]] = {}
    pending = []
    for item in state["items"]:
        planned = _planned_start(state, item)
        entry = {"planned_start": planned, "ready": planned + float(item.get("ready_offset", 0)), "present": bool(item.get("present", True))}
        out[str(item["id"])] = entry
        if entry["present"]:
            pending.append((planned, str(item["id"]), item))
    pending.sort(key=lambda w: (w[0], w[1]))

    order: list[str] = []
    last_end = cursor
    while pending:
        if policy == "ready_first":
            ready = [w for w in pending if out[w[1]]["ready"] <= cursor + 1e-9]
            if not ready:
                cursor = min(out[w[1]]["ready"] for w in pending)
                ready = [w for w in pending if out[w[1]]["ready"] <= cursor + 1e-9]
            chosen = min(ready, key=lambda w: (w[0], w[1]))
        else:
            chosen = pending[0]
        pending.remove(chosen)
        _, iid, item = chosen
        entry = out[iid]
        if policy == "independent":
            start = entry["ready"]
            idle = 0.0
        else:
            start = max(entry["ready"], cursor)
            idle = max(0.0, start - last_end)
        end = start + float(item.get("duration", 0))
        entry.update(actual_start=start, actual_end=end, wait=round(start - entry["ready"], 6), idle_before=round(idle, 6))
        if policy == "independent":
            last_end = max(last_end, end)
        else:
            cursor = last_end = end
        order.append(iid)
        frozen = state["frozen"].get(iid)
        if frozen:
            entry["actual_start"], entry["actual_end"] = frozen["actual_start"], frozen["actual_end"]
            entry["wait"] = round(max(0.0, frozen["actual_start"] - entry["ready"]), 6)
            entry["idle_before"] = 0.0
    order += [iid for iid, e in out.items() if not e["present"]]
    # Measure the end the viewer sees: items held by a deferred EXPAND still sit
    # where they were, so their consequence is not shown (or counted) yet.
    ends = [e["actual_end"] for e in out.values() if e["present"]]
    last_end = max(ends) if ends else float(state.get("resource_available_at", axis.get("start", 0)))
    deadline = state.get("deadline")
    overrun = round(max(0.0, last_end - float(deadline)), 6) if deadline is not None else 0.0
    return {"items": out, "order": order, "last_end": last_end, "overrun": overrun}


def _item(state: dict[str, Any], iid: str) -> dict[str, Any]:
    for item in state["items"]:
        if str(item["id"]) == str(iid):
            return item
    raise KeyError(f"timeline_rail has no item {iid!r}")


def apply_rail_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return the state after one operation (input state is not mutated)."""
    s = copy.deepcopy(state)
    op = event["operation"]
    target = str(event.get("target", ""))
    params = event.get("params") or {}

    if op == "ADD":
        item = dict(params.get("item") or {})
        item.setdefault("id", target)
        item.setdefault("present", True)
        item.setdefault("ready_offset", 0)
        if any(str(i["id"]) == str(item["id"]) for i in s["items"]):
            _item(s, item["id"]).update(item)
        else:
            s["items"].append(item)
    elif op == "REMOVE":
        _item(s, target)["present"] = False
        s["frozen"].pop(target, None)
    elif op == "EXPAND":
        before = rail_schedule(s)["items"]
        item = _item(s, target)
        if "to" in params:
            item["duration"] = float(params["to"])
        else:
            item["duration"] = float(item.get("duration", 0)) + float(params.get("by", 0))
        if params.get("propagate", "immediate") == "deferred":
            target_start = before[target]["planned_start"]
            for iid, row in before.items():
                if row["present"] and row["planned_start"] > target_start and iid not in s["frozen"]:
                    s["frozen"][iid] = {"actual_start": row["actual_start"], "actual_end": row["actual_end"]}
    elif op == "SHIFT":
        if target == "slot_interval":
            s["slot_interval"] = float(params["interval"])
        elif target == "view":
            for key in ("start", "end", "tick"):
                if key in params:
                    s["axis"][key] = params[key]
            if "deadline" in params:
                s["deadline"] = params["deadline"]
            for key in ("show_planned", "show_actual"):
                if key in params:
                    s[key] = bool(params[key])
        else:
            item = _item(s, target)
            if "ready_by" in params:
                item["ready_offset"] = float(item.get("ready_offset", 0)) + float(params["ready_by"])
            else:
                item["planned_start"] = _planned_start(s, item) + float(params.get("by", 0))
    elif op == "PROPAGATE":
        if target in ("", "all"):
            s["frozen"] = {}
        else:
            start = _planned_start(s, _item(s, target))
            for iid in list(s["frozen"]):
                if _planned_start(s, _item(s, iid)) > start:
                    del s["frozen"][iid]
    elif op == "MEASURE":
        if params.get("clear"):
            s["measures"] = []
        else:
            metric = params.get("metric", "wait")
            if params.get("exclusive"):
                s["measures"] = []
            s["measures"] = [m for m in s["measures"] if not (m["target"] == target and m["metric"] == metric)]
            s["measures"].append({"target": target, "metric": metric, "label": params.get("label")})
    else:
        raise ValueError(f"timeline_rail does not support operation {op!r}")
    return s


def rail_state_signature(state: dict[str, Any]) -> dict[str, Any]:
    """What a viewer could see change: geometry, presence, measures, view."""
    sched = rail_schedule(state)
    return {
        "axis": state["axis"],
        "deadline": state.get("deadline"),
        "items": {
            iid: {k: row.get(k) for k in ("planned_start", "ready", "present", "actual_start", "actual_end")}
            for iid, row in sched["items"].items()
        },
        "measures": state["measures"],
        "show": [state.get("show_planned", True), state.get("show_actual", True)],
    }


# ---------------------------------------------------------------------------
# Element models (any model type without a dedicated reducer)
# ---------------------------------------------------------------------------
#
# A model type names what the picture *means* (flow_network, quantity_stack,
# comparison_split, ...). Only a few types have a dedicated reducer and a
# generic renderer; every other type is an element model: a set of named
# elements (nodes, edges, values, labels, groups) whose visibility and
# attributes change by operation. That is enough to validate a direction, to
# resolve it in time, and to check a bespoke implementation against it — so a
# missing generic renderer never forces the plan to be dropped.

ELEMENT_OPERATIONS = ("ADD", "REMOVE", "REVEAL", "CONNECT", "EXPAND", "SHIFT", "PROPAGATE", "MEASURE")
ELEMENT_RESERVED_TARGETS = {"view", "all"}


def element_initial_state(model: dict[str, Any]) -> dict[str, Any]:
    initial = copy.deepcopy(model.get("initial_state") or {})
    elements: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for el in initial.get("elements") or []:
        e = {"kind": "node", "visible": False, "attrs": {}, **el}
        e["id"] = str(e["id"])
        elements[e["id"]] = e
        order.append(e["id"])
    return {
        "elements": elements,
        "order": order,
        "measures": [],
        "active": [],
        "view": dict(initial.get("view") or {}),
    }


def _element(state: dict[str, Any], eid: str) -> dict[str, Any]:
    if eid not in state["elements"]:
        raise KeyError(f"model has no element {eid!r}")
    return state["elements"][eid]


def apply_element_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return the element-model state after one operation (input is not mutated)."""
    s = copy.deepcopy(state)
    op = event["operation"]
    target = str(event.get("target", ""))
    params = event.get("params") or {}

    if op in ("ADD", "CONNECT"):
        spec = dict(params.get("element") or {})
        if op == "CONNECT":
            spec.setdefault("kind", "edge")
            for key in ("from", "to", "label"):
                if key in params:
                    spec[key] = params[key]
        spec["id"] = target
        spec.setdefault("kind", "node")
        spec.setdefault("attrs", {})
        spec["visible"] = spec.get("visible", True)
        if target in s["elements"]:
            s["elements"][target].update(spec)
        else:
            s["elements"][target] = spec
            s["order"].append(target)
    elif op == "REVEAL":
        el = _element(s, target)
        el["visible"] = True
        el["attrs"].update(params.get("attrs") or {})
    elif op == "REMOVE":
        _element(s, target)["visible"] = False
    elif op == "EXPAND":
        el = _element(s, target)
        attr = params.get("attr", "value")
        current = float(el["attrs"].get(attr, 0))
        el["attrs"][attr] = float(params["to"]) if "to" in params else current + float(params.get("by", 0))
    elif op == "SHIFT":
        if target == "view":
            s["view"].update({k: v for k, v in params.items()})
        else:
            _element(s, target)["attrs"].update(params.get("attrs") or {k: v for k, v in params.items()})
    elif op == "PROPAGATE":
        path = [target] + [str(p) for p in params.get("path") or []]
        for eid in path:
            if eid in s["elements"]:
                s["elements"][eid]["attrs"]["active"] = True
                if eid not in s["active"]:
                    s["active"].append(eid)
    elif op == "MEASURE":
        if params.get("clear"):
            s["measures"] = []
        else:
            metric = params.get("metric", "value")
            if params.get("exclusive"):
                s["measures"] = []
            s["measures"] = [m for m in s["measures"] if not (m["target"] == target and m["metric"] == metric)]
            s["measures"].append({"target": target, "metric": metric, "label": params.get("label"), "value": params.get("value")})
    else:
        raise ValueError(f"element model does not support operation {op!r}")
    return s


def element_state_signature(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "elements": {eid: {k: el.get(k) for k in ("kind", "visible", "attrs", "from", "to", "label")} for eid, el in state["elements"].items()},
        "measures": state["measures"],
        "active": state["active"],
        "view": state["view"],
    }


# ---------------------------------------------------------------------------
# Model dispatch
# ---------------------------------------------------------------------------

# Model types with a dedicated reducer and a generic (templated) renderer.
GENERIC_RENDERERS = {"timeline_rail"}


def model_renderer(model: dict[str, Any]) -> str:
    """'generic' (a shared renderer draws it) or 'bespoke' (atelier implements it)."""
    return model.get("renderer") or ("generic" if model.get("type") in GENERIC_RENDERERS else "bespoke")


def is_rail(model: dict[str, Any]) -> bool:
    return model.get("type") == "timeline_rail"


def model_initial_state(model: dict[str, Any]) -> dict[str, Any]:
    return rail_initial_state(model) if is_rail(model) else element_initial_state(model)


def apply_model_event(model: dict[str, Any], state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return apply_rail_event(state, event) if is_rail(model) else apply_element_event(state, event)


def model_state_signature(model: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return rail_state_signature(state) if is_rail(model) else element_state_signature(state)


def model_operations(model: dict[str, Any]) -> tuple[str, ...]:
    return MODEL_OPERATIONS["timeline_rail"] if is_rail(model) else ELEMENT_OPERATIONS


# ---------------------------------------------------------------------------
# Validation and compilation
# ---------------------------------------------------------------------------


def _model_targets(model: dict[str, Any]) -> set[str]:
    if is_rail(model):
        state = rail_initial_state(model)
        return {str(i["id"]) for i in state["items"]} | RAIL_RESERVED_TARGETS
    return set(element_initial_state(model)["elements"]) | ELEMENT_RESERVED_TARGETS


def script_text(script: dict[str, Any] | None) -> str:
    if not script:
        return ""
    return " ".join(section.get("text") or "" for section in script.get("sections") or [])


# Scenes whose job is to show a mechanism. When a direction has several of them
# and no visual model at all, the plan was dropped rather than decided.
EXPLANATION_ROLES = {"explanation", "deliver_payload", "comparison"}


def validate_direction(direction: dict[str, Any], script: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Contract checks that must pass before assets are produced.

    Errors: malformed model type/renderer/policy, operation or target the model
    does not have, beat on a scene without a model, anchor that does not occur
    in the script (it could never be aligned), and a direction whose
    explanation scenes carry no visual model at all (the plan was dropped).
    Warnings: long stretches with no reality scene, model scenes without beats,
    explanation scenes that only describe a graphic.

    Renderer support is not a planning constraint: a model type without a
    generic renderer is valid with ``renderer: "bespoke"`` and is implemented
    in atelier.
    """
    errors: list[str] = []
    warnings: list[str] = []
    models = {m["id"]: m for m in direction.get("visual_models") or []}
    for mid, model in models.items():
        mtype = str(model.get("type") or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", mtype):
            errors.append(f"visual model {mid!r}: type {mtype!r} must be a lowercase identifier naming what the picture means")
        renderer = model_renderer(model)
        if renderer not in ("generic", "bespoke"):
            errors.append(f"visual model {mid!r}: renderer {renderer!r} must be 'generic' or 'bespoke'")
        elif renderer == "generic" and mtype not in GENERIC_RENDERERS:
            errors.append(
                f"visual model {mid!r}: no generic renderer for type {mtype!r} (generic: {', '.join(sorted(GENERIC_RENDERERS))}). "
                "Keep the model and set renderer: 'bespoke' so atelier implements it; never drop the model."
            )
        if is_rail(model):
            policy = (model.get("queue") or {}).get("policy", "sequential")
            if policy not in RAIL_POLICIES:
                errors.append(f"visual model {mid!r}: queue.policy {policy!r} not in {RAIL_POLICIES}")
    norm_script = normalize_text(script_text(script)) if script else ""

    added: dict[str, set[str]] = {mid: set() for mid in models}
    explanation_without_model = []
    for scene in direction.get("scenes") or []:
        sid = scene.get("scene_id")
        mid = scene.get("visual_model_id")
        beats = scene.get("beats") or []
        if scene.get("narrative_role") in EXPLANATION_ROLES and not mid:
            explanation_without_model.append(sid)
        if beats and not mid:
            errors.append(f"scene {sid}: has beats but no visual_model_id")
            continue
        if mid and mid not in models:
            errors.append(f"scene {sid}: visual_model_id {mid!r} is not declared in visual_models")
            continue
        if mid and not beats:
            warnings.append(f"scene {sid}: shows model {mid!r} without beats; the model will hold still for the whole scene")
        role = scene.get("narrative_role")
        if role == "breather" and len(beats) >= 2:
            warnings.append(f"scene {sid}: breather carries {len(beats)} model changes; a breather adds no new information — is it an explanation?")
        if role == "immersion" and mid:
            warnings.append(f"scene {sid}: immersion scene develops model {mid!r}; immersion is the real place, explanations belong in explanation scenes")
        if not mid:
            continue
        model = models[mid]
        allowed = model_operations(model)
        for beat in beats:
            bid = beat.get("id")
            op = beat.get("operation")
            if op not in allowed:
                errors.append(f"beat {bid}: operation {op!r} not supported by {model.get('type')} ({', '.join(allowed)})")
                continue
            target = str(beat.get("target", ""))
            params = beat.get("params") or {}
            known = _model_targets(model) | added[mid]
            if is_rail(model):
                if op == "ADD":
                    added[mid].add(str((params.get("item") or {}).get("id") or target))
                elif target not in known:
                    errors.append(f"beat {bid}: target {target!r} does not exist in model {mid!r}")
                if op == "MEASURE" and not params.get("clear"):
                    metric = params.get("metric", "wait")
                    if metric not in RAIL_METRICS:
                        errors.append(f"beat {bid}: MEASURE metric {metric!r} not in {RAIL_METRICS}")
            else:
                if op in ("ADD", "CONNECT"):
                    if op == "CONNECT":
                        for end in ("from", "to"):
                            if str(params.get(end, "")) not in known:
                                errors.append(f"beat {bid}: CONNECT {end} {params.get(end)!r} does not exist in model {mid!r}")
                    added[mid].add(target)
                elif target not in known:
                    errors.append(f"beat {bid}: target {target!r} does not exist in model {mid!r}")
            anchor = beat.get("narration_anchor") or ""
            if not normalize_text(anchor):
                errors.append(f"beat {bid}: narration_anchor is empty")
            elif norm_script and normalize_text(anchor) not in norm_script:
                errors.append(f"beat {bid}: narration_anchor {anchor!r} does not occur in the script text")

    if not models and len(explanation_without_model) >= 2:
        errors.append(
            f"{len(explanation_without_model)} explanation scenes ({', '.join(explanation_without_model[:5])}"
            f"{'…' if len(explanation_without_model) > 5 else ''}) but no visual model: decide the model the mechanism needs "
            "(any type; renderer 'bespoke' when no generic renderer exists) and write its beats. "
            "Renderer support must not remove the plan: in a templated project render a bespoke model in atelier "
            "or as a scene with runtime 'hyperframes' (skills/core/tool-routing.md)."
        )
    elif explanation_without_model:
        warnings.append(
            f"explanation scenes without a visual model: {', '.join(explanation_without_model[:8])}"
            f"{'…' if len(explanation_without_model) > 8 else ''} — confirm they need no state change"
        )

    run = []
    for scene in direction.get("scenes") or []:
        if scene.get("narrative_role") in REALITY_ROLES or scene.get("visual_mode") == "reality":
            run = []
        else:
            run.append(scene.get("scene_id"))
            if len(run) == 6:
                warnings.append(
                    f"scenes {run[0]}..{run[-1]}: six scenes in a row without an immersion/breather/closure scene"
                )
    return {"errors": errors, "warnings": warnings}


def compile_timeline(
    direction: dict[str, Any],
    alignment: Any,
    *,
    scene_windows: dict[str, tuple[float, float]] | None = None,
    min_score: float = 0.8,
    source: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve every beat's narration anchor to a real time.

    Beats are matched in document order with a moving cursor, so a phrase
    repeated later in the narration binds to the right occurrence. When
    ``scene_windows`` is given, the search for a scene's beats starts no
    earlier than the first word inside that scene's window.
    """
    words = flatten_alignment(alignment)
    events: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    cursor = 0
    models = {m["id"]: m for m in direction.get("visual_models") or []}
    for scene in direction.get("scenes") or []:
        beats = scene.get("beats") or []
        if not beats:
            continue
        sid = scene.get("scene_id")
        if scene_windows and sid in scene_windows:
            win_start = scene_windows[sid][0]
            scene_first = next((i for i, w in enumerate(words) if w["end"] > win_start - 0.05), len(words))
            cursor = max(cursor, scene_first)
        for beat in beats:
            match = match_anchor(beat.get("narration_anchor", ""), words, from_index=cursor, min_score=min_score)
            if match is None:
                unmatched.append({"beat_id": beat.get("id"), "scene_id": sid, "narration_anchor": beat.get("narration_anchor"),
                                  "reason": "anchor not found in aligned narration after the previous beat"})
                continue
            cursor = match["word_index"]
            t = match["end_seconds"] if beat.get("anchor_at", "start") == "end" else match["start_seconds"]
            t = round(t + float(beat.get("offset_seconds", 0)), 3)
            op = beat["operation"]
            events.append({
                "id": f"ev-{beat.get('id')}",
                "beat_id": beat.get("id"),
                "scene_id": sid,
                "model_id": scene.get("visual_model_id"),
                "operation": op,
                "target": beat.get("target", ""),
                "params": beat.get("params") or {},
                "time_seconds": max(0.0, t),
                "duration_seconds": float(beat.get("duration_seconds", DEFAULT_EVENT_SECONDS.get(op, 0.8))),
                "anchor": {"text": beat.get("narration_anchor"), **{k: v for k, v in match.items() if k not in ("word_index", "last_word_index")}},
                "takeaway": beat.get("takeaway"),
            })
    events.sort(key=lambda e: e["time_seconds"])
    used = {s.get("visual_model_id") for s in direction.get("scenes") or [] if s.get("visual_model_id")}
    return {
        "version": "1.0",
        "source": source or {},
        "models": [copy.deepcopy(models[m]) for m in models if m in used],
        "events": events,
        "unmatched": unmatched,
    }


def replay_model_states(timeline: dict[str, Any], model_id: str) -> list[tuple[dict[str, Any] | None, dict[str, Any]]]:
    """[(event, state_after)] for one model, starting with (None, initial_state)."""
    model = next(m for m in timeline["models"] if m["id"] == model_id)
    state = model_initial_state(model)
    out: list[tuple[dict[str, Any] | None, dict[str, Any]]] = [(None, state)]
    for ev in timeline["events"]:
        if ev["model_id"] == model_id:
            state = apply_model_event(model, state, ev)
            out.append((ev, state))
    return out


def state_at(timeline: dict[str, Any], model_id: str, time_seconds: float) -> dict[str, Any]:
    """Contract state of one model once every event up to ``time_seconds`` has fired."""
    state = None
    for ev, st in replay_model_states(timeline, model_id):
        if ev is not None and ev["time_seconds"] > time_seconds:
            break
        state = st
    return state


def ineffective_events(timeline: dict[str, Any]) -> list[str]:
    """Event ids whose operation changes nothing a viewer could see."""
    bad = []
    for model in timeline.get("models") or []:
        prev = None
        for ev, state in replay_model_states(timeline, model["id"]):
            sig = model_state_signature(model, state)
            if ev is not None and sig == prev:
                bad.append(ev["id"])
            prev = sig
    return bad
