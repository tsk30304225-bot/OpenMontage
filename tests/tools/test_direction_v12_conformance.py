"""Visual Direction v1.2 — Phase 1 contract-conformance corrections.

The runtime is brought in line with what the shipped 40/41 schemas already say;
no schema field is added or changed.

X1  41 transitions: absent or [] = unrestricted, a non-empty list is an allowlist.
X2  41 handoffs: from_scene ends in the state AND to_scene starts from it (ENTRY_SIGNATURE).
Action completion: the end of the last timeline operation; completion_state_id, completion_condition
and must_execute false are unsupported in v1.2 (contract errors).
Event completion_condition is unsupported in v1.2 as well.
"""

import json
from pathlib import Path

import pytest

from lib.direction_contract import hooks as h

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _errors(doc_40, doc_41):
    return h.validate_contract(h.load_contract(doc_40, doc_41), _load("script.json"))["errors"]


# --- X1: transitions ---------------------------------------------------------------------------------

def _with_transitions(transitions):
    pvm = _load("41_persistent_visual_models.json")
    if transitions is None:
        pvm["models"][0].pop("transitions", None)
    else:
        pvm["models"][0]["transitions"] = transitions
    return pvm


def _transition_errors(errors):
    return [e for e in errors if "is not a transition of" in e]


def test_absent_transitions_allow_any_move_between_named_states() -> None:
    assert _transition_errors(_errors(_load("40_visual_direction_contract.json"), _with_transitions(None))) == []


def test_empty_transitions_allow_any_move_between_named_states() -> None:
    assert _transition_errors(_errors(_load("40_visual_direction_contract.json"), _with_transitions([]))) == []


def test_listed_transitions_are_allowed() -> None:
    pvm = _load("41_persistent_visual_models.json")
    assert pvm["models"][0]["transitions"]
    assert _transition_errors(_errors(_load("40_visual_direction_contract.json"), pvm)) == []


def test_a_move_missing_from_a_non_empty_allowlist_is_a_contract_error() -> None:
    pvm = _with_transitions([{"from": "BASE", "to": "MORE_SUPPLY"}, {"from": "MORE_SUPPLY", "to": "REALLOCATED"}])
    errors = _transition_errors(_errors(_load("40_visual_direction_contract.json"), pvm))
    assert len(errors) == 1
    assert "SC009/A03: CAPITAL_FLOW.REALLOCATED -> CAPITAL_FLOW.YIELD_PRESSURE" in errors[0]


# --- X2: handoff = cross-scene continuity (A semantics) ----------------------------------------------
# A 41 handoff means: the state holds when from_scene ends AND to_scene starts from it. to_scene declares
# the model (HIDDEN_BUT_ACTIVE when off screen); the inheritance is checked on the ENTRY_SIGNATURE —
# the replayed state before the scene's own first operation.

def _handoff_case(state="YIELD_PRESSURE", visibility="HIDDEN_BUT_ACTIVE", enter_state=None, declare=True, **persistence):
    doc_40, doc_41 = _load("40_visual_direction_contract.json"), _load("41_persistent_visual_models.json")
    model = doc_41["models"][0]
    model["handoffs"] = [{"from_scene": "SC009", "to_scene": "SC010", "state": state}]
    model["persistence"].update({"last_scene": "SC010", **persistence})
    if declare:
        entry = {"model_id": "CAPITAL_FLOW", "visibility": visibility}
        if enter_state:
            entry["enter_state"] = enter_state
        next(s for s in doc_40["scenes"] if s["id"] == "SC010")["models"] = [entry]
    return doc_40, doc_41


def _handoff_errors(errors):
    return [e for e in errors if "handoff" in e]


def test_declared_hidden_handoff_is_a_valid_contract() -> None:
    assert _errors(*_handoff_case()) == []


def test_handoff_destination_must_declare_the_model() -> None:
    errors = _handoff_errors(_errors(*_handoff_case(declare=False)))
    assert len(errors) == 1 and "SC010 does not declare CAPITAL_FLOW in models" in errors[0]


def test_handoff_destination_enter_state_must_be_the_handed_off_state() -> None:
    assert _errors(*_handoff_case(enter_state="CAPITAL_FLOW.YIELD_PRESSURE")) == []
    errors = _handoff_errors(_errors(*_handoff_case(enter_state="CAPITAL_FLOW.BASE")))
    assert len(errors) == 1 and "enter_state CAPITAL_FLOW.BASE is not the handed-off CAPITAL_FLOW.YIELD_PRESSURE" in errors[0]


