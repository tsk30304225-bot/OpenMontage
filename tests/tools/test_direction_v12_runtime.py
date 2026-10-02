"""Visual Direction v1.2, Phase 1 — runtime behaviour beyond the acceptance scenarios.

Authority (D15), staleness (D3), anchor resolution, stage gates through the
real checkpoint seam (lib/checkpoint.validate_checkpoint → checkpoint_hooks →
completion_gate), deviations (44) and binding integrity (43).
"""

import copy
import json
import sys
from pathlib import Path

import pytest

from lib.checkpoint import CheckpointValidationError, validate_checkpoint
from lib.direction_contract import hooks as h

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_direction_v12_acceptance as acc  # noqa: E402


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract():
    return h.load_contract(FIX / "40_visual_direction_contract.json", FIX / "41_persistent_visual_models.json")


def _checkpoint(stage, artifacts):
    return {"version": "1.0", "project_id": "capital-competition", "stage": stage, "status": "completed",
            "pipeline_type": "animated-explainer", "timestamp": "2026-10-03T00:00:00Z", "artifacts": artifacts}


RENDER_REPORT = {"version": "1.0", "outputs": [{"path": "renders/final.mp4", "format": "mp4", "codec": "h264",
                                                 "resolution": "1920x1080", "fps": 30, "duration_seconds": 24.6}]}


def _base():
    return {"visual_direction_contract": _load("40_visual_direction_contract.json"),
            "persistent_visual_models": _load("41_persistent_visual_models.json")}


# --- authority (D15) ---------------------------------------------------------------------------------

def test_script_change_after_lock_is_a_contract_error(contract) -> None:
    script = _load("script.json")
    script["sections"][2]["text"] = script["sections"][2]["text"].replace("같은 돈이", "같은 자금이")
    errors = h.validate_contract(contract, script)["errors"]
    assert any("script_sha256" in e for e in errors)
    assert any("SC009/AN03" in e for e in errors)  # the span no longer spells the anchor


def test_section_timings_and_line_endings_do_not_change_the_hash(contract) -> None:
    script = _load("script.json")
    for s in script["sections"]:
        s["start_seconds"] += 1.0  # only sections[].text is authority
    assert h.validate_contract(contract, script)["errors"] == []
    lf, crlf, cr = (dict(script, sections=[dict(s, text=s["text"] + end + "끝") for s in script["sections"]]) for end in ("\n", "\r\n", "\r"))
    assert h.script_sha256(lf) == h.script_sha256(crlf) == h.script_sha256(cr) != h.script_sha256(script)


# --- identity and staleness (D3) ---------------------------------------------------------------------

def test_artifacts_for_another_contract_revision_are_rejected(contract) -> None:
    vd = _load("visual_direction.good.json")
    vd["contract"]["revision"] = 2
    with pytest.raises(h.DirectionContractError):
        h.compile_timeline(vd, _load("alignment.json"), models=contract.definitions(), contract=contract)
    lineage = _load("42_direction_lineage.json")
    lineage["contract"]["fingerprint"] = "sha256:" + "1" * 64
    with pytest.raises(h.DirectionContractError):
        h.check_lineage(contract, lineage, _load("visual_direction.good.json"), _load("scene_plan.json"))


def test_v12_direction_needs_models_and_contract() -> None:
    with pytest.raises(ValueError):
        h.compile_timeline(_load("visual_direction.good.json"), _load("alignment.json"))


def test_binding_from_another_timeline_is_stale() -> None:
    run = acc._run(acc._good())
    other = copy.deepcopy(run["timeline"])
    other["events"][0]["time_seconds"] += 0.1
    with pytest.raises(h.DirectionContractError):
        h.qa_report(run["contract"], run["lineage"], None, other, run["binding"])


# --- anchors -----------------------------------------------------------------------------------------

def test_fuzzy_anchor_is_never_the_contract_span(contract) -> None:
    alignment = _load("alignment.json")
    words = alignment["segments"][2]["words"]
    words[1]["word"] = "돈은"  # narration drifted from the approved script
    timeline = h.compile_timeline(_load("visual_direction.good.json"), alignment, models=contract.definitions(), contract=contract)
    an03 = next(r for r in timeline["anchor_resolution"]["resolved_anchors"] if r["anchor_id"] == "SC009/AN03")
    assert an03["status"] == "FUZZY" and an03["same_span"] is False


def test_compiled_v12_timeline_validates_and_carries_contract_ids(contract) -> None:
    from schemas.artifacts import validate_artifact

    timeline = h.compile_timeline(_load("visual_direction.good.json"), _load("alignment.json"), models=contract.definitions(), contract=contract)
    validate_artifact("visual_timeline", timeline)
    ev = next(e for e in timeline["events"] if e["id"] == "ev-sc16-b5")
    assert (ev["action_id"], ev["state_after_id"], ev["sync_group"]) == ("SC009/A02", "SC009/S2", "sc16-realloc")
    assert timeline["anchor_resolution"]["unresolved_anchors"] == []


# --- check_states --------------------------------------------------------------------------------------

def test_check_states_clean_for_the_good_plan_and_specific_for_the_card() -> None:
    assert acc._run(acc._good())["states"]["violations"] == []
    kinds = {(v["type"], tuple(v["target_ids"])) for v in acc._run(acc._card(), atelier="atelier_card")["states"]["violations"]}
    assert ("ACTION_EXISTENCE", ("SC009/A02",)) in kinds
    assert ("STATE_TRANSITION", ("SC009/S2",)) in kinds


