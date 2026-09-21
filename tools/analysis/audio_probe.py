"""Lightweight audio/video file probe using ffprobe.

Returns duration, format, sample rate, channels, and codec info
for any media file ffprobe can read. No heavy dependencies — just
requires ffmpeg/ffprobe on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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


PROBE_ATTEMPTS = 4          # ffprobe calls at most, per file
PROBE_RETRY_SECONDS = 1.0   # pause between attempts


def probe_duration(file_path: str | Path) -> float | None:
    """Quick helper: return duration in seconds, or None on failure.

    Use this from other tools that just need the duration without
    going through the full tool execute() flow.

    ffprobe output is decoded as UTF-8 (locale-independent: it may echo
    non-ASCII paths), and a failed probe is retried a few times because on
    Windows a file a worker process has just written can be briefly locked.
    A missing ffprobe or a missing file returns None at once.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not Path(file_path).is_file():
        return None
    for attempt in range(PROBE_ATTEMPTS):
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except Exception:
            if attempt < PROBE_ATTEMPTS - 1:
                time.sleep(PROBE_RETRY_SECONDS)
    return None


class AudioProbe(BaseTool):
    name = "audio_probe"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "ffprobe"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffprobe"]
    install_instructions = (
        "Install ffmpeg (includes ffprobe):\n"
        "  Windows: winget install ffmpeg\n"
        "  macOS: brew install ffmpeg\n"
        "  Linux: sudo apt install ffmpeg"
    )

    capabilities = ["probe_duration", "probe_format", "probe_streams"]
    best_for = [
        "getting audio/video duration before composition",
        "validating media file format and codec",
        "pre-render checks on asset files",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to audio or video file",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=64, vram_mb=0, disk_mb=0, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["input_path"]
    side_effects = []

    def get_status(self) -> ToolStatus:
        if shutil.which("ffprobe"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        input_path = Path(inputs["input_path"])
        if not input_path.exists():
            return ToolResult(success=False, error=f"File not found: {input_path}")

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return ToolResult(success=False, error="ffprobe not found on PATH")

        start = time.time()

        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    str(input_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"ffprobe failed: {result.stderr.strip()}",
                )

            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="ffprobe timed out (15s)")
        except json.JSONDecodeError:
            return ToolResult(success=False, error="ffprobe returned invalid JSON")

        fmt = data.get("format", {})
        streams = data.get("streams", [])

        # Find audio stream
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        probe_data: dict[str, Any] = {
            "file": str(input_path),
            "duration_seconds": round(float(fmt.get("duration", 0)), 3),
            "format_name": fmt.get("format_name"),
            "format_long_name": fmt.get("format_long_name"),
            "size_bytes": int(fmt.get("size", 0)),
            "bit_rate": int(fmt.get("bit_rate", 0)),
            "stream_count": len(streams),
        }

        if audio_stream:
            probe_data["audio"] = {
                "codec": audio_stream.get("codec_name"),
                "sample_rate": int(audio_stream.get("sample_rate", 0)),
                "channels": audio_stream.get("channels"),
                "channel_layout": audio_stream.get("channel_layout"),
                "bit_rate": int(audio_stream.get("bit_rate", 0)) if audio_stream.get("bit_rate") else None,
            }

        return ToolResult(
            success=True,
            data=probe_data,
            duration_seconds=round(time.time() - start, 2),
        )