def test_handoff_destination_initial_model_state_must_be_the_handed_off_state() -> None:
    doc_40, doc_41 = _handoff_case()
    sc010 = next(s for s in doc_40["scenes"] if s["id"] == "SC010")
    sc010["states"].append({"state_id": "SC010/S_MODEL", "semantic_meaning": "model as handed over", "pvm_state": "CAPITAL_FLOW.BASE"})
    sc010["initial_state"] = "SC010/S_MODEL"
    errors = _handoff_errors(_errors(doc_40, doc_41))
    assert len(errors) == 1 and "initial_state is CAPITAL_FLOW.BASE" in errors[0]


def test_handoff_must_lie_inside_the_model_persistence() -> None:
    errors = _handoff_errors(_errors(*_handoff_case(last_scene="SC009")))
    assert len(errors) == 1 and "last_scene SC009 ends before to_scene" in errors[0]
    errors = _handoff_errors(_errors(*_handoff_case(first_scene="SC010")))
    assert len(errors) == 1 and "first_scene SC010 starts after from_scene" in errors[0]


def test_handoff_must_point_forward_to_a_named_state() -> None:
    doc_40, doc_41 = _handoff_case(state="NO_SUCH_STATE")
    doc_41["models"][0]["handoffs"].append({"from_scene": "SC010", "to_scene": "SC009", "state": "BASE"})
    errors = _handoff_errors(_errors(doc_40, doc_41))
    assert any("NO_SUCH_STATE is not a named state" in e for e in errors)
    assert any("SC010 -> SC009: to_scene must come after from_scene" in e for e in errors)


def test_hidden_handoff_needs_a_model_that_survives_hidden() -> None:
    errors = _handoff_errors(_errors(*_handoff_case(survives_hidden=False)))
    assert len(errors) == 1 and "HIDDEN_BUT_ACTIVE but persistence.survives_hidden is false" in errors[0]
    assert _handoff_errors(_errors(*_handoff_case(visibility="VISIBLE", survives_hidden=False))) == []


# --- X2: destination start is judged on the ENTRY_SIGNATURE (45) -------------------------------------

