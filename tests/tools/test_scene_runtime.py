"""Scene runtime override v1 and the context-light tool menu.

Offline tests fake the HyperFrames renderer. With OPENMONTAGE_RENDER_TESTS=1 a
real mixed-runtime project renders: footage, Remotion and HyperFrames scenes in
one MP4, with the HyperFrames reveals checked against the narration anchors.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.scene_runtime import resolve_scene_runtimes, scene_events, trace_workspace, write_bridge
from lib.tool_routing import creative_menu
from lib.visual_direction import compile_timeline
from schemas.artifacts import validate_artifact
from tools.analysis.direction_qa import DirectionQA
from tools.analysis.tool_router import ToolRouter
from tools.base_tool import ToolResult
from tools.video import hyperframes_compose
from tools.video.video_compose import VideoCompose

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "scene_runtime"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _timeline():
    plan = _load("scene_plan.json")
    return compile_timeline(_load("visual_direction.json"), _load("alignment.json"),
                            scene_windows={s["id"]: (s["start_seconds"], s["end_seconds"]) for s in plan["scenes"]})


# ---------------------------------------------------------------- context-light menu

def _cap(**routable):
    def rec(offer, tool, axes, notes, ok):
        return {"offer": offer, "tool": tool, "axes": axes, "notes": notes, "strengths": {}, "routable": ok,
                "evidence_level": "OUTPUT_VERIFIED" if ok else "DISCOVERED", "smoke": {"artifact": "C:/x/smoke.mp4"},
                "blocked_by": [] if ok else ["tool status is 'unavailable'"]}
    return {"generated_at": "t", "offers": [
        rec("pexels_footage", "pexels_video", ["reality_footage"], "real places, people", routable.get("footage", True)),
        rec("remotion_graphics", "video_compose", ["structured_graphics"], "data, causal diagrams", True),
        rec("hyperframes_motion", "hyperframes_compose", ["expressive_motion"], "kinetic type, hero reveals",
            routable.get("hyperframes", True)),
        rec("flux_still", "flux_image", ["synthetic_image"], "things footage cannot show", False),
        rec("qwen3_narration", "qwen3_tts", ["narration"], "voice", True),
    ]}


def test_menu_is_short_and_carries_no_audit_detail() -> None:
    menu = creative_menu(_cap(), approved_runtimes=["remotion", "hyperframes"])
    text = menu["text"]
    assert len(text.splitlines()) <= 8 and len(text) < 1200
    for leak in ("OUTPUT_VERIFIED", "smoke", "evidence", "score", "blocked", "C:/x", "rejected"):
        assert leak not in text, leak
    assert '[ROUTABLE] HyperFrames (hyperframes_compose): kinetic type, hero reveals -> scene runtime "hyperframes"' in text
    assert "[UNAVAILABLE] Generated image / video: things footage cannot show -> do not select" in text


def test_menu_marks_unverified_runtime_unavailable() -> None:
    text = creative_menu(_cap(hyperframes=False))["text"]
    assert "[UNAVAILABLE] HyperFrames: kinetic type, hero reveals -> do not select" in text


def test_menu_separates_installed_unverified_and_approval_required() -> None:
    cap = _cap()
    grok = {"offer": "grok_i2v_clip", "tool": "grok_cli_video", "axes": ["synthetic_video"], "notes": "I2V shots",
            "strengths": {}, "routable": False, "status": "available", "cost_tier": "subscription"}
    text = creative_menu({**cap, "offers": [o for o in cap["offers"] if o["offer"] != "flux_still"] + [grok]})["text"]
    assert "[AVAILABLE] Generated image / video (grok_cli_video): I2V shots -> installed but output not verified here" in text
    codex = {"offer": "codex_still", "tool": "codex_image", "axes": ["synthetic_image"], "notes": "text stills",
             "strengths": {}, "routable": True, "status": "available", "cost_tier": "subscription"}
    menu = creative_menu({**cap, "offers": cap["offers"] + [grok, codex]})
    line = next(l for l in menu["text"].splitlines() if "Generated" in l)
    assert line.startswith("- [APPROVAL_REQUIRED] Generated image / video (codex_image): text stills")
    assert "only after the user approves that provider" in line and line.endswith("not verified here: grok_cli_video")
    assert {f["family"]: f["state"] for f in menu["families"]}["footage"] == "ROUTABLE"


def test_live_menu_lists_only_offered_families_not_the_registry(monkeypatch) -> None:
    from tools.tool_registry import registry

    registry.ensure_discovered()
    text = ToolRouter().execute({"operation": "menu", "capability": _cap()}).data["text"]
    named = [t.name for t in registry._tools.values() if t.name in text]
    assert len(registry._tools) > 100 and len(named) <= 8


# ---------------------------------------------------------------- runtime resolution

def _scenes(*runtimes):
    return [{"id": f"s{i}", **({"runtime": r} if r else {}), "runtime_reason": "why"} for i, r in enumerate(runtimes)]


def test_inherit_and_missing_runtime_use_the_project_default() -> None:
    out = resolve_scene_runtimes(_scenes(None, "inherit"), "remotion", ["remotion"])
    assert [s["runtime"] for s in out["scenes"]] == ["remotion", "remotion"] and out["warnings"] == []


def test_override_is_used_when_approved() -> None:
    out = resolve_scene_runtimes(_scenes("footage", "remotion", "hyperframes"), "remotion", ["remotion", "hyperframes"])
    assert [s["runtime"] for s in out["scenes"]] == ["footage", "remotion", "hyperframes"] and out["warnings"] == []


def test_unapproved_runtime_warns_and_falls_back() -> None:
    out = resolve_scene_runtimes(_scenes("hyperframes", "footage"), "remotion", ["remotion"])
    assert out["scenes"][0] == {"scene_id": "s0", "runtime": "remotion", "reason": "why", "requested": "hyperframes"}
    assert out["scenes"][1]["runtime"] == "footage"  # footage is a cut, not a composition runtime
    assert [w["code"] for w in out["warnings"]] == ["RUNTIME_NOT_APPROVED"]


def test_unavailable_runtime_warns() -> None:
    out = resolve_scene_runtimes(_scenes("hyperframes"), "remotion", ["remotion", "hyperframes"], ["hyperframes"])
    assert out["scenes"][0]["runtime"] == "remotion" and out["warnings"][0]["code"] == "RUNTIME_UNAVAILABLE"


def test_scene_runtimes_operation_returns_compact_rows() -> None:
    r = ToolRouter().execute({"operation": "scene_runtimes", "scene_plan": _load("scene_plan.json"),
                              "master_runtime": "remotion", "approved_runtimes": ["remotion", "hyperframes"],
                              "capability": _cap()})
    assert r.success
    assert [(s["scene_id"], s["runtime"]) for s in r.data["scenes"]] == [
        ("sc1", "footage"), ("sc2", "remotion"), ("sc3", "hyperframes"), ("sc4", "remotion"), ("sc5", "hyperframes")]
    assert set(r.data["scenes"][2]) == {"scene_id", "runtime", "reason"}


def test_schemas_accept_scene_runtime_fields() -> None:
    validate_artifact("scene_plan", _load("scene_plan.json"))
    edit = _edit(Path("x.mp4"), Path("ws3"), Path("ws5"))
    for cut in edit["cuts"]:
        cut.pop("text", None)  # templated card text is outside the cut schema (pre-existing)
    validate_artifact("edit_decisions", edit)


# ---------------------------------------------------------------- hyperframes direction bridge

def _cut(scene="sc3", start=8.0, end=12.0):
    return {"id": f"c-{scene}", "scene_id": scene, "in_seconds": start, "out_seconds": end}


def _workspace(tmp_path, name="hf_sc3"):
    ws = tmp_path / name
    shutil.copytree(FIX / name, ws)
    return ws


def test_bridge_gives_the_scene_its_events_in_local_time(tmp_path) -> None:
    ws = _workspace(tmp_path)
    events = scene_events(_timeline(), _cut())
    assert [(e["id"], e["t"]) for e in events] == [("ev-b1", 1.5)]
    js = write_bridge(ws, _cut(), events).read_text(encoding="utf-8")
    assert '"ev-b1"' in js and "window.OM" in js
    trace = trace_workspace(ws, events, expected_duration=4.0)
    assert trace["hard_failures"] == [] and trace["implemented"] == 1
    assert trace["events"][0]["where"][0].startswith("index.html:")


def test_trace_refuses_missing_bridge_unplaced_or_foreign_events_and_wrong_duration(tmp_path) -> None:
    ws = _workspace(tmp_path)
    html = (ws / "index.html").read_text(encoding="utf-8")
    events = scene_events(_timeline(), _cut())
    (ws / "index.html").write_text(html.replace('<script src="om-direction.js"></script>', ""), encoding="utf-8")
    assert any("does not load om-direction.js" in h for h in trace_workspace(ws, events)["hard_failures"])
    (ws / "index.html").write_text(html.replace('OM.at("ev-b1")', "1.5"), encoding="utf-8")
    assert any("ev-b1" in h and "not placed" in h for h in trace_workspace(ws, events)["hard_failures"])
    (ws / "index.html").write_text(html.replace("ev-b1", "ev-b9"), encoding="utf-8")
    assert any("'ev-b9'" in h for h in trace_workspace(ws, events)["hard_failures"])
    (ws / "index.html").write_text(html, encoding="utf-8")
    assert any("data-duration" in h for h in trace_workspace(ws, events, expected_duration=5.0)["hard_failures"])


# ---------------------------------------------------------------- video_compose integration (faked renderers)

def _edit(footage, ws3, ws5, approved=("remotion", "hyperframes"), timeline=None):
    return {
        "version": "1.0", "renderer_family": "explainer-data", "render_runtime": "remotion",
        "approved_runtimes": list(approved),
        **({"visual_timeline": timeline} if timeline is not None else {}),
        "cuts": [
            {"id": "c1", "scene_id": "sc1", "source": str(footage), "in_seconds": 0, "out_seconds": 4, "runtime": "footage"},
            {"id": "c2", "scene_id": "sc2", "source": "", "in_seconds": 4, "out_seconds": 8, "type": "text_card",
             "text": "Old pipes run under the city"},
            {"id": "c3", "scene_id": "sc3", "source": "", "in_seconds": 8, "out_seconds": 12, "runtime": "hyperframes",
             "hyperframes": {"workspace": str(ws3), "quality": "draft"}},
            {"id": "c4", "scene_id": "sc4", "source": "", "in_seconds": 12, "out_seconds": 16, "type": "text_card",
             "text": "Leaks hide underground", "runtime": "remotion"},
            {"id": "c5", "scene_id": "sc5", "source": "", "in_seconds": 16, "out_seconds": 20, "runtime": "hyperframes",
             "hyperframes": {"workspace": str(ws5), "quality": "draft"}},
        ],
    }


@pytest.fixture
def capture(monkeypatch):
    seen = {}

    def fake_remotion(self, remotion_inputs):
        seen["cuts"] = remotion_inputs["edit_decisions"]["cuts"]
        return ToolResult(success=True, data={})

    def fake_hf(self, inputs):
        seen.setdefault("hf", []).append(inputs)
        Path(inputs["output_path"]).write_bytes(b"clip")
        return ToolResult(success=True, data={"output": inputs["output_path"]})

    monkeypatch.setattr(VideoCompose, "_remotion_render", fake_remotion)
    monkeypatch.setattr(VideoCompose, "_pre_compose_validation", lambda self, *a: None)
    monkeypatch.setattr(hyperframes_compose.HyperFramesCompose, "execute", fake_hf)
    return seen


def test_project_without_overrides_renders_exactly_as_before(tmp_path, capture) -> None:
    edit = {"version": "1.0", "renderer_family": "explainer-data", "render_runtime": "remotion",
            "cuts": [{"id": "c1", "source": "", "in_seconds": 0, "out_seconds": 3, "type": "text_card", "text": "hi"}]}
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "asset_manifest": {"assets": []},
                                     "output_path": str(tmp_path / "out.mp4")})
    assert result.success and capture["cuts"] == edit["cuts"] and "hf" not in capture
    assert "scene_runtimes" not in (result.data or {})


def test_hyperframes_scenes_become_clips_in_the_remotion_assembly(tmp_path, capture) -> None:
    ws3, ws5 = _workspace(tmp_path, "hf_sc3"), _workspace(tmp_path, "hf_sc5")
    footage = tmp_path / "plant.mp4"
    footage.write_bytes(b"v")
    result = VideoCompose().execute({"operation": "render", "edit_decisions": _edit(footage, ws3, ws5, timeline=_timeline()),
                                     "asset_manifest": {"assets": []}, "output_path": str(tmp_path / "out.mp4")})
    assert result.success, result.error
    cuts = {c["id"]: c for c in capture["cuts"]}
    assert cuts["c3"]["source"].endswith("scene_clips\\c3.mp4") or cuts["c3"]["source"].endswith("scene_clips/c3.mp4")
    assert "runtime" not in cuts["c3"] and "hyperframes" not in cuts["c3"] and cuts["c3"]["source_in_seconds"] == 0
    assert cuts["c2"] == _edit(footage, ws3, ws5)["cuts"][1]  # Remotion scene untouched
    assert [i["operation"] for i in capture["hf"]] == ["render_existing", "render_existing"]
    assert json.loads((ws5 / "om-direction.json").read_text(encoding="utf-8"))["events"][0]["id"] == "ev-b2"


def test_hyperframes_scene_without_approval_is_refused(tmp_path, capture) -> None:
    ws3, ws5 = _workspace(tmp_path, "hf_sc3"), _workspace(tmp_path, "hf_sc5")
    footage = tmp_path / "plant.mp4"
    footage.write_bytes(b"v")
    result = VideoCompose().execute({"operation": "render", "asset_manifest": {"assets": []},
                                     "edit_decisions": _edit(footage, ws3, ws5, approved=("remotion",), timeline=_timeline()),
                                     "output_path": str(tmp_path / "out.mp4")})
    assert not result.success and result.error.startswith("RUNTIME_NOT_APPROVED") and "hf" not in capture


def test_hyperframes_scene_that_skips_its_direction_is_refused(tmp_path, capture) -> None:
    ws3, ws5 = _workspace(tmp_path, "hf_sc3"), _workspace(tmp_path, "hf_sc5")
    html = (ws3 / "index.html").read_text(encoding="utf-8").replace('OM.at("ev-b1")', "1.5")
    (ws3 / "index.html").write_text(html, encoding="utf-8")
    footage = tmp_path / "plant.mp4"
    footage.write_bytes(b"v")
    result = VideoCompose().execute({"operation": "render", "asset_manifest": {"assets": []},
                                     "edit_decisions": _edit(footage, ws3, ws5, timeline=_timeline()),
                                     "output_path": str(tmp_path / "out.mp4")})
    assert not result.success and "does not implement its visual direction" in result.error and "hf" not in capture


# ---------------------------------------------------------------- real mixed-runtime render

RENDER = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_RENDER_TESTS") != "1" or not shutil.which("ffmpeg") or not shutil.which("npx"),
    reason="set OPENMONTAGE_RENDER_TESTS=1 (needs ffmpeg, Remotion and HyperFrames)",
)


def _mean_rgb(video: Path, t: float) -> tuple[float, float, float]:
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1",
                          "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    px = np.frombuffer(raw, dtype=np.uint8).reshape(90, 160, 3).astype(float)
    return tuple(px.reshape(-1, 3).mean(axis=0))


@RENDER
def test_mixed_runtime_project_renders_one_mp4_and_keeps_direction(tmp_path) -> None:
    footage = tmp_path / "plant.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(footage)], check=True)
    ws3, ws5 = _workspace(tmp_path, "hf_sc3"), _workspace(tmp_path, "hf_sc5")
    timeline = _timeline()
    tl_path = tmp_path / "visual_timeline.json"
    tl_path.write_text(json.dumps(timeline), encoding="utf-8")
    edit = _edit(footage, ws3, ws5, timeline=str(tl_path))
    video = tmp_path / "mixed.mp4"
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "asset_manifest": {"assets": []},
                                     "output_path": str(video)})
    assert result.success, result.error
    runtimes = {r["cut_id"]: r for r in result.data["scene_runtimes"]}
    assert [runtimes[c]["runtime"] for c in ("c1", "c2", "c3", "c4", "c5")] == [
        "footage", "remotion", "hyperframes", "remotion", "hyperframes"]
    assert runtimes["c3"]["implemented"] == 1 and runtimes["c5"]["implemented"] == 1

    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(video)], capture_output=True, text=True).stdout)
    assert abs(duration - 21.0) < 0.3  # 20 s of cuts + the Explainer's existing 1 s final-fade padding
    # Each runtime is visibly different: colour-bar footage, Remotion card, dark HyperFrames stage.
    footage_rgb, card_rgb, hero_rgb = _mean_rgb(video, 2.0), _mean_rgb(video, 6.0), _mean_rgb(video, 11.0)
    assert max(abs(a - b) for a, b in zip(footage_rgb, hero_rgb)) > 10
    assert max(abs(a - b) for a, b in zip(card_rgb, hero_rgb)) > 3

    # Direction: the HyperFrames reveals change the picture at their narration anchors.
    qa = DirectionQA().execute({"video_path": str(video), "visual_timeline": timeline, "edit_decisions": edit,
                                "output_dir": str(tmp_path / "qa")})
    assert qa.success, qa.data["hard_failures"]
    rows = {r["event"]: r for r in qa.data["checks"]}
    assert rows["ev-b1"]["executed"] and rows["ev-b1"]["implemented"] and rows["ev-b1"]["changed_pixels"] >= 150
    assert rows["ev-b2"]["executed"] and rows["ev-b2"]["implemented"] and rows["ev-b2"]["changed_pixels"] >= 150


# ---------------------------------------------------------------- atelier assembly

ROUTE = REPO / "tests" / "fixtures" / "visual_direction" / "atelier_route"


def _route_timeline():
    load = lambda n: json.loads((ROUTE / n).read_text(encoding="utf-8"))
    plan = load("scene_plan.json")
    return compile_timeline(load("visual_direction.json"), load("alignment.json"),
                            scene_windows={s["id"]: (s["start_seconds"], s["end_seconds"]) for s in plan["scenes"]})


def test_atelier_needs_the_composition_to_read_scene_clips(tmp_path) -> None:
    ws = _workspace(tmp_path, "hf_sc3")
    edit = {"version": "1.0", "render_runtime": "remotion", "composition_mode": "atelier",
            "approved_runtimes": ["remotion", "hyperframes"],
            "cuts": [{"id": "c4", "scene_id": "sc4", "source": "", "in_seconds": 18.61, "out_seconds": 22.78,
                      "runtime": "hyperframes", "hyperframes": {"workspace": str(ws)}}],
            "bespoke": {"entry": str(ROUTE / "atelier_route_fixture" / "index.tsx"),
                        "composition_id": "AtelierRouteFixture", "art_direction": "fixture"}}
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "output_path": str(tmp_path / "o.mp4")})
    assert not result.success and "props.sceneClips" in result.error


def test_atelier_props_carry_scene_clips_and_trace_skips_their_events(tmp_path) -> None:
    timeline = _route_timeline()
    sc3_events = {e["id"] for e in timeline["events"] if e["scene_id"] == "sc3"}
    assert sc3_events
    edit = {"visual_timeline": timeline, "cuts": [
        {"id": "c3", "scene_id": "sc3", "in_seconds": 11.07, "out_seconds": 18.61, "runtime": "hyperframes",
         "hyperframes": {"workspace": "unused"}}]}
    clips = [{"scene_id": "sc3", "cut_id": "c3", "src": "scene_clips/c3.mp4", "start": 11.07, "end": 18.61}]
    out = VideoCompose._prepare_atelier_direction(ROUTE / "atelier_route_fixture" / "index.tsx", edit, None,
                                                  tmp_path / "o.mp4", scene_clips=clips)
    assert "error" not in out, out.get("error")
    props = json.loads(Path(out["props_path"]).read_text(encoding="utf-8"))
    assert props["sceneClips"] == clips and props["visualTimeline"]["events"]
    traced = {e["event_id"] for e in out["trace"]["events"]}
    assert traced and not traced & sc3_events
