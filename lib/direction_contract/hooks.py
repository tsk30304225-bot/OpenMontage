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

v1.2 contract (only when a project carries visual_direction_contract, 40):

- contract: ``load_contract`` (40 + 41 → Contract), ``validate_contract`` (against
            the script), ``contract_fingerprint``
- plan:     ``check_lineage`` (42 system_coverage, recomputed)
- edit:     ``compile_timeline(..., models=, contract=)`` (timeline 1.2), ``check_states``
- compose:  ``bind`` (43), ``qa_report`` (45), ``record_deviation`` / ``open_deviations`` (44)
- gate:     ``completion_gate`` (checkpoint_hooks.validate_stage)
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
from lib.direction_contract.authority import SCRIPT_SECTIONS_TEXT_V1, canonical_script_text, script_sha256, source_identical
from lib.direction_contract.binding.execution import bind
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
from lib.direction_contract.contract_v12 import (
    Contract,
    DirectionContractError,
    contract_fingerprint,
    load_contract,
    validate_contract,
)
from lib.direction_contract.deviations import open_deviations, record_deviation
from lib.direction_contract.gate import CONTRACT_ARTIFACTS, completion_gate
from lib.direction_contract.guards import (
    attach_visual_timeline,
    prepare_atelier_direction,
    scene_clips_unread_error,
)
from lib.direction_contract.lineage import check_lineage
from lib.direction_contract.qa import qa_report
from lib.direction_contract.states import check_states

# Pipelines whose scene_plan stage must carry a visual_direction that passes
# validate_direction (errors block; warnings pass).
DIRECTION_CONTRACT_PIPELINES = {"animated-explainer"}

# Artifacts the direction contract adds next to the canonical stage artifacts.
DIRECTION_ARTIFACTS = {
    "visual_direction",     # Scene-stage meaning contract: viewer journey, visual models, anchored beats
    "visual_timeline",      # Edit-stage execution contract: beats resolved to aligned narration time
} | CONTRACT_ARTIFACTS      # v1.2: 40–46 (Director contract, models, lineage, binding, deviations, QA, review)


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

    if direction.get("version") == "1.2":
        # 1.2 takes its models from persistent_visual_models (41), never from the direction itself
        pvm = artifacts.get("persistent_visual_models")
        if not isinstance(pvm, dict):
            raise CheckpointValidationError("a 1.2 visual_direction needs persistent_visual_models (41) in the checkpoint")
        direction = {**direction, "visual_models": [m["definition"] for m in pvm.get("models") or []]}
    errors = validate_direction(direction).get("errors") or []
    if errors:
        raise CheckpointValidationError(
            "visual_direction contract errors (fix the plan; renderer support never removes it):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


__all__ = [
    "CONTRACT_ARTIFACTS",
    "Contract",
    "DIRECTION_ARTIFACTS",
    "DirectionContractError",
    "SCRIPT_SECTIONS_TEXT_V1",
    "bind",
    "canonical_script_text",
    "check_lineage",
    "check_states",
    "completion_gate",
    "contract_fingerprint",
    "load_contract",
    "open_deviations",
    "qa_report",
    "record_deviation",
    "script_sha256",
    "source_identical",
    "validate_contract",
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
