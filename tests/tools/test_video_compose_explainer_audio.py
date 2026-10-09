"""edit_decisions.audio -> Explainer audio props (tools/video/video_compose.py).

edit_decisions names narration and music by asset id; the Remotion Explainer
plays {src} layers. Without this translation the templated Remotion render
dropped both tracks and music ducking never happened.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.video.video_compose import VideoCompose

ROOT = Path(__file__).resolve().parents[2]

LOOKUP = {
    "narr-1": {"id": "narr-1", "path": "/p/narr1.mp3", "duration_seconds": 4.0},
    "narr-2": {"id": "narr-2", "path": "/p/narr2.mp3", "duration_seconds": 3.0},
    "music-bg": {"id": "music-bg", "path": "/p/music.mp3"},
}


def test_segments_and_music_with_ducking_windows():
    audio = {
        "narration": {
            "segments": [
                {"asset_id": "narr-1", "start_seconds": 0},
                {"asset_id": "narr-2", "start_seconds": 10, "end_seconds": 12.5},
            ]
        },
        "music": {
            "asset_id": "music-bg",
            "volume": 0.1,
            "fade_in_seconds": 1,
            "fade_out_seconds": 2,
            "ducking": {"enabled": True, "reduction_db": -8, "attack_ms": 100, "release_ms": 400},
        },
    }
    props = VideoCompose._explainer_audio_props(audio, LOOKUP)
    assert props["narration"] == {
        "segments": [
            {"src": "/p/narr1.mp3", "startSeconds": 0.0},
            {"src": "/p/narr2.mp3", "startSeconds": 10.0},
        ]
    }
    assert props["music"] == {
        "src": "/p/music.mp3",
        "volume": 0.1,
        "fadeInSeconds": 1,
        "fadeOutSeconds": 2,
        "ducking": {
            "windows": [[0.0, 4.0], [10.0, 12.5]],
            "reductionDb": -8.0,
            "attackSeconds": 0.1,
            "releaseSeconds": 0.4,
        },
    }


def test_boolean_ducking_uses_defaults_and_false_disables():
    narration = {"segments": [{"asset_id": "narr-1", "start_seconds": 0}]}
    on = VideoCompose._explainer_audio_props(
        {"narration": narration, "music": {"asset_id": "music-bg", "ducking": True}}, LOOKUP
    )
    assert on["music"]["ducking"]["reductionDb"] == -12.0
    off = VideoCompose._explainer_audio_props(
        {"narration": narration, "music": {"asset_id": "music-bg", "ducking": False}}, LOOKUP
    )
    assert "ducking" not in off["music"]


def test_unresolved_assets_return_none():
    audio = {"narration": {"segments": [{"asset_id": "missing", "start_seconds": 0}]},
             "music": {"asset_id": "also-missing"}}
    assert VideoCompose._explainer_audio_props(audio, LOOKUP) is None


def test_explainer_root_has_no_blank_tail_padding():
    root = (ROOT / "remotion-composer" / "src" / "Root.tsx").read_text(encoding="utf-8")
    assert "lastEnd + 1" not in root


def test_decision_log_accepts_approval_policy():
    schema = json.loads(
        (ROOT / "schemas" / "artifacts" / "decision_log.schema.json").read_text(encoding="utf-8")
    )
    category_enum = schema["properties"]["decisions"]["items"]["properties"]["category"]["enum"]
    assert "approval_policy" in category_enum
