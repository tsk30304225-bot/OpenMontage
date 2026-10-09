"""Unit tests for the MiniMax TTS provider (tools/audio/minimax_tts.py).

The real API is never called — requests.post/get are patched. Covers status
gating, request shape and defaults, region routing, hex audio decoding,
base_resp error handling, subtitle download and word-timestamp flattening,
selector aliases, idempotency keys, cost, and API-key redaction.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tools.audio.minimax_tts import MiniMaxTTS
from tools.base_tool import ToolStatus

AUDIO_BYTES = b"ID3fake-audio"


class _FakeResponse:
    def __init__(self, payload=None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _ok_body(subtitle_file=None):
    data = {"audio": AUDIO_BYTES.hex(), "status": 2}
    if subtitle_file:
        data["subtitle_file"] = subtitle_file
    return {
        "data": data,
        "extra_info": {"audio_length": 2450, "usage_characters": 12},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


WORD_SUBTITLES = [
    {
        "text": "안녕하세요 여러분",
        "time_begin": 0,
        "time_end": 1500,
        "timestamped_words": [
            {"word": "안녕하세요", "time_begin": 0, "time_end": 900},
            {"word": "여러분", "time_begin": 950, "time_end": 1500},
        ],
    }
]


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax-secret")
    monkeypatch.delenv("MINIMAX_REGION", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    return "sk-minimax-secret"


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)


class TestStatus:
    def test_unavailable_without_key(self, no_api_key):
        assert MiniMaxTTS().get_status() == ToolStatus.UNAVAILABLE

    def test_available_with_key(self, api_key):
        assert MiniMaxTTS().get_status() == ToolStatus.AVAILABLE

    def test_execute_fails_without_key(self, no_api_key):
        result = MiniMaxTTS().execute({"text": "hello"})
        assert result.success is False
        assert "MINIMAX_API_KEY" in result.error

    def test_registered_as_tts(self):
        from tools.tool_registry import registry

        registry.ensure_discovered()
        assert "minimax_tts" in [t.name for t in registry.get_by_capability("tts")]


class TestRequest:
    def test_default_payload_matches_korean_preset(self, api_key, tmp_path):
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            result = MiniMaxTTS().execute(
                {"text": "안녕하세요", "output_path": str(tmp_path / "a.mp3")}
            )
        assert result.success, result.error
        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        headers = post.call_args.kwargs["headers"]
        assert url == "https://api.minimax.io/v1/t2a_v2"
        assert headers["Authorization"] == "Bearer sk-minimax-secret"
        assert body["model"] == "speech-2.8-hd"
        assert body["language_boost"] == "Korean"
        assert body["voice_setting"] == {
            "voice_id": "Korean_LonelyWarrior",
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        }
        assert body["subtitle_enable"] is True
        assert body["subtitle_type"] == "word"
        assert body["output_format"] == "hex"
        assert body["stream"] is False
        assert body["audio_setting"]["format"] == "mp3"
        assert body["audio_setting"]["bitrate"] == 128000

    def test_overrides_and_emotion(self, api_key, tmp_path):
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            MiniMaxTTS().execute(
                {
                    "text": "hi",
                    "model_id": "speech-2.8-turbo",
                    "voice_id": "English_Graceful_Lady",
                    "language_boost": "English",
                    "speed": 1.2,
                    "emotion": "happy",
                    "format": "wav",
                    "subtitle_enable": False,
                    "output_path": str(tmp_path / "a.wav"),
                }
            )
        body = post.call_args.kwargs["json"]
        assert body["model"] == "speech-2.8-turbo"
        assert body["voice_setting"]["voice_id"] == "English_Graceful_Lady"
        assert body["voice_setting"]["emotion"] == "happy"
        assert body["voice_setting"]["speed"] == 1.2
        assert "bitrate" not in body["audio_setting"]
        assert "subtitle_enable" not in body

    def test_selector_pitch_is_clamped(self, api_key, tmp_path):
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            MiniMaxTTS().execute(
                {"text": "hi", "pitch": 30, "output_path": str(tmp_path / "a.mp3")}
            )
        assert post.call_args.kwargs["json"]["voice_setting"]["pitch"] == 12

    def test_timestamps_alias_disables_subtitles(self, api_key, tmp_path):
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            MiniMaxTTS().execute(
                {"text": "hi", "timestamps": False, "output_path": str(tmp_path / "a.mp3")}
            )
        assert "subtitle_enable" not in post.call_args.kwargs["json"]

    def test_cn_region(self, api_key, monkeypatch, tmp_path):
        monkeypatch.setenv("MINIMAX_REGION", "cn")
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            MiniMaxTTS().execute({"text": "hi", "output_path": str(tmp_path / "a.mp3")})
        assert post.call_args.args[0] == "https://api.minimaxi.com/v1/t2a_v2"

    def test_base_url_override(self, api_key, monkeypatch, tmp_path):
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://proxy.example.com/")
        with patch("requests.post", return_value=_FakeResponse(_ok_body())) as post:
            MiniMaxTTS().execute({"text": "hi", "output_path": str(tmp_path / "a.mp3")})
        assert post.call_args.args[0] == "https://proxy.example.com/v1/t2a_v2"


class TestOutput:
    def test_writes_decoded_audio_and_metadata(self, api_key, tmp_path):
        out = tmp_path / "narration.mp3"
        with patch("requests.post", return_value=_FakeResponse(_ok_body())):
            result = MiniMaxTTS().execute({"text": "안녕하세요", "output_path": str(out)})
        assert result.success, result.error
        assert out.read_bytes() == AUDIO_BYTES
        assert result.data["audio_duration_seconds"] == 2.45
        assert result.data["output"] == str(out)
        assert result.artifacts == [str(out)]
        assert result.model == "minimax/speech-2.8-hd"

    def test_subtitles_downloaded_and_flattened(self, api_key, tmp_path):
        out = tmp_path / "narration.mp3"
        with patch(
            "requests.post",
            return_value=_FakeResponse(_ok_body("https://cdn.example.com/sub.json")),
        ), patch("requests.get", return_value=_FakeResponse(WORD_SUBTITLES)) as get:
            result = MiniMaxTTS().execute({"text": "안녕하세요 여러분", "output_path": str(out)})
        assert result.success, result.error
        get.assert_called_once()
        sub_path = tmp_path / "narration.subtitles.json"
        assert result.data["subtitle_path"] == str(sub_path)
        assert json.loads(sub_path.read_text(encoding="utf-8")) == WORD_SUBTITLES
        assert result.data["word_timestamps"] == [
            {"word": "안녕하세요", "start": 0.0, "end": 0.9},
            {"word": "여러분", "start": 0.95, "end": 1.5},
        ]
        assert str(sub_path) in result.artifacts

    def test_sentence_subtitles_fall_back_to_segments(self):
        segments = [{"text": "문장 하나.", "time_begin": 0, "time_end": 1200}]
        assert MiniMaxTTS._word_timestamps(segments) == [
            {"word": "문장 하나.", "start": 0.0, "end": 1.2}
        ]

    def test_subtitle_download_failure_keeps_audio(self, api_key, tmp_path):
        out = tmp_path / "narration.mp3"
        with patch(
            "requests.post",
            return_value=_FakeResponse(_ok_body("https://cdn.example.com/sub.json")),
        ), patch("requests.get", return_value=_FakeResponse(None, status_code=403)):
            result = MiniMaxTTS().execute({"text": "hi", "output_path": str(out)})
        assert result.success
        assert out.exists()
        assert result.data["subtitle_path"] is None
        assert "subtitle_warning" in result.data


class TestErrors:
    def test_base_resp_error_reported(self, api_key, tmp_path):
        body = {"base_resp": {"status_code": 1004, "status_msg": "authentication failed"}}
        with patch("requests.post", return_value=_FakeResponse(body)):
            result = MiniMaxTTS().execute({"text": "hi", "output_path": str(tmp_path / "a.mp3")})
        assert result.success is False
        assert "1004" in result.error and "authentication failed" in result.error

    def test_missing_audio_reported(self, api_key, tmp_path):
        body = {"data": {}, "base_resp": {"status_code": 0}}
        with patch("requests.post", return_value=_FakeResponse(body)):
            result = MiniMaxTTS().execute({"text": "hi", "output_path": str(tmp_path / "a.mp3")})
        assert result.success is False
        assert "no audio" in result.error

    def test_api_key_redacted(self, api_key, tmp_path):
        with patch("requests.post", side_effect=RuntimeError("bad key sk-minimax-secret")):
            result = MiniMaxTTS().execute({"text": "hi", "output_path": str(tmp_path / "a.mp3")})
        assert result.success is False
        assert "sk-minimax-secret" not in result.error
        assert "***" in result.error


class TestKeysAndCost:
    def test_idempotency_defaults_hash_equal(self):
        tool = MiniMaxTTS()
        assert tool.idempotency_key({"text": "hi"}) == tool.idempotency_key(
            {"text": "hi", "model": "speech-2.8-hd", "voice_id": "Korean_LonelyWarrior", "speed": 1.0}
        )
        assert tool.idempotency_key({"text": "hi"}) != tool.idempotency_key(
            {"text": "hi", "voice_id": "other"}
        )

    def test_cost_per_character(self):
        tool = MiniMaxTTS()
        assert tool.estimate_cost({"text": "x" * 1000}) == 0.1
        assert tool.estimate_cost({"text": "x" * 1000, "model": "speech-2.8-turbo"}) == 0.06
