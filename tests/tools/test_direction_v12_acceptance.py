"""Visual Direction v1.2, Phase 1 — acceptance (fixed before implementation, xfail-strict until it landed).

Fixture: tests/fixtures/direction_v1_2/capital_competition — the SC009 capital
competition scene of the failed production, written as a Director contract
(40/41, copied verbatim from docs/design/visual-direction-v1.2), plus SC010
(locked static evidence) and SC014 (flex b-roll).

Scenarios (all must hold once Phase 1 lands):
  SC009 correct implementation          -> PASS (structural + required review)
  SC009 A02 replaced by a card          -> FAIL
  allocation total 120 / transient 80   -> invariant FAIL
  actions reordered                     -> FAIL
  SC010 static evidence                 -> decided by source identity + 43 ASSET binding, no human review (D16, D17)
  SC014 flex                            -> PASS
  legacy v1.0                           -> unchanged (tests/tools/test_direction_v12_legacy.py)
Principles: 40/41 are the authority; 42/45 coverage is derived and recomputed
every time; no semantic transformation; PIXEL_CHANGE is supporting evidence only.

API under test: docs/design/visual-direction-v1.2/README.md §11.
"""

import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _api():
    from lib.direction_contract import hooks
    return hooks


# --- scenarios: planner output + atelier implementation -------------------------------------------

def _good():
    return _load("visual_direction.good.json")


def _card():
    return _load("visual_direction.as_produced.json")


def _total_120():
    vd = _good()
    next(b for s in vd["scenes"] for b in s.get("beats", []) if b["id"] == "sc16-b4")["params"]["to"] = 30
    return vd


def _transient_80():
    vd = _good()
    next(b for s in vd["scenes"] for b in s.get("beats", []) if b["id"] == "sc16-b3")["narration_anchor"] = "같은 돈이 더 많은 채권 사이로"
    return vd


def _reordered():
    vd = _good()
    for b in next(s for s in vd["scenes"] if s["scene_id"] == "sc17")["beats"]:
        b["narration_anchor"] = "그런데 메타와 아마존이"
    return vd


def _run(visual_direction, atelier="atelier_good", lineage=None, pixel_qa=None, edit=None, contract_path=None):
    h = _api()
    contract = h.load_contract(contract_path or FIX / "40_visual_direction_contract.json", FIX / "41_persistent_visual_models.json")
    script = _load("script.json")
    scene_plan = _load("scene_plan.json")
    edit = edit or _load("edit_decisions.json")
    lineage = lineage or _load("42_direction_lineage.json")
    if contract_path:  # a revised contract: downstream artifacts name the new fingerprint
        for doc in (visual_direction, lineage):
            doc["contract"]["fingerprint"] = h.contract_fingerprint(contract)
    validation = h.validate_contract(contract, script)
    lineage = h.check_lineage(contract, lineage, visual_direction, scene_plan)
    pvm = _load("41_persistent_visual_models.json")
    timeline = h.compile_timeline(visual_direction, _load("alignment.json"),
                                  models=[m["definition"] for m in pvm["models"]], contract=contract)
    windows = {s["id"]: (s["start_seconds"], s["end_seconds"]) for s in scene_plan["scenes"]}
    states = h.check_states(contract, timeline, lineage, windows)
    traces = {"deterministic_graphics": h.build_trace(timeline, FIX / atelier)}
    binding = h.bind(contract, timeline, edit, traces)
    qa = h.qa_report(contract, lineage, visual_direction, timeline, binding, pixel_qa=pixel_qa)
    return {"contract": contract, "validation": validation, "lineage": lineage, "timeline": timeline,
            "states": states, "binding": binding, "qa": qa}


def _scene(qa, scene_id):
    return next(s for s in qa["scenes"] if s["scene_id"] == scene_id)


def _failed(scene, check_type):
    return [c for c in scene["checks"] if c["type"] == check_type and c["role"] == "REQUIRED" and c["result"] == "FAIL"]


