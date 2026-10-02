"""Completion gate of the v1.2 direction contract (README §10), called from checkpoint_hooks.validate_stage.

Runs only when the checkpoint carries a contract (40); projects without one
keep the v1.0 behaviour. Nothing is taken on trust: lineage coverage, state
checks and the QA report are recomputed here from the artifacts, and a
stored 45 that disagrees with the recomputation is stale.

- scene_plan: LOCKED 40 valid against the script, 42/visual_direction made
  for this contract, recomputed omitted ids empty or under a deviation
  (PROPOSED passes here and blocks compose).
- edit: timeline 1.2 for this contract, locked anchors resolved on their own
  words, check_states clean (deviated ids excepted).
- compose: recomputed 45 PASS for every scene (FAIL only on APPROVED-deviated
  ids), receipts agree with 42, no PROPOSED/REJECTED deviation, and a PASS
  Direction Review (46) for every scene that needs one, on the same render.
"""

from __future__ import annotations

from typing import Any

from jsonschema import ValidationError

from lib.direction_contract.contract_v12 import LOCKED, Contract, DirectionContractError, load_contract, validate_contract
from lib.direction_contract.deviations import exempt_ids
from lib.direction_contract.lineage import check_lineage
from lib.direction_contract.qa import qa_report
from lib.direction_contract.states import check_states
from schemas.direction_contract import validate as validate_schema

CONTRACT_ARTIFACTS = {
    "visual_direction_contract",  # 40 Director contract (authority input)
    "persistent_visual_models",   # 41 project visual models
    "direction_lineage",          # 42 planner lineage + system coverage
    "execution_binding",          # 43 generated binding
    "direction_deviations",       # 44 deviations (user decides)
    "direction_qa_report",        # 45 structural QA + locked receipts
    "direction_review",           # 46 human Direction Review
}
_GATED = {"completed", "awaiting_human"}


def _fail(stage: str, problems: list[str]) -> None:
    from lib.checkpoint import CheckpointValidationError

    raise CheckpointValidationError(
        f"visual direction contract gate ({stage}) — the approved direction is not delivered:\n"
        + "\n".join(f"  - {p}" for p in problems)
    )


def _contract(stage: str, artifacts: dict[str, Any]) -> Contract:
    if not isinstance(artifacts.get("persistent_visual_models"), dict):
        _fail(stage, ["a checkpoint with visual_direction_contract must carry persistent_visual_models (41)"])
    try:
        return load_contract(artifacts["visual_direction_contract"], artifacts["persistent_visual_models"])
    except (ValidationError, DirectionContractError) as exc:
        _fail(stage, [f"visual_direction_contract / persistent_visual_models: {getattr(exc, 'message', exc)}"])
    raise AssertionError("unreachable")


def _scene_windows(scene_plan: dict[str, Any]) -> dict[str, tuple[float, float]]:
    return {s["id"]: (float(s["start_seconds"]), float(s["end_seconds"])) for s in scene_plan.get("scenes") or []
            if "start_seconds" in s and "end_seconds" in s}


