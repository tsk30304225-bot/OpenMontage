"""Contract for visual_direction -> visual_timeline -> renderer -> Direction QA.

The scene director writes narration-anchored beats; the compiler resolves them
against forced-aligned narration; Remotion executes the events; direction_qa
checks they happened. The contract is topic-agnostic: these tests use a
synthetic release-plan fixture (tests/fixtures/visual_direction/release_plan)
and small inline models, never a specific project's domain.

Set OPENMONTAGE_RENDER_TESTS=1 to also render the fixture with Remotion and run
direction_qa on the video.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.visual_direction import (
    apply_rail_event,
    compile_timeline,
    flatten_alignment,
    ineffective_events,
    match_anchor,
    rail_initial_state,
    rail_schedule,
    replay_model_states,
    validate_direction,
)
from schemas.artifacts import validate_artifact
from tools.analysis.direction_qa import DirectionQA
from tools.video.video_compose import VideoCompose
from tools.video.visual_timeline_compiler import VisualTimelineCompiler

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "visual_direction" / "release_plan"


def _load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def _model(policy="sequential", **state):
    initial = {
        "axis": {"start": 0, "end": 10},
        "slot_interval": 2,
        "items": [
            {"id": "a", "slot": 0, "duration": 2},
            {"id": "b", "slot": 1, "duration": 2},
            {"id": "c", "slot": 2, "duration": 2},
            {"id": "d", "slot": 3, "duration": 2},
        ],
    }
    initial.update(state)
    return {"id": "m", "type": "timeline_rail", "queue": {"policy": policy}, "initial_state": initial}


def _rows(state):
    return rail_schedule(state)["items"]


def _timeline():
    return compile_timeline(_load("visual_direction.json"), _load("alignment.json"),
                            scene_windows={s["id"]: (s["start_seconds"], s["end_seconds"]) for s in _load("scene_plan.json")["scenes"]})


# ---- anchors ----

def test_anchor_matching_ignores_punctuation_and_follows_the_cursor() -> None:
    words = flatten_alignment({"segments": [
        {"words": [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("the plan, the plan again".split())]},
    ]})
    first = match_anchor("the plan", words)
    later = match_anchor("THE PLAN", words, from_index=first["last_word_index"] + 1)
    assert (first["start_seconds"], first["score"]) == (0.0, 1.0)
    assert later["start_seconds"] == 1.0


def test_anchor_matching_works_for_non_latin_scripts() -> None:
    words = flatten_alignment({"word_timestamps": [
        {"word": "금리가", "start": 0.0, "end": 0.4}, {"word": "오르면", "start": 0.5, "end": 0.9},
        {"word": "대출이", "start": 1.0, "end": 1.4}, {"word": "무거워집니다.", "start": 1.5, "end": 2.0},
    ]})
    assert match_anchor("오르면 대출이", words)["start_seconds"] == 0.5
    fuzzy = match_anchor("대출이 무거워집니당", words)
    assert fuzzy is not None and 0.8 <= fuzzy["score"] < 1.0
    assert match_anchor("전혀 다른 문장", words) is None


# ---- schedule policies ----

def test_sequential_policy_propagates_a_longer_item() -> None:
    state = apply_rail_event(rail_initial_state(_model()), {"operation": "EXPAND", "target": "b", "params": {"to": 5}})
    rows = _rows(state)
    assert (rows["b"]["actual_start"], rows["b"]["actual_end"]) == (2, 7)
    assert (rows["c"]["actual_start"], rows["c"]["wait"]) == (7, 3)


def test_independent_policy_has_no_shared_resource() -> None:
    state = apply_rail_event(rail_initial_state(_model("independent")), {"operation": "EXPAND", "target": "b", "params": {"to": 5}})
    rows = _rows(state)
    assert rows["c"]["actual_start"] == 4 and rows["c"]["wait"] == 0


def test_ready_first_policy_takes_a_ready_item_before_a_late_earlier_one() -> None:
    state = rail_initial_state(_model("ready_first"))
    state = apply_rail_event(state, {"operation": "SHIFT", "target": "b", "params": {"ready_by": 3}})
    state = apply_rail_event(state, {"operation": "ADD", "target": "x", "params": {"item": {"id": "x", "planned_start": 2.5, "duration": 1}}})
    rows = _rows(state)
    assert rows["x"]["actual_start"] == 2.5 and rows["x"]["wait"] == 0
    # c becomes ready at 4 while b is still late, so the resource takes c first.
    assert rows["c"]["actual_start"] == 4 and rows["b"]["actual_start"] == 6
    seq = rail_initial_state(_model("sequential"))
    seq = apply_rail_event(seq, {"operation": "SHIFT", "target": "b", "params": {"ready_by": 3}})
    seq = apply_rail_event(seq, {"operation": "ADD", "target": "x", "params": {"item": {"id": "x", "planned_start": 2.5, "duration": 1}}})
    assert _rows(seq)["x"]["actual_start"] == 7


def test_deferred_expand_holds_downstream_until_propagate_and_remove_recovers() -> None:
    held = apply_rail_event(rail_initial_state(_model()), {"operation": "EXPAND", "target": "b", "params": {"to": 5, "propagate": "deferred"}})
    assert _rows(held)["c"]["actual_start"] == 4
    released = apply_rail_event(held, {"operation": "PROPAGATE", "target": "b"})
    assert _rows(released)["c"]["actual_start"] == 7
    recovered = apply_rail_event(released, {"operation": "REMOVE", "target": "c"})
    assert _rows(recovered)["d"]["actual_start"] == 7 and _rows(recovered)["c"]["present"] is False


def test_slot_interval_view_and_overrun() -> None:
    state = apply_rail_event(rail_initial_state(_model()), {"operation": "SHIFT", "target": "slot_interval", "params": {"interval": 3}})
    assert [r["planned_start"] for r in _rows(state).values()] == [0, 3, 6, 9]
    state = apply_rail_event(state, {"operation": "SHIFT", "target": "view", "params": {"deadline": 10}})
    assert rail_schedule(state)["overrun"] == 1


# ---- synthetic fixture: validate + compile ----

def test_fixture_direction_validates_and_compiles_to_exact_anchor_times() -> None:
    direction = _load("visual_direction.json")
    validate_artifact("visual_direction", direction)
    for scene in _load("scene_plan.json")["scenes"]:
        assert scene["id"]
    report = validate_direction(direction, _load("script.json"))
    assert report["errors"] == []

    timeline = _timeline()
    validate_artifact("visual_timeline", timeline)
    assert timeline["unmatched"] == [] and ineffective_events(timeline) == []
    assert [e["beat_id"] for e in timeline["events"]] == ["b1", "b2", "b3", "b4", "b5", "b6"]
    assert all(e["anchor"]["score"] == 1.0 for e in timeline["events"])
    words = flatten_alignment(_load("alignment.json"))
    assert timeline["events"][2]["time_seconds"] == next(w["start"] for w in words if w["word"] == "testing")

    final = replay_model_states(timeline, "release_plan")[-1][1]
    assert rail_schedule(final)["overrun"] == 3


def test_validation_rejects_bad_targets_policies_and_unscripted_anchors() -> None:
    direction = _load("visual_direction.json")
    direction["visual_models"][0]["queue"]["policy"] = "priority_lane"
    beats = direction["scenes"][2]["beats"]
    beats.append({"id": "bx", "narration_anchor": "words nobody said", "operation": "MEASURE", "target": "docs", "takeaway": "x"})
    beats.append({"id": "by", "narration_anchor": "Nothing moves yet", "operation": "EXPAND", "target": "nobody", "takeaway": "x"})
    errors = validate_direction(direction, _load("script.json"))["errors"]
    assert any("priority_lane" in e for e in errors)
    assert any("bx" in e and "does not occur in the script" in e for e in errors)
    assert any("by" in e and "does not exist" in e for e in errors)


def test_compiler_tool_writes_timeline_and_fails_on_noop_or_unmatched(tmp_path) -> None:
    common = {"visual_direction": str(FIXTURE / "visual_direction.json"), "script": str(FIXTURE / "script.json"),
              "scene_plan": str(FIXTURE / "scene_plan.json"), "alignment": str(FIXTURE / "alignment.json")}
    ok = VisualTimelineCompiler().execute({"operation": "compile", **common, "output_path": str(tmp_path / "vt.json")})
    assert ok.success, ok.error
    assert json.loads((tmp_path / "vt.json").read_text(encoding="utf-8"))["events"]

    direction = _load("visual_direction.json")
    direction["scenes"][2]["beats"].append(
        {"id": "b7", "narration_anchor": "misses its date by three days", "operation": "MEASURE", "target": "all",
         "params": {"metric": "overrun", "exclusive": True}, "takeaway": "duplicate"})
    dup = VisualTimelineCompiler().execute({"operation": "compile", **common, "visual_direction": direction})
    assert not dup.success and "ev-b7" in dup.data["ineffective_events"]


def test_compiler_warns_when_items_run_past_the_visible_axis() -> None:
    direction = _load("visual_direction.json")
    direction["visual_models"][0]["initial_state"]["axis"]["end"] = 9
    common = {"script": str(FIXTURE / "script.json"), "scene_plan": str(FIXTURE / "scene_plan.json"),
              "alignment": str(FIXTURE / "alignment.json")}
    narrow = VisualTimelineCompiler().execute({"operation": "compile", **common, "visual_direction": direction})
    assert narrow.success
    overflow = [w for w in narrow.data["warnings"] if "beyond axis end 9" in w]
    assert len(overflow) == 1 and "ev-b5" in overflow[0]
    wide = VisualTimelineCompiler().execute({"operation": "compile", **common, "visual_direction": str(FIXTURE / "visual_direction.json")})
    assert not any("beyond axis end" in w for w in wide.data["warnings"])


# ---- renderer wiring and QA contract ----

def _edit(timeline_path):
    windows = {s["id"]: s for s in _load("scene_plan.json")["scenes"]}
    return {
        "version": "1.0", "render_runtime": "remotion", "renderer_family": "explainer-data",
        "cuts": [
            {"id": "sc1", "source": "", "in_seconds": 0, "out_seconds": windows["sc1"]["end_seconds"], "type": "text_card"},
            {"id": "sc2-sc3", "source": "", "in_seconds": windows["sc2"]["start_seconds"], "out_seconds": windows["sc3"]["end_seconds"],
             "type": "visual_model", "visual_model": {"model_id": "release_plan", "caption": "One estimate moves the launch"}},
            {"id": "sc4", "source": "", "in_seconds": windows["sc4"]["start_seconds"], "out_seconds": windows["sc4"]["end_seconds"], "type": "text_card"},
        ],
        "visual_timeline": str(timeline_path),
    }


def test_video_compose_attaches_timeline_and_rejects_unknown_model(tmp_path) -> None:
    path = tmp_path / "visual_timeline.json"
    path.write_text(json.dumps(_timeline()), encoding="utf-8")
    edit = _edit(path)
    validate_artifact("edit_decisions", edit)

    props = json.loads(json.dumps(edit))
    assert VideoCompose._attach_visual_timeline(props, "Explainer") is None
    assert len(props["visualTimeline"]["events"]) == 6 and "visual_timeline" not in props

    props = json.loads(json.dumps(edit))
    props["cuts"][1]["visual_model"]["model_id"] = "other"
    assert "not in visual_timeline models" in VideoCompose._attach_visual_timeline(props, "Explainer")
    assert "Explainer" in VideoCompose._attach_visual_timeline(json.loads(json.dumps(edit)), "CinematicRenderer")


def test_direction_qa_hard_fails_event_without_its_model_on_screen(tmp_path) -> None:
    timeline = _timeline()
    edit = _edit(tmp_path / "unused.json")
    ok = DirectionQA().execute({"visual_timeline": timeline, "edit_decisions": edit, "scene_plan": _load("scene_plan.json")})
    assert ok.success and ok.data["hard_failures"] == []

    short = json.loads(json.dumps(edit))
    short["cuts"][1]["out_seconds"] = timeline["events"][-1]["time_seconds"] - 0.5
    bad = DirectionQA().execute({"visual_timeline": timeline, "edit_decisions": short})
    assert not bad.success
    assert any("ev-b6" in f and "never executes" in f for f in bad.data["hard_failures"])


def test_explainer_renders_visual_model_cuts() -> None:
    source = (REPO / "remotion-composer" / "src" / "Explainer.tsx").read_text(encoding="utf-8")
    assert 'cut.type === "visual_model"' in source
    assert "visualTimeline={props.visualTimeline}" in source


def _npx_cmd():
    npx = shutil.which("npx")
    return [npx] if npx else None


@pytest.mark.skipif(not shutil.which("npx") or not shutil.which("node"), reason="needs Node/npx for the Remotion reducer")
def test_remotion_reducer_matches_python_for_every_policy(tmp_path) -> None:
    """The TS reducer is what renders; the Python mirror is what compile and QA reason with."""
    composer = REPO / "remotion-composer"
    if not (composer / "node_modules" / "typescript").exists():
        pytest.skip("remotion-composer node_modules not installed")
    out = tmp_path / "js"
    build = subprocess.run(
        _npx_cmd() + ["--no-install", "tsc", "--outDir", str(out), "--module", "commonjs", "--target", "es2019",
                      "--skipLibCheck", str(composer / "src" / "components" / "visual-models" / "timelineRail.ts")],
        cwd=composer, capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    events = [
        {"id": "e1", "model_id": "m", "operation": "EXPAND", "target": "b", "params": {"to": 5, "propagate": "deferred"}, "time_seconds": 1, "duration_seconds": 1},
        {"id": "e2", "model_id": "m", "operation": "PROPAGATE", "target": "b", "time_seconds": 2, "duration_seconds": 1},
        {"id": "e3", "model_id": "m", "operation": "SHIFT", "target": "c", "params": {"ready_by": 4}, "time_seconds": 3, "duration_seconds": 1},
        {"id": "e4", "model_id": "m", "operation": "ADD", "target": "x", "params": {"item": {"id": "x", "planned_start": 5, "duration": 1.5}}, "time_seconds": 4, "duration_seconds": 1},
        {"id": "e5", "model_id": "m", "operation": "REMOVE", "target": "d", "time_seconds": 5, "duration_seconds": 1},
        {"id": "e6", "model_id": "m", "operation": "SHIFT", "target": "slot_interval", "params": {"interval": 2.5}, "time_seconds": 6, "duration_seconds": 1},
    ]
    js = (
        "const r=require(process.argv[1]);const cases=require(process.argv[2]);const res={};"
        "for(const [name,tl] of Object.entries(cases)){let s=r.initialRailState(tl.models[0]);"
        "for(const e of tl.events){s=r.applyRailEvent(s,e);}const rows=r.railSchedule(s).rows;const o={};"
        "for(const k of Object.keys(rows)){const x=rows[k];o[k]=[x.actual_start??null,x.actual_end??null,x.wait??null,x.idle_before??null];}"
        "s.deadline=9;const sc=r.railSchedule(s);o.__end=[sc.lastEnd,sc.overrun,null,null];res[name]=o;}console.log(JSON.stringify(res));"
    )
    cases, expected = {}, {}
    # "held" stops after the deferred EXPAND: downstream items have not moved, and the
    # visible end / overrun must not include consequences the viewer has not seen yet.
    variants = {p: (p, events) for p in ("independent", "sequential", "ready_first")}
    variants["held"] = ("sequential", events[:1])
    for policy, (queue, evs) in variants.items():
        tl = {"models": [_model(queue)], "events": evs}
        cases[policy] = tl
        state = replay_model_states(tl, "m")[-1][1]
        state["deadline"] = 9
        sched = rail_schedule(state)
        expected[policy] = {k: [r.get("actual_start"), r.get("actual_end"), r.get("wait"), r.get("idle_before")] for k, r in sched["items"].items()}
        expected[policy]["__end"] = [sched["last_end"], sched["overrun"], None, None]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    run = subprocess.run(["node", "-e", js, str(out / "timelineRail.js"), str(tmp_path / "cases.json")], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    for policy, rows in expected.items():
        for item_id, values in rows.items():
            assert got[policy][item_id] == pytest.approx(values, abs=1e-6) if values[0] is not None else got[policy][item_id] == values, (policy, item_id)


@pytest.mark.skipif(os.environ.get("OPENMONTAGE_RENDER_TESTS") != "1", reason="set OPENMONTAGE_RENDER_TESTS=1 to render with Remotion")
def test_fixture_renders_and_passes_direction_qa(tmp_path) -> None:
    path = tmp_path / "visual_timeline.json"
    path.write_text(json.dumps(_timeline()), encoding="utf-8")
    edit = _edit(path)
    edit["cuts"][0].update({"text": "Every release starts as a clean plan."})
    edit["cuts"][2].update({"text": "The plan was fine. The estimate was not."})
    video = tmp_path / "release_plan.mp4"
    result = VideoCompose().execute({"operation": "remotion_render", "edit_decisions": edit, "output_path": str(video)})
    assert result.success, result.error
    qa = DirectionQA().execute({"video_path": str(video), "visual_timeline": str(path), "edit_decisions": edit,
                                "visual_direction": _load("visual_direction.json"), "scene_plan": _load("scene_plan.json"),
                                "output_dir": str(tmp_path / "qa")})
    assert qa.success, qa.data["hard_failures"]
    assert all(c["executed"] for c in qa.data["checks"])

    # Negative control: claim the events happen during the static closing card.
    # The contract checks still pass (a model cut covers them), so only the
    # pixel check can catch it - and it must.
    fake = json.loads(json.dumps(_timeline()))
    closing = next(c for c in edit["cuts"] if c["id"] == "sc4")
    for i, ev in enumerate(fake["events"]):
        ev["time_seconds"] = closing["in_seconds"] + 0.6 + i * 0.5
    fake_edit = {"cuts": [{"id": "claimed", "source": "", "in_seconds": closing["in_seconds"], "out_seconds": closing["out_seconds"],
                           "type": "visual_model", "visual_model": {"model_id": "release_plan"}}]}
    control = DirectionQA().execute({"video_path": str(video), "visual_timeline": fake, "edit_decisions": fake_edit,
                                     "output_dir": str(tmp_path / "qa_negative")})
    assert not control.success
    unchanged = [f for f in control.data["hard_failures"] if "did not change" in f]
    assert len(unchanged) >= len(fake["events"]) - 1