def _artifacts(run, review=True, deviations=None):
    arts = {
        "visual_direction_contract": _load("40_visual_direction_contract.json"),
        "persistent_visual_models": _load("41_persistent_visual_models.json"),
        "direction_lineage": run["lineage"],
        "visual_timeline": run["timeline"],
        "execution_binding": run["binding"],
        "direction_qa_report": run["qa"],
        "direction_deviations": deviations or {"version": "1.2", "contract": run["lineage"]["contract"], "deviations": []},
    }
    if review:
        arts["direction_review"] = _load("46_direction_review.good.json")
    return arts


def _gate(run, **kw):
    return _api().completion_gate("compose", "completed", _artifacts(run, **kw), "animated-explainer")


# --- the contract itself ---------------------------------------------------------------------------

def test_contract_is_valid_against_the_authority_script() -> None:
    run = _run(_good())
    assert run["validation"]["errors"] == []


# --- SC009 ---------------------------------------------------------------------------------------

def test_sc009_correct_implementation_passes() -> None:
    run = _run(_good())
    sc = _scene(run["qa"], "SC009")
    assert sc["result"] == "PASS"
    assert sc["receipt"]["verdict"] == "PASS"
    assert sc["receipt"]["omitted"] == []
    assert sc["review_required"] is True
    _gate(run)  # structural QA + the required Direction Review: complete


def test_sc009_correct_implementation_still_needs_the_review() -> None:
    from lib.checkpoint import CheckpointValidationError
    with pytest.raises(CheckpointValidationError):
        _gate(_run(_good()), review=False)


def test_sc009_card_replacement_fails() -> None:
    from lib.checkpoint import CheckpointValidationError
    run = _run(_card(), atelier="atelier_card")
    sc = _scene(run["qa"], "SC009")
    assert sc["result"] == "FAIL"
    assert {"SC009/A02", "SC009/S2"} <= set(sc["receipt"]["omitted"])
    assert _failed(sc, "ACTION_EXISTENCE") and _failed(sc, "STATE_TRANSITION") and _failed(sc, "CAUSAL_CHAIN")
    with pytest.raises(CheckpointValidationError):
        _gate(run)


@pytest.mark.parametrize("variant", [_total_120, _transient_80], ids=["total_120", "transient_80"])
def test_sc009_invariant_violations_fail(variant) -> None:
    sc = _scene(_run(variant())["qa"], "SC009")
    assert sc["result"] == "FAIL"
    assert [c["target_ids"] for c in _failed(sc, "INVARIANT")] == [["SC009/INV01"]]


def test_sc009_reordered_actions_fail() -> None:
    sc = _scene(_run(_reordered())["qa"], "SC009")
    assert sc["result"] == "FAIL"
    assert _failed(sc, "ORDER")


# --- SC010 / SC014 ---------------------------------------------------------------------------------

def _check(scene, check_type):
    return [c for c in scene["checks"] if c["type"] == check_type and c["role"] == "REQUIRED"]


def test_sc010_static_evidence_needs_no_review_and_is_decided_by_source_and_binding() -> None:
    run = _run(_good())
    sc = _scene(run["qa"], "SC010")
    assert sc["review_required"] is False
    assert [c["result"] for c in _check(sc, "SOURCE_EVIDENCE")] == ["PASS"]
    assert [c["result"] for c in _check(sc, "LAST_FRAME")] == ["PASS"]
    assert sc["result"] == "PASS" and sc["receipt"]["verdict"] == "PASS"
    assert not any(c["type"] in ("STATE_TRANSITION", "INVARIANT") and c["target_ids"] == ["SC010/S0"] for c in sc["checks"])
    # the evidence is a 43 ASSET binding of the declaring layer (D16), not a code reference
    sc18 = next(b for b in run["binding"]["bindings"] if b["production_scene_id"] == "sc18")
    assert (sc18["layer"], sc18["status"], sc18["consumes"]["state_ids"]) == ("factual_source", "bound", ["SC010/S0"])
    assert sc18["locator"]["kind"] == "ASSET" and sc18["locator"]["cut_id"] == "c-sc18"


def test_sc010_wrong_source_fails_source_evidence() -> None:
    edit = _load("edit_decisions.json")
    next(c for c in edit["cuts"] if c["scene_id"] == "sc18")["source"] = "assets/evidence/other_bank_table.png"
    sc = _scene(_run(_good(), edit=edit)["qa"], "SC010")
    assert [c["result"] for c in _check(sc, "SOURCE_EVIDENCE")] == ["FAIL"]
    assert sc["result"] == "FAIL"