def completion_gate(stage: str, status: str, artifacts: dict[str, Any], pipeline_type: str | None) -> None:
    """Raise CheckpointValidationError when a stage would complete without the approved direction."""
    from lib.checkpoint import CheckpointValidationError

    if not isinstance(artifacts.get("visual_direction_contract"), dict) or status not in _GATED:
        return
    contract = _contract(stage, artifacts)
    problems: list[str] = []
    if not contract.locked:
        problems.append(f"contract status is {contract.doc['lifecycle']['status']}: only a LOCKED contract can complete a stage")

    for name in sorted(CONTRACT_ARTIFACTS - {"visual_direction_contract", "persistent_visual_models"}):
        doc = artifacts.get(name)
        if doc is None:
            continue
        try:
            validate_schema(name, doc)
            contract.check_ref(name, doc.get("contract"))
        except (ValidationError, DirectionContractError) as exc:
            problems.append(f"{name}: {getattr(exc, 'message', exc)}")
    for name in ("visual_direction", "visual_timeline"):
        doc = artifacts.get(name)
        if isinstance(doc, dict) and doc.get("version") == "1.2":
            try:
                contract.check_ref(name, doc.get("contract"))
            except DirectionContractError as exc:
                problems.append(str(exc))
    if problems:
        _fail(stage, problems)

    deviations = artifacts.get("direction_deviations")
    approved = exempt_ids(deviations, {"APPROVED"})
    pending = exempt_ids(deviations, {"PROPOSED"})

    def need(*names: str) -> list[Any]:
        missing = [n for n in names if not isinstance(artifacts.get(n), dict)]
        if missing:
            _fail(stage, [f"stage {stage} with a contract needs {missing}"])
        return [artifacts[n] for n in names]

    try:
        if stage == "scene_plan":
            script, scene_plan, direction, lineage = need("script", "scene_plan", "visual_direction", "direction_lineage")
            problems += [f"contract: {e}" for e in validate_contract(contract, script)["errors"]]
            if direction.get("version") != "1.2":
                problems.append("visual_direction must be version 1.2 when a contract exists")
            coverage = check_lineage(contract, lineage, direction, scene_plan)["system_coverage"]
            uncovered = [i for i in coverage["omitted_locked_ids"] if i not in approved | pending]
            if uncovered:
                problems.append(f"locked ids the plan does not implement (no deviation recorded): {uncovered}")
        elif stage == "edit":
            timeline, lineage, scene_plan = need("visual_timeline", "direction_lineage", "scene_plan")
            if timeline.get("version") != "1.2":
                problems.append("visual_timeline must be version 1.2 (compile_timeline with models and contract)")
            else:
                locked_anchors = {a["anchor_id"] for s in contract.scenes.values() if s.get("importance") == LOCKED
                                  for a in s.get("anchors") or []}
                res = timeline.get("anchor_resolution") or {}
                for aid in res.get("unresolved_anchors") or []:
                    if aid in locked_anchors and aid not in approved | pending:
                        problems.append(f"locked anchor {aid} is not resolved in the narration")
                for r in res.get("resolved_anchors") or []:
                    if r["anchor_id"] in locked_anchors and not r.get("same_span", True) and r["anchor_id"] not in approved | pending:
                        problems.append(f"locked anchor {r['anchor_id']} resolved {r['status']} to other words without a deviation")
                for v in check_states(contract, timeline, lineage, _scene_windows(scene_plan))["violations"]:
                    if v["target_ids"] and set(v["target_ids"]) <= approved | pending:
                        continue
                    problems.append(f"{v['scene_id'] or '-'} {v['type']} {v['target_ids']}: {v['detail']}")
        elif stage == "compose":
            lineage, timeline, binding = need("direction_lineage", "visual_timeline", "execution_binding")
            fresh = qa_report(contract, lineage, artifacts.get("visual_direction"), timeline, binding)
            stored = artifacts.get("direction_qa_report")
            if stored is not None and stored.get("verdict") != fresh["verdict"]:
                problems.append(f"direction_qa_report says {stored.get('verdict')} but the artifacts give {fresh['verdict']}: it is stale")
            for scene in fresh["scenes"]:
                sid = scene["scene_id"]
                failed = [c for c in scene["checks"] if c["role"] == "REQUIRED" and c["result"] == "FAIL"]
                unexcused = [c for c in failed if not c["target_ids"] or not set(c["target_ids"]) <= approved]
                for c in unexcused:
                    problems.append(f"{sid} {c['type']} {c['target_ids']} FAIL: {c.get('detail', '')}")
                receipt = scene.get("receipt")
                if receipt:
                    left = [i for i in receipt["omitted"] if i not in approved]
                    if left:
                        problems.append(f"{sid}: locked ids not delivered {left}")
                    if not receipt["lineage_coverage_agrees"]:
                        problems.append(f"{sid}: direction_lineage system_coverage disagrees with the recomputed receipt (stale or edited 42)")
                unverified = [c for c in scene["checks"] if c["role"] == "REQUIRED" and c["result"] == "UNVERIFIED"]
                for c in unverified:
                    problems.append(f"{sid} {c['type']} {c['target_ids']} UNVERIFIED: {c.get('detail', '')}")
            for d in (deviations or {}).get("deviations") or []:
                if d.get("status") in ("PROPOSED", "REJECTED"):
                    problems.append(f"deviation {d['deviation_id']} ({d['scene_id']}) is {d['status']}: the user must decide before completion")
            needs_review = [s["scene_id"] for s in fresh["scenes"] if s["review_required"]]
            review = artifacts.get("direction_review")
            if needs_review:
                if not isinstance(review, dict):
                    problems.append(f"Direction Review (46) required for {needs_review} and missing")
                else:
                    verdicts = {s["scene_id"]: s["verdict"] for s in review.get("scenes") or []}
                    for sid in needs_review:
                        if verdicts.get(sid) != "PASS":
                            problems.append(f"Direction Review of {sid} is {verdicts.get(sid, 'missing')}, PASS required")
                    render = (stored or {}).get("inputs", {}).get("render_sha256")
                    if render and review["render"]["sha256"] != render:
                        problems.append("Direction Review was made on another render than the QA report")
    except CheckpointValidationError:
        raise
    except (ValidationError, DirectionContractError, ValueError) as exc:
        problems.append(str(getattr(exc, "message", exc)))
    if problems:
        _fail(stage, problems)
