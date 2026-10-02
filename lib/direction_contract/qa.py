"""Structural Direction QA (45) with the locked lineage receipt.

``qa_report`` works from the original artifacts — contract, lineage, the
compiled timeline and the execution binding — never from earlier verdicts.
For every locked scene it recomputes coverage itself (D13: what 42 claims AND
the timeline + binding show) and records whether 42's system_coverage agrees.
REQUIRED checks decide a scene; PIXEL_CHANGE (the existing pixel check) is
SUPPORTING evidence only and never makes a scene pass or fail (D12). A scene
that needs a human Direction Review can pass here and still be incomplete:
that is the completion gate's job (46).
"""

from __future__ import annotations

from typing import Any

from lib.direction_contract.authority import canonical_json_sha256, source_identical
from lib.direction_contract.binding.execution import bound_ids
from lib.direction_contract.contract_v12 import FLEX, LOCKED, Contract, DirectionContractError, assertion_holds
from lib.direction_contract.evaluate import EPS, evaluate_scene
from lib.direction_contract.lineage import (
    Evidence,
    causal_ok,
    claimed_ids,
    coverage,
    implemented,
    invariant_ok,
    last_frame_elements,
    model_object_visible_at_end,
    production_map,
)
from lib.direction_contract.states import last_frame, scene_window
from schemas.direction_contract import validate as validate_schema

_TALLY = {"beat": "beats", "state": "states", "action": "actions", "event": "events", "anchor": "anchors"}


def _worst(results: list[str]) -> str:
    return "FAIL" if "FAIL" in results else ("UNVERIFIED" if "UNVERIFIED" in results else "PASS")


