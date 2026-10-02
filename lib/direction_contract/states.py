"""Edit-stage state checks (``check_states``) and the last-frame rule shared with 45 (D17).

Everything is decided by replaying the compiled visual_timeline inside each
locked scene's window (the 42 production scenes it maps to). A cut or an
asset that merely covers the scene end is ACTIVE_AT_SCENE_END evidence for a
source object; LAST_FRAME passes only when every declared requirement of
``last_frame_contract`` holds, and anything that needs the render (visible
text, camera) leaves it UNVERIFIED.
"""

from __future__ import annotations

from typing import Any, Callable

from lib.direction_contract.contract_v12 import LOCKED, Contract, assertion_holds
from lib.direction_contract.evaluate import EPS, SceneFacts, evaluate_scene
from lib.direction_contract.lineage import model_object_visible_at_end, production_map

# source object id -> (active at scene end?, since when) ; (None, None) = cannot tell before the render
SourceActive = Callable[[str], tuple[bool | None, float | None]]


def _no_render(_: str) -> tuple[bool | None, float | None]:
    return None, None


def scene_window(production_ids: list[str], windows: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    known = [windows[p] for p in production_ids if p in windows]
    if not known:
        return None
    return min(w[0] for w in known), max(w[1] for w in known)


def last_frame(contract: Contract, scene_id: str, facts: SceneFacts, source_active: SourceActive = _no_render) -> tuple[str, list[str]]:
    """LAST_FRAME verdict (PASS / FAIL / UNVERIFIED) and one note per declared requirement."""
    scene = contract.scenes[scene_id]
    lf = scene.get("last_frame_contract") or {}
    end = facts.window[1]
    notes: list[str] = []
    results: list[str] = []

    def put(result: str, note: str) -> None:
        results.append(result)
        notes.append(f"{result}: {note}")

    def final_holds(model_id: str, assertion: dict[str, Any]) -> bool:
        sig = facts.final_signature.get(model_id)
        return sig is not None and assertion_holds(assertion, sig)

    def object_visible(oid: str) -> tuple[bool | None, float | None]:
        seen = model_object_visible_at_end(contract, facts, oid)
        if seen is not None:
            return seen, None
        return source_active(oid)

    req = lf.get("required_state_id")
    reached_since: float | None = None
    if req:
        if contract.is_model_state(req):
            ok = all(final_holds(mid, a) for mid, a in contract.state_assertions(req))
            put("PASS" if ok else "FAIL", f"required state {req} {'holds' if ok else 'does not hold'} at scene end")
            reached_since = facts.reached_at.get(req) if facts.reached.get(req) else None
        else:
            shown = [object_visible(o) for o in (contract.obj(req) or {}).get("visible_objects") or []]
            if not shown:
                put("UNVERIFIED", f"required state {req} has no model assertions and no visible objects to check")
            elif any(v is False for v, _ in shown):
                put("FAIL", f"required state {req}: a visible object is not active at scene end")
            elif any(v is None for v, _ in shown):
                put("UNVERIFIED", f"required state {req}: visible objects need the render")
            else:
                put("PASS", f"required state {req}: every visible object is active at scene end")
                reached_since = max((s for _, s in shown if s is not None), default=None)
    for oid in lf.get("visible_objects") or []:
        v, _ = object_visible(oid)
        put({True: "PASS", False: "FAIL", None: "UNVERIFIED"}[v], f"{oid} visible at scene end")
    for oid in lf.get("hidden_objects") or []:
        seen = model_object_visible_at_end(contract, facts, oid)
        put({True: "FAIL", False: "PASS", None: "UNVERIFIED"}[seen], f"{oid} hidden at scene end")
    for chk in lf.get("object_states") or []:
        ok = all(final_holds(chk["model_id"], a) for a in chk["assert"])
        put("PASS" if ok else "FAIL", f"object_states on {chk['model_id']}")
    for ref in lf.get("persistent_states") or []:
        mid = ref.split(".", 1)[0]
        ok = all(final_holds(mid, a) for a in contract.named_state(ref))
        put("PASS" if ok else "FAIL", f"persistent state {ref} at scene end")
    motion = lf.get("motion_state")
    if motion == "HOLD":
        after = [e["id"] for e in facts.events
                 if e.get("model_id") in facts.models_on_timeline and reached_since is not None and e["time_seconds"] > reached_since + EPS]
        if reached_since is None:
            put("UNVERIFIED" if not req or not contract.is_model_state(req) else "FAIL", "HOLD: required state never settles")
        else:
            put("FAIL" if after else "PASS", f"HOLD after {reached_since:g}s" + (f": still moving {after}" if after else ""))
    elif motion:
        put("UNVERIFIED", f"motion_state {motion} needs the render")
    if lf.get("minimum_hold_seconds") is not None:
        need = float(lf["minimum_hold_seconds"])
        if reached_since is None:
            put("UNVERIFIED" if not req or not contract.is_model_state(req) else "FAIL", f"minimum_hold {need:g}s: required state not reached")
        else:
            held = end - reached_since
            put("PASS" if held >= need - EPS else "FAIL", f"held {held:.2f}s of minimum {need:g}s")
    if lf.get("visible_text"):
        put("UNVERIFIED", f"visible_text {lf['visible_text']} needs the render")
    if lf.get("camera_state"):
        put("UNVERIFIED", f"camera_state {lf['camera_state']!r} needs the render")
    if not results:
        return "UNVERIFIED", ["no last_frame_contract requirement"]
    verdict = "FAIL" if "FAIL" in results else ("UNVERIFIED" if "UNVERIFIED" in results else "PASS")
    return verdict, notes


def check_states(contract: Contract, timeline: dict[str, Any], lineage: dict[str, Any],
                 scene_windows: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """Edit-stage gate: replay the compiled timeline per locked scene (states, invariants, sync, order, last frame)."""
    contract.check_ref("visual_timeline", timeline.get("contract"))
    contract.check_ref("direction_lineage", lineage.get("contract"))
    mapping = production_map(lineage)
    resolution = timeline.get("anchor_resolution") or {}
    resolved = {r["anchor_id"]: r for r in resolution.get("resolved_anchors") or []}
    violations: list[dict[str, Any]] = []
    scenes: dict[str, Any] = {}

    def add(sid: str, kind: str, targets: list[str], detail: str, violation: str | None = None) -> None:
        row = {"scene_id": sid, "type": kind, "target_ids": targets, "detail": detail}
        if violation:
            row["violation"] = violation
        violations.append(row)

    for sid, scene in contract.scenes.items():
        if scene.get("importance") != LOCKED:
            continue
        prod = mapping.get(sid, [])
        facts = evaluate_scene(contract, sid, timeline, prod, scene_window(prod, scene_windows))
        scenes[sid] = {"production_scene_ids": prod, "window": list(facts.window)}
        for a in scene.get("anchors") or []:
            r = resolved.get(a["anchor_id"])
            if r is None:
                add(sid, "ANCHOR_TIMING", [a["anchor_id"]], "anchor not resolved in the aligned narration")
            elif not r.get("same_span", True):
                add(sid, "ANCHOR_TIMING", [a["anchor_id"]], f"resolved {r['status']} to other words: needs a deviation")
        for a in scene.get("actions") or []:
            if not facts.fired(a["action_id"]):
                add(sid, "ACTION_EXISTENCE", [a["action_id"]], "no operation of the action runs in the scene window", "REMOVE_REQUIRED_ACTION")
        for st, ok in facts.reached.items():
            if not ok:
                add(sid, "STATE_TRANSITION", [st], facts.state_detail[st], "REMOVE_INTERMEDIATE_STATE")
        for iid, bad in facts.invariant_violations.items():
            add(sid, "INVARIANT", [iid], "; ".join(bad[:4]), "ALTER_INVARIANT")
        for iid, (ok, seq) in facts.order.items():
            if not ok:
                add(sid, "ORDER", [iid], f"times {seq}", "REORDER_LOCKED_ACTIONS")
        for d in facts.dependency_violations:
            add(sid, "ORDER", [d.split(" ")[0]], d, "REORDER_LOCKED_ACTIONS")
        for aid, why in facts.merged.items():
            add(sid, "PROHIBITED_SIMPLIFICATION", [aid], why, "MERGE_LOCKED_ACTIONS")
        if facts.collapsed_beats:
            add(sid, "PROHIBITED_SIMPLIFICATION", facts.collapsed_beats, "beats resolve to one instant", "COLLAPSE_MULTIPLE_BEATS_TO_SINGLE_REVEAL")
        attributed = {g for bad in facts.invariant_violations.values() for b in bad for g in facts.sync_bad if f"sync group {g} " in b}
        for g, spans in facts.sync_bad.items():
            if g not in attributed:
                add(sid, "INVARIANT", [], f"sync group {g} is not simultaneous {spans}")
        verdict, notes = last_frame(contract, sid, facts)
        if verdict == "FAIL":
            add(sid, "LAST_FRAME", [scene["last_frame_contract"]["required_state_id"]], "; ".join(n for n in notes if n.startswith("FAIL")))
        scenes[sid]["last_frame"] = {"verdict": verdict, "notes": notes}
    for u in timeline.get("unmatched") or []:
        violations.append({"scene_id": None, "type": "ANCHOR_TIMING", "target_ids": [], "detail": f"beat {u.get('beat_id')} unmatched: {u.get('reason')}"})
    return {"violations": violations, "scenes": scenes}
