"""Capability-based tool routing: contract, evidence ladder, router, usage QA.

Offline: fake tools and hand-built audit records, no network and no renders.
"""

import copy
import json
import random
from pathlib import Path

import jsonschema
import pytest

from lib import tool_routing as tr
from lib.tool_routing import RouteOffer, audit_tools, route_scenes, tool_usage_report
from schemas.artifacts import validate_artifact
from tools.analysis.direction_qa import DirectionQA
from tools.analysis.tool_router import ToolRouter
from tools.base_tool import BaseTool, ToolResult, ToolStatus
from tools.tool_registry import registry
from tools.video.visual_timeline_compiler import VisualTimelineCompiler

REPO = Path(__file__).resolve().parents[2]
ROUTE = REPO / "tests" / "fixtures" / "visual_direction" / "atelier_route"


# ---------------------------------------------------------------- contract

def _registry_tools():
    registry.ensure_discovered()
    return list(registry._tools.values())


def test_every_declared_offer_has_valid_routing_metadata() -> None:
    offers = [(t.name, o) for t in _registry_tools() for o in t.route_offers]
    assert offers, "no tool declares route offers"
    for name, offer in offers:
        assert isinstance(offer, RouteOffer), name
        assert offer.problems() == [], f"{name}/{offer.id}: {offer.problems()}"
    ids = [o.id for _, o in offers]
    assert len(ids) == len(set(ids)), "offer ids must be unique across tools"
    for _, offer in offers:
        for fb in offer.fallback:
            assert fb in ids, f"{offer.id} falls back to unknown offer {fb!r}"


def test_selector_capability_strings_are_untouched() -> None:
    """Selectors discover providers by `capability`; routing must not change it."""
    by_name = {t.name: t for t in _registry_tools()}
    assert by_name["pexels_video"].capability == "video_generation"
    assert by_name["hyperframes_compose"].capability == "video_post"
    assert "reality_footage" in by_name["pexels_video"].route_offers[0].axes


def test_tools_without_offers_keep_default_contract() -> None:
    tool = next(t for t in _registry_tools() if not t.route_offers)
    assert tool.get_info()["route_offers"] == []
    assert tool.routing_smoke("x", Path("."), {}) is None


def test_every_need_maps_to_known_axes_and_roles() -> None:
    for key, spec in tr.NEEDS.items():
        assert spec["axes"] and all(a in tr.CAPABILITY_AXES for a in spec["axes"]), key


def test_music_gen_does_not_claim_sfx_it_cannot_make() -> None:
    by_name = {t.name: t for t in _registry_tools()}
    assert not any("sfx" in o.axes for o in by_name["music_gen"].route_offers)


# ---------------------------------------------------------------- evidence ladder

class _Fake(BaseTool):
    name = "fake_tool"
    version = "1.0.0"
    available = True
    fail = False
    calls = 0

    def get_status(self):
        return ToolStatus.AVAILABLE if self.available else ToolStatus.UNAVAILABLE

    def routing_smoke(self, offer_id, workdir, cache):
        type(self).calls += 1
        if self.fail:
            raise RuntimeError("provider said no")
        out = workdir / f"{offer_id}.json"
        out.write_text('{"ok": true}', encoding="utf-8")
        return {"artifact": str(out), "detail": "fake"}

    def execute(self, inputs):
        return ToolResult(success=True)


def _offer(id="fake_footage", **kw):
    base = dict(id=id, axes=("reality_footage",), scopes=("scene",), triggers=("location",))
    base.update(kw)
    return RouteOffer(**base)


def _fake(name="fake_tool", offers=None, **attrs):
    cls = type(f"Fake_{name}", (_Fake,), {"name": name, "route_offers": offers or [_offer()], "calls": 0, **attrs})
    return cls()


def _audit(tools, tmp_path, **kw):
    kw.setdefault("projects_roots", [])
    return audit_tools(tools, root=tmp_path / "audit", **kw)


