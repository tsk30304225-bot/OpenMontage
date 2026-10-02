"""Visual Direction v1.2 — Phase 1 contract-conformance corrections.

The runtime is brought in line with what the shipped 40/41 schemas already say;
no schema field is added or changed.

X1  41 transitions: absent or [] = unrestricted, a non-empty list is an allowlist.
"""

import copy
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
