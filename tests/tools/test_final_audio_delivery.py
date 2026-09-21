"""Final audio delivery: normalization + a gate on the measured final file."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib import audio_delivery as ad
from schemas.artifacts import validate_artifact
from tools.video.video_compose import VideoCompose

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")

NARRATION = {"audio": {"narration": {"segments": [{"asset_id": "n1", "start_seconds": 0, "end_seconds": 4}]}}}


def _clip(path: Path, audio: str | None, seconds: int = 4) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"{audio}:duration={seconds}", "-shortest", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


QUIET = "anoisesrc=color=pink:amplitude=0.02"       # about -52 LUFS
SILENT = "anullsrc=r=48000:cl=stereo"


def _video_signature(path: Path) -> tuple:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=codec_name,width,height,nb_read_packets", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return s["codec_name"], s["width"], s["height"], s["nb_read_packets"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- contract precedence

def test_defaults_come_from_the_sound_design_table() -> None:
    c = ad.resolve_contract({})
    assert (c["target_lufs"], c["tolerance_lu"], c["true_peak_max_dbtp"], c["normalize"]) == (-14.0, 1.5, -1.5, True)
    assert set(c["source"].values()) == {"default"}


def test_existing_loudnorm_target_is_kept_and_explicit_contract_wins() -> None:
    c = ad.resolve_contract({"metadata": {"loudnorm_target": -16}})
    assert c["target_lufs"] == -16.0 and c["source"]["target_lufs"] == "metadata.loudnorm_target"
    c = ad.resolve_contract({"metadata": {"loudnorm_target": -16},
                             "audio_delivery": {"target_lufs": -23, "tolerance_lu": 1.0, "true_peak_max_dbtp": -2}})
    assert (c["target_lufs"], c["tolerance_lu"], c["true_peak_max_dbtp"]) == (-23, 1.0, -2)
    assert c["source"]["target_lufs"] == "audio_delivery"


def test_schema_accepts_the_contract() -> None:
    validate_artifact("edit_decisions", {"version": "1.0", "cuts": [], "render_runtime": "remotion", "audio_delivery": {
        "target_lufs": -14, "tolerance_lu": 1.5, "true_peak_max_dbtp": -1.5, "normalize": True}})


# ---------------------------------------------------------------- normalization + measurement

def test_too_quiet_audio_is_normalized_and_the_final_file_passes(tmp_path) -> None:
    clip = _clip(tmp_path / "quiet.mp4", QUIET)
    video_before = _video_signature(clip)
    report = ad.deliver(clip, NARRATION)
    assert report["before"]["integrated_lufs"] < -40 and report["normalization"]["applied"]
    final = ad.measure(clip)
    assert ad.evaluate(final, report["contract"], True)["ok"], final
    assert _video_signature(clip) == video_before  # video stream copied, not re-rendered


def test_in_range_audio_is_left_untouched(tmp_path) -> None:
    clip = _clip(tmp_path / "quiet.mp4", QUIET)
    ad.deliver(clip, NARRATION)
    digest = _sha(clip)
    report = ad.deliver(clip, NARRATION)
    assert report["normalization"] is None and _sha(clip) == digest


def test_true_peak_over_the_maximum_fails() -> None:
    m = {"has_audio": True, "integrated_lufs": -14.2, "true_peak_dbtp": -0.3}
    verdict = ad.evaluate(m, ad.resolve_contract({}), True)
    assert not verdict["ok"] and "true peak" in verdict["issues"][0]


def test_no_audio_stream_is_exempt_unless_audio_is_declared(tmp_path) -> None:
    clip = _clip(tmp_path / "mute.mp4", None)
    m = ad.measure(clip)
    assert m["has_audio"] is False
    assert ad.evaluate(m, ad.resolve_contract({}), False) == {"applies": False, "ok": True, "issues": []}
    assert not ad.evaluate(m, ad.resolve_contract({}), True)["ok"]


def test_silent_track_is_exempt_unless_audio_is_declared(tmp_path) -> None:
    clip = _clip(tmp_path / "silent.mp4", SILENT)
    m = ad.measure(clip)
    assert ad.evaluate(m, ad.resolve_contract({}), False)["applies"] is False
    verdict = ad.evaluate(m, ad.resolve_contract({}), True)
    assert not verdict["ok"] and "effectively silent" in verdict["issues"][0]
    assert ad.deliver(clip, NARRATION)["normalization"] is None  # silence is never "normalized" into a pass


# ---------------------------------------------------------------- final review gate (all render paths join here)

def _review(clip: Path, edit: dict) -> dict:
    return VideoCompose()._run_final_review(clip, edit)


def test_final_review_normalizes_then_passes_on_the_measured_file(tmp_path) -> None:
    clip = _clip(tmp_path / "quiet.mp4", QUIET)
    review = _review(clip, {"version": "1.0", "render_runtime": "ffmpeg", "cuts": [], **NARRATION})
    check = review["checks"]["audio_delivery"]
    assert check["normalization"]["applied"] and check["ok"] and check["applies"]
    assert -15.5 <= check["final"]["integrated_lufs"] <= -12.5
    assert review["status"] != "fail"
    validate_artifact("final_review", review)


def test_normalization_that_misses_the_target_still_fails(tmp_path, monkeypatch) -> None:
    clip = _clip(tmp_path / "quiet.mp4", QUIET)
    monkeypatch.setattr(ad, "normalize", lambda path, contract: {"applied": True, "filter": "noop"})
    review = _review(clip, {"version": "1.0", "render_runtime": "ffmpeg", "cuts": [], **NARRATION})
    assert review["status"] == "fail" and review["recommended_action"] == "revise_assets"
    assert any("integrated loudness" in i for i in review["issues_found"])


def test_normalize_false_keeps_the_file_and_fails(tmp_path) -> None:
    clip = _clip(tmp_path / "quiet.mp4", QUIET)
    digest = _sha(clip)
    review = _review(clip, {"version": "1.0", "cuts": [], "audio_delivery": {"normalize": False}, **NARRATION})
    assert review["status"] == "fail" and _sha(clip) == digest


def test_video_without_declared_audio_keeps_its_previous_verdict(tmp_path) -> None:
    clip = _clip(tmp_path / "silent.mp4", SILENT)
    review = _review(clip, {"version": "1.0", "cuts": []})
    assert review["checks"]["audio_delivery"]["applies"] is False and review["status"] != "fail"


def test_every_render_path_goes_through_the_same_gate() -> None:
    import inspect

    src = inspect.getsource(VideoCompose)
    assert src.count("self._run_final_review(") == 4  # atelier, templated remotion, hyperframes, ffmpeg
    review_src = inspect.getsource(VideoCompose._run_final_review)
    assert "audio_delivery.deliver(" in review_src and "audio_delivery.measure(" in review_src


def test_ffmpeg_render_path_delivers_normalized_audio(tmp_path) -> None:
    src = _clip(tmp_path / "quiet.mp4", QUIET, seconds=3)
    out = tmp_path / "final.mp4"
    edit = {"version": "1.0", "render_runtime": "ffmpeg", "renderer_family": "documentary-montage",
            "cuts": [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 3}], **NARRATION}
    result = VideoCompose().execute({"operation": "render", "edit_decisions": edit, "asset_manifest": {"assets": []},
                                     "output_path": str(out)})
    review = (result.data or {}).get("final_review") or {}
    check = review.get("checks", {}).get("audio_delivery")
    assert check is not None, result.error
    assert check["ok"], (check, result.error)
    assert -15.5 <= ad.measure(out)["integrated_lufs"] <= -12.5
