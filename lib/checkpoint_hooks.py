"""Fork seam for lib/checkpoint.py.

checkpoint.py is an upstream file. It carries two calls into this module
(search it for ``checkpoint_hooks``): the extra supplementary artifacts and the
per-stage validation the fork adds. Keep both when merging upstream.
"""

from __future__ import annotations

from typing import Any

from lib.direction_contract.hooks import DIRECTION_ARTIFACTS, completion_gate, validate_scene_plan_direction

SUPPLEMENTARY_ARTIFACTS = DIRECTION_ARTIFACTS | {
    "tool_plan",            # Scene-stage WHAT WITH: verified tool offers routed from scene visual_need
}


def validate_stage(stage: str, status: str, artifacts: dict[str, Any], pipeline_type: str | None) -> None:
    """Fork validations for one checkpoint; raise CheckpointValidationError to block it."""
    validate_scene_plan_direction(stage, status, artifacts, pipeline_type)
    completion_gate(stage, status, artifacts, pipeline_type)  # v1.2: only when a contract (40) is present