def test_ladder_from_status_to_output_verified(tmp_path) -> None:
    down = _fake("down_tool", [_offer("down_offer")], available=False)
    report = _audit([_fake(), down], tmp_path)
    levels = {o["offer"]: o for o in report["offers"]}
    assert levels["down_offer"]["evidence_level"] == "DISCOVERED" and not levels["down_offer"]["routable"]
    assert levels["fake_footage"]["evidence_level"] == "AVAILABLE" and not levels["fake_footage"]["routable"]
    assert "no smoke evidence" in levels["fake_footage"]["blocked_by"][0]

    smoked = _audit([_fake()], tmp_path, run_smoke=True)["offers"][0]
    assert smoked["evidence_level"] == "OUTPUT_VERIFIED" and smoked["routable"] and smoked["blocked_by"] == []


def test_failed_smoke_is_evidence_not_a_crash(tmp_path) -> None:
    rec = _audit([_fake(fail=True)], tmp_path, run_smoke=True)["offers"][0]
    assert rec["evidence_level"] == "AVAILABLE" and not rec["routable"]
    assert "provider said no" in rec["blocked_by"][0]


def test_paid_offers_are_never_smoked_without_approval(tmp_path) -> None:
    tool = _fake(offers=[_offer("paid_offer", cost_tier="paid")])
    rec = _audit([tool], tmp_path, run_smoke=True)["offers"][0]
    assert type(tool).calls == 0 and not rec["routable"]
    assert any("not approved" in b for b in rec["blocked_by"])
    rec = _audit([tool], tmp_path, run_smoke=True, allow_cost_tiers=("free", "paid"))["offers"][0]
    assert type(tool).calls == 1 and rec["routable"]


def test_evidence_is_reused_and_invalidated_by_version(tmp_path) -> None:
    _audit([_fake()], tmp_path, run_smoke=True)
    again = _audit([_fake()], tmp_path)["offers"][0]
    assert again["routable"] and again["smoke"]["from_evidence"]
    bumped = _audit([_fake(version="2.0.0")], tmp_path)["offers"][0]
    assert bumped["evidence_level"] == "AVAILABLE"


def test_output_probe_rejects_empty_artifacts(tmp_path) -> None:
    class Empty(_Fake):
        name = "empty_tool"
        route_offers = [_offer("empty_offer")]

        def routing_smoke(self, offer_id, workdir, cache):
            out = workdir / "empty.mp4"
            out.write_bytes(b"")
            return {"artifact": str(out)}

    rec = _audit([Empty()], tmp_path, run_smoke=True)["offers"][0]
    assert rec["evidence_level"] == "SMOKE_TESTED" and not rec["routable"]


def _events(root: Path, tool: str, success: bool = True) -> None:
    proj = root / "p1"
    proj.mkdir(parents=True, exist_ok=True)
    with (proj / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool, "event": "finish", "success": success}) + "\n")


def test_production_evidence_counts_only_for_single_offer_tools(tmp_path) -> None:
    projects = tmp_path / "projects"
    _events(projects, "fake_tool")
    _events(projects, "multi_tool")
    _events(projects, "fake_tool", success=False)
    single = _fake()
    multi = _fake("multi_tool", [_offer("m1"), _offer("m2", axes=("reality_still",))])
    report = {o["offer"]: o for o in _audit([single, multi], tmp_path, projects_roots=[projects])["offers"]}
    assert report["fake_footage"]["evidence_level"] == "PRODUCTION_VERIFIED"
    assert report["fake_footage"]["production_successes"] == 1
    assert report["m1"]["evidence_level"] == "AVAILABLE"
    assert any("tool-level" in n for n in report["m1"]["notes_audit"])


