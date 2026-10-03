"""Director Authoring Bridge: human authoring document -> canonical 40 (director-authoring-guide.md section 8).

Acceptance: the capital-competition authoring source compiles to exactly the canonical example 40
(lifecycle clock fixed), and every rule the guide makes an error is rejected with its code.
"""

import json
import sys
from pathlib import Path

import pytest

from lib.direction_contract.authoring import AuthoringError, compile_authoring
from lib.direction_contract.authoring.syntax import parse_authoring

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"
EXAMPLE = REPO / "docs" / "design" / "visual-direction-v1.2" / "examples" / "capital-competition"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


SOURCE = (FIX / "40_visual_direction_contract.md").read_text(encoding="utf-8")
CANONICAL = _load("40_visual_direction_contract.json")
LIFECYCLE = CANONICAL["lifecycle"]


def _compile(text=SOURCE, pvm=None, script=None, **kw):
    kw.setdefault("revision", LIFECYCLE["revision"])
    kw.setdefault("generated_at", LIFECYCLE["generated_at"])
    kw.setdefault("lock", {"by": LIFECYCLE["locked_by"], "at": LIFECYCLE["locked_at"]})
    return compile_authoring(text, pvm or _load("41_persistent_visual_models.json"), script or _load("script.json"), **kw)


def _edit(*pairs, text=SOURCE):
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def _codes(text, **kw):
    with pytest.raises(AuthoringError) as exc:
        _compile(text, **kw)
    return exc.value.codes, str(exc.value)


def _scene(doc, sid):
    return next(s for s in doc["scenes"] if s["id"] == sid)


# --- acceptance: the canonical example is the Bridge output -----------------------------------------

def test_capital_competition_source_compiles_to_the_canonical_40() -> None:
    assert _compile() == CANONICAL


def test_fixture_and_design_example_are_the_same_source_and_contract() -> None:
    assert (EXAMPLE / "40_visual_direction_contract.md").read_text(encoding="utf-8") == SOURCE
    assert json.loads((EXAMPLE / "40_visual_direction_contract.json").read_text(encoding="utf-8")) == CANONICAL


def test_compilation_is_deterministic() -> None:
    first, second = _compile(), _compile()
    assert json.dumps(first, ensure_ascii=False, indent=2) == json.dumps(second, ensure_ascii=False, indent=2)


