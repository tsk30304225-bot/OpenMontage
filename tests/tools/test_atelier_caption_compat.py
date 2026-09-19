"""Caption compatibility for atelier renders.

1. The atelier doctrine forbids importing stock creative components, but the
   shared caption renderer (PhraseCaptions) is infrastructure: it is allowed by
   exact module path, and that exception must never mask a creative import.
2. remotion_caption_burn copied the clip into remotion-composer/public/ and
   passed ``public/talking-head/<file>`` to TalkingHead, which resolves it with
   staticFile(); Remotion rejects a ``public/`` prefix, so every burn failed
   ("Do not include the public/ prefix when using staticFile()").

Set OPENMONTAGE_RENDER_TESTS=1 for the real renders: a caption burn on a tiny
clip and the atelier fixture with shared PhraseCaptions + the direction contract.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from lib.visual_direction import compile_timeline
from tools.analysis.direction_qa import DirectionQA
from tools.video import remotion_caption_burn as burn_module
from tools.video.remotion_caption_burn import RemotionCaptionBurn
from tools.video.video_compose import VideoCompose

REPO = Path(__file__).resolve().parents[2]
ROUTE = REPO / "tests" / "fixtures" / "visual_direction" / "atelier_route"


def _atelier_checks(tmp_path: Path, source: str) -> dict:
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    (project / "Composition.tsx").write_text(source, encoding="utf-8")
    (project / "index.tsx").write_text('import "./Composition";\n', encoding="utf-8")
    return VideoCompose()._run_atelier_checks(project / "index.tsx", {"art_direction": "test"})


# ---- Fix 1: PhraseCaptions is shared infrastructure, stock creative reuse still fails ----

@pytest.mark.parametrize("spec", [
    "../../src/components/PhraseCaptions",
    "../../src/components/PhraseCaptions.tsx",
    "../../../src/components/PhraseCaptions",
    "remotion-composer/src/components/PhraseCaptions",
])
def test_phrase_captions_import_is_allowed(tmp_path, spec) -> None:
    checks = _atelier_checks(tmp_path, f'import {{ PhraseCaptions }} from "{spec}";\nimport {{ useElement }} from "../../src/direction";\n')
    assert checks["stock_reuse_detected"] is False
    assert [i["import"] for i in checks["shared_infrastructure_imports"]] == [spec]


@pytest.mark.parametrize("spec", [
    "../../src/components/StatCard",
    "../../src/components/charts/BarChart",
    "../../src/components/ComparisonCard",
    "../../src/Explainer",
    "../../src/components",           # barrel: would pull every stock component
    "../../src/components/index",
    "../../src/components/PhraseCaptionsV2",  # prefix lookalike is not the allowlisted module
])
def test_stock_creative_imports_still_fail(tmp_path, spec) -> None:
    checks = _atelier_checks(tmp_path, f'import X from "{spec}";\n')
    assert checks["stock_reuse_detected"] is True
    assert checks["offending_imports"][0]["import"] == spec


def test_allowlist_does_not_mask_a_creative_import(tmp_path) -> None:
    checks = _atelier_checks(tmp_path, (
        'import { PhraseCaptions } from "../../src/components/PhraseCaptions";\n'
        'import { StatCard } from "../../src/components/StatCard";\n'
        'const Lazy = React.lazy(() => import("../../src/components/charts/BarChart"));\n'
    ))
    assert checks["stock_reuse_detected"] is True
    assert sorted(i["import"] for i in checks["offending_imports"]) == [
        "../../src/components/StatCard", "../../src/components/charts/BarChart"]
    assert [i["import"] for i in checks["shared_infrastructure_imports"]] == ["../../src/components/PhraseCaptions"]
    assert any("StatCard" in issue for issue in checks["issues"])


def test_route_fixture_uses_shared_captions_and_passes_reuse_check() -> None:
    checks = VideoCompose()._run_atelier_checks(ROUTE / "atelier_route_fixture" / "index.tsx", {"art_direction": "fixture"})
    assert checks["stock_reuse_detected"] is False
    assert any("PhraseCaptions" in i["import"] for i in checks["shared_infrastructure_imports"])


# ---- Fix 2: remotion_caption_burn passes a staticFile()-relative path ----

@pytest.mark.parametrize("name", ["clip.mp4", "clip with space.mp4", "클립 테스트.mp4"])
def test_static_file_path_is_relative_to_public(tmp_path, name) -> None:
    public = tmp_path / "some worktree" / "remotion-composer" / "public"
    video = public / "talking-head" / name
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    rel = RemotionCaptionBurn._static_file_path(video, public)
    assert rel == f"talking-head/{name}" and not rel.startswith("public/") and "\\" not in rel


def _fake_composer(root: Path) -> Path:
    composer = root / "remotion-composer"
    (composer / "node_modules").mkdir(parents=True)
    (composer / "package.json").write_text("{}", encoding="utf-8")
    return composer


def test_render_props_video_src_resolves_inside_public(tmp_path, monkeypatch) -> None:
    """The acceptance failure: props carried 'public/talking-head/…' into staticFile()."""
    composer = _fake_composer(tmp_path / "worktree")
    src = tmp_path / "elsewhere" / "clip 01.mp4"
    src.parent.mkdir()
    src.write_bytes(b"video")
    out = tmp_path / "out" / "burned.mp4"
    out.parent.mkdir()
    tool = RemotionCaptionBurn()
    monkeypatch.setattr(tool, "_find_remotion_root", lambda: composer)

    class Done:
        def __init__(self, stdout=""):
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return Done("2.0\n" if "format=duration" in cmd else "640x360\n")
        out.write_bytes(b"rendered")
        return Done()

    monkeypatch.setattr(tool, "run_command", fake_run)
    result = tool._render_remotion(str(src), str(out), [{"word": "a", "startMs": 0, "endMs": 500}], 4, 42, "#fff",
                                   caption_style="karaoke")
    assert result.success
    props = json.loads((composer / "public" / "demo-props" / "caption-burn-clip 01.json").read_text(encoding="utf-8"))
    assert props["videoSrc"] == "talking-head/clip 01.mp4"
    assert (composer / "public" / props["videoSrc"]).is_file()


def test_remotion_root_prefers_the_tools_own_checkout(tmp_path, monkeypatch) -> None:
    """In a worktree the cwd may be another checkout; render with this checkout's composer."""
    _fake_composer(tmp_path)
    monkeypatch.chdir(tmp_path)
    own = Path(burn_module.__file__).resolve().parents[2] / "remotion-composer"
    root = RemotionCaptionBurn()._find_remotion_root()
    if (own / "node_modules").is_dir():
        assert root == own
    else:
        assert root == tmp_path / "remotion-composer"