def test_local_offers_json_declares_offers_for_local_only_tools(tmp_path) -> None:
    class Local(_Fake):
        name = "local_voice"
        route_offers = []

        def execute(self, inputs):
            Path(inputs["output_path"]).write_text("[]", encoding="utf-8")
            return ToolResult(success=True, data={"output": inputs["output_path"]})

    root = tmp_path / "audit"
    root.mkdir()
    (root / "local_offers.json").write_text(json.dumps({"local_voice": [{
        "id": "local_narration", "axes": ["narration"], "scopes": ["track"], "triggers": ["spoken_words"],
        "smoke": {"inputs": {"output_path": "{workdir}/t.json"}},
    }]}), encoding="utf-8")
    rec = audit_tools([Local()], root=root, projects_roots=[], run_smoke=True)["offers"][0]
    assert rec["declared_in"] == "local_offers.json" and rec["routable"]


# ---------------------------------------------------------------- router

def _rec(offer, tool, axes, *, level="OUTPUT_VERIFIED", routable=True, scopes=("scene", "asset"),
         triggers=(), strengths=None, runtime=None, cost="free", provider=None):
    return {"offer": offer, "tool": tool, "provider": provider or tool, "axes": list(axes), "scopes": list(scopes),
            "triggers": list(triggers), "strengths": strengths or {}, "runtime": runtime, "cost_tier": cost,
            "evidence_level": level, "routable": routable, "blocked_by": [] if routable else ["no smoke evidence"]}


def _capability(**overrides):
    offers = [
        _rec("pexels_footage", "pexels_video", ["reality_footage"], triggers=["location", "human_activity"],
             strengths={"reality": 4}),
        _rec("pixabay_footage", "pixabay_video", ["reality_footage"], triggers=["location"], strengths={"reality": 3}),
        _rec("remotion_graphics", "video_compose", ["structured_graphics"], scopes=["project", "scene"],
             triggers=["data_value"], strengths={"information_precision": 5}, runtime="remotion"),
        _rec("hyperframes_motion", "hyperframes_compose", ["expressive_motion"], scopes=["scene", "beat"],
             triggers=["major_reveal", "kinetic_text"], strengths={"motion_expressiveness": 5}, runtime="hyperframes"),
        _rec("phrase_captions", "video_compose", ["caption"], scopes=["track", "scene"], runtime="remotion"),
        _rec("qwen3_narration", "qwen3_tts", ["narration"], scopes=["track"]),
        _rec("qwen3_alignment", "qwen3_tts", ["alignment"], scopes=["track"]),
        _rec("flux_still", "flux_image", ["synthetic_image"], level="AVAILABLE", routable=False, cost="paid"),
    ]
    for o in offers:
        o.update(overrides.get(o["offer"], {}))
    return {"generated_at": "t", "offers": offers}


def _plan(*needs):
    return {"version": "1.0", "scenes": [
        {"id": f"s{i}", "type": "broll", "description": "", "start_seconds": i, "end_seconds": i + 1,
         "visual_need": need} for i, need in enumerate(needs)]}


DATACENTER = {"reality": "high", "information_precision": "medium", "motion_expressiveness": "high",
              "narration": "high", "word_sync": "high", "captions": "high",
              "cues": ["infrastructure", "data_value", "major_reveal"]}


def test_one_scene_composes_several_tools() -> None:
    plan = route_scenes(_plan(DATACENTER), _capability(), approved_runtimes=["remotion", "hyperframes"])
    layers = {l["role"]: l["offer"] for l in plan["scenes"][0]["layers"]}
    assert layers == {"visual_source": "pexels_footage", "base_composition": "remotion_graphics",
                      "emphasis_overlay": "hyperframes_motion"}
    tracks = {t["role"]: t["offer"] for t in plan["tracks"]}
    assert tracks == {"narration": "qwen3_narration", "sync": "qwen3_alignment", "captions": "phrase_captions"}
    validate_artifact("tool_plan", plan)


