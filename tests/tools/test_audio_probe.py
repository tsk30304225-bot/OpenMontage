"""probe_duration: UTF-8 output, bounded retries for transient Windows file locks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.analysis import audio_probe
from tools.analysis.audio_probe import PROBE_ATTEMPTS, probe_duration


class _Done:
    def __init__(self, stdout):
        self.stdout = stdout


@pytest.fixture
def media(tmp_path):
    f = tmp_path / "clip.wav"
    f.write_bytes(b"x")
    return f


@pytest.fixture
def fake(monkeypatch):
    state = {"calls": [], "sleeps": [], "results": []}

    def run(cmd, **kwargs):
        state["calls"].append(kwargs)
        r = state["results"].pop(0) if state["results"] else "garbage"
        if isinstance(r, Exception):
            raise r
        return _Done(r)

    monkeypatch.setattr(audio_probe.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(audio_probe.subprocess, "run", run)
    monkeypatch.setattr(audio_probe.time, "sleep", lambda s: state["sleeps"].append(s))
    return state


OK = json.dumps({"format": {"duration": "2.5"}})


def test_success_returns_at_once_without_sleeping(fake, media) -> None:
    fake["results"] = [OK]
    assert probe_duration(media) == 2.5
    assert len(fake["calls"]) == 1 and fake["sleeps"] == []
    assert fake["calls"][0]["encoding"] == "utf-8" and fake["calls"][0]["errors"] == "replace"


def test_one_transient_failure_then_success(fake, media) -> None:
    fake["results"] = [subprocess.TimeoutExpired("ffprobe", 10), OK]
    assert probe_duration(media) == 2.5
    assert len(fake["calls"]) == 2 and fake["sleeps"] == [1.0]


def test_persistent_failure_is_bounded(fake, media) -> None:
    fake["results"] = ["not json"] * 10
    assert probe_duration(media) is None
    assert len(fake["calls"]) == PROBE_ATTEMPTS == 4
    assert fake["sleeps"] == [1.0, 1.0, 1.0]  # never more than 3 s of waiting


def test_missing_ffprobe_returns_none_without_calls(fake, media, monkeypatch) -> None:
    monkeypatch.setattr(audio_probe.shutil, "which", lambda name: None)
    assert probe_duration(media) is None
    assert fake["calls"] == [] and fake["sleeps"] == []


def test_missing_file_returns_none_without_retries(fake, tmp_path) -> None:
    assert probe_duration(tmp_path / "nope.wav") is None
    assert fake["calls"] == [] and fake["sleeps"] == []


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg/ffprobe")
def test_real_unicode_path_with_spaces(tmp_path) -> None:
    d = tmp_path / "한글 경로"
    d.mkdir()
    wav = d / "클립 1.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
                    str(wav)], check=True)
    assert probe_duration(wav) == pytest.approx(1.5, abs=0.05)