# ---- real renders ----

RENDER = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_RENDER_TESTS") != "1" or not shutil.which("ffmpeg") or not shutil.which("npx"),
    reason="set OPENMONTAGE_RENDER_TESTS=1 (needs ffmpeg + Remotion)",
)

SEGMENTS = [{"id": "s1", "text": "캡션 경로 확인", "start": 0.1, "end": 1.8, "words": [
    {"word": "캡션", "start": 0.1, "end": 0.6}, {"word": "경로", "start": 0.7, "end": 1.1}, {"word": "확인", "start": 1.2, "end": 1.8}]}]


def _band_changed(video: Path, a: float, b: float) -> int:
    import subprocess

    import numpy as np

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(video), "-frames:v", "1",
                              "-vf", "scale=480:270,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(270, 480).astype(int)
    fa, fb = frame(a), frame(b)
    return int((np.abs(fa[int(270 * 0.82):] - fb[int(270 * 0.82):]) > 24).sum())


@RENDER
def test_caption_burn_renders_a_clip_with_a_space_in_its_name(tmp_path) -> None:
    import subprocess

    clip = tmp_path / "clip 테스트.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
    out = tmp_path / "burned.mp4"
    result = RemotionCaptionBurn().execute({"input_path": str(clip), "output_path": str(out), "segments": SEGMENTS,
                                            "caption_style": "karaoke"})
    assert result.success, result.error
    assert result.data["method"] == "remotion" and out.is_file()


@RENDER
def test_atelier_fixture_renders_shared_phrase_captions_and_keeps_the_contract(tmp_path) -> None:
    load = lambda n: json.loads((ROUTE / n).read_text(encoding="utf-8"))
    plan = load("scene_plan.json")
    timeline = compile_timeline(load("visual_direction.json"), load("alignment.json"),
                                scene_windows={s["id"]: (s["start_seconds"], s["end_seconds"]) for s in plan["scenes"]})
    tl = tmp_path / "visual_timeline.json"
    tl.write_text(json.dumps(timeline), encoding="utf-8")
    captions = VideoCompose._caption_words_from_timing(load("alignment.json"))
    props = {"scenes": [{"id": s["id"], "start": s["start_seconds"], "end": s["end_seconds"]} for s in plan["scenes"]],
             "durationSeconds": plan["scenes"][-1]["end_seconds"], "captions": captions}
    (tmp_path / "props.json").write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    edit = {"version": "1.0", "render_runtime": "remotion", "composition_mode": "atelier", "cuts": [],
            "visual_timeline": str(tl),
            "bespoke": {"entry": str(ROUTE / "atelier_route_fixture" / "index.tsx"), "composition_id": "AtelierRouteFixture",
                        "props_path": str(tmp_path / "props.json"), "art_direction": "fixture", "scale": 0.5, "concurrency": 4}}
    video = tmp_path / "route_captions.mp4"
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "output_path": str(video)})
    assert result.success, result.error
    checks = result.data["final_review"]["checks"]
    assert checks["atelier"]["stock_reuse_detected"] is False
    assert checks["direction_trace"]["implemented"] == 8

    # Karaoke: the cue box is on screen while words are spoken, and a word turning
    # active changes the caption band between two word starts of the same cue.
    first, second = captions[0], captions[1]
    assert _band_changed(video, 0.0, (first["startMs"] + 100) / 1000) > 100
    assert _band_changed(video, (first["startMs"] + 50) / 1000, (second["startMs"] + 150) / 1000) > 0

    qa = DirectionQA().execute({"video_path": str(video), "visual_timeline": timeline, "edit_decisions": edit,
                                "visual_direction": load("visual_direction.json"), "scene_plan": plan,
                                "output_dir": str(tmp_path / "qa")})
    assert qa.success, qa.data["hard_failures"]
