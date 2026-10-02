"""Replay a (plan or compiled) timeline against one contract scene.

One evaluator serves every stage: ``check_lineage`` feeds it the plan's beats
in document order, ``check_states`` and ``qa_report`` feed it the compiled
visual_timeline. It reports facts, not verdicts: which actions fired, which
states were reached and when, invariant values after each sync group inside
the scene window (D2), order, merge and collapse evidence, and the model
signature at the scene end. Pixels are never involved (P6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lib.direction_contract.contract import apply_model_event, model_initial_state, model_state_signature
from lib.direction_contract.contract_v12 import Contract, assertion_holds, target_value

EPS = 1e-6


@dataclass
class SceneFacts:
    scene_id: str
    window: tuple[float, float]
    events: list[dict[str, Any]]
    action_events: dict[str, list[dict[str, Any]]]
    reached: dict[str, bool]                    # model states only
    reached_at: dict[str, float]                # when the operation that entered the state ends
    state_detail: dict[str, str]
    invariant_violations: dict[str, list[str]]  # CONSTANT / ASSERT
    sync_bad: dict[str, list[tuple[float, float]]]
    order: dict[str, tuple[bool, list[Any]]]    # ORDER invariant id -> (ok, times)
    dependency_violations: list[str]
    merged: dict[str, str]                      # action id -> why it collapses below min_duration
    collapsed_beats: list[str]
    final_signature: dict[str, Any]             # model id -> signature at scene end
    models_on_timeline: set[str] = field(default_factory=set)

    def action_span(self, aid: str) -> tuple[float, float] | None:
        evs = self.action_events.get(aid) or []
        if not evs:
            return None
        return min(e["time_seconds"] for e in evs), max(e["time_seconds"] + e["duration_seconds"] for e in evs)

    def fired(self, aid: str) -> bool:
        return bool(self.action_events.get(aid))


class _Replay:
    """Model signatures over time for the models a scene uses."""

    def __init__(self, timeline: dict[str, Any], model_ids: list[str]):
        self.models = {m["id"]: m for m in timeline.get("models") or [] if m["id"] in model_ids}
        self.steps: dict[str, list[tuple[float, Any]]] = {}
        for mid, model in self.models.items():
            state = model_initial_state(model)
            steps = [(float("-inf"), model_state_signature(model, state))]
            for ev in sorted((e for e in timeline.get("events") or [] if e.get("model_id") == mid), key=lambda e: e["time_seconds"]):
                state = apply_model_event(model, state, ev)
                steps.append((ev["time_seconds"], model_state_signature(model, state)))
            self.steps[mid] = steps

    def at(self, mid: str, t: float, *, inclusive: bool = True) -> Any:
        """Signature once every operation at or before ``t`` (strictly before, if not inclusive) has applied."""
        sig = None
        for when, s in self.steps.get(mid) or []:
            if when < t - EPS or (inclusive and abs(when - t) <= EPS) or when == float("-inf"):
                sig = s
            else:
                break
        return sig


def _paths(inv: dict[str, Any]) -> list[str]:
    if inv.get("target"):
        tg = inv["target"]
        return list(tg.get("paths") or ([tg["path"]] if tg.get("path") else []))
    return [a.get("path", "") for h in inv.get("holds") or [] for a in h["assert"]] + \
           [p for h in inv.get("holds") or [] for a in h["assert"] for p in a.get("paths") or []]


def evaluate_scene(contract: Contract, scene_id: str, timeline: dict[str, Any], production_ids: list[str],
                   window: tuple[float, float] | None = None) -> SceneFacts:
    scene = contract.scenes[scene_id]
    model_ids = contract.scene_models(scene_id)
    replay = _Replay(timeline, model_ids)
    prod = set(production_ids)
    events = sorted((e for e in timeline.get("events") or [] if e.get("scene_id") in prod), key=lambda e: e["time_seconds"])
    if window is None:
        window = (min((e["time_seconds"] for e in events), default=0.0),
                  max((e["time_seconds"] + e["duration_seconds"] for e in events), default=0.0))
    lo, hi = window
    in_window = [e for e in events if lo - EPS <= e["time_seconds"] <= hi + EPS]

    action_events: dict[str, list[dict[str, Any]]] = {}
    for e in in_window:
        if e.get("action_id"):
            action_events.setdefault(e["action_id"], []).append(e)

    # --- states ---------------------------------------------------------------------------------
    reached: dict[str, bool] = {}
    reached_at: dict[str, float] = {}
    detail: dict[str, str] = {}

    def holds_at(state_id: str, t: float, inclusive: bool = True) -> tuple[bool, str]:
        failed = []
        for mid, a in contract.state_assertions(state_id):
            sig = replay.at(mid, t, inclusive=inclusive)
            if sig is None:
                failed.append(f"{mid} not on the timeline")
            elif not assertion_holds(a, sig):
                failed.append(str(a))
        return not failed, "; ".join(failed)

    for st in scene.get("states") or []:
        sid = st["state_id"]
        if not contract.is_model_state(sid):
            continue
        if sid == scene.get("initial_state"):
            ok, why = holds_at(sid, lo, inclusive=False)
            reached[sid], reached_at[sid] = ok, lo
            detail[sid] = "holds at scene start" if ok else f"does not hold at scene start: {why}"
            continue
        entering = [e for e in in_window if e.get("state_after_id") == sid]
        if not entering:
            reached[sid] = False
            detail[sid] = "no operation in the scene window enters it"
            continue
        t = max(e["time_seconds"] for e in entering)
        group = [e for e in in_window if abs(e["time_seconds"] - t) <= EPS or
                 (e.get("sync_group") and e.get("sync_group") in {x.get("sync_group") for x in entering})]
        t_eval = max(e["time_seconds"] for e in group)
        ok, why = holds_at(sid, t_eval)
        reached[sid] = ok
        reached_at[sid] = max(e["time_seconds"] + e["duration_seconds"] for e in group)
        detail[sid] = f"reached at {t_eval:g}s" if ok else f"entered at {t_eval:g}s but {why}"

    # --- sync groups (D2) -----------------------------------------------------------------------
    groups: dict[str, set[tuple[float, float]]] = {}
    group_targets: dict[str, set[str]] = {}
    for e in in_window:
        g = e.get("sync_group")
        if g:
            groups.setdefault(g, set()).add((round(e["time_seconds"], 6), round(e["duration_seconds"], 6)))
            group_targets.setdefault(g, set()).add(str(e.get("target")))
    sync_bad = {g: sorted(v) for g, v in groups.items() if len(v) > 1}

    # --- invariants: after each sync group, inside the window ----------------------------------
    times = sorted({e["time_seconds"] for e in in_window if e.get("model_id") in replay.models})
    inv_bad: dict[str, list[str]] = {}
    order: dict[str, tuple[bool, list[Any]]] = {}
    for inv in scene.get("invariants") or []:
        iid = inv["invariant_id"]
        if inv["kind"] == "ORDER":
            seq = []
            for x in inv["order"]:
                kind = contract.kind(x)
                if kind == "action":
                    span = [e["time_seconds"] for e in action_events.get(x) or []]
                    seq.append(min(span) if span else None)
                elif kind == "event":
                    span = [e["time_seconds"] for e in in_window if e.get("contract_event_id") == x]
                    seq.append(min(span) if span else None)
                else:
                    seq.append(reached_at.get(x) if reached.get(x) else None)
            ok = None not in seq and all(a < b - EPS for a, b in zip(seq, seq[1:]))
            order[iid] = (ok, seq)
            continue
        start, end = lo, hi
        during = inv.get("during")
        if isinstance(during, dict):
            if reached.get(during["from"]) and reached.get(during["to"]):
                start, end = reached_at[during["from"]], reached_at[during["to"]]
        points = [start] + [t for t in times if start - EPS <= t <= end + EPS]
        bad: list[str] = []
        if inv["kind"] == "CONSTANT":
            tg = inv["target"]
            expected = inv.get("value")
            for i, t in enumerate(points):
                sig = replay.at(tg["model_id"], t, inclusive=i > 0)
                if sig is None:
                    bad.append(f"{tg['model_id']} not on the timeline")
                    break
                value = target_value(tg, sig)
                if expected is None:
                    expected = value
                if value is None or abs(value - float(expected)) > float(inv.get("tolerance") or 1e-9):
                    bad.append(f"{value:g} at {t:g}s (expected {float(expected):g})" if value is not None else f"no value at {t:g}s")
        else:  # ASSERT
            for i, t in enumerate(points):
                for chk in inv["holds"]:
                    sig = replay.at(chk["model_id"], t, inclusive=i > 0)
                    for a in chk["assert"]:
                        if sig is None or not assertion_holds(a, sig):
                            bad.append(f"{a} fails at {t:g}s")
        touched = [g for g in sync_bad if any(f"elements.{tgt}." in p for tgt in group_targets.get(g, ()) for p in _paths(inv))]
        bad += [f"sync group {g} is not simultaneous {sync_bad[g]}: the invariant is broken between its operations" for g in touched]
        if bad:
            inv_bad[iid] = bad

    # --- dependencies, merge, collapse ----------------------------------------------------------
    dep_bad: list[str] = []
    merged: dict[str, str] = {}
    spans = {aid: (min(e["time_seconds"] for e in evs), max(e["time_seconds"] + e["duration_seconds"] for e in evs))
             for aid, evs in action_events.items()}
    for a in scene.get("actions") or []:
        aid = a["action_id"]
        for d in (a.get("dependency") or {}).get("after") or []:
            other, on = (d["action"], d.get("on", "complete")) if isinstance(d, dict) else (d, "complete")
            if aid in spans and other in spans:
                limit = spans[other][1] if on == "complete" else spans[other][0]
                if spans[aid][0] < limit - EPS:
                    dep_bad.append(f"{aid} starts at {spans[aid][0]:g}s before {other} {'completes' if on == 'complete' else 'starts'} ({limit:g}s)")
        need = a.get("min_duration_seconds")
        if need and aid in spans and spans[aid][1] - spans[aid][0] < float(need) - EPS:
            merged[aid] = f"runs {spans[aid][1] - spans[aid][0]:.2f}s < min_duration {need}s"
    beat_times: dict[str, float] = {}
    for b in scene.get("beats") or []:
        ts = [spans[x][0] for x in b.get("linked_actions") or [] if x in spans]
        if ts:
            beat_times[b["beat_id"]] = min(ts)
    seen: dict[float, str] = {}
    collapsed: list[str] = []
    for bid, t in beat_times.items():
        key = round(t, 3)
        if key in seen:
            collapsed += [seen[key], bid]
        seen[key] = bid

    final = {mid: replay.at(mid, hi) for mid in replay.models}
    return SceneFacts(
        scene_id=scene_id, window=window, events=in_window, action_events=action_events, reached=reached,
        reached_at=reached_at, state_detail=detail, invariant_violations=inv_bad, sync_bad=sync_bad, order=order,
        dependency_violations=dep_bad, merged=merged, collapsed_beats=sorted(set(collapsed)), final_signature=final,
        models_on_timeline=set(replay.models),
    )


def plan_timeline(contract: Contract, visual_direction: dict[str, Any]) -> dict[str, Any]:
    """The plan as a timeline: beats in document order, one tick each, a sync group sharing its tick.

    Lets the lineage gate replay states and invariants before any narration
    exists; only order and grouping are meaningful, not seconds.
    """
    events: list[dict[str, Any]] = []
    tick = 0.0
    group_tick: dict[str, float] = {}
    used: set[str] = set()
    for scene in visual_direction.get("scenes") or []:
        mid = scene.get("visual_model_id")
        if mid:
            used.add(mid)
        for beat in scene.get("beats") or []:
            g = beat.get("sync_group")
            if g and g in group_tick:
                t = group_tick[g]
            else:
                tick += 1.0
                t = tick
                if g:
                    group_tick[g] = t
            events.append({
                "id": f"ev-{beat.get('id')}", "beat_id": beat.get("id"), "scene_id": scene.get("scene_id"),
                "model_id": mid, "operation": beat.get("operation"), "target": beat.get("target", ""),
                "params": beat.get("params") or {}, "time_seconds": t, "duration_seconds": 0.0,
                **{k: beat[k] for k in ("action_id", "state_after_id", "contract_event_id", "anchor_id", "sync_group") if k in beat},
            })
    events.sort(key=lambda e: e["time_seconds"])
    return {"models": [d for d in contract.definitions() if d["id"] in used], "events": events}