# --- gates through the checkpoint seam ----------------------------------------------------------------

def _plan_artifacts(direction):
    run = acc._run(direction, atelier="atelier_card" if direction.get("scenes")[1].get("visual_mode") == "text" else "atelier_good")
    return run, {**_base(), "script": _load("script.json"), "scene_plan": _load("scene_plan.json"),
                 "visual_direction": direction, "direction_lineage": run["lineage"]}


def test_scene_plan_gate_passes_the_good_plan() -> None:
    _, artifacts = _plan_artifacts(acc._good())
    validate_checkpoint(_checkpoint("scene_plan", artifacts))


def test_scene_plan_gate_refuses_the_card_unless_a_deviation_is_recorded() -> None:
    _, artifacts = _plan_artifacts(acc._card())
    with pytest.raises(CheckpointValidationError, match="SC009/A02"):
        validate_checkpoint(_checkpoint("scene_plan", artifacts))
    deviations = _load("44_direction_deviations.json")
    deviations["deviations"][0]["affected_contract_ids"] = sorted(artifacts["direction_lineage"]["system_coverage"]["omitted_locked_ids"])
    validate_checkpoint(_checkpoint("scene_plan", {**artifacts, "direction_deviations": deviations}))  # PROPOSED passes here


def test_edit_gate_blocks_an_invariant_violation() -> None:
    run = acc._run(acc._total_120())
    artifacts = {**_base(), "visual_timeline": run["timeline"], "direction_lineage": run["lineage"], "scene_plan": _load("scene_plan.json"),
                 "edit_decisions": _load("edit_decisions.json")}
    with pytest.raises(CheckpointValidationError, match="SC009/INV01"):
        validate_checkpoint(_checkpoint("edit", artifacts))


def test_edit_gate_passes_the_good_timeline() -> None:
    run = acc._run(acc._good())
    validate_checkpoint(_checkpoint("edit", {**_base(), "visual_timeline": run["timeline"], "direction_lineage": run["lineage"],
                                             "scene_plan": _load("scene_plan.json"), "edit_decisions": _load("edit_decisions.json")}))


def test_compose_gate_through_the_checkpoint_seam() -> None:
    run = acc._run(acc._good())
    validate_checkpoint(_checkpoint("compose", {**acc._artifacts(run), "render_report": RENDER_REPORT}))
    with pytest.raises(CheckpointValidationError, match="Direction Review"):
        validate_checkpoint(_checkpoint("compose", {**acc._artifacts(run, review=False), "render_report": RENDER_REPORT}))


def test_compose_gate_rejects_a_stale_qa_report() -> None:
    run = acc._run(acc._good())
    artifacts = acc._artifacts(run)
    artifacts["direction_qa_report"] = acc._run(acc._card(), atelier="atelier_card")["qa"]
    artifacts["direction_qa_report"]["contract"] = run["qa"]["contract"]
    with pytest.raises(CheckpointValidationError, match="stale"):
        h.completion_gate("compose", "completed", artifacts, "animated-explainer")


def test_compose_gate_rejects_a_hand_edited_lineage_coverage() -> None:
    run = acc._run(acc._card(), atelier="atelier_card")
    artifacts = acc._artifacts(run)
    artifacts["direction_lineage"]["system_coverage"]["omitted_locked_ids"] = []  # edited after check_lineage
    with pytest.raises(CheckpointValidationError, match="plan-derived coverage .42. and execution-derived coverage .45 receipt. disagree"):
        h.completion_gate("compose", "completed", artifacts, "animated-explainer")


def test_approved_deviation_exempts_exactly_its_ids() -> None:
    run = acc._run(acc._card(), atelier="atelier_card")
    omitted = run["lineage"]["system_coverage"]["omitted_locked_ids"]
    deviations = _load("44_direction_deviations.json")
    dev = deviations["deviations"][0]
    dev.update(status="APPROVED", decision={"by": "user", "at": "2026-10-03T09:00:00+09:00", "note": "approved for the test"},
               affected_contract_ids=sorted(set(omitted) | {"SC009/E02", "SC009/A02"}))
    with pytest.raises(CheckpointValidationError) as exc:
        h.completion_gate("compose", "completed", acc._artifacts(run, deviations=deviations), "animated-explainer")
    text = str(exc.value)
    assert "ACTION_EXISTENCE ['SC009/A02']" not in text and "STATE_TRANSITION ['SC009/S2']" not in text
    assert "locked ids not delivered" not in text
    assert "ORDER ['SC009/A01', 'SC009/A02', 'SC009/A03']" in text  # A01 and A03 are not part of the approval


def test_projects_without_a_contract_skip_the_gate() -> None:
    h.completion_gate("compose", "completed", {"render_report": {}}, "animated-explainer")


# --- deviations (44) ---------------------------------------------------------------------------------

def test_record_deviation_rejects_ids_of_another_scene(contract, tmp_path) -> None:
    dev = dict(_load("44_direction_deviations.json")["deviations"][0], affected_contract_ids=["SC010/S0"])
    with pytest.raises(h.DirectionContractError):
        h.record_deviation(tmp_path, contract, dev)


def test_decided_deviation_leaves_the_open_list(contract, tmp_path) -> None:
    dev = dict(_load("44_direction_deviations.json")["deviations"][0])
    h.record_deviation(tmp_path, contract, dev)
    h.record_deviation(tmp_path, contract, {**dev, "status": "REJECTED",
                                            "decision": {"by": "user", "at": "2026-10-03T09:00:00+09:00", "note": "keep the model"}})
    assert h.open_deviations(tmp_path) == []
