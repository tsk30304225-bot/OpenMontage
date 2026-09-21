"""Final audio delivery contract: loudness normalization + an authoritative gate.

The final MP4 is what the viewer hears, so the gate measures *that file*
(integrated loudness and true peak, ffmpeg ebur128). Whether normalization ran
is never the pass criterion.

Contract (edit_decisions.audio_delivery), precedence per field:
  1. edit_decisions.audio_delivery.<field>   (approved project value)
  2. edit_decisions.metadata.loudnorm_target (existing convention, target only)
  3. defaults: -14 LUFS +/-1.5 LU, true peak <= -1.5 dBTP, normalize on
     (skills/creative/sound-design.md platform table)

Normalization reuses AudioMixer's loudnorm filter on the audio stream only;
the video stream is copied.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

DEFAULTS: dict[str, Any] = {
    "target_lufs": -14.0,
    "tolerance_lu": 1.5,
    "true_peak_max_dbtp": -1.5,
    "normalize": True,
}
SILENCE_LUFS = -60.0
# loudnorm's own true-peak ceiling sits below the contract maximum so AAC
# re-encoding overshoot does not push the delivered file over it.
TRUE_PEAK_HEADROOM_DB = 0.5


def resolve_contract(edit_decisions: Optional[dict[str, Any]]) -> dict[str, Any]:
    edit = edit_decisions or {}
    contract = dict(DEFAULTS)
    source = {k: "default" for k in DEFAULTS}
    target = (edit.get("metadata") or {}).get("loudnorm_target")
    if isinstance(target, (int, float)) and not isinstance(target, bool):
        contract["target_lufs"] = float(target)
        source["target_lufs"] = "metadata.loudnorm_target"
    declared = edit.get("audio_delivery") or {}
    for key in DEFAULTS:
        if declared.get(key) is not None:
            contract[key] = declared[key]
            source[key] = "audio_delivery"
    contract["source"] = source
    return contract


def audio_expected(edit_decisions: Optional[dict[str, Any]]) -> bool:
    """Whether the edit declares audio that must be audible in the delivery."""
    edit = edit_decisions or {}
    audio = edit.get("audio") or {}
    declared = edit.get("audio_delivery") or {}
    return bool(declared.get("required") or audio.get("narration") or audio.get("music") or edit.get("music"))


def measure(path: str | Path) -> dict[str, Any]:
    """Integrated loudness (LUFS), true peak (dBTP) and LRA of the first audio stream."""
    p = Path(path)
    out: dict[str, Any] = {"has_audio": False, "integrated_lufs": None, "true_peak_dbtp": None, "lra_lu": None}
    if not p.is_file() or not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        out["error"] = "file, ffprobe or ffmpeg missing"
        return out
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                            "-of", "json", str(p)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    try:
        streams = json.loads(probe.stdout or "{}").get("streams", [])
    except ValueError:
        streams = []
    if not streams:
        return out
    out["has_audio"] = True
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-map", "0:a:0",
                           "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    summary = proc.stderr.split("Summary:")[-1] if "Summary:" in proc.stderr else ""
    if not summary:
        out["error"] = f"ebur128 produced no summary (exit {proc.returncode})"
        return out

    def grab(pattern: str) -> Optional[float]:
        m = re.search(pattern, summary)
        if not m:
            return None
        v = m.group(1)
        return float("-inf") if v.lstrip("-").lower() == "inf" else float(v)

    out["integrated_lufs"] = grab(r"I:\s+(-?inf|-?[\d.]+)\s+LUFS")
    out["lra_lu"] = grab(r"LRA:\s+(-?inf|-?[\d.]+)\s+LU")
    out["true_peak_dbtp"] = grab(r"True peak:\s+Peak:\s+(-?inf|-?[\d.]+)\s+dBFS")
    return out


def evaluate(m: dict[str, Any], contract: dict[str, Any], expected: bool) -> dict[str, Any]:
    """Judge a measurement against the contract. Returns {applies, ok, issues}."""
    issues: list[str] = []
    if not m.get("has_audio"):
        if expected:
            issues.append("audio delivery: the edit declares narration/music but the final file has no audio stream")
        return {"applies": expected, "ok": not issues, "issues": issues}
    lufs = m.get("integrated_lufs")
    if lufs is None:
        issues.append(f"audio delivery: loudness could not be measured ({m.get('error', 'no ebur128 result')})")
        return {"applies": True, "ok": False, "issues": issues}
    silent = lufs <= SILENCE_LUFS
    if silent and not expected:
        return {"applies": False, "ok": True, "issues": []}  # intentionally silent track (no declared audio)
    if silent:
        issues.append(f"audio delivery: final audio is effectively silent ({lufs:.1f} LUFS) but narration/music is declared")
    else:
        lo = contract["target_lufs"] - contract["tolerance_lu"]
        hi = contract["target_lufs"] + contract["tolerance_lu"]
        if not lo <= lufs <= hi:
            issues.append(f"audio delivery: integrated loudness {lufs:.1f} LUFS outside {contract['target_lufs']:g} "
                          f"+/- {contract['tolerance_lu']:g} LU")
    tp = m.get("true_peak_dbtp")
    if tp is not None and tp > contract["true_peak_max_dbtp"]:
        issues.append(f"audio delivery: true peak {tp:.1f} dBTP above the {contract['true_peak_max_dbtp']:g} dBTP maximum")
    return {"applies": True, "ok": not issues, "issues": issues}


def normalize(path: str | Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Loudness-normalize the audio stream in place (video copied). Reuses AudioMixer's loudnorm filter."""
    from tools.audio.audio_mixer import AudioMixer

    p = Path(path)
    ceiling = float(contract["true_peak_max_dbtp"]) - TRUE_PEAK_HEADROOM_DB
    flt = AudioMixer._loudnorm_filter({"loudnorm_target": contract["target_lufs"]}, "0:a:0", "delivered")
    flt = flt.replace(":TP=-1.5", f":TP={ceiling:g}")
    tmp = p.with_name(p.stem + ".delivery_tmp" + p.suffix)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(p), "-filter_complex", flt,
         "-map", "0:v?", "-map", "[delivered]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(tmp)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return {"applied": False, "error": (proc.stderr or "ffmpeg failed")[-400:], "filter": flt}
    os.replace(tmp, p)
    return {"applied": True, "filter": flt}


def deliver(path: str | Path, edit_decisions: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Normalize when the file is audible and out of contract. Never the pass criterion."""
    contract = resolve_contract(edit_decisions)
    expected = audio_expected(edit_decisions)
    before = measure(path)
    verdict = evaluate(before, contract, expected)
    report: dict[str, Any] = {"contract": contract, "expected": expected, "before": before, "normalization": None}
    audible = before.get("has_audio") and before.get("integrated_lufs") is not None \
        and before["integrated_lufs"] > SILENCE_LUFS
    if verdict["applies"] and not verdict["ok"] and audible and contract.get("normalize", True):
        report["normalization"] = normalize(path, contract)
    return report
