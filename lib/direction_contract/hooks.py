"""Public entry points of the direction contract — the only names outside this package should use.

Tools and tests import from here, never from the submodules.

- plan:  ``validate_direction`` (contract errors/warnings)
- edit:  ``compile_timeline`` (beats → real seconds from the alignment), ``is_rail`` /
  ``rail_schedule`` / ``replay_model_states`` (state replay for reports)
- render / QA: the implementation binding per runtime — ``build_trace``
  (atelier Remotion source), ``hyperframes_cuts`` / ``scene_events`` /
  ``write_bridge`` / ``trace_workspace`` / ``without_scene_events`` (HyperFrames
  scene workspaces), ``ineffective_events``
"""

from __future__ import annotations

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

__all__ = [
    "REALITY_ROLES",
    "build_trace",
    "compile_timeline",
    "hyperframes_cuts",
    "ineffective_events",
    "is_rail",
    "rail_schedule",
    "replay_model_states",
    "scene_events",
    "trace_workspace",
    "validate_direction",
    "without_scene_events",
    "write_bridge",
]