def _run_with(doc_40, doc_41, tmp_path):
    """The acceptance pipeline (good plan, good atelier) against a revised 40/41."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_direction_v12_acceptance as acc
    p40, p41 = tmp_path / "40.json", tmp_path / "41.json"
    p40.write_text(json.dumps(doc_40, ensure_ascii=False), encoding="utf-8")
    p41.write_text(json.dumps(doc_41, ensure_ascii=False), encoding="utf-8")
    contract = h.load_contract(p40, p41)
    vd, lineage = acc._good(), _load("42_direction_lineage.json")
    for doc in (vd, lineage):
        doc["contract"]["fingerprint"] = h.contract_fingerprint(contract)
    scene_plan = _load("scene_plan.json")
    lineage = h.check_lineage(contract, lineage, vd, scene_plan)
    timeline = h.compile_timeline(vd, _load("alignment.json"), models=contract.definitions(), contract=contract)
    binding = h.bind(contract, timeline, _load("edit_decisions.json"), {"deterministic_graphics": h.build_trace(timeline, FIX / "atelier_good")})
    return contract, timeline, h.qa_report(contract, lineage, vd, timeline, binding)


def _persistent_rows(qa, scene_id):
    scene = next(s for s in qa["scenes"] if s["scene_id"] == scene_id)
    return [c for c in scene["checks"] if c["type"] == "PERSISTENT_STATE"
            and ("hands" in c.get("detail", "") or "enters from" in c.get("detail", ""))]


def test_hidden_destination_inherits_the_handed_off_state(tmp_path) -> None:
    _, _, qa = _run_with(*_handoff_case(), tmp_path)
    (exit_row,) = _persistent_rows(qa, "SC009")
    (entry_row,) = _persistent_rows(qa, "SC010")
    assert exit_row["result"] == "PASS"
    assert entry_row["result"] == "PASS" and "enters from SC009 in YIELD_PRESSURE" in entry_row["detail"]
    assert next(s for s in qa["scenes"] if s["scene_id"] == "SC010")["result"] == "PASS"


def test_destination_that_does_not_start_in_the_handed_off_state_fails(tmp_path) -> None:
    _, _, qa = _run_with(*_handoff_case(state="BASE"), tmp_path)
    (entry_row,) = _persistent_rows(qa, "SC010")
    assert entry_row["result"] == "FAIL" and "does not hold before the scene's first operation" in entry_row["detail"]
    assert entry_row["violation"] == "REPLACE_PVM_WITH_UNRELATED_BROLL"


@pytest.mark.parametrize("lead", [0.0, 0.25])
def test_entry_signature_excludes_an_action_at_the_first_anchor(tmp_path, lead) -> None:
    """A scene whose first operation fires at (or just before) its window start still enters in the prior state."""
    from lib.direction_contract.contract_v12 import assertion_holds
    from lib.direction_contract.evaluate import evaluate_scene
    from lib.direction_contract.lineage import production_map
    contract, timeline, _ = _run_with(_load("40_visual_direction_contract.json"), _load("41_persistent_visual_models.json"), tmp_path)
    prod = production_map(_load("42_direction_lineage.json"))["SC009"]
    own = sorted(e["time_seconds"] for e in timeline["events"] if e.get("scene_id") in prod and e.get("model_id") == "CAPITAL_FLOW")
    t0 = own[0]
    facts = evaluate_scene(contract, "SC009", timeline, prod, window=(t0 + lead, own[-1] + 5.0))
    base, supply = contract.named_state("CAPITAL_FLOW.BASE"), contract.named_state("CAPITAL_FLOW.MORE_SUPPLY")
    entry = facts.entry_signature["CAPITAL_FLOW"]
    assert all(assertion_holds(a, entry) for a in base)
    assert not all(assertion_holds(a, entry) for a in supply)


# --- action completion (v1.2) ------------------------------------------------------------------------
# An action completes when its last timeline operation ends. Reaching to_state_id is a separate check
# (STATE_TRANSITION). completion_state_id / completion_condition are reserved and unsupported;
# must_execute is required-only (omitted or true).

def _with_a02(**fields):
    doc_40 = _load("40_visual_direction_contract.json")
    next(a for a in doc_40["scenes"][0]["actions"] if a["action_id"] == "SC009/A02").update(fields)
    return doc_40


def _completion_errors(errors):
    return [e for e in errors if "SC009/A02" in e and ("reserved" in e or "must_execute" in e)]


@pytest.mark.parametrize("fields", [{}, {"must_execute": True}])
def test_omitted_or_true_must_execute_is_a_valid_contract(fields) -> None:
    assert _errors(_with_a02(**fields), _load("41_persistent_visual_models.json")) == []


@pytest.mark.parametrize("fields, needle", [
    ({"completion_state_id": "SC009/S2"}, "completion_state_id is reserved and unsupported"),
    ({"completion_condition": "the bars settle"}, "completion_condition is reserved and unsupported"),
    ({"must_execute": False}, "must_execute false is unsupported"),
])
def test_unsupported_completion_fields_are_contract_errors(fields, needle) -> None:
    errors = _completion_errors(_errors(_with_a02(**fields), _load("41_persistent_visual_models.json")))
    assert len(errors) == 1 and needle in errors[0]


def test_action_completes_when_its_last_timeline_operation_ends(tmp_path) -> None:
    """dependency.after {on: complete} is measured against the end of the action's LAST operation."""
    from lib.direction_contract.evaluate import evaluate_scene
    from lib.direction_contract.lineage import production_map
    contract, timeline, _ = _run_with(_load("40_visual_direction_contract.json"), _load("41_persistent_visual_models.json"), tmp_path)
    prod = production_map(_load("42_direction_lineage.json"))["SC009"]
    a01 = [e for e in timeline["events"] if e.get("action_id") == "SC009/A01"]
    first_end = min(e["time_seconds"] + e["duration_seconds"] for e in a01)
    last_end = max(e["time_seconds"] + e["duration_seconds"] for e in a01)
    assert len(a01) > 1 and first_end < last_end

    def a02_starting_at(t):
        moved = json.loads(json.dumps(timeline))
        ops = [e for e in moved["events"] if e.get("action_id") == "SC009/A02"]
        shift = t - min(e["time_seconds"] for e in ops)
        for e in ops:
            e["time_seconds"] = round(e["time_seconds"] + shift, 6)
        facts = evaluate_scene(contract, "SC009", moved, prod)
        return [d for d in facts.dependency_violations if d.startswith("SC009/A02")]

    early = a02_starting_at((first_end + last_end) / 2)  # after A01's first operation, before its last one ends
    assert len(early) == 1 and f"before SC009/A01 completes ({last_end:g}s)" in early[0]
    assert a02_starting_at(last_end) == []


# --- event completion_condition (v1.2: reserved, unsupported) ---------------------------------------

def test_events_without_completion_condition_stay_valid() -> None:
    doc_40 = _load("40_visual_direction_contract.json")
    assert all("completion_condition" not in e for e in doc_40["scenes"][0]["events"])
    assert _errors(doc_40, _load("41_persistent_visual_models.json")) == []


def test_event_completion_condition_is_a_contract_error() -> None:
    doc_40 = _load("40_visual_direction_contract.json")
    doc_40["scenes"][0]["events"][1]["completion_condition"] = "the bars settle"
    errors = [e for e in _errors(doc_40, _load("41_persistent_visual_models.json")) if "completion_condition" in e]
    assert errors == ["SC009/E02: completion_condition is reserved and unsupported in v1.2"]