def test_routing_is_deterministic_regardless_of_offer_order() -> None:
    cap = _capability()
    first = route_scenes(_plan(DATACENTER, {"reality": "high"}), cap, approved_runtimes=["remotion", "hyperframes"])
    for seed in range(5):
        shuffled = copy.deepcopy(cap)
        random.Random(seed).shuffle(shuffled["offers"])
        again = route_scenes(_plan(DATACENTER, {"reality": "high"}), shuffled,
                             approved_runtimes=["remotion", "hyperframes"])
        assert again["scenes"] == first["scenes"] and again["tracks"] == first["tracks"]


def test_unverified_offer_is_never_chosen_and_is_reported() -> None:
    """Negative control: a matching but unverified tool stays out of the plan."""
    plan = route_scenes(_plan({"impossible_visual": "high", "cues": ["not_filmable"]}), _capability())
    scene = plan["scenes"][0]
    assert scene["layers"] == []
    assert scene["unmet"][0]["blocked"][0]["offer"] == "flux_still"
    assert any(w["code"] == "NEED_UNMET" and "flux_still (AVAILABLE)" in w["message"] for w in plan["warnings"])


def test_demoting_the_best_offer_falls_back_to_the_next() -> None:
    top = route_scenes(_plan({"reality": "high"}), _capability())["scenes"][0]["layers"][0]["offer"]
    assert top == "pexels_footage"
    demoted = _capability(pexels_footage={"routable": False, "evidence_level": "AVAILABLE"})
    assert route_scenes(_plan({"reality": "high"}), demoted)["scenes"][0]["layers"][0]["offer"] == "pixabay_footage"


def test_unapproved_runtime_is_rejected_loudly_not_silently() -> None:
    plan = route_scenes(_plan(DATACENTER, DATACENTER), _capability(), master_runtime="remotion")
    assert all("hyperframes_motion" not in {l["offer"] for l in s["layers"]} for s in plan["scenes"])
    warn = [w for w in plan["warnings"] if w["code"] == "RUNTIME_NOT_APPROVED"]
    assert len(warn) == 1 and warn[0]["offer"] == "hyperframes_motion" and warn[0]["scenes"] == ["s0", "s1"]
    # Without a declared fallback the need is unmet and the message names the rejected candidate.
    unmet = [w for w in plan["warnings"] if w["code"] == "NEED_UNMET" and w["need"] == "motion_expressiveness"]
    assert unmet and "hyperframes_motion (runtime 'hyperframes' was not approved" in unmet[0]["message"]


def test_declared_fallback_fills_a_need_whose_candidates_cannot_be_used() -> None:
    cap = _capability(hyperframes_motion={"fallback": ["remotion_graphics"]})
    plan = route_scenes(_plan({"motion_expressiveness": "high"}), cap, master_runtime="remotion")
    layer = plan["scenes"][0]["layers"][0]
    assert (layer["role"], layer["offer"]) == ("emphasis_overlay", "remotion_graphics")
    assert layer["reason"].startswith("fallback for hyperframes_motion (runtime 'hyperframes' was not approved")
    assert [w["code"] for w in plan["warnings"]] == ["RUNTIME_NOT_APPROVED"]  # still surfaced
    # A fallback is never used when it is not routable itself.
    cap = _capability(hyperframes_motion={"fallback": ["flux_still"]})
    assert route_scenes(_plan({"motion_expressiveness": "high"}), cap, master_runtime="remotion")["scenes"][0]["layers"] == []


def test_low_needs_are_recorded_not_routed_and_roles_do_not_double_fill() -> None:
    needs = ({"reality": "low"}, {"reality": "medium", "impossible_visual": "high"})
    plan = route_scenes(_plan(*needs), _capability())
    assert plan["scenes"][0]["layers"] == []
    # The stronger need has no routable generator, so the role stays open and
    # real footage fills it; the unmet need is still reported.
    second = plan["scenes"][1]
    assert second["unmet"][0]["need"] == "impossible_visual"
    assert [(l["need"], l["offer"]) for l in second["layers"]] == [("reality", "pexels_footage")]

    verified = _capability(flux_still={"routable": True, "evidence_level": "OUTPUT_VERIFIED"})
    second = route_scenes(_plan(*needs), verified)["scenes"][1]
    assert [(l["need"], l["offer"]) for l in second["layers"]] == [("impossible_visual", "flux_still")]
    assert any(r["need"] == "reality" and "already filled" in r["reason"] for r in second["rejected"])