def qa_report(contract: Contract, lineage: dict[str, Any], visual_direction: dict[str, Any] | None,
              timeline: dict[str, Any], binding: dict[str, Any], pixel_qa: dict[str, Any] | None = None) -> dict[str, Any]:
    contract.check_ref("direction_lineage", lineage.get("contract"))
    contract.check_ref("visual_timeline", timeline.get("contract"))
    contract.check_ref("execution_binding", binding.get("contract"))
    if visual_direction is not None:
        contract.check_ref("visual_direction", visual_direction.get("contract"))
    if binding.get("timeline_sha256") != canonical_json_sha256(timeline):
        raise DirectionContractError("execution_binding was made from another visual_timeline (timeline_sha256 differs): run bind() again")

    mapping = production_map(lineage)
    windows = {w["production_scene_id"]: (w["start_seconds"], w["end_seconds"]) for w in binding.get("scene_windows") or []}
    resolved = {r["anchor_id"]: r for r in (timeline.get("anchor_resolution") or {}).get("resolved_anchors") or []}
    bound = bound_ids(binding)
    assets = [b for b in binding.get("bindings") or [] if (b.get("locator") or {}).get("kind") == "ASSET"]
    lineage_omitted = (lineage.get("system_coverage") or {}).get("omitted_locked_ids")
    pixel_failures = [str(h) for h in (pixel_qa or {}).get("hard_failures") or []]

    scenes_out = []
    for sid, scene in contract.scenes.items():
        importance = scene.get("importance")
        prod = mapping.get(sid, [])
        window = scene_window(prod, windows)
        facts = evaluate_scene(contract, sid, timeline, prod, window)
        lo, hi = facts.window
        checks: list[dict[str, Any]] = []

        def add(kind: str, result: str, targets: list[str], detail: str = "", *, role: str = "REQUIRED",
                violation: str | None = None, time: float | None = None) -> dict[str, Any]:
            row: dict[str, Any] = {"check_id": f"{sid}/Q{len(checks) + 1:02d}", "type": kind, "role": role,
                                   "target_ids": targets, "result": result}
            if detail:
                row["detail"] = detail
            if violation and result == "FAIL":
                row["violation"] = violation
            if time is not None:
                row["time_seconds"] = round(max(0.0, time), 6)
            checks.append(row)
            return row

        claimed = claimed_ids(lineage, prod)
        preserve_anchors = set((scene.get("must_preserve") or {}).get("narration_anchors") or [])
        used_anchors = {e.get("anchor_id") for e in facts.events}

        # --- anchors ------------------------------------------------------------------------
        for a in scene.get("anchors") or []:
            aid = a["anchor_id"]
            r = resolved.get(aid)
            if r is None:
                add("ANCHOR_TIMING", "FAIL", [aid], "not resolved in the aligned narration")
            elif not r.get("same_span", True):
                add("ANCHOR_TIMING", "FAIL", [aid], f"resolved {r['status']} to other words", time=r["start_time"])
            elif importance == LOCKED and aid in preserve_anchors and aid not in used_anchors:
                add("ANCHOR_TIMING", "FAIL", [aid], "preserved anchor drives no operation in the scene window", time=r["start_time"])
            else:
                add("ANCHOR_TIMING", "PASS", [aid], f"{r['status']} at {r['start_time']:g}s", time=r["start_time"])

        if importance == LOCKED:
            def binding_ok(cid: str) -> bool:
                layers = contract.declaring_layers(sid, cid)
                return not layers or all((bound.get(cid) or {}).get(layer) in ("bound", "deviated") for layer in layers)

            def source_active(oid: str) -> tuple[bool | None, float | None]:
                asset = (contract.obj(oid) or {}).get("source_asset")
                if not asset:
                    return None, None
                hits = [b for b in assets if b["status"] == "bound" and b["production_scene_id"] in prod
                        and source_identical(asset, b["locator"]["source_asset_ref"])]
                covering = [b for b in hits if b["locator"].get("in_seconds", 0) <= hi + EPS and b["locator"].get("out_seconds", 0) >= hi - EPS]
                if not covering:
                    return False, None
                return True, max(lo, min(b["locator"]["in_seconds"] for b in covering))

            # --- actions ------------------------------------------------------------------
            for a in scene.get("actions") or []:
                aid = a["action_id"]
                fired_in = sorted({e["scene_id"] for e in facts.action_events.get(aid) or []})
                claimed_in = [p for p in prod if aid in claimed_ids(lineage, [p])]
                ok = bool(fired_in) and set(claimed_in) <= set(fired_in)
                span = facts.action_span(aid)
                add("ACTION_EXISTENCE", "PASS" if ok else "FAIL", [aid],
                    f"lineage {claimed_in or '-'}, operations in {fired_in or '-'}", violation="REMOVE_REQUIRED_ACTION",
                    time=span[0] if span else None)

            # --- states -------------------------------------------------------------------
            source_ok: dict[str, bool] = {}
            for st in scene.get("states") or []:
                stid = st["state_id"]
                if contract.is_model_state(stid):
                    ok = facts.reached.get(stid, False)
                    add("STATE_TRANSITION", "PASS" if ok else "FAIL", [stid], facts.state_detail.get(stid, ""),
                        violation="REMOVE_INTERMEDIATE_STATE", time=facts.reached_at.get(stid) if ok else None)
                    continue
                results, notes = [], []
                for oid in st.get("visible_objects") or []:
                    obj = contract.obj(oid) or {}
                    if obj.get("truth_class") != "SOURCE" and not obj.get("source_asset"):
                        continue
                    asset = obj.get("source_asset")
                    if not asset:
                        results.append("UNVERIFIED")
                        notes.append(f"{oid} has no source_asset to compare")
                        continue
                    placed = [b for b in assets if b["production_scene_id"] in prod and stid in b["consumes"].get("state_ids", [])]
                    same = [b for b in placed if b["status"] == "bound" and source_identical(asset, b["locator"]["source_asset_ref"])]
                    if same:
                        results.append("PASS")
                        notes.append(f"{oid}: cut {same[0]['locator']['cut_id']} places {same[0]['locator']['source_asset_ref']} = {asset}")
                    else:
                        results.append("FAIL")
                        shown = [b["locator"]["source_asset_ref"] for b in placed]
                        notes.append(f"{oid}: contract source {asset}, cuts show {shown or 'nothing'}")
                verdict = _worst(results) if results else "UNVERIFIED"
                if not results:
                    notes.append("no source object to compare; needs the render")
                source_ok[stid] = verdict == "PASS"
                add("SOURCE_EVIDENCE", verdict, [stid], "; ".join(notes))

            # --- invariants, order, simplifications ---------------------------------------
            for inv in scene.get("invariants") or []:
                iid = inv["invariant_id"]
                if inv["kind"] == "ORDER":
                    ok, seq = facts.order.get(iid, (False, []))
                    add("ORDER", "PASS" if ok else "FAIL", list(inv["order"]), f"times {seq}", violation="REORDER_LOCKED_ACTIONS")
                else:
                    bad = facts.invariant_violations.get(iid)
                    add("INVARIANT", "FAIL" if bad else "PASS", [iid], "; ".join((bad or [])[:4]) or "holds after every sync group",
                        violation="ALTER_INVARIANT")
            for d in facts.dependency_violations:
                add("ORDER", "FAIL", [d.split(" ")[0]], d, violation="REORDER_LOCKED_ACTIONS")
            for a in scene.get("actions") or []:
                if a.get("min_duration_seconds") and facts.fired(a["action_id"]):
                    why = facts.merged.get(a["action_id"])
                    add("PROHIBITED_SIMPLIFICATION", "FAIL" if why else "PASS", [a["action_id"]],
                        why or f"runs at least {a['min_duration_seconds']}s", violation="MERGE_LOCKED_ACTIONS")
            if facts.collapsed_beats:
                add("PROHIBITED_SIMPLIFICATION", "FAIL", facts.collapsed_beats, "beats resolve to one instant",
                    violation="COLLAPSE_MULTIPLE_BEATS_TO_SINGLE_REVEAL")

            def state_ok(stid: str) -> bool:
                ok = facts.reached.get(stid, False) if contract.is_model_state(stid) else source_ok.get(stid, False)
                return ok and binding_ok(stid)

            def action_ok(aid: str) -> bool:
                return any(c["type"] == "ACTION_EXISTENCE" and c["target_ids"] == [aid] and c["result"] == "PASS" for c in checks) \
                    and binding_ok(aid)

            lf_elements = last_frame_elements(contract, sid)
            timeline_models = {e.get("model_id") for e in facts.events}

            def object_ok(oid: str) -> bool:
                obj = contract.obj(oid) or {}
                if obj.get("model_id"):
                    if obj["model_id"] not in timeline_models:
                        return False
                    return bool(model_object_visible_at_end(contract, facts, oid)) if oid in lf_elements else True
                if obj.get("source_asset"):
                    active, _ = source_active(oid)
                    placed = any(b["status"] == "bound" and b["production_scene_id"] in prod
                                 and source_identical(obj["source_asset"], b["locator"]["source_asset_ref"]) for b in assets)
                    return bool(active) if oid in lf_elements else placed
                return oid in claimed

            ev = Evidence(facts=facts, state_ok=state_ok, object_ok=object_ok, action_ok=action_ok,
                          anchor_ok=lambda aid: any(c["type"] == "ANCHOR_TIMING" and c["target_ids"] == [aid]
                                                    and c["result"] == "PASS" for c in checks))
            for cc in scene.get("causal_motion_contracts") or []:
                ok, why = causal_ok(contract, facts, cc, ev)
                add("CAUSAL_CHAIN", "PASS" if ok else "FAIL", [cc["causal_chain_id"]], why, violation="REPLACE_CAUSAL_MODEL_WITH_TEXT")

            lf_verdict, lf_notes = last_frame(contract, sid, facts, source_active)
            lf_target = [scene["last_frame_contract"]["required_state_id"]] if scene.get("last_frame_contract") else []
            add("LAST_FRAME", lf_verdict, lf_target, "; ".join(lf_notes), time=hi)

            for h in contract.models.values():
                for handoff in h.get("handoffs") or []:
                    if handoff.get("from_scene") != sid:
                        continue
                    mid = h["definition"]["id"]
                    sig = facts.final_signature.get(mid)
                    ok = sig is not None and all(assertion_holds(a, sig) for a in contract.named_state(f"{mid}.{handoff['state']}"))
                    add("PERSISTENT_STATE", "PASS" if ok else "FAIL", [],
                        f"{mid} hands {handoff['state']} to {handoff.get('to_scene')}: {'holds' if ok else 'does not hold'} at scene end",
                        violation="REPLACE_PVM_WITH_UNRELATED_BROLL", time=hi)
            for mid in (scene.get("must_preserve") or {}).get("persistent_models") or []:
                ok = mid in timeline_models
                add("PERSISTENT_STATE", "PASS" if ok else "FAIL", [], f"persistent model {mid} {'runs' if ok else 'does not run'} in the scene",
                    violation="REPLACE_PVM_WITH_UNRELATED_BROLL")

            declared = sorted({cid for ids in (contract.layer_consumes.get(sid) or {}).values() for cid in ids})
            for cid in declared:
                statuses = {layer: (bound.get(cid) or {}).get(layer, "missing") for layer in contract.declaring_layers(sid, cid)}
                ok = all(s in ("bound", "deviated") for s in statuses.values())
                add("BINDING", "PASS" if ok else "FAIL", [cid], ", ".join(f"{k}: {v}" for k, v in statuses.items()),
                    violation="REMOVE_REQUIRED_ACTION" if contract.kind(cid) == "action" else None)

            if scene.get("actions"):
                ids = {e["id"] for e in facts.events}
                mine = [h for h in pixel_failures if any(i in h for i in ids)]
                result = "UNVERIFIED" if pixel_qa is None else ("FAIL" if mine else "PASS")
                add("PIXEL_CHANGE", result, [a["action_id"] for a in scene["actions"]],
                    "supporting evidence only" + (f": {mine[:3]}" if mine else ""), role="SUPPORTING")

            # --- receipt -----------------------------------------------------------------
            impl = implemented(contract, sid, ev)
            effective, omitted, _ = coverage(contract, sid, claimed, impl)
            done = claimed & impl
            expected: dict[str, list[str]] = {v: [] for v in _TALLY.values()}
            got: dict[str, list[str]] = {v: [] for v in _TALLY.values()}
            for cid in effective:
                key = _TALLY.get(contract.kind(cid) or "")
                if key:
                    expected[key].append(cid)
                    if cid in done:
                        got[key].append(cid)
            verdicts = {t: _worst([c["result"] for c in checks if c["type"] == t and c["role"] == "REQUIRED"] or ["PASS"])
                        for t in ("INVARIANT", "CAUSAL_CHAIN", "LAST_FRAME", "BINDING")}
            mine_42 = sorted(i for i in lineage_omitted or [] if contract.scene_of(i) == sid)
            agrees = lineage_omitted is not None and mine_42 == omitted
            receipt = {
                "effective_must_preserve": effective,
                "expected": expected,
                "implemented": got,
                "omitted": omitted,
                "merged": sorted(facts.merged),
                "reordered": sorted({x for c in checks if c["type"] == "ORDER" and c["result"] == "FAIL" for x in c["target_ids"]}),
                "unresolved_anchors": sorted(a["anchor_id"] for a in scene.get("anchors") or [] if a["anchor_id"] not in resolved),
                "invariant_checks": verdicts["INVARIANT"],
                "causal_contract": verdicts["CAUSAL_CHAIN"],
                "last_frame": verdicts["LAST_FRAME"],
                "binding": verdicts["BINDING"],
                "lineage_coverage_agrees": agrees,
            }
            parts = [receipt[k] for k in ("invariant_checks", "causal_contract", "last_frame", "binding")]
            required = [c["result"] for c in checks if c["role"] == "REQUIRED"]
            receipt["verdict"] = "FAIL" if omitted or not agrees else _worst(parts + required)
        else:
            receipt = None
            if importance == FLEX:
                rendered = [p for p in prod if p in windows]
                add("BINDING", "PASS" if rendered else "FAIL", [],
                    f"production scenes {prod or '-'} rendered as {rendered or '-'}" if prod else "no production scene carries this scene")
                for tr in scene.get("pvm_transitions") or []:
                    sig = facts.final_signature.get(tr["model_id"])
                    ok = sig is not None and all(assertion_holds(a, sig) for a in contract.named_state(tr["to"]))
                    add("STATE_TRANSITION", "PASS" if ok else "FAIL", [], f"{tr['model_id']} reaches {tr['to']} by scene end")
                for truth in scene.get("truth_requirements") or []:
                    if truth.get("source"):
                        add("SOURCE_EVIDENCE", "UNVERIFIED", [], f"{truth['statement']!r} from {truth['source']}: not bound for a non-locked scene")

        # --- handoff destination: the scene starts from the handed-off state (any importance) -------
        for h in contract.models.values():
            for handoff in h.get("handoffs") or []:
                if handoff.get("to_scene") != sid:
                    continue
                mid = h["definition"]["id"]
                sig = facts.entry_signature.get(mid)
                ok = sig is not None and all(assertion_holds(a, sig) for a in contract.named_state(f"{mid}.{handoff['state']}"))
                add("PERSISTENT_STATE", "PASS" if ok else "FAIL", [],
                    f"{mid} enters from {handoff.get('from_scene')} in {handoff['state']}: "
                    f"{'holds' if ok else ('not on the timeline' if sig is None else 'does not hold')} before the scene's first operation",
                    violation="REPLACE_PVM_WITH_UNRELATED_BROLL", time=lo)

        required = [c["result"] for c in checks if c["role"] == "REQUIRED"]
        result = _worst(required + ([receipt["verdict"]] if receipt else []))
        row = {"scene_id": sid, "importance": importance, "checks": checks,
               "review_required": contract.review_required[sid], "result": result}
        if receipt is not None:
            row["receipt"] = receipt
        scenes_out.append(row)

    inputs = {"timeline_sha256": canonical_json_sha256(timeline), "lineage_sha256": canonical_json_sha256(lineage),
              "binding_sha256": canonical_json_sha256(binding)}
    if visual_direction is not None:
        inputs["visual_direction_sha256"] = canonical_json_sha256(visual_direction)
    report = {"version": "1.2", "contract": contract.ref, "inputs": inputs, "scenes": scenes_out,
              "verdict": _worst([s["result"] for s in scenes_out])}
    validate_schema("direction_qa_report", report)
    return report
