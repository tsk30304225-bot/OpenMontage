"""Capability-based tool routing: audit, route, usage report.

``audit``  classifies every tool route offer on the evidence ladder
           (DISCOVERED → AVAILABLE → SMOKE_TESTED → OUTPUT_VERIFIED →
           PRODUCTION_VERIFIED, plus the ``routable`` flag). Smoke calls are
           off unless ``run_smoke`` is set, and only free offers run unless a
           cost tier is explicitly approved. Results are machine-level.
``route``  turns ``scene_plan.scenes[].visual_need`` into a ``tool_plan`` using
           only routable offers.
``usage_report`` checks the produced asset_manifest / edit_decisions against
           the tool_plan (soft warnings: ignored layers, underused tools,
           unmet needs).

See lib/tool_routing.py and skills/core/tool-routing.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from lib.tool_routing import audit_dir, audit_tools, route_scenes, tool_usage_report
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


def _write(path: Any, doc: dict[str, Any]) -> str | None:
    if not path:
        return None
    out = Path(str(path))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


class ToolRouter(BaseTool):
    name = "tool_router"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    capabilities = ["audit_tool_capabilities", "route_scene_tools", "tool_usage_report"]
    best_for = [
        "deciding which verified tools fill each scene need, instead of defaulting to one runtime",
        "finding tools that are installed but never proven to produce output on this machine",
        "catching fitting tools that production ignored without a reason",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["audit", "route", "usage_report"]},
            "run_smoke": {"type": "boolean", "default": False,
                          "description": "audit: make the smallest real call per offer (free offers only by default)"},
            "allow_cost_tiers": {"type": "array", "items": {"type": "string", "enum": ["free", "subscription", "paid"]},
                                 "default": ["free"],
                                 "description": "audit: cost tiers approved for smoke calls; never widen without user approval"},
            "only": {"type": "array", "items": {"type": "string"}, "description": "audit: limit smoke calls to these tool names"},
            "projects_roots": {"type": "array", "items": {"type": "string"},
                               "description": "audit: project roots scanned for production evidence (events.jsonl)"},
            "capability": {"type": ["object", "string"],
                           "description": "route: audit report or path (default: <audit dir>/tool_capability.json)"},
            "scene_plan": {"type": ["object", "string"], "description": "route: scene_plan artifact or path"},
            "master_runtime": {"type": "string", "description": "route: approved render_runtime (master compositor)"},
            "approved_runtimes": {"type": "array", "items": {"type": "string"},
                                  "description": "route: every composition runtime the user approved at proposal"},
            "tool_plan": {"type": ["object", "string"], "description": "usage_report: tool_plan artifact or path"},
            "asset_manifest": {"type": ["object", "string"], "description": "usage_report: asset_manifest or path"},
            "edit_decisions": {"type": ["object", "string"], "description": "usage_report: edit_decisions or path"},
            "output_path": {"type": "string", "description": "Where to write the result JSON"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10, network_required=False)
    side_effects = [
        "audit with run_smoke: makes one minimal real call per approved offer and writes evidence under the "
        "machine-level audit dir (~/.openmontage/tool_audit)",
        "writes the result JSON when output_path is given",
    ]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation")
        try:
            if op == "audit":
                return self._audit(inputs)
            if op == "route":
                return self._route(inputs)
            if op == "usage_report":
                return self._usage(inputs)
        except (FileNotFoundError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=False, error=f"unknown operation {op!r}")

    def _audit(self, inputs: dict[str, Any]) -> ToolResult:
        from tools.tool_registry import registry

        registry.ensure_discovered()
        roots = [Path(p) for p in inputs["projects_roots"]] if inputs.get("projects_roots") else None
        report = audit_tools(
            registry._tools.values(),
            run_smoke=bool(inputs.get("run_smoke")),
            allow_cost_tiers=inputs.get("allow_cost_tiers") or ("free",),
            only=inputs.get("only"),
            projects_roots=roots,
        )
        out = _write(inputs.get("output_path") or audit_dir() / "tool_capability.json", report)
        return ToolResult(success=True, data={**report, "output_path": out}, artifacts=[out] if out else [])

    def _route(self, inputs: dict[str, Any]) -> ToolResult:
        from tools.tool_registry import registry

        scene_plan = _load(inputs.get("scene_plan"), "scene_plan")
        if not scene_plan:
            return ToolResult(success=False, error="route needs scene_plan")
        capability = _load(inputs.get("capability") or audit_dir() / "tool_capability.json", "capability audit")
        registry.ensure_discovered()
        plan = route_scenes(
            scene_plan,
            capability,
            approved_runtimes=inputs.get("approved_runtimes"),
            master_runtime=inputs.get("master_runtime"),
            tool_names=registry.list_all(),
        )
        try:
            validate_artifact("tool_plan", plan)
        except jsonschema.ValidationError as exc:
            return ToolResult(success=False, error=f"tool_plan failed schema: {exc.message}", data=plan)
        out = _write(inputs.get("output_path"), plan)
        return ToolResult(success=True, data={**plan, "output_path": out}, artifacts=[out] if out else [])

    def _usage(self, inputs: dict[str, Any]) -> ToolResult:
        plan = _load(inputs.get("tool_plan"), "tool_plan")
        if not plan:
            return ToolResult(success=False, error="usage_report needs tool_plan")
        report = tool_usage_report(plan, _load(inputs.get("asset_manifest"), "asset_manifest"),
                                   _load(inputs.get("edit_decisions"), "edit_decisions"))
        out = _write(inputs.get("output_path"), report)
        return ToolResult(success=True, data={**report, "output_path": out}, artifacts=[out] if out else [])