def test_scene_without_need_and_tool_names_in_plan_warn() -> None:
    plan = _plan({"reality": "high"})
    plan["scenes"].append({"id": "x", "type": "t", "description": "Remotion bar chart of revenue",
                           "start_seconds": 5, "end_seconds": 6})
    out = route_scenes(plan, _capability(), tool_names=["pexels_video"])
    codes = [w["code"] for w in out["warnings"]]
    assert "SCENE_WITHOUT_VISUAL_NEED" in codes and "TOOL_NAMED_IN_SCENE_PLAN" in codes


def test_scene_plan_schema_accepts_visual_need_and_rejects_tool_names() -> None:
    doc = _plan(DATACENTER)
    validate_artifact("scene_plan", doc)
    doc["scenes"][0]["visual_need"]["tool"] = "pexels_video"
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("scene_plan", doc)
    legacy = json.loads((ROUTE / "scene_plan.json").read_text(encoding="utf-8"))
    validate_artifact("scene_plan", legacy)  # no visual_need: still valid


# ---------------------------------------------------------------- usage QA

def _routed(n=10):
    return route_scenes(_plan(*[{"reality": "high", "cues": ["location"]}] * n), _capability())


def _assets(*scene_ids, tool="pexels_video"):
    return {"assets": [{"id": f"a{i}", "type": "video", "path": "x.mp4", "source_tool": tool, "scene_id": sid}
                       for i, sid in enumerate(scene_ids)]}


def test_ignored_broll_is_reported_as_underuse() -> None:
    report = tool_usage_report(_routed(), _assets("s0"), {"render_runtime": "remotion"})
    codes = [w["code"] for w in report["warnings"]]
    assert codes.count("ROUTED_LAYER_IGNORED") == 9
    assert "REAL_WORLD_BROLL_UNDERUSED" in codes
    assert report["tally"]["reality"] == {"planned": 10, "used": 1, "overridden": 0}


def test_stated_overrides_and_provider_matches_count_as_honoured() -> None:
    plan = _routed(4)
    plan["overrides"] = [{"scene_id": "s2", "offer": "pexels_footage", "reason": "user supplied footage"},
                         {"scene_id": "s3", "offer": "pexels_footage", "reason": ""}]
    assets = {"assets": [{"id": "a", "type": "video", "path": "x", "source_tool": "video_selector",
                          "provider": "pexels_video", "scene_id": "s0"},
                         {"id": "b", "type": "video", "path": "x", "source_tool": "pexels_video", "scene_id": "s1"}]}
    report = tool_usage_report(plan, assets, {})
    assert report["tally"]["reality"] == {"planned": 4, "used": 2, "overridden": 1}
    assert [w["scene_id"] for w in report["warnings"] if w["code"] == "ROUTED_LAYER_IGNORED"] == ["s3"]
    assert "REAL_WORLD_BROLL_UNDERUSED" not in [w["code"] for w in report["warnings"]]


def test_no_false_positive_when_nothing_needed_reality() -> None:
    plan = route_scenes(_plan(*[{"information_precision": "high"}] * 5), _capability())
    report = tool_usage_report(plan, {"assets": []}, {"render_runtime": "remotion"})
    assert report["warnings"] == []


