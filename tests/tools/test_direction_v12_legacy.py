"""Visual Direction v1.2, Phase 1 — legacy guard: projects without a 40 contract behave exactly as v1.0.

These pass before the v1.2 implementation and must keep passing after it.
The golden file was recorded from the v1.0 code on origin/main 7bf48d9.
"""

import json
from pathlib import Path

from lib.checkpoint import validate_checkpoint
from lib.direction_contract.hooks import compile_timeline, validate_direction
from schemas.artifacts import validate_artifact

REPO = Path(__file__).resolve().parents[2]
LEGACY = REPO / "tests" / "fixtures" / "visual_direction" / "release_plan"
GOLDEN = REPO / "tests" / "fixtures" / "direction_v1_2" / "legacy_release_plan.golden.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_v10_compile_timeline_output_is_unchanged() -> None:
    direction, alignment = _load(LEGACY / "visual_direction.json"), _load(LEGACY / "alignment.json")
    timeline = compile_timeline(direction, alignment, source={"visual_direction": "visual_direction.json", "alignment": "alignment.json"})
    golden = _load(GOLDEN)
    assert json.loads(json.dumps(timeline, sort_keys=True)) == golden["timeline"]


def test_v10_validate_direction_result_is_unchanged() -> None:
    result = validate_direction(_load(LEGACY / "visual_direction.json"), _load(LEGACY / "script.json"))
    assert json.loads(json.dumps(result, sort_keys=True)) == _load(GOLDEN)["validate_direction"]


def test_v10_artifacts_still_validate_with_the_shipped_schemas() -> None:
    validate_artifact("visual_direction", _load(LEGACY / "visual_direction.json"))
    timeline = compile_timeline(_load(LEGACY / "visual_direction.json"), _load(LEGACY / "alignment.json"))
    validate_artifact("visual_timeline", timeline)


def test_v10_scene_plan_checkpoint_without_contract_passes() -> None:
    validate_checkpoint({
        "version": "1.0",
        "project_id": "legacy-release-plan",
        "stage": "scene_plan",
        "status": "completed",
        "pipeline_type": "animated-explainer",
        "timestamp": "2026-10-03T00:00:00Z",
        "artifacts": {
            "scene_plan": _load(LEGACY / "scene_plan.json"),
            "visual_direction": _load(LEGACY / "visual_direction.json"),
        },
    })
