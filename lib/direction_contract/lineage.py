"""Direction lineage (42): which production scenes carry which locked contract ids — and what is actually there.

``check_lineage`` never trusts the planner's coverage (D13). It recomputes,
for every REQUIRED_LOCKED scene, the effective must_preserve set (D1) minus
what the lineage claims AND the plan implements (beats replayed in document
order: actions present, states reached, invariants kept, order kept), and
writes that as ``system_coverage``. The same ``coverage`` rule runs again in
45 on the compiled timeline and the execution binding.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from lib.direction_contract.contract_v12 import LOCKED, Contract, DirectionContractError
from lib.direction_contract.evaluate import SceneFacts, evaluate_scene, plan_timeline
from schemas.direction_contract import validate as validate_schema

CONSUMED_KINDS = {
    "beat_ids": "beat", "state_ids": "state", "action_ids": "action", "event_ids": "event", "anchor_ids": "anchor",
    "invariant_ids": "invariant", "object_ids": "object", "causal_chain_ids": "causal_chain",
}


def production_map(lineage: dict[str, Any]) -> dict[str, list[str]]:
    """contract scene id -> production scene ids that carry it (42 source_scene_ids)."""
    out: dict[str, list[str]] = {}
    for ps in lineage.get("production_scenes") or []:
        for cid in ps.get("source_scene_ids") or []:
            out.setdefault(cid, []).append(ps["scene_id"])
    return out


def claimed_ids(lineage: dict[str, Any], production_ids: list[str]) -> set[str]:
    ids: set[str] = set()
    for ps in lineage.get("production_scenes") or []:
        if ps["scene_id"] in production_ids:
            for key, values in (ps.get("consumed") or {}).items():
                if key != "pvm_ids":
                    ids |= set(values)
    return ids


@dataclass
class Evidence:
    """What one stage can show for a contract scene; ``coverage`` turns it into implemented ids."""
    facts: SceneFacts
    state_ok: Callable[[str], bool]
    object_ok: Callable[[str], bool]
    anchor_ok: Callable[[str], bool]
    action_ok: Callable[[str], bool]


def invariant_ok(facts: SceneFacts, inv: dict[str, Any]) -> bool:
    if inv["kind"] == "ORDER":
        return facts.order.get(inv["invariant_id"], (False, []))[0]
    return inv["invariant_id"] not in facts.invariant_violations


def causal_ok(contract: Contract, facts: SceneFacts, cc: dict[str, Any], ev: Evidence) -> tuple[bool, str]:
    parts = [cc["cause"]] + list(cc.get("intermediate_reactions") or []) + [cc["effect"]]
    missing = [p["state_id"] for p in parts if not ev.state_ok(p["state_id"])]
    missing += [a for p in parts for a in p.get("actions") or [] if not ev.action_ok(a)]
    starts = []
    for p in parts:
        spans = [facts.action_span(a) for a in p.get("actions") or []]
        spans = [s for s in spans if s]
        if spans:
            starts.append(min(s[0] for s in spans))
    ordered = all(a < b for a, b in zip(starts, starts[1:]))
    if missing:
        return False, f"missing {sorted(set(missing))}"
    if not ordered:
        return False, f"cause → intermediate → effect out of order (starts {starts})"
    return True, "cause, intermediate reactions and effect all happen, in order"


def implemented(contract: Contract, scene_id: str, ev: Evidence) -> set[str]:
    """Contract ids of one scene the evidence shows implemented (before intersecting with claims)."""
    scene = contract.scenes[scene_id]
    facts = ev.facts
    impl: set[str] = set()
    impl |= {a["action_id"] for a in scene.get("actions") or [] if ev.action_ok(a["action_id"])}
    impl |= {s["state_id"] for s in scene.get("states") or [] if ev.state_ok(s["state_id"])}
    impl |= {i["invariant_id"] for i in scene.get("invariants") or [] if invariant_ok(facts, i)}
    impl |= {a["anchor_id"] for a in scene.get("anchors") or [] if ev.anchor_ok(a["anchor_id"])}
    impl |= {o["object_id"] for o in scene.get("objects") or [] if ev.object_ok(o["object_id"])}
    for b in scene.get("beats") or []:
        need_actions = all(a in impl for a in b.get("linked_actions") or [])
        need_state = b.get("visual_state_after") is None or b["visual_state_after"] in impl
        if need_actions and need_state:
            impl.add(b["beat_id"])
    for e in scene.get("events") or []:
        if all(a in impl for a in e.get("actions") or []) and (not e.get("resulting_state") or e["resulting_state"] in impl):
            impl.add(e["event_id"])
    for cc in scene.get("causal_motion_contracts") or []:
        if causal_ok(contract, facts, cc, ev)[0]:
            impl.add(cc["causal_chain_id"])
    return impl


def coverage(contract: Contract, scene_id: str, claimed: set[str], impl: set[str]) -> tuple[list[str], list[str], list[str]]:
    """(effective must_preserve, omitted, claimed_but_not_implemented). An id counts only when claimed AND implemented."""
    effective = set(contract.effective.get(scene_id) or [])
    omitted = sorted(effective - (claimed & impl))
    claimed_bad = sorted((claimed & effective) - impl)
    return sorted(effective), omitted, claimed_bad


def last_frame_elements(contract: Contract, scene_id: str) -> set[str]:
    return set((contract.scenes[scene_id].get("must_preserve") or {}).get("last_frame_elements") or [])


def model_object_visible_at_end(contract: Contract, facts: SceneFacts, object_id: str) -> bool | None:
    """None for an object outside every model."""
    obj = contract.obj(object_id) or {}
    if not obj.get("model_id"):
        return None
    sig = facts.final_signature.get(obj["model_id"])
    if sig is None:
        return False
    return bool(((sig.get("elements") or {}).get(obj["element_id"]) or {}).get("visible"))


def _plan_evidence(contract: Contract, scene_id: str, facts: SceneFacts, claimed: set[str],
                   plan: dict[str, Any], production_ids: list[str]) -> Evidence:
    lf = last_frame_elements(contract, scene_id)
    used_models = {e.get("model_id") for e in plan["events"] if e.get("scene_id") in production_ids}
    used_anchors = {e.get("anchor_id") for e in plan["events"] if e.get("scene_id") in production_ids}

    def state_ok(sid: str) -> bool:
        if contract.is_model_state(sid):
            return facts.reached.get(sid, False)
        return sid in claimed  # outside every model: only the render can show it (binding + source evidence)

    def object_ok(oid: str) -> bool:
        obj = contract.obj(oid) or {}
        if obj.get("model_id"):
            if obj["model_id"] not in used_models:
                return False
            return model_object_visible_at_end(contract, facts, oid) if oid in lf else True
        return oid in claimed

    return Evidence(facts=facts, state_ok=state_ok, object_ok=object_ok,
                    anchor_ok=lambda aid: aid in used_anchors, action_ok=facts.fired)


def check_lineage(contract: Contract, lineage: dict[str, Any], visual_direction: dict[str, Any],
                  scene_plan: dict[str, Any]) -> dict[str, Any]:
    """Return 42 with ``system_coverage`` recomputed from contract, lineage and plan (a planner value is overwritten).

    Raises jsonschema.ValidationError for a 42 the schema rejects (e.g. a
    semantic transformation, D11) and DirectionContractError when 42 or the
    visual_direction belong to another contract or name ids/scenes that do not exist.
    """
    validate_schema("direction_lineage", lineage)
    contract.check_ref("direction_lineage", lineage.get("contract"))
    contract.check_ref("visual_direction", visual_direction.get("contract"))
    plan_ids = {s["id"] for s in scene_plan.get("scenes") or []}
    vd_ids = {s["scene_id"] for s in visual_direction.get("scenes") or []}
    problems: list[str] = []
    for ps in lineage["production_scenes"]:
        psid = ps["scene_id"]
        if psid not in plan_ids:
            problems.append(f"production scene {psid} is not in scene_plan")
        if psid not in vd_ids:
            problems.append(f"production scene {psid} has no visual_direction scene")
        sources = ps.get("source_scene_ids") or []
        for cid in sources:
            if cid not in contract.scenes:
                problems.append(f"{psid}: source scene {cid} is not in the contract")
        for key, values in (ps.get("consumed") or {}).items():
            if key == "pvm_ids":
                problems += [f"{psid}: model {m} is not in persistent_visual_models" for m in values if m not in contract.models]
                continue
            for cid in values:
                if contract.kind(cid) != CONSUMED_KINDS[key]:
                    problems.append(f"{psid}.consumed.{key}: {cid} is not a {CONSUMED_KINDS[key]} of the contract")
                elif contract.scene_of(cid) not in sources:
                    problems.append(f"{psid}.consumed.{key}: {cid} belongs to {contract.scene_of(cid)}, not to {sources}")
        for tr in ps.get("transformations") or []:
            for cid in tr.get("target_ids") or []:
                if contract.scene_of(cid) not in sources:
                    problems.append(f"{psid}: {tr['type']} transformation targets {cid} outside its source scenes")
    if problems:
        raise DirectionContractError("direction_lineage does not fit the contract:\n" + "\n".join(f"  - {p}" for p in problems))

    plan = plan_timeline(contract, visual_direction)
    mapping = production_map(lineage)
    effective_total, omitted_all, claimed_bad_all = 0, [], []
    for sid, scene in contract.scenes.items():
        if scene.get("importance") != LOCKED:
            continue
        prod = mapping.get(sid, [])
        claimed = claimed_ids(lineage, prod)
        facts = evaluate_scene(contract, sid, plan, prod)
        impl = implemented(contract, sid, _plan_evidence(contract, sid, facts, claimed, plan, prod))
        effective, omitted, claimed_bad = coverage(contract, sid, claimed, impl)
        effective_total += len(effective)
        omitted_all += omitted
        claimed_bad_all += claimed_bad
    out = copy.deepcopy(lineage)
    out["system_coverage"] = {
        "computed_by": "check_lineage",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "effective_must_preserve_count": effective_total,
        "omitted_locked_ids": sorted(omitted_all),
        "claimed_but_not_implemented": sorted(claimed_bad_all),
    }
    validate_schema("direction_lineage", out)
    return out