def test_tracks_and_runtime_layers_are_checked() -> None:
    plan = route_scenes(_plan(DATACENTER), _capability(), approved_runtimes=["remotion", "hyperframes"])
    edit = {"render_runtime": "remotion", "subtitles": {"enabled": True, "style": "karaoke"}}
    assets = {"assets": [{"id": "v", "type": "audio", "path": "n.wav", "source_tool": "qwen3_tts", "scene_id": None},
                         {"id": "b", "type": "video", "path": "b.mp4", "source_tool": "pexels_video", "scene_id": "s0"}]}
    codes = {(w["code"], w.get("offer")) for w in tool_usage_report(plan, assets, edit)["warnings"]}
    # remotion base layer honoured by the render, captions by subtitles, voice by the asset;
    # the HyperFrames overlay produced no asset -> reported.
    assert codes == {("ROUTED_LAYER_IGNORED", "hyperframes_motion")}


# ---------------------------------------------------------------- tool + pipeline integration

def test_tool_router_route_operation_validates_and_writes(tmp_path) -> None:
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(_capability()), encoding="utf-8")
    out = tmp_path / "tool_plan.json"
    result = ToolRouter().execute({"operation": "route", "scene_plan": _plan(DATACENTER), "capability": str(cap),
                                   "approved_runtimes": ["remotion", "hyperframes"], "output_path": str(out)})
    assert result.success, result.error
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["layers_by_role"]["emphasis_overlay"] == 1


def test_visual_timeline_keeps_tool_layers(tmp_path) -> None:
    scene_plan = json.loads((ROUTE / "scene_plan.json").read_text(encoding="utf-8"))
    for s in scene_plan["scenes"]:
        s["visual_need"] = {"reality": "high", "information_precision": "medium"}
    plan = route_scenes(scene_plan, _capability())
    result = VisualTimelineCompiler().execute({
        "operation": "compile", "visual_direction": str(ROUTE / "visual_direction.json"),
        "scene_plan": scene_plan, "alignment": str(ROUTE / "alignment.json"), "tool_plan": plan})
    assert result.success, result.error
    validate_artifact("visual_timeline", result.data["visual_timeline"])
    assert result.data["visual_timeline"]["tool_layers"]["sc2"] == [
        {"role": "visual_source", "need": "reality", "offer": "pexels_footage", "tool": "pexels_video"},
        {"role": "base_composition", "need": "information_precision", "offer": "remotion_graphics",
         "tool": "video_compose"}]


def test_direction_qa_reports_tool_usage_as_soft_warnings() -> None:
    timeline = {"version": "1.0", "models": {}, "events": [], "unmatched": []}
    result = DirectionQA().execute({"visual_timeline": timeline, "edit_decisions": {"cuts": []},
                                    "tool_plan": _routed(4), "asset_manifest": {"assets": []}})
    assert result.success, result.error  # soft: never blocks
    assert any(w.startswith("REAL_WORLD_BROLL_UNDERUSED") for w in result.data["warnings"])
    assert result.data["tool_usage"]["tally"]["reality"]["planned"] == 4


def test_synthetic_fixture_routes_to_composed_scenes() -> None:
    """Domain-neutral fixture: every scene gets layers from several tools, needs no tool names."""
    scene_plan = json.loads((REPO / "tests/fixtures/tool_routing/scene_plan.json").read_text(encoding="utf-8"))
    validate_artifact("scene_plan", scene_plan)
    plan = route_scenes(scene_plan, _capability(), master_runtime="remotion",
                        approved_runtimes=["remotion", "hyperframes"])
    validate_artifact("tool_plan", plan)
    roles = {s["scene_id"]: sorted(l["role"] for l in s["layers"]) for s in plan["scenes"]}
    assert roles["sc1"] == ["visual_source"]
    assert roles["sc3"] == ["base_composition", "emphasis_overlay"]
    assert roles["sc5"] == []  # impossible visual: generator unverified -> unmet, not faked
    assert {t["role"] for t in plan["tracks"]} == {"narration", "sync", "captions"}
    assert not [w for w in plan["warnings"] if w["code"] == "TOOL_NAMED_IN_SCENE_PLAN"]
