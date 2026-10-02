"""visual_timeline_compiler — the production entry point of the edit stage, v1.0 and v1.2 (Phase 1).

The timeline is produced by the real tool (``VisualTimelineCompiler().execute``)
and then fed to the downstream v1.2 checks, so a 1.2 project is exercised end
to end through the path the pipeline uses.
"""

import json
from pathlib import Path

import pytest

from lib.direction_contract import hooks as h
from schemas.artifacts import validate_artifact
from tools.video.visual_timeline_compiler import VisualTimelineCompiler

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"
LEGACY = REPO / "tests" / "fixtures" / "visual_direction" / "release_plan"
GOLDEN = REPO / "tests" / "fixtures" / "direction_v1_2" / "legacy_release_plan.golden.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _compile(direction: str = "visual_direction.good.json", **overrides):
    inputs = {
        "operation": "compile",
        "visual_direction": str(FIX / direction),
        "visual_direction_contract": str(FIX / "40_visual_direction_contract.json"),
        "persistent_visual_models": str(FIX / "41_persistent_visual_models.json"),
        "script": str(FIX / "script.json"),
        "alignment": str(FIX / "alignment.json"),
    }
    inputs.update(overrides)
    return VisualTimelineCompiler().execute({k: v for k, v in inputs.items() if v is not None})


def _downstream(timeline: dict, direction: str, atelier: str) -> dict:
    """Lineage, binding and Direction QA on the timeline the tool produced."""
    contract = h.load_contract(FIX / "40_visual_direction_contract.json", FIX / "41_persistent_visual_models.json")
    lineage = h.check_lineage(contract, _load(FIX / "42_direction_lineage.json"), _load(FIX / direction), _load(FIX / "scene_plan.json"))
    binding = h.bind(contract, timeline, _load(FIX / "edit_decisions.json"),
                     {"deterministic_graphics": h.build_trace(timeline, FIX / atelier)})
    return h.qa_report(contract, lineage, _load(FIX / direction), timeline, binding)


# --- v1.2 ----------------------------------------------------------------------------------------------

def test_sc009_v12_timeline_from_the_tool(tmp_path) -> None:
    out = tmp_path / "visual_timeline.json"
    result = _compile(scene_plan=str(FIX / "scene_plan.json"), output_path=str(out))
    assert result.success, result.error
    timeline = result.data["visual_timeline"]
    validate_artifact("visual_timeline", timeline)
    assert timeline["version"] == "1.2"
    assert timeline["contract"] == result.data["contract"]
    assert result.data["contract"]["fingerprint"] == _load(FIX / "visual_direction.good.json")["contract"]["fingerprint"]
    # anchor resolution is kept on the timeline (and in the written file)
    resolution = timeline["anchor_resolution"]
    assert resolution["unresolved_anchors"] == [] and len(resolution["resolved_anchors"]) == 9
    assert all(r["status"] == "EXACT" and r["same_span"] for r in resolution["resolved_anchors"])
    assert _load(out)["anchor_resolution"] == resolution
    # models come from 41, contract ids ride on the events
    assert [m["id"] for m in timeline["models"]] == ["CAPITAL_FLOW"]
    assert {e["action_id"] for e in timeline["events"]} == {"SC009/A01", "SC009/A02", "SC009/A03"}
    qa = _downstream(timeline, "visual_direction.good.json", "atelier_good")
    assert qa["verdict"] == "PASS"


def test_card_replacement_from_the_tool_fails_direction_qa() -> None:
    result = _compile("visual_direction.as_produced.json")
    assert result.success, result.error  # the timeline itself compiles: the loss is in what it no longer contains
    qa = _downstream(result.data["visual_timeline"], "visual_direction.as_produced.json", "atelier_card")
    sc009 = next(s for s in qa["scenes"] if s["scene_id"] == "SC009")
    assert qa["verdict"] == "FAIL" and sc009["result"] == "FAIL"
    assert {"SC009/A02", "SC009/S2"} <= set(sc009["receipt"]["omitted"])


def test_v12_without_contract_fails_without_legacy_fallback() -> None:
    for missing in ("visual_direction_contract", "persistent_visual_models"):
        result = _compile(**{missing: None})
        assert not result.success
        assert "no legacy fallback" in result.error and missing in result.error


def test_v12_for_another_revision_or_fingerprint_fails(tmp_path) -> None:
    for key, value in (("revision", 2), ("fingerprint", "sha256:" + "0" * 64)):
        direction = _load(FIX / "visual_direction.good.json")
        direction["contract"][key] = value
        path = tmp_path / f"vd_{key}.json"
        path.write_text(json.dumps(direction, ensure_ascii=False), encoding="utf-8")
        result = _compile(visual_direction=str(path))
        assert not result.success and key in result.error


def test_v12_against_an_unlocked_contract_fails(tmp_path) -> None:
    contract = _load(FIX / "40_visual_direction_contract.json")
    contract["lifecycle"]["status"] = "DRAFT"  # lifecycle is outside the fingerprint
    path = tmp_path / "40.json"
    path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    result = _compile(visual_direction_contract=str(path))
    assert not result.success and "LOCKED" in result.error


def test_v12_with_a_changed_script_reports_the_contract_error(tmp_path) -> None:
    script = _load(FIX / "script.json")
    script["sections"][0]["text"] = script["sections"][0]["text"].replace("장기", "단기")
    path = tmp_path / "script.json"
    path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    result = _compile(script=str(path))
    assert not result.success and "script_sha256" in result.error


def test_lost_locked_anchor_fails_the_compile() -> None:
    alignment = _load(FIX / "alignment.json")
    alignment["segments"] = [s for s in alignment["segments"] if s["id"] != "s4"]  # sentence of SC009/AN04 never spoken
    result = _compile(alignment=alignment)
    assert not result.success and "SC009/AN04" in result.error


def test_contract_with_a_v10_direction_is_refused() -> None:
    result = _compile(visual_direction=str(LEGACY / "visual_direction.json"), script=str(LEGACY / "script.json"),
                      alignment=str(LEGACY / "alignment.json"))
    assert not result.success and "must be 1.2" in result.error


# --- v1.0 unchanged -----------------------------------------------------------------------------------

def test_v10_tool_output_equals_the_golden_timeline() -> None:
    result = VisualTimelineCompiler().execute({
        "operation": "compile",
        "visual_direction": _load(LEGACY / "visual_direction.json"),
        "script": _load(LEGACY / "script.json"),
        "alignment": _load(LEGACY / "alignment.json"),
    })
    assert result.success, result.error
    golden = _load(GOLDEN)["timeline"]
    timeline = json.loads(json.dumps(result.data["visual_timeline"], sort_keys=True))
    assert {k: v for k, v in timeline.items() if k != "source"} == {k: v for k, v in golden.items() if k != "source"}
    assert timeline["version"] == "1.0" and "anchor_resolution" not in timeline and "contract" not in result.data
