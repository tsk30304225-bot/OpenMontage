"""Public entry points of the direction contract — the only names outside this package should use.

Core files never import the submodules directly; they go through the fork
seams ``lib/compose_hooks.py`` (video_compose) and ``lib/checkpoint_hooks.py``
(checkpoint), which call the functions here. Tools and tests may import this
module.

Stages, in pipeline order:

- plan:     ``validate_direction`` (contract errors/warnings),
            ``validate_scene_plan_direction`` (scene_plan checkpoint gate)
- edit:     ``compile_timeline`` (beats → real seconds from the alignment), ``is_rail`` /
            ``rail_schedule`` / ``replay_model_states`` (state replay for reports)
- render:   ``attach_visual_timeline`` (templated), ``prepare_atelier_direction``
            and ``scene_clips_unread_error`` (atelier), the HyperFrames binding
            (``hyperframes_cuts``, ``scene_events``, ``write_bridge``, ``trace_workspace``)
- QA:       ``build_trace``, ``trace_workspace``, ``without_scene_events``,
            ``ineffective_events``
"""

from __future__ import annotations

from typing import Any

from lib.direction_contract.binding.hyperframes import (
    hyperframes_cuts,
    scene_events,
    trace_workspace,
    without_scene_events,
    write_bridge,
)
from lib.direction_contract.binding.remotion_source import build_trace
from lib.direction_contract.contract import (
    REALITY_ROLES,
    compile_timeline,
    ineffective_events,
    is_rail,
    rail_schedule,
    replay_model_states,
    validate_direction,
)
from lib.direction_contract.guards import (
    attach_visual_timeline,
    prepare_atelier_direction,
    scene_clips_unread_error,
)

# Pipelines whose scene_plan stage must carry a visual_direction that passes
# validate_direction (errors block; warnings pass).
DIRECTION_CONTRACT_PIPELINES = {"animated-explainer"}

# Artifacts the direction contract adds next to the canonical stage artifacts.
DIRECTION_ARTIFACTS = {
    "visual_direction",     # Scene-stage meaning contract: viewer journey, visual models, anchored beats
    "visual_timeline",      # Edit-stage execution contract: beats resolved to aligned narration time
}


def validate_scene_plan_direction(
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    pipeline_type: str | None,
) -> None:
    """Run the existing visual-direction validator at the scene_plan checkpoint.

    The validator already refuses a direction whose explanation scenes carry no
    visual model; it only ran when an agent called visual_timeline_compiler, so
    a plan could drop every model and still complete the stage.
    """
    from lib.checkpoint import CheckpointValidationError

    if pipeline_type not in DIRECTION_CONTRACT_PIPELINES or stage != "scene_plan":
        return
    if status not in {"completed", "awaiting_human"}:
        return
    direction = artifacts.get("visual_direction")
    if not isinstance(direction, dict):
        raise CheckpointValidationError(
            f"{pipeline_type} scene_plan must include the visual_direction artifact "
            "(skills/core/visual-direction.md)"
        )

    errors = validate_direction(direction).get("errors") or []
    if errors:
        raise CheckpointValidationError(
            "visual_direction contract errors (fix the plan; renderer support never removes it):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


__all__ = [
    "DIRECTION_ARTIFACTS",
    "DIRECTION_CONTRACT_PIPELINES",
    "REALITY_ROLES",
    "attach_visual_timeline",
    "build_trace",
    "compile_timeline",
    "hyperframes_cuts",
    "ineffective_events",
    "is_rail",
    "rail_schedule",
    "replay_model_states",
    "prepare_atelier_direction",
    "scene_clips_unread_error",
    "scene_events",
    "trace_workspace",
    "validate_direction",
    "validate_scene_plan_direction",
    "without_scene_events",
    "write_bridge",
]
