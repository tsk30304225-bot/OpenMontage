"""Compile visual_direction beats into a visual_timeline from aligned narration.

``validate`` runs at the scene_plan stage (before any spend): models, operations,
targets and whether every narration anchor occurs in the script. ``compile``
runs at the edit stage once qwen3_tts has written its forced-aligned
``timestamps_path`` (om_segments.json).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.visual_direction import (
    compile_timeline,
    ineffective_events,
    is_rail,
    rail_schedule,
    replay_model_states,
    validate_direction,
)
from schemas.artifacts import validate_artifact
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


def _load(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    path = Path(str(value))
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class VisualTimelineCompiler(BaseTool):
    name = "visual_timeline_compiler"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    capabilities = ["validate_visual_direction", "compile_visual_timeline"]
    best_for = [
        "checking a visual_direction contract before assets are produced",
        "turning narration-anchored beats into timed renderer events after forced alignment",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation", "visual_direction"],
        "properties": {
            "operation": {"type": "string", "enum": ["validate", "compile"]},
            "visual_direction": {"type": ["object", "string"], "description": "visual_direction artifact or path"},
            "script": {"type": ["object", "string"], "description": "script artifact or path; anchors must occur in it"},
            "scene_plan": {"type": ["object", "string"], "description": "scene_plan artifact or path; scene windows guide anchor search"},
            "alignment": {"type": ["object", "array", "string"], "description": "qwen3_tts timestamps_path / word_timestamps_path JSON or path (compile)"},
            "output_path": {"type": "string", "description": "Where to write visual_timeline.json (compile)"},
            "min_score": {"type": "number", "default": 0.8, "description": "Fuzzy anchor acceptance threshold"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=1, network_required=False)
    side_effects = ["writes visual_timeline.json when output_path is given"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            direction = _load(inputs["visual_direction"], "visual_direction")
            validate_artifact("visual_direction", direction)
            script = _load(inputs.get("script"), "script")
            scene_plan = _load(inputs.get("scene_plan"), "scene_plan")
        except Exception as exc:
            return ToolResult(success=False, error=f"visual_direction is not valid: {exc}")

        report = validate_direction(direction, script)
        if scene_plan:
            plan_ids = {s["id"] for s in scene_plan.get("scenes") or []}
            for scene in direction.get("scenes") or []:
                if scene["scene_id"] not in plan_ids:
                    report["errors"].append(f"scene {scene['scene_id']}: not present in scene_plan")

        if inputs["operation"] == "validate":
            return ToolResult(success=not report["errors"], data=report,
                              error="; ".join(report["errors"]) if report["errors"] else None)
        if report["errors"]:
            return ToolResult(success=False, data=report, error="visual_direction contract errors: " + "; ".join(report["errors"]))

        try:
            alignment = _load(inputs.get("alignment"), "alignment")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        if not alignment:
            return ToolResult(success=False, error="compile needs alignment (qwen3_tts timestamps_path JSON)")

        windows = None
        if scene_plan:
            windows = {s["id"]: (float(s["start_seconds"]), float(s["end_seconds"])) for s in scene_plan.get("scenes") or []}
        source = {k: str(inputs[k]) for k in ("visual_direction", "alignment") if isinstance(inputs.get(k), str)}
        timeline = compile_timeline(direction, alignment, scene_windows=windows,
                                    min_score=float(inputs.get("min_score", 0.8)), source=source)
        validate_artifact("visual_timeline", timeline)

        problems = []
        if timeline["unmatched"]:
            problems.append(f"{len(timeline['unmatched'])} beat anchor(s) not found in the aligned narration")
        dead = ineffective_events(timeline)
        if dead:
            problems.append(f"events change nothing on screen: {', '.join(dead)}")
        if windows:
            for ev in timeline["events"]:
                start, end = windows.get(ev["scene_id"], (None, None))
                if start is not None and not (start - 0.5 <= ev["time_seconds"] <= end + 0.5):
                    report["warnings"].append(
                        f"{ev['id']} fires at {ev['time_seconds']}s outside scene {ev['scene_id']} ({start}-{end}s); "
                        "the edit must extend that model cut or the anchor is wrong"
                    )

        # Items pushed past the visible axis leave the frame; the direction should widen the view first.
        for model in (m for m in timeline["models"] if is_rail(m)):
            for ev, state in replay_model_states(timeline, model["id"]):
                sched = rail_schedule(state)
                axis_end = float(state["axis"].get("end", 0))
                if sched["last_end"] > axis_end + 1e-6:
                    where = f"after {ev['id']} ({ev['time_seconds']}s)" if ev else "in the initial state"
                    report["warnings"].append(
                        f"model {model['id']!r}: items run to {sched['last_end']:g} beyond axis end {axis_end:g} {where}; "
                        "add a SHIFT target=view beat with a larger end"
                    )
                    break

        artifacts = []
        if inputs.get("output_path"):
            out = Path(inputs["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(out))

        data = {
            "visual_timeline": timeline,
            "event_count": len(timeline["events"]),
            "unmatched": timeline["unmatched"],
            "ineffective_events": dead,
            "warnings": report["warnings"],
        }
        return ToolResult(success=not problems, data=data, artifacts=artifacts,
                          error="; ".join(problems) if problems else None)
