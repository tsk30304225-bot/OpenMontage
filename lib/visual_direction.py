"""Visual direction contract: persistent visual models driven by narration anchors.

The scene director writes ``visual_direction`` (what must change on screen and
why, anchored to narration text, no seconds). After TTS + forced alignment the
edit stage compiles it into ``visual_timeline`` (when each change happens, in
real seconds). Renderers execute the timeline; they do not reinterpret prose.

This module is topic-agnostic. It knows model types, their generic state,
operations, anchors and timing — never what the items mean in a particular
video. Meaning lives in the project's ``visual_direction`` (ids, labels,
grammar, palette, and model configuration such as the queue policy).

The first model type is ``timeline_rail``: items planned on a time (or any
numeric) axis above the rail where they actually happen. The Remotion
implementation in
``remotion-composer/src/components/visual-models/timelineRail.ts`` mirrors
:func:`rail_schedule` and :func:`apply_rail_event`; keep them in step.
"""

from __future__ import annotations

import copy
import difflib
import re
import unicodedata
from typing import Any

MODEL_TYPES = ("timeline_rail",)

# Operations each model type understands. Operations outside this set are a
# contract error, not something a renderer should improvise.
MODEL_OPERATIONS = {
    "timeline_rail": ("ADD", "REMOVE", "EXPAND", "SHIFT", "PROPAGATE", "MEASURE"),
}

DEFAULT_EVENT_SECONDS = {
    "ADD": 0.6,
    "REMOVE": 0.6,
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
# Validation and compilation
# ---------------------------------------------------------------------------


def _model_targets(model: dict[str, Any]) -> set[str]:
    state = rail_initial_state(model)
    return {str(i["id"]) for i in state["items"]} | RAIL_RESERVED_TARGETS


def script_text(script: dict[str, Any] | None) -> str:
    if not script:
        return ""
    return " ".join(section.get("text") or "" for section in script.get("sections") or [])


def validate_direction(direction: dict[str, Any], script: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Contract checks that must pass before assets are produced.

    Errors: unknown model type/policy/operation/target, beat on a scene without
    a model, anchor that does not occur in the script (it could never be
    aligned). Warnings: long stretches with no reality scene, model scenes
    without beats.
    """
    errors: list[str] = []
    warnings: list[str] = []
    models = {m["id"]: m for m in direction.get("visual_models") or []}
    for mid, model in models.items():
        if model.get("type") not in MODEL_TYPES:
            errors.append(f"visual model {mid!r}: unsupported type {model.get('type')!r} (supported: {', '.join(MODEL_TYPES)})")
        policy = (model.get("queue") or {}).get("policy", "sequential")
        if policy not in RAIL_POLICIES:
            errors.append(f"visual model {mid!r}: queue.policy {policy!r} not in {RAIL_POLICIES}")
    norm_script = normalize_text(script_text(script)) if script else ""

    added: dict[str, set[str]] = {mid: set() for mid in models}
    for scene in direction.get("scenes") or []:
        sid = scene.get("scene_id")
        mid = scene.get("visual_model_id")
        beats = scene.get("beats") or []
        if beats and not mid:
            errors.append(f"scene {sid}: has beats but no visual_model_id")
            continue
        if mid and mid not in models:
            errors.append(f"scene {sid}: visual_model_id {mid!r} is not declared in visual_models")
            continue
        if mid and not beats:
            warnings.append(f"scene {sid}: shows model {mid!r} without beats; the model will hold still for the whole scene")
        if not mid:
            continue
        model = models[mid]
        allowed = MODEL_OPERATIONS.get(model.get("type"), ())
        for beat in beats:
            bid = beat.get("id")
            op = beat.get("operation")
            if op not in allowed:
                errors.append(f"beat {bid}: operation {op!r} not supported by {model.get('type')} ({', '.join(allowed)})")
                continue
            target = str(beat.get("target", ""))
            params = beat.get("params") or {}
            if op == "ADD":
                added[mid].add(str((params.get("item") or {}).get("id") or target))
            elif target not in _model_targets(model) | added[mid]:
                errors.append(f"beat {bid}: target {target!r} does not exist in model {mid!r}")
            if op == "MEASURE" and not params.get("clear"):
                metric = params.get("metric", "wait")
                if metric not in RAIL_METRICS:
                    errors.append(f"beat {bid}: MEASURE metric {metric!r} not in {RAIL_METRICS}")
            anchor = beat.get("narration_anchor") or ""
            if not normalize_text(anchor):
                errors.append(f"beat {bid}: narration_anchor is empty")
            elif norm_script and normalize_text(anchor) not in norm_script:
                errors.append(f"beat {bid}: narration_anchor {anchor!r} does not occur in the script text")

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
    state = rail_initial_state(model)
    out: list[tuple[dict[str, Any] | None, dict[str, Any]]] = [(None, state)]
    for ev in timeline["events"]:
        if ev["model_id"] == model_id:
            state = apply_rail_event(state, ev)
            out.append((ev, state))
    return out


def ineffective_events(timeline: dict[str, Any]) -> list[str]:
    """Event ids whose operation changes nothing a viewer could see."""
    bad = []
    for model in timeline.get("models") or []:
        prev = None
        for ev, state in replay_model_states(timeline, model["id"]):
            sig = rail_state_signature(state)
            if ev is not None and sig == prev:
                bad.append(ev["id"])
            prev = sig
    return bad