def test_bridge_output_runs_the_phase1_pipeline(tmp_path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_direction_v12_acceptance as acc
    path = tmp_path / "40.json"
    path.write_text(json.dumps(_compile(), ensure_ascii=False), encoding="utf-8")
    run = acc._run(acc._good(), contract_path=path)
    assert run["validation"]["errors"] == []
    assert {s["scene_id"]: s["result"] for s in run["qa"]["scenes"]} == {"SC009": "PASS", "SC010": "PASS", "SC014": "PASS"}


# --- 1-4: scene kinds ---------------------------------------------------------------------------------

def test_sc009_dynamic_locked_derivations() -> None:
    sc = _scene(_compile(), "SC009")
    assert sc["narration_span"] == {"start_anchor": "SC009/AN01", "end_anchor": "SC009/AN05"}
    assert sc["anchors"][4] == {"anchor_id": "SC009/AN05", "exact_text": "더 높은 금리를 약속해야 했습니다",
                                "source_span": {"char_start": 95, "char_end": 113}, "edge": "END"}
    states = {s["state_id"]: s for s in sc["states"]}
    assert (states["SC009/S1"]["entered_by"], states["SC009/S1"]["exited_by"]) == ("SC009/A01", "SC009/A02")
    assert all(a["model_id"] == "CAPITAL_FLOW" for a in sc["actions"])
    assert sc["actions"][1]["dependency"] == {"after": [{"action": "SC009/A01", "on": "complete"}], "sync_group": "SC009/REALLOCATE"}
    assert sc["invariants"][0]["target"]["paths"][0] == "elements.ALLOC_UST.attrs.value"
    assert sc["runtime_stack"]["deterministic_graphics"]["consumes"] == ["SC009/A01", "SC009/A02", "SC009/A03"]
    assert "consumes" not in sc["runtime_stack"]["captions"]
    assert "execution_graph" not in sc
    assert set(sc["must_preserve"]) == {"beats", "objects", "causal_chains", "narration_anchors", "persistent_models", "last_frame_elements"}
    assert sc["fallback_contract"] == {"on_failure": "DIRECTION_DEVIATION"}       # authored allowed: [] is not written
    assert sc["qa_contract"]["review"] == "auto" and "checks" not in sc["qa_contract"]


def test_sc010_static_source_evidence_routes_to_factual_source() -> None:
    sc = _scene(_compile(), "SC010")
    assert sc["runtime_stack"] == {"factual_source": {"runtime": "remotion", "purpose": "금리표 원본 캡처를 읽을 수 있게 배치",
                                                      "consumes": ["SC010/S0"]}}
    assert sc["prohibited_simplification"] == []                                    # schema-required for LOCKED
    assert "actions" not in sc and "events" not in sc


def test_sc014_flex_writes_no_consumes_and_no_qa_contract() -> None:
    sc = _scene(_compile(), "SC014")
    assert sc["runtime_hint"] == "footage" and "consumes" not in sc["runtime_stack"]["base_visual"]
    assert "qa_contract" not in sc and "must_preserve" not in sc


def test_discretionary_scene() -> None:
    text = _edit(("importance: REQUIRED_FLEX\nrole: immersion\nmode: reality", "importance: DISCRETIONARY\nrole: breather"),
                 ("[SHOW]\nrequirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]\n\n", ""))
    sc = _scene(_compile(text, lock=None), "SC014")
    assert sc["importance"] == "DISCRETIONARY" and "visual_mode" not in sc and "requirements" not in sc


def test_draft_without_lock() -> None:
    doc = _compile(lock=None)
    assert doc["lifecycle"] == {"revision": 1, "status": "DRAFT", "generated_at": LIFECYCLE["generated_at"]}


# --- 5-12: rejected input -----------------------------------------------------------------------------

def test_ambiguous_anchor_fails() -> None:
    codes, text = _codes(_edit(("AN01: 투자할 수 있는 장기 자금은 정해져 있습니다", "AN01: 있습니다")))
    assert codes == ["ANCHOR_AMBIGUOUS"] and "occurs" in text


def test_anchor_not_in_script_fails() -> None:
    codes, _ = _codes(_edit(("AN01: 투자할 수 있는 장기 자금은 정해져 있습니다", "AN01: 투자할 수 있는 장기 자금은 무한합니다")))
    assert codes == ["ANCHOR_NOT_FOUND"]


@pytest.mark.parametrize("pairs, code", [
    ((("[MEANING CONTRACT]\nafter: 추상 설명에서", "[CAMERA]\nmove: dolly\n\n[MEANING CONTRACT]\nafter: 추상 설명에서"),), "PARSE_SECTION_UNKNOWN"),
    ((("importance: REQUIRED_FLEX\nrole: immersion", "importance: REQUIRED_FLEX\ncolour: blue\nrole: immersion"),), "KEY_UNKNOWN"),
    ((("  type: ADD\n", "  type: ADD\n  speed: fast\n"),), "KEY_UNKNOWN"),
])
def test_unknown_section_or_key_fails(pairs, code) -> None:
    codes, _ = _codes(_edit(*pairs))
    assert codes == [code]


def test_duplicate_ids_fail() -> None:
    codes, _ = _codes(_edit(("S1:\n  meaning: 자금 100, 채권 선택지 4개", "S0:\n  meaning: 자금 100, 채권 선택지 4개")))
    assert codes == ["PARSE_YAML_KEY_DUPLICATE"]
    codes, _ = _codes(_edit(("[SHOW]\nRATE_TABLE:", "[SHOW]\nS0: {role: 상태와 같은 이름, type: document}\nRATE_TABLE:")))
    assert "ID_DUPLICATE" in codes


def test_unresolved_reference_fails() -> None:
    codes, text = _codes(_edit(("targets: [META, AMZN]", "targets: [META, NVDA]")))
    assert codes == ["REF_UNRESOLVED"] and "NVDA" in text
    codes, text = _codes(_edit(("  after: S0\nB02:", "  after: A01\nB02:")))
    assert codes == ["REF_UNRESOLVED"] and "(it is a action)" in text


def test_missing_runtime_layer_fails() -> None:
    codes, text = _codes(_edit(("deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델}\n", "")))
    assert set(codes) == {"ROUTING_LAYER_MISSING"} and len(codes) == 3


def test_layers_override_routes_to_every_listed_layer() -> None:
    text = _edit(("  after: {A02: complete}\n  min_seconds: 0.6", "  after: {A02: complete}\n  min_seconds: 0.6\n  layers: [deterministic_graphics, character]"),
                 ("captions: {runtime: remotion, purpose: PhraseCaptions}", "captions: {runtime: remotion, purpose: PhraseCaptions}\ncharacter: {runtime: hyperframes, purpose: 발행자 캐릭터 반응}"))
    sc = _scene(_compile(text), "SC009")
    assert sc["runtime_stack"]["deterministic_graphics"]["consumes"] == ["SC009/A01", "SC009/A02", "SC009/A03"]
    assert sc["runtime_stack"]["character"]["consumes"] == ["SC009/A03"]
    assert all("layers" not in a for a in sc["actions"])                          # a Bridge hint, not a 40 field


def test_show_layer_override_routes_a_non_model_state() -> None:
    text = _edit(("  source: kb_rate_table_capture.png\n  required: true", "  source: kb_rate_table_capture.png\n  layer: base_visual\n  required: true"),
                 ("factual_source: {runtime: remotion, purpose: 금리표 원본 캡처를 읽을 수 있게 배치}",
                  "base_visual: {runtime: remotion, purpose: 금리표 원본 캡처를 읽을 수 있게 배치}"))
    sc = _scene(_compile(text), "SC010")
    assert sc["runtime_stack"]["base_visual"]["consumes"] == ["SC010/S0"] and sc["objects"][0]["layer_id"] == "base_visual"


def test_invariant_during_takes_states_not_actions() -> None:
    codes, _ = _codes(_edit(("  value: 100\n  during: scene\nINV02:", "  value: 100\n  during: {from: A01, to: A03}\nINV02:")))
    assert codes == ["DURING_NOT_STATE", "DURING_NOT_STATE"]
    sc = _scene(_compile(_edit(("  value: 100\n  during: scene\nINV02:", "  value: 100\n  during: {from: S1, to: S3}\nINV02:"))), "SC009")
    assert sc["invariants"][0]["during"] == {"from": "SC009/S1", "to": "SC009/S3"}
    assert "during" not in sc["invariants"][2]                                      # omitted stays omitted


@pytest.mark.parametrize("old, new", [
    ("  from: S0\n  to: S1\n  min_seconds: 0.6", "  from: S0\n  to: S1\n  must_execute: true\n  min_seconds: 0.6"),
    ("  from: S0\n  to: S1\n  min_seconds: 0.6", "  from: S0\n  to: S1\n  completion_state_id: S1\n  min_seconds: 0.6"),
    ("  from: S0\n  to: S1\n  min_seconds: 0.6", "  from: S0\n  to: S1\n  completion_condition: settled\n  min_seconds: 0.6"),
    ("E03: {on: AN04, from: S2, do: [A03], to: S3}", "E03: {on: AN04, from: S2, do: [A03], to: S3, completion_condition: settled}"),
])
def test_unsupported_completion_fields_fail(old, new) -> None:
    codes, _ = _codes(_edit((old, new)))
    assert codes == ["UNSUPPORTED_FIELD"]


# --- strict parser and system-owned values --------------------------------------------------------------

@pytest.mark.parametrize("old, new, code", [
    ("  pvm: CAPITAL_FLOW.MORE_SUPPLY\n", "  pvm: CAPITAL_FLOW.MORE_SUPPLY\n  entered_by: A01\n", "SYSTEM_FIELD"),
    ("deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델}",
     "deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델, consumes: [A01]}", "SYSTEM_FIELD"),
    ("evidence_states: [S1, S2, S3]", "evidence_states: [S1, S2, S3]\nchecks: [ORDER]", "SYSTEM_FIELD"),
    ("objects: [RATE_TABLE]\n", "objects: [RATE_TABLE]\nstates: [S0]\n", "SYSTEM_FIELD"),
    ("AN04: 더 높은 금리를 약속해야 했습니다\n", "AN04: &dup 더 높은 금리를 약속해야 했습니다\n", "PARSE_YAML_FEATURE"),
    ("AN04: 더 높은 금리를 약속해야 했습니다\n", "AN04: !!str 더 높은 금리를 약속해야 했습니다\n", "PARSE_YAML_FEATURE"),
    ("B03:\n  at: AN03", "B03:\n> 메모\n  at: AN03", "PARSE_MEMO"),
    ("  pvm: CAPITAL_FLOW.MORE_SUPPLY\n", "  pvm: CAPITAL_FLOW.MORE_SUPPLY\n  initial: true\n", "INITIAL_STATE"),
    ("## SC014\n", "## SC014\nfree text\n", "PARSE_TEXT_OUTSIDE"),
    ("[MEANING CONTRACT]\nafter: 추상 설명에서", "[MOTION]\nrequired: false\nstatic_replacement_valid: true\n\n[MEANING CONTRACT]\nafter: 추상 설명에서",
     "PARSE_SECTION_NOT_APPLICABLE"),
])
def test_strict_input_errors(old, new, code) -> None:
    codes, _ = _codes(_edit((old, new)))
    assert codes == [code]


def test_yaml_on_is_a_key_not_a_boolean() -> None:
    doc, issues = parse_authoring("# PROJECT\n[PROJECT]\nid: p\nscript: s\n\n## SC001\n[EVENTS]\nE01: {on: AN01, do: [A01], to: S1, yes: no}\n")
    assert issues == []
    assert doc.scenes[0].sections["EVENTS"].body == {"E01": {"on": "AN01", "do": ["A01"], "to": "S1", "yes": "no"}}


def test_graph_cycle_fails() -> None:
    text = _edit(("[EVENTS]\n", "A04:\n  role: 되돌림\n  targets: [META]\n  at: AN05\n  from: S3\n  to: S0\n\n[EVENTS]\n"))
    codes, text = _codes(text)
    assert "GRAPH_CYCLE" in codes and "SC009/S0 -> SC009/A01" in text


def test_every_problem_is_reported_at_once() -> None:
    codes, _ = _codes(_edit(("targets: [META, AMZN]", "targets: [META, NVDA]"),
                            ("deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델}\n", "")))
    assert "REF_UNRESOLVED" in codes and "ROUTING_LAYER_MISSING" in codes


def test_validate_contract_errors_surface_as_contract_semantic() -> None:
    codes, text = _codes(_edit(("  pvm: CAPITAL_FLOW.REALLOCATED\n", "  pvm: CAPITAL_FLOW.NO_SUCH_STATE\n")))
    assert set(codes) == {"CONTRACT_SEMANTIC"} and "NO_SUCH_STATE" in text


# --- audit fixes: no silent defaults ----------------------------------------------------------------------

@pytest.mark.parametrize("old, new", [
    ("[SHOW]\nrequirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]", "[SHOW]\n~"),
    ("[SHOW]\nrequirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]", "[SHOW]\nnull"),
    ("[ALLOWED FREEDOM]\n[SOURCE_CROP_MARGIN, LAYOUT_COORDINATES]", "[ALLOWED FREEDOM]\n~"),
])
def test_null_section_body_is_an_empty_section(old, new) -> None:
    codes, text = _codes(_edit((old, new)))
    assert codes == ["PARSE_SECTION_EMPTY"] and "body is null" in text


def test_empty_list_body_keeps_its_existing_meaning() -> None:
    assert _scene(_compile(), "SC010")["prohibited_simplification"] == []        # [PROHIBITED SIMPLIFICATION] []


@pytest.mark.parametrize("empty", ["[]", "~"])
def test_explicitly_empty_layers_is_an_error_not_the_default_route(empty) -> None:
    codes, text = _codes(_edit(("  after: {A02: complete}\n  min_seconds: 0.6", f"  after: {{A02: complete}}\n  min_seconds: 0.6\n  layers: {empty}")))
    assert codes == ["KEY_TYPE"] and "A03.layers must list at least one runtime layer" in text


# --- defaults apply only to omitted values ---------------------------------------------------------------

def test_omitted_edge_and_review_take_their_defaults() -> None:
    sc = _scene(_compile(), "SC009")
    assert sc["anchors"][0]["edge"] == "START"                                     # AN01 writes no edge
    assert sc["qa_contract"]["review"] == "auto"                                   # [REVIEW] writes no review


@pytest.mark.parametrize("old, new", [
    ("AN05: {text: 더 높은 금리를 약속해야 했습니다, edge: END}", "AN05: {text: 더 높은 금리를 약속해야 했습니다, edge: ''}"),
    ("evidence_states: [S1, S2, S3]", "evidence_states: [S1, S2, S3]\nreview: ''"),
])
def test_explicit_empty_string_is_not_replaced_by_a_default(old, new) -> None:
    codes, _ = _codes(_edit((old, new)))
    assert codes == ["CONTRACT_SCHEMA"]


# --- a required key written as null is missing, not empty ---------------------------------------------

@pytest.mark.parametrize("old, new", [
    ("  targets: [META, AMZN]", "  targets: ~"),
    ("cause: {state: S1, objects: [META, AMZN], actions: [A01], anchor: AN02}",
     "cause: {state: S1, objects: [META, AMZN], actions: ~, anchor: AN02}"),
    ("E03: {on: AN04, from: S2, do: [A03], to: S3}", "E03: {on: AN04, from: S2, do: ~, to: S3}"),
])
def test_required_key_written_as_null_fails_at_authoring(old, new) -> None:
    codes, text = _codes(_edit((old, new)))
    assert codes == ["KEY_REQUIRED"] and "is null" in text


def test_optional_key_written_as_null_is_omitted() -> None:
    doc = _compile(_edit(("hold_seconds: 1.5\nnext_scene: SC010", "hold_seconds: 1.5\ncamera: null\nnext_scene: SC010")))
    assert _scene(doc, "SC009")["last_frame_contract"] == _scene(CANONICAL, "SC009")["last_frame_contract"]
