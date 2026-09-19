"""Atelier ↔ visual direction bridge.

Renderer support must not decide whether a visual model exists: a model type
without a generic renderer (here flow_network) keeps its contract, is resolved
into visual_timeline like any other, and a bespoke (atelier) composition must
implement every event through the direction runtime. These tests use the
synthetic parcel-route fixture (tests/fixtures/visual_direction/atelier_route).

Set OPENMONTAGE_RENDER_TESTS=1 to render the fixture through the atelier path and
run direction_qa on it, including the static-final-state negative control.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.atelier_direction import build_trace
from lib.visual_direction import (
    apply_element_event,
    compile_timeline,
    element_initial_state,
    ineffective_events,
    model_renderer,
    replay_model_states,
    state_at,
    validate_direction,
)
from schemas.artifacts import validate_artifact
from tools.analysis.direction_qa import DirectionQA
from tools.video.video_compose import VideoCompose
from tools.video.visual_timeline_compiler import VisualTimelineCompiler

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "visual_direction" / "atelier_route"
PROJECT = FIXTURE / "atelier_route_fixture"


def _load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def _windows():
    return {s["id"]: (s["start_seconds"], s["end_seconds"]) for s in _load("scene_plan.json")["scenes"]}


def _timeline():
    return compile_timeline(_load("visual_direction.json"), _load("alignment.json"), scene_windows=_windows())


def _edit(timeline_path, entry=PROJECT / "index.tsx"):
    return {"version": "1.0", "render_runtime": "remotion", "composition_mode": "atelier", "cuts": [],
            "visual_timeline": str(timeline_path),
            "bespoke": {"entry": str(entry), "composition_id": "AtelierRouteFixture", "art_direction": "fixture"}}


# ---- planning contract is independent of renderer support ----

def test_model_without_generic_renderer_stays_in_the_contract() -> None:
    direction = _load("visual_direction.json")
    validate_artifact("visual_direction", direction)
    assert model_renderer(direction["visual_models"][0]) == "bespoke"
    assert validate_direction(direction, _load("script.json"))["errors"] == []

    generic = json.loads(json.dumps(direction))
    generic["visual_models"][0]["renderer"] = "generic"
    errors = validate_direction(generic, _load("script.json"))["errors"]
    assert any("no generic renderer" in e and "never drop the model" in e for e in errors)


def test_dropping_the_model_is_a_contract_error() -> None:
    direction = _load("visual_direction.json")
    for scene in direction["scenes"]:
        scene.pop("beats", None)
        scene.pop("visual_model_id", None)
        if scene["visual_mode"] == "model":
            scene["visual_mode"] = "evidence"
    direction["visual_models"] = []
    direction["metadata"] = {"unsupported_model_type": "flow/network; use custom atelier graphics"}
    errors = validate_direction(direction)["errors"]
    assert any("explanation scenes" in e and "no visual model" in e for e in errors)


def test_element_operations_and_endpoint_validation() -> None:
    model = _load("visual_direction.json")["visual_models"][0]
    s = element_initial_state(model)
    assert s["elements"]["warehouse"]["visible"] and not s["elements"]["hub"]["visible"]
    s = apply_element_event(s, {"operation": "REVEAL", "target": "hub"})
    s = apply_element_event(s, {"operation": "CONNECT", "target": "leg1", "params": {"from": "warehouse", "to": "hub"}})
    s = apply_element_event(s, {"operation": "EXPAND", "target": "leg1", "params": {"attr": "delay", "to": 12}})
    s = apply_element_event(s, {"operation": "PROPAGATE", "target": "hub", "params": {"path": ["locker"]}})
    s = apply_element_event(s, {"operation": "MEASURE", "target": "leg1", "params": {"metric": "delay", "label": "+12"}})
    assert s["elements"]["leg1"]["kind"] == "edge" and s["elements"]["leg1"]["attrs"]["delay"] == 12
    assert s["active"] == ["hub", "locker"] and s["measures"][0]["label"] == "+12"

    direction = _load("visual_direction.json")
    direction["scenes"][1]["beats"].append({"id": "bx", "narration_anchor": "drives the city route", "operation": "CONNECT",
                                            "target": "legx", "params": {"from": "hub", "to": "nowhere"}, "takeaway": "x"})
    assert any("CONNECT to 'nowhere'" in e for e in validate_direction(direction)["errors"])


def test_bespoke_model_resolves_to_a_timeline_across_scenes() -> None:
    timeline = _timeline()
    validate_artifact("visual_timeline", timeline)
    assert timeline["unmatched"] == [] and ineffective_events(timeline) == []
    assert len(timeline["events"]) == 8 and {e["scene_id"] for e in timeline["events"]} == {"sc2", "sc3"}
    boundary = _windows()["sc3"][0]
    before = state_at(timeline, "route", boundary - 0.01)
    after = state_at(timeline, "route", boundary + 0.01)
    assert before == after and before["elements"]["leg2"]["visible"]
    final = replay_model_states(timeline, "route")[-1][1]
    assert final["elements"]["customer"]["visible"] and final["elements"]["leg2"]["attrs"]["delay"] == 40


# ---- implementation trace ----

def test_trace_maps_every_event_to_bespoke_code() -> None:
    trace = build_trace(_timeline(), PROJECT)
    assert trace["hard_failures"] == [] and trace["implemented"] == trace["total"] == 8
    refs = {e["event_id"]: e["implementation_reference"] for e in trace["events"]}
    assert any("RouteMap" in r and "useMeasures" in r for r in refs["ev-b6"])
    assert all(any("Composition.tsx:" in r for r in rs) for rs in refs.values())
    b5 = next(e for e in trace["events"] if e["event_id"] == "ev-b5")
    assert b5["state_before"]["attrs"] == {} and b5["state_after"]["attrs"] == {"delay": 40.0}
    assert trace["persistent_models"]["route"]["spans_scenes"] is True


def _copy_project(tmp_path: Path) -> Path:
    dst = tmp_path / "atelier_route_fixture"
    shutil.copytree(PROJECT, dst)
    return dst


def test_trace_fails_when_an_event_is_not_implemented(tmp_path) -> None:
    project = _copy_project(tmp_path)
    comp = project / "Composition.tsx"
    text = comp.read_text(encoding="utf-8")
    comp.write_text("\n".join(l for l in text.splitlines() if 'id="customer"' not in l), encoding="utf-8")
    trace = build_trace(_timeline(), project)
    assert any(f.startswith("ev-b8 ") and "not implemented" in f for f in trace["hard_failures"])

    tl = tmp_path / "vt.json"
    tl.write_text(json.dumps(_timeline()), encoding="utf-8")
    prepared = VideoCompose._prepare_atelier_direction(project / "index.tsx", _edit(tl, project / "index.tsx"), None, tmp_path / "out.mp4")
    assert "does not implement the direction contract" in prepared["error"] and "ev-b8" in prepared["error"]


def test_trace_fails_without_provider_or_with_unknown_ids(tmp_path) -> None:
    project = _copy_project(tmp_path)
    comp = project / "Composition.tsx"
    text = comp.read_text(encoding="utf-8").replace("<DirectionProvider timeline={visualTimeline}>", "<>").replace("</DirectionProvider>", "</>")
    text = text.replace('useMeasures("route")', 'useMeasures("routes")')
    comp.write_text(text, encoding="utf-8")
    hard = build_trace(_timeline(), project)["hard_failures"]
    assert any("DirectionProvider" in f for f in hard)
    assert any("'routes' that is not in visual_timeline" in f for f in hard)


def test_atelier_render_requires_the_compiled_timeline_and_injects_it(tmp_path) -> None:
    project = _copy_project(tmp_path)
    (project / "artifacts").mkdir()
    shutil.copy(FIXTURE / "visual_direction.json", project / "artifacts" / "visual_direction.json")
    edit = _edit("unused", project / "index.tsx")
    edit.pop("visual_timeline")
    missing = VideoCompose._prepare_atelier_direction(project / "index.tsx", edit, None, tmp_path / "out.mp4")
    assert "visual_timeline is missing" in missing["error"]

    tl = tmp_path / "vt.json"
    tl.write_text(json.dumps(_timeline()), encoding="utf-8")
    props = tmp_path / "props.json"
    props.write_text(json.dumps({"durationSeconds": 22}), encoding="utf-8")
    ok = VideoCompose._prepare_atelier_direction(project / "index.tsx", _edit(tl, project / "index.tsx"), str(props), tmp_path / "out.mp4")
    merged = json.loads(Path(ok["props_path"]).read_text(encoding="utf-8"))
    assert merged["durationSeconds"] == 22 and len(merged["visualTimeline"]["events"]) == 8
    assert ok["trace"]["implemented"] == 8


def test_templated_render_refuses_a_bespoke_model(tmp_path) -> None:
    tl = tmp_path / "vt.json"
    tl.write_text(json.dumps(_timeline()), encoding="utf-8")
    props = {"cuts": [{"id": "c", "source": "", "in_seconds": 0, "out_seconds": 5, "type": "visual_model",
                       "visual_model": {"model_id": "route"}}], "visual_timeline": str(tl)}
    assert "Render it in atelier" in VideoCompose._attach_visual_timeline(props, "Explainer")


def test_direction_qa_contract_mode_for_atelier() -> None:
    timeline = _timeline()
    edit = _edit("unused")
    edit.pop("visual_timeline")
    qa = DirectionQA().execute({"visual_timeline": timeline, "edit_decisions": edit})
    assert qa.data["mode"] == "atelier" and qa.success
    assert qa.data["implementation_trace"]["implemented"] == 8

    empty = dict(timeline, events=[])
    bad = DirectionQA().execute({"visual_timeline": empty, "edit_decisions": edit, "visual_direction": _load("visual_direction.json")})
    assert not bad.success and any("timeline not compiled" in f for f in bad.data["hard_failures"])


@pytest.mark.skipif(not shutil.which("npx") or not shutil.which("node"), reason="needs Node/npx")
def test_element_reducer_parity_with_typescript(tmp_path) -> None:
    composer = REPO / "remotion-composer"
    if not (composer / "node_modules" / "typescript").exists():
        pytest.skip("remotion-composer node_modules not installed")
    out = tmp_path / "js"
    build = subprocess.run(
        [shutil.which("npx"), "--no-install", "tsc", "--outDir", str(out), "--module", "commonjs", "--target", "es2019",
         "--skipLibCheck", str(composer / "src" / "direction" / "elementModel.ts")],
        cwd=composer, capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    timeline = _timeline()
    timeline["events"].append({"id": "ev-x", "model_id": "route", "operation": "SHIFT", "target": "view",
                               "params": {"zoom": 2}, "time_seconds": 20, "duration_seconds": 1})
    timeline["events"].append({"id": "ev-y", "model_id": "route", "operation": "REMOVE", "target": "hub",
                               "time_seconds": 21, "duration_seconds": 1})
    (tmp_path / "tl.json").write_text(json.dumps(timeline), encoding="utf-8")
    js = ("const r=require(process.argv[1]);const tl=require(process.argv[2]);let s=r.elementInitialState(tl.models[0]);"
          "for(const e of tl.events){s=r.applyElementEvent(s,e);}console.log(JSON.stringify(s));")
    run = subprocess.run(["node", "-e", js, str(out / "elementModel.js"), str(tmp_path / "tl.json")], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    expected = replay_model_states(timeline, "route")[-1][1]
    assert json.loads(run.stdout) == json.loads(json.dumps(expected))


@pytest.mark.skipif(os.environ.get("OPENMONTAGE_RENDER_TESTS") != "1", reason="set OPENMONTAGE_RENDER_TESTS=1 to render with Remotion")
@pytest.mark.parametrize("mode", ["contract", "static_final"])
def test_atelier_fixture_renders_and_direction_qa_judges_it(tmp_path, mode) -> None:
    timeline = _timeline()
    tl = tmp_path / "visual_timeline.json"
    tl.write_text(json.dumps(timeline), encoding="utf-8")
    plan = _load("scene_plan.json")
    props = {"scenes": [{"id": s["id"], "start": s["start_seconds"], "end": s["end_seconds"]} for s in plan["scenes"]],
             "durationSeconds": plan["scenes"][-1]["end_seconds"]}
    if mode == "static_final":
        props["negativeControl"] = "static_final"
    (tmp_path / "props.json").write_text(json.dumps(props), encoding="utf-8")
    edit = _edit(tl)
    edit["bespoke"].update({"props_path": str(tmp_path / "props.json"), "scale": 0.5, "concurrency": 4})
    video = tmp_path / f"route_{mode}.mp4"
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "output_path": str(video)})
    assert result.success, result.error
    assert result.data["final_review"]["checks"]["direction_trace"]["implemented"] == 8
    qa = DirectionQA().execute({"video_path": str(video), "visual_timeline": timeline, "edit_decisions": edit,
                                "visual_direction": _load("visual_direction.json"), "scene_plan": plan,
                                "output_dir": str(tmp_path / "qa")})
    if mode == "contract":
        assert qa.success, qa.data["hard_failures"]
        assert all(c["implemented"] and c["changed_pixels"] >= 25 for c in qa.data["checks"])
    else:
        # Final state drawn from the first frame: the trace still sees the runtime
        # imports, but no anchor changes the picture, so every event fails.
        assert not qa.success
        assert sum("did not change" in f for f in qa.data["hard_failures"]) == len(timeline["events"])
