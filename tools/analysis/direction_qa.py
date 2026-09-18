"""Direction QA: did the planned state changes actually happen on screen?

Hard gate (deterministic, fails the review):
  - every beat anchor resolved to narration time (no ``unmatched``)
  - every event changes the model state (no no-op beats)
  - a ``visual_model`` cut for the event's model is on screen when it fires
  - the rendered pixels change across the event window (anchor before vs after)

Soft warnings (judgement, surfaced for the reviewer, never blocking):
  - weak visible change, long model holds with no event, long stretches without
    a reality scene, consecutive cuts that switch models, events crowded at the
    very start of a scene (everything revealed before it is narrated)

Frames before/after each anchor are written so a vision reviewer can judge
meaning; this tool does not claim to understand the picture.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from lib.visual_direction import REALITY_ROLES, ineffective_events
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

SAMPLE_W, SAMPLE_H = 480, 270
# A sampled pixel counts as changed when its luma moves by more than this (0-255).
PIXEL_DELTA = 24


def _load(value: Any, label: str) -> Any:
    if value is None or isinstance(value, dict):
        return value
    path = Path(str(value))
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _gray_frame(video: Path, t: float) -> bytes | None:
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
        "-vf", f"scale={SAMPLE_W}:{SAMPLE_H},format=gray", "-f", "rawvideo", "-",
    ]
    out = subprocess.run(cmd, capture_output=True)
    data = out.stdout
    return data if len(data) == SAMPLE_W * SAMPLE_H else None


def _changed_pixels(a: bytes, b: bytes, region: str) -> int:
    """Sampled pixels inside the model's region whose luma changed noticeably.

    A count, not a frame mean: model changes are often local (a line, a label,
    one block) and a mean over the whole picture dilutes them to nothing.
    """
    import numpy as np

    fa = np.frombuffer(a, dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W).astype(np.int16)
    fb = np.frombuffer(b, dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W).astype(np.int16)
    x0, x1 = {"left": (0, SAMPLE_W // 2), "right": (SAMPLE_W // 2, SAMPLE_W)}.get(region, (0, SAMPLE_W))
    # Ignore the caption band at the bottom so subtitles do not count as a model change.
    y1 = int(SAMPLE_H * 0.82)
    return int((np.abs(fa[:y1, x0:x1] - fb[:y1, x0:x1]) > PIXEL_DELTA).sum())


def _png(video: Path, t: float, out: Path) -> str | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=960:-2", str(out)]
    return str(out) if subprocess.run(cmd, capture_output=True).returncode == 0 and out.is_file() else None


class DirectionQA(BaseTool):
    name = "direction_qa"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg"]
    install_instructions = "Requires ffmpeg on PATH."

    capabilities = ["direction_qa", "anchor_frame_review"]
    best_for = [
        "verifying that visual_timeline events really changed the rendered picture at their narration anchors",
        "catching scene-plan direction that compose flattened into a static card",
    ]

    input_schema = {
        "type": "object",
        "required": ["visual_timeline", "edit_decisions"],
        "properties": {
            "video_path": {"type": "string", "description": "Rendered video. Without it only contract checks run."},
            "visual_timeline": {"type": ["object", "string"]},
            "edit_decisions": {"type": ["object", "string"]},
            "visual_direction": {"type": ["object", "string"], "description": "Enables rhythm warnings"},
            "scene_plan": {"type": ["object", "string"], "description": "Scene windows for rhythm/early-reveal warnings"},
            "output_dir": {"type": "string", "description": "Where anchor frames and direction_qa.json are written"},
            "min_changed_pixels": {"type": "integer", "default": 25,
                                   "description": f"Hard floor: sampled pixels ({SAMPLE_W}x{SAMPLE_H}) that must change across an event"},
            "weak_changed_pixels": {"type": "integer", "default": 150},
            "max_static_hold_seconds": {"type": "number", "default": 12.0},
            "max_seconds_without_reality": {"type": "number", "default": 75.0},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=False)
    side_effects = ["writes anchor frames and direction_qa.json under output_dir"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if shutil.which("ffmpeg") else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            timeline = _load(inputs["visual_timeline"], "visual_timeline")
            edit = _load(inputs["edit_decisions"], "edit_decisions")
            direction = _load(inputs.get("visual_direction"), "visual_direction")
            scene_plan = _load(inputs.get("scene_plan"), "scene_plan")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

        hard: list[str] = []
        warnings: list[str] = []
        checks: list[dict[str, Any]] = []
        events = sorted(timeline.get("events") or [], key=lambda e: e["time_seconds"])
        cuts = sorted(edit.get("cuts") or [], key=lambda c: c["in_seconds"])
        model_cuts = [c for c in cuts if c.get("type") == "visual_model"]

        for u in timeline.get("unmatched") or []:
            hard.append(f"beat {u.get('beat_id')}: anchor {u.get('narration_anchor')!r} not found in narration")
        for eid in ineffective_events(timeline):
            hard.append(f"{eid}: operation changes nothing in the model state")

        def cut_for(ev: dict[str, Any]) -> dict[str, Any] | None:
            t = ev["time_seconds"]
            for c in model_cuts:
                if (c.get("visual_model") or {}).get("model_id") == ev["model_id"] and c["in_seconds"] - 1e-3 <= t < c["out_seconds"]:
                    return c
            return None

        video = Path(inputs["video_path"]) if inputs.get("video_path") else None
        if video is not None and not video.is_file():
            return ToolResult(success=False, error=f"video not found: {video}")
        out_dir = Path(inputs.get("output_dir") or (video.parent / "direction_qa" if video else "direction_qa"))
        floor = int(inputs.get("min_changed_pixels", 25))
        weak = int(inputs.get("weak_changed_pixels", 150))

        for i, ev in enumerate(events):
            cut = cut_for(ev)
            row: dict[str, Any] = {"event": ev["id"], "operation": ev["operation"], "target": ev["target"],
                                   "time_seconds": ev["time_seconds"], "anchor": (ev.get("anchor") or {}).get("text")}
            if cut is None:
                hard.append(f"{ev['id']} ({ev['operation']} {ev['target']}) at {ev['time_seconds']}s: no visual_model cut for "
                            f"model {ev['model_id']!r} is on screen, so the renderer never executes it")
                row["executed"] = False
                checks.append(row)
                continue
            row["executed"] = True
            row["cut"] = cut["id"]
            end = ev["time_seconds"] + ev["duration_seconds"]
            if end > cut["out_seconds"] + 1e-3:
                warnings.append(f"{ev['id']}: animation ends at {end:.2f}s after cut {cut['id']} ends ({cut['out_seconds']}s)")
            if video is not None:
                before_t = max(cut["in_seconds"] + 0.04, ev["time_seconds"] - 0.12)
                after_t = min(cut["out_seconds"] - 0.04, end + 0.2)
                a, b = _gray_frame(video, before_t), _gray_frame(video, after_t)
                if a is None or b is None:
                    hard.append(f"{ev['id']}: could not decode frames at {before_t:.2f}s/{after_t:.2f}s")
                else:
                    changed = _changed_pixels(a, b, (cut.get("visual_model") or {}).get("region", "full"))
                    row["changed_pixels"] = changed
                    if changed < floor:
                        hard.append(f"{ev['id']} ({ev['operation']} {ev['target']}): picture did not change across the anchor "
                                    f"({changed} changed pixels < {floor})")
                    elif changed < weak:
                        warnings.append(f"{ev['id']} ({ev['operation']} {ev['target']}): visible change is small ({changed} changed pixels)")
                frames = {
                    "anchor_before": _png(video, before_t, out_dir / f"{i:03d}_{ev['id']}_before.png"),
                    "anchor_after": _png(video, after_t, out_dir / f"{i:03d}_{ev['id']}_after.png"),
                }
                row["frames"] = frames
            checks.append(row)

        # Soft: model holds with nothing happening.
        hold = float(inputs.get("max_static_hold_seconds", 12.0))
        for c in model_cuts:
            mid = (c.get("visual_model") or {}).get("model_id")
            times = [c["in_seconds"]] + [e["time_seconds"] for e in events if e["model_id"] == mid and c["in_seconds"] <= e["time_seconds"] < c["out_seconds"]] + [c["out_seconds"]]
            gaps = [b - a for a, b in zip(times, times[1:])]
            if gaps and max(gaps) > hold:
                warnings.append(f"cut {c['id']}: model {mid!r} holds still for {max(gaps):.1f}s (> {hold}s)")

        # Soft: consecutive model cuts that switch models break persistence.
        prev = None
        for c in cuts:
            if c.get("type") != "visual_model" or c.get("layer") == "overlay":
                prev = None if c.get("layer") != "overlay" else prev
                continue
            mid = (c.get("visual_model") or {}).get("model_id")
            if prev and prev != mid:
                warnings.append(f"cut {c['id']}: switches directly from model {prev!r} to {mid!r}; the viewer loses the persistent model")
            prev = mid

        # Soft: early reveal — every event of a scene firing in its first 15%.
        if scene_plan:
            windows = {s["id"]: (float(s["start_seconds"]), float(s["end_seconds"])) for s in scene_plan.get("scenes") or []}
            by_scene: dict[str, list[float]] = {}
            for ev in events:
                by_scene.setdefault(ev["scene_id"], []).append(ev["time_seconds"])
            for sid, ts in by_scene.items():
                if sid in windows and len(ts) >= 2:
                    s0, s1 = windows[sid]
                    if max(ts) < s0 + 0.15 * (s1 - s0):
                        warnings.append(f"scene {sid}: all {len(ts)} changes happen in the first 15% of the scene (information revealed before it is narrated)")

        # Soft: rhythm — long stretches without a reality scene.
        if direction and scene_plan:
            windows = {s["id"]: (float(s["start_seconds"]), float(s["end_seconds"])) for s in scene_plan.get("scenes") or []}
            limit = float(inputs.get("max_seconds_without_reality", 75.0))
            run_start = None
            for sc in direction.get("scenes") or []:
                w = windows.get(sc["scene_id"])
                if not w:
                    continue
                if sc.get("narrative_role") in REALITY_ROLES or sc.get("visual_mode") == "reality":
                    run_start = None
                    continue
                run_start = w[0] if run_start is None else run_start
                if w[1] - run_start > limit:
                    warnings.append(f"scene {sc['scene_id']}: {w[1] - run_start:.0f}s of graphics without a reality/breather scene")
                    run_start = w[1]

        report = {
            "passed": not hard,
            "hard_failures": hard,
            "warnings": warnings,
            "events_checked": len(events),
            "checks": checks,
        }
        artifacts = []
        if video is not None or inputs.get("output_dir"):
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "direction_qa.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(path))
        return ToolResult(
            success=not hard,
            data=report,
            artifacts=artifacts,
            error=f"{len(hard)} direction hard failure(s)" if hard else None,
            duration_seconds=round(time.time() - start, 2),
        )
