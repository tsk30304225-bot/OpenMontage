"""The animated-explainer scene_plan checkpoint enforces the existing visual-direction validator.

The failure this guards: a templated explainer split every mechanism into
discrete cards, left visual_models empty, and the checkpoint (schema only)
completed, so the direction runtime never ran.
"""

import json
from pathlib import Path

import pytest

from lib.checkpoint import CheckpointValidationError, validate_checkpoint
from lib.scene_runtime import planned_runtime_gaps

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "visual_direction"


def _scene(sid: str, role: str, start: float) -> dict:
    return {"id": sid, "type": "text_card", "description": "", "start_seconds": start, "end_seconds": start + 4,
            "narrative_role": role}


def _plan(*roles: str) -> dict:
    return {"version": "1.0", "scenes": [_scene(f"sc{i + 1}", r, i * 4.0) for i, r in enumerate(roles)]}


def _direction(roles: list[str], models: list | None = None, beats: dict | None = None) -> dict:
    scenes = []
    for i, role in enumerate(roles):
        sc = {"scene_id": f"sc{i + 1}", "narrative_role": role,
              "visual_mode": "reality" if role in ("immersion", "closure", "breather") else "text"}
        if beats and sc["scene_id"] in beats:
            sc.update(beats[sc["scene_id"]])
        scenes.append(sc)
    doc = {"version": "1.0", "viewer_journey": [{"id": "j1", "scene_ids": [s["scene_id"] for s in scenes],
                                                 "viewer_goal": "follow the money"}], "scenes": scenes}
    if models is not None:
        doc["visual_models"] = models
    return doc


# Mirrors the failing production in shape (synthetic, no real script): process scenes as cards, no model.
CARD_ONLY_ROLES = ["immersion", "explanation", "explanation", "evidence", "explanation", "closure"]

FLOW_MODEL = {
    "id": "money_path", "type": "flow_network", "renderer": "bespoke", "title": "Money path",
    "initial_state": {"elements": [{"id": "spend", "kind": "node", "label": "AI spend"},
                                   {"id": "bonds", "kind": "node", "label": "Corporate bonds"}]},
}


def _write(tmp_path, artifacts, pipeline_type="animated-explainer", status="completed"):
    """Validate a scene_plan checkpoint the way write_checkpoint does (stage prerequisites aside)."""
    validate_checkpoint({"version": "1.0", "project_id": "p", "pipeline_type": pipeline_type, "stage": "scene_plan",
                         "status": status, "timestamp": "2026-09-22T00:00:00Z", "artifacts": artifacts})
    return True


def test_explanation_scenes_without_any_model_cannot_complete(tmp_path) -> None:
    with pytest.raises(CheckpointValidationError) as exc:
        _write(tmp_path, {"scene_plan": _plan(*CARD_ONLY_ROLES), "visual_direction": _direction(CARD_ONLY_ROLES)})
    msg = str(exc.value)
    assert "no visual model" in msg and "runtime 'hyperframes'" in msg


def test_the_same_plan_with_a_bespoke_model_completes(tmp_path) -> None:
    beats = {"sc2": {"visual_mode": "model", "visual_model_id": "money_path",
                     "beats": [{"id": "b1", "narration_anchor": "the money moves", "operation": "REVEAL", "takeaway": "the money starts moving",
                                "target": "spend"}]},
             "sc3": {"visual_mode": "model", "visual_model_id": "money_path",
                     "beats": [{"id": "b2", "narration_anchor": "into bonds", "operation": "REVEAL", "target": "bonds", "takeaway": "it lands in bonds"}]}}
    path = _write(tmp_path, {"scene_plan": _plan(*CARD_ONLY_ROLES),
                             "visual_direction": _direction(CARD_ONLY_ROLES, [FLOW_MODEL], beats)})
    assert path is True


def test_card_and_footage_video_without_explanations_is_not_blocked(tmp_path) -> None:
    roles = ["immersion", "introduce_subject", "evidence", "call_to_action", "closure"]
    assert _write(tmp_path, {"scene_plan": _plan(*roles), "visual_direction": _direction(roles)})


def test_a_single_explanation_scene_without_model_is_only_a_warning(tmp_path) -> None:
    roles = ["immersion", "explanation", "closure"]
    assert _write(tmp_path, {"scene_plan": _plan(*roles), "visual_direction": _direction(roles)})


def test_explainer_scene_plan_must_carry_visual_direction(tmp_path) -> None:
    with pytest.raises(CheckpointValidationError, match="must include the visual_direction"):
        _write(tmp_path, {"scene_plan": _plan("immersion", "closure")})


def test_gate_is_scoped_to_completed_animated_explainer_scene_plans(tmp_path) -> None:
    bad = {"scene_plan": _plan(*CARD_ONLY_ROLES), "visual_direction": _direction(CARD_ONLY_ROLES)}
    assert _write(tmp_path / "a", bad, status="in_progress")
    assert _write(tmp_path / "b", {"scene_plan": _plan("immersion")}, pipeline_type="cinematic")


@pytest.mark.parametrize("fixture", ["atelier_route", "release_plan"])
def test_existing_direction_fixtures_pass_the_gate(tmp_path, fixture) -> None:
    d = FIX / fixture
    direction = json.loads((d / "visual_direction.json").read_text(encoding="utf-8"))
    plan = json.loads((d / "scene_plan.json").read_text(encoding="utf-8"))
    assert _write(tmp_path, {"scene_plan": plan, "visual_direction": direction})


def test_scene_runtime_fixture_passes_the_gate(tmp_path) -> None:
    d = REPO / "tests" / "fixtures" / "scene_runtime"
    direction = json.loads((d / "visual_direction.json").read_text(encoding="utf-8"))
    plan = json.loads((d / "scene_plan.json").read_text(encoding="utf-8"))
    assert _write(tmp_path, {"scene_plan": plan, "visual_direction": direction})


# ---------------------------------------------------------------- planned runtime dropped (soft)

def test_planned_hyperframes_scene_rendered_without_it_is_reported() -> None:
    scenes = [{"id": "sc1", "runtime": "hyperframes", "start_seconds": 0, "end_seconds": 4},
              {"id": "sc2", "runtime": "hyperframes", "start_seconds": 4, "end_seconds": 8},
              {"id": "sc3", "runtime": "remotion", "start_seconds": 8, "end_seconds": 12}]
    cuts = [{"id": "cut-sc01", "in_seconds": 0, "out_seconds": 4, "type": "hero_title"},
            {"id": "c2", "scene_id": "sc2", "in_seconds": 4, "out_seconds": 8, "runtime": "hyperframes"},
            {"id": "c3", "in_seconds": 8, "out_seconds": 12, "type": "text_card"}]
    gaps = planned_runtime_gaps(scenes, cuts)
    assert [(g["code"], g["scene_id"]) for g in gaps] == [("PLANNED_RUNTIME_DROPPED", "sc1")]
