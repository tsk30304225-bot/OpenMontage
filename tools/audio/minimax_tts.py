"""MiniMax text-to-speech provider tool (T2A v2 HTTP API).

MiniMax Speech models give natural multilingual narration with strong Korean,
Chinese, and Japanese voices, per-request emotion control, and optional
word- or sentence-level subtitle timestamps returned alongside the audio.
Shares MINIMAX_API_KEY / MINIMAX_REGION / MINIMAX_BASE_URL with minimax_image
and minimax_video.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

REGION_BASE_URLS = {
    "global": "https://api.minimax.io",
    "global_en": "https://api.minimax.io",
    "cn": "https://api.minimaxi.com",
    "cn_zh": "https://api.minimaxi.com",
}
DEFAULT_REGION = "global"

DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "Korean_LonelyWarrior"
DEFAULT_LANGUAGE_BOOST = "Korean"

_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"]
_FORMATS = ["mp3", "wav", "flac", "pcm"]


class MiniMaxTTS(BaseTool):
    name = "minimax_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "minimax"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:MINIMAX_API_KEY"]
    install_instructions = (
        "Set MINIMAX_API_KEY to your MiniMax API key.\n"
        "  Get one at https://platform.minimax.io/ (global) or "
        "https://platform.minimaxi.com/ (CN).\n"
        "  Optionally set MINIMAX_REGION=cn to route to the mainland China host, "
        "or MINIMAX_BASE_URL to override the endpoint entirely."
    )
    fallback = "elevenlabs_tts"
    fallback_tools = ["elevenlabs_tts", "google_tts", "openai_tts", "piper_tts"]
    agent_skills = ["text-to-speech"]

    capabilities = [
        "text_to_speech",
        "voice_selection",
        "multilingual",
        "emotion_control",
        "word_timestamps",
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
        "ssml": False,
        "word_timestamps": True,
    }
    best_for = [
        "natural Korean narration (language_boost=Korean)",
        "multilingual CJK voiceovers with emotion control",
        "narration that needs word-level subtitle timestamps from the TTS call",
    ]
    not_good_for = [
        "fully offline production",
        "SSML markup control",
        "deterministic reproducible output",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to convert to speech (MiniMax limit: 10,000 characters per call).",
            },
            "model": {
                "type": "string",
                "default": DEFAULT_MODEL,
                "description": (
                    "MiniMax speech model, e.g. speech-2.8-hd (best quality), "
                    "speech-2.8-turbo (faster/cheaper), speech-2.6-hd, speech-02-hd."
                ),
            },
            "model_id": {
                "type": "string",
                "description": "Alias for model (selector compatibility). Used only when model is absent.",
            },
            "voice_id": {
                "type": "string",
                "default": DEFAULT_VOICE_ID,
                "description": "MiniMax system or cloned voice id, e.g. Korean_LonelyWarrior.",
            },
            "speed": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0},
            "vol": {"type": "number", "default": 1, "exclusiveMinimum": 0, "maximum": 10},
            "pitch": {"type": "integer", "default": 0, "minimum": -12, "maximum": 12},
            "emotion": {
                "type": "string",
                "enum": _EMOTIONS,
                "description": "Optional delivery emotion. Omit to let the model choose.",
            },
            "language_boost": {
                "type": "string",
                "default": DEFAULT_LANGUAGE_BOOST,
                "description": "Language hint such as Korean, English, Japanese, Chinese, or auto.",
            },
            "format": {"type": "string", "default": "mp3", "enum": _FORMATS},
            "sample_rate": {
                "type": "integer",
                "default": 32000,
                "enum": [8000, 16000, 22050, 24000, 32000, 44100],
            },
            "bitrate": {
                "type": "integer",
                "default": 128000,
                "enum": [32000, 64000, 128000, 256000],
                "description": "Only applies to mp3.",
            },
            "channel": {"type": "integer", "default": 1, "enum": [1, 2]},
            "subtitle_enable": {
                "type": "boolean",
                "default": True,
                "description": "Ask MiniMax for a subtitle timestamp file alongside the audio.",
            },
            "subtitle_type": {
                "type": "string",
                "default": "word",
                "enum": ["word", "sentence"],
            },
            "timestamps": {
                "type": "boolean",
                "description": "Selector alias for subtitle_enable. Used only when subtitle_enable is absent.",
            },
            "output_path": {"type": "string"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "output": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "voice_id": {"type": "string"},
            "format": {"type": "string"},
            "text_length": {"type": "integer"},
            "audio_duration_seconds": {"type": ["number", "null"]},
            "subtitle_path": {"type": ["string", "null"]},
            "word_timestamps": {"type": "array"},
        },
    }
    artifact_schema = {"type": "array", "items": {"type": "string"}}

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=2, backoff_seconds=2.0, retryable_errors=["rate_limit", "timeout"]
    )
    idempotency_key_fields = [
        "text",
        "model",
        "voice_id",
        "speed",
        "vol",
        "pitch",
        "emotion",
        "language_boost",
        "format",
        "sample_rate",
        "bitrate",
        "channel",
        "subtitle_enable",
        "subtitle_type",
    ]
    side_effects = [
        "writes audio file to output_path",
        "writes subtitle timestamp JSON next to the audio when subtitles are enabled",
        "calls the MiniMax T2A v2 API",
    ]
    user_visible_verification = [
        "Listen to generated audio for pronunciation, pacing, and voice fit",
    ]
    quality_score = 0.9
    latency_p50_seconds = 5.0

    # Approximate pay-as-you-go price per input character. Verify against the
    # MiniMax pricing page when refreshing.
    _RATES = {
        "hd": 0.0001,     # ~$100 / 1M characters
        "turbo": 0.00006,  # ~$60 / 1M characters
    }

    _KEY_DEFAULTS = {
        "model": DEFAULT_MODEL,
        "voice_id": DEFAULT_VOICE_ID,
        "speed": 1.0,
        "vol": 1,
        "pitch": 0,
        "language_boost": DEFAULT_LANGUAGE_BOOST,
        "format": "mp3",
        "sample_rate": 32000,
        "bitrate": 128000,
        "channel": 1,
        "subtitle_enable": True,
        "subtitle_type": "word",
    }

    @classmethod
    def _effective_inputs(cls, inputs: dict[str, Any]) -> dict[str, Any]:
        """Resolve selector aliases and fill API defaults."""
        provided = {k: v for k, v in inputs.items() if v is not None}
        if "model" not in provided and provided.get("model_id"):
            provided["model"] = provided["model_id"]
        if "subtitle_enable" not in provided and "timestamps" in provided:
            provided["subtitle_enable"] = bool(provided["timestamps"])
        effective = {**cls._KEY_DEFAULTS, **provided}
        # The selector's pitch range is wider than MiniMax's integer -12..12.
        effective["pitch"] = max(-12, min(12, int(round(float(effective["pitch"])))))
        return effective

    def idempotency_key(self, inputs: dict[str, Any]) -> str:
        return super().idempotency_key(self._effective_inputs(inputs))

    def _get_api_key(self) -> str | None:
        return os.environ.get("MINIMAX_API_KEY")

    def _base_url(self) -> str:
        override = os.environ.get("MINIMAX_BASE_URL")
        if override:
            return override.rstrip("/")
        region = os.environ.get("MINIMAX_REGION", DEFAULT_REGION).strip().lower()
        return REGION_BASE_URLS.get(region, REGION_BASE_URLS[DEFAULT_REGION])

    def get_status(self) -> ToolStatus:
        if self._get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        effective = self._effective_inputs(inputs)
        rate = self._RATES["turbo"] if "turbo" in str(effective["model"]) else self._RATES["hd"]
        return round(len(str(effective.get("text", ""))) * rate, 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                success=False, error="MINIMAX_API_KEY not set. " + self.install_instructions
            )

        effective = self._effective_inputs(inputs)
        start = time.time()
        try:
            result = self._generate(effective, api_key=api_key)
        except Exception as exc:
            return ToolResult(
                success=False, error=f"MiniMax TTS failed: {self._safe_error(exc, api_key)}"
            )

        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _build_payload(self, effective: dict[str, Any]) -> dict[str, Any]:
        voice_setting: dict[str, Any] = {
            "voice_id": effective["voice_id"],
            "speed": float(effective["speed"]),
            "vol": float(effective["vol"]),
            "pitch": effective["pitch"],
        }
        if effective.get("emotion"):
            voice_setting["emotion"] = effective["emotion"]

        audio_setting: dict[str, Any] = {
            "sample_rate": int(effective["sample_rate"]),
            "format": effective["format"],
            "channel": int(effective["channel"]),
        }
        if effective["format"] == "mp3":
            audio_setting["bitrate"] = int(effective["bitrate"])

        payload: dict[str, Any] = {
            "model": effective["model"],
            "text": effective["text"],
            "stream": False,
            "language_boost": effective["language_boost"],
            "voice_setting": voice_setting,
            "audio_setting": audio_setting,
            "output_format": "hex",
        }
        if effective["subtitle_enable"]:
            payload["subtitle_enable"] = True
            payload["subtitle_type"] = effective["subtitle_type"]
        return payload

    def _generate(self, effective: dict[str, Any], *, api_key: str) -> ToolResult:
        import requests

        payload = self._build_payload(effective)
        response = requests.post(
            f"{self._base_url()}/v1/t2a_v2",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        body = response.json()

        # MiniMax reports API errors in base_resp with HTTP 200.
        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            return ToolResult(
                success=False,
                error=(
                    f"MiniMax TTS error {base_resp.get('status_code')}: "
                    f"{base_resp.get('status_msg', 'unknown error')}"
                ),
            )

        data = body.get("data") or {}
        audio_hex = data.get("audio")
        if not audio_hex:
            return ToolResult(success=False, error="MiniMax TTS returned no audio data.")

        fmt = effective["format"]
        output_path = Path(effective.get("output_path") or f"minimax_tts.{fmt}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes.fromhex(audio_hex))
        artifacts = [str(output_path)]

        extra = body.get("extra_info") or {}
        audio_length_ms = extra.get("audio_length")
        usage_characters = extra.get("usage_characters")

        result_data: dict[str, Any] = {
            "provider": self.provider,
            "model": effective["model"],
            "voice_id": effective["voice_id"],
            "language_boost": effective["language_boost"],
            "format": fmt,
            "text_length": len(effective["text"]),
            "output": str(output_path),
            "audio_duration_seconds": (
                round(audio_length_ms / 1000, 3) if isinstance(audio_length_ms, (int, float)) else None
            ),
            "usage_characters": usage_characters,
            "subtitle_path": None,
            "word_timestamps": [],
        }

        subtitle_url = data.get("subtitle_file")
        if effective["subtitle_enable"] and subtitle_url:
            try:
                sub_response = requests.get(subtitle_url, timeout=60)
                sub_response.raise_for_status()
                subtitles = sub_response.json()
                subtitle_path = output_path.with_suffix(".subtitles.json")
                subtitle_path.write_text(
                    json.dumps(subtitles, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                result_data["subtitle_path"] = str(subtitle_path)
                result_data["word_timestamps"] = self._word_timestamps(subtitles)
                artifacts.append(str(subtitle_path))
            except Exception as exc:
                result_data["subtitle_warning"] = (
                    f"Could not fetch subtitle file: {self._safe_error(exc, api_key)}"
                )

        cost_inputs = dict(effective)
        if isinstance(usage_characters, int):
            cost_inputs["text"] = "x" * usage_characters
        return ToolResult(
            success=True,
            data=result_data,
            artifacts=artifacts,
            cost_usd=self.estimate_cost(cost_inputs),
            model=f"minimax/{effective['model']}",
        )

    @staticmethod
    def _word_timestamps(subtitles: Any) -> list[dict[str, Any]]:
        """Flatten MiniMax subtitle JSON into [{word, start, end}] in seconds.

        Segments carry text/time_begin/time_end in milliseconds; word-level
        files add a per-segment timestamped_words list. Sentence-level files
        fall back to one entry per segment.
        """
        segments = subtitles if isinstance(subtitles, list) else []
        if isinstance(subtitles, dict):
            for key in ("subtitles", "segments", "data"):
                if isinstance(subtitles.get(key), list):
                    segments = subtitles[key]
                    break

        def entry(item: dict[str, Any], text_key: str) -> dict[str, Any] | None:
            text = item.get(text_key)
            begin, end = item.get("time_begin"), item.get("time_end")
            if not text or not isinstance(begin, (int, float)) or not isinstance(end, (int, float)):
                return None
            return {"word": text, "start": round(begin / 1000, 3), "end": round(end / 1000, 3)}

        words: list[dict[str, Any]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            nested = segment.get("timestamped_words") or segment.get("words")
            if isinstance(nested, list) and nested:
                for word in nested:
                    if isinstance(word, dict):
                        item = entry(word, "word") or entry(word, "text")
                        if item:
                            words.append(item)
            else:
                item = entry(segment, "text")
                if item:
                    words.append(item)
        return words

    @staticmethod
    def _safe_error(exc: Exception, api_key: str | None) -> str:
        message = str(exc)
        if api_key:
            message = message.replace(api_key, "***")
        return message