def test_cut_covering_scene_end_alone_is_not_a_last_frame_pass(tmp_path) -> None:
    contract = _load("40_visual_direction_contract.json")
    sc010 = next(s for s in contract["scenes"] if s["id"] == "SC010")
    sc010["last_frame_contract"]["visible_text"] = ["5년 고정 4.12%"]  # needs the render to judge
    path = tmp_path / "40_visual_direction_contract.json"
    path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    sc = _scene(_run(_good(), contract_path=path)["qa"], "SC010")
    assert [c["result"] for c in _check(sc, "SOURCE_EVIDENCE")] == ["PASS"]
    assert [c["result"] for c in _check(sc, "LAST_FRAME")] == ["UNVERIFIED"]
    assert sc["result"] != "PASS"


def test_bindings_are_per_production_scene_and_layer() -> None:
    good = {b["binding_id"]: b for b in _run(_good())["binding"]["bindings"]}
    for sid, action in (("sc15", "SC009/A01"), ("sc16", "SC009/A02"), ("sc17", "SC009/A03")):
        b = good[f"{sid}/deterministic_graphics"]
        assert b["status"] == "bound" and action in b["consumes"]["action_ids"] and b["locator"]["kind"] == "CODE"
    card = {b["binding_id"]: b for b in _run(_card(), atelier="atelier_card")["binding"]["bindings"]}
    assert card["sc16/deterministic_graphics"]["status"] == "unbound"


def test_sc014_flex_passes() -> None:
    assert _scene(_run(_good())["qa"], "SC014")["result"] == "PASS"


# --- principles ------------------------------------------------------------------------------------

def test_coverage_is_recomputed_not_trusted_from_the_lineage() -> None:
    lineage = _load("42_direction_lineage.json")
    lineage["system_coverage"] = {"computed_by": "check_lineage", "computed_at": "2026-10-03T00:00:00+09:00",
                                  "effective_must_preserve_count": 0, "omitted_locked_ids": []}  # forged
    run = _run(_card(), atelier="atelier_card", lineage=lineage)
    assert "SC009/A02" in run["lineage"]["system_coverage"]["omitted_locked_ids"]  # check_lineage recomputed
    assert "SC009/A02" in _scene(run["qa"], "SC009")["receipt"]["omitted"]          # 45 recomputed independently


def test_semantic_transformation_is_rejected() -> None:
    lineage = _load("42_direction_lineage.json")
    lineage["production_scenes"][1]["transformations"].append({"type": "SEMANTIC_CHANGE", "target_ids": ["SC009/A02"]})
    h = _api()
    contract = h.load_contract(FIX / "40_visual_direction_contract.json", FIX / "41_persistent_visual_models.json")
    # rejected by check_lineage itself (schema enum or semantic check), not by a missing API
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        h.check_lineage(contract, lineage, _good(), _load("scene_plan.json"))


def test_pixel_change_is_supporting_evidence_only() -> None:
    failing_pixels = {"hard_failures": ["ev-sc16-b3: no visible change"], "warnings": []}
    run = _run(_good(), pixel_qa=failing_pixels)
    sc = _scene(run["qa"], "SC009")
    pixel = [c for c in sc["checks"] if c["type"] == "PIXEL_CHANGE"]
    assert pixel and all(c["role"] == "SUPPORTING" for c in pixel)
    assert sc["result"] == "PASS"


def test_proposed_deviation_blocks_completion() -> None:
    from lib.checkpoint import CheckpointValidationError
    run = _run(_good())
    deviations = _load("44_direction_deviations.json")  # DEV001 PROPOSED, MATERIAL
    with pytest.raises(CheckpointValidationError):
        _gate(run, deviations=deviations)


def test_deviation_is_recorded_and_listed(tmp_path) -> None:
    h = _api()
    contract = h.load_contract(FIX / "40_visual_direction_contract.json", FIX / "41_persistent_visual_models.json")
    dev = dict(_load("44_direction_deviations.json")["deviations"][0])
    h.record_deviation(tmp_path, contract, dev)
    assert [d["deviation_id"] for d in h.open_deviations(tmp_path)] == ["DEV001"]
