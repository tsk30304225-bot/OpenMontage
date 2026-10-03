"""The human authoring grammar as data: sections, which scenes they apply to, and the keys each accepts.

Source of truth: director-authoring-guide.md in the v1.2 design folder (sections 1, 4, 5, 7).
"""

from __future__ import annotations

LOCKED, FLEX, DISCRETIONARY = "REQUIRED_LOCKED", "REQUIRED_FLEX", "DISCRETIONARY"
ALL = frozenset({LOCKED, FLEX, DISCRETIONARY})

PROJECT_SECTIONS = ("PROJECT", "VIEWER JOURNEY")

# scene section -> importances it applies to (guide section 5; "—" there = not applicable)
SCENE_SECTION_SCOPE = {
    "SCENE": ALL,
    "MEANING CONTRACT": ALL,
    "SHOW": ALL,
    "ANCHORS": ALL,
    "PRESENTATION": ALL,
    "MOTION": frozenset({LOCKED}),
    "MODELS": ALL,
    "STATES": frozenset({LOCKED}),
    "ACTIONS": frozenset({LOCKED}),
    "EVENTS": frozenset({LOCKED}),
    "BEATS": ALL,
    "INVARIANTS": frozenset({LOCKED}),
    "CAUSAL": frozenset({LOCKED}),
    "TRUTH": ALL,
    "MUST PRESERVE": frozenset({LOCKED}),
    "ALLOWED FREEDOM": ALL,
    "PROHIBITED SIMPLIFICATION": ALL,
    "LAST FRAME": ALL,
    "RUNTIME": ALL,
    "FALLBACK": ALL,
    "REVIEW": frozenset({LOCKED}),
    "PVM TRANSITIONS": frozenset({FLEX, DISCRETIONARY}),
    "OUTPUT": ALL,
    "APPROVAL": ALL,
}
SCENE_SECTIONS = tuple(SCENE_SECTION_SCOPE)

# (allowed keys, required keys)
PROJECT_KEYS = ({"id", "script", "narration", "visual_identity", "approval"}, {"id", "script"})
APPROVAL_KEYS = ({"continue_pipeline", "generated_media", "cost_tools"}, set())
JOURNEY_KEYS = ({"id", "scenes", "goal", "feeling"}, {"id", "scenes", "goal"})
SCENE_KEYS = ({"importance", "role", "mode"}, {"importance", "role"})
MEANING_KEYS = ({"before", "change", "after", "question"}, {"after"})
OBJECT_KEYS = ({"model", "type", "role", "truth", "source", "persistence", "required", "removable", "layer", "parent"}, {"role"})
ANCHOR_KEYS = ({"text", "edge", "offset_ms", "script_span_id"}, {"text"})
PRESENTATION_KEYS = ({"layers", "assets", "source_pixels", "camera", "text", "sound", "readability", "transition_in", "transition_out"}, set())
MOTION_KEYS = ({"required", "static_replacement_valid", "causal", "dependency", "temporal_logic", "decorative_motion_allowed"},
               {"required", "static_replacement_valid"})
MODEL_KEYS = ({"enter", "visibility"}, set())
STATE_KEYS = ({"pvm", "also", "visible", "meaning", "invariants", "until", "bookkeeping", "initial"}, {"meaning"})
ACTION_KEYS = ({"from", "to", "at", "until", "targets", "type", "role", "model", "path", "easing", "min_seconds", "freedom",
                "after", "before", "with", "wait_until", "sync", "layers"}, {"from", "to", "at", "targets", "role"})
EVENT_KEYS = ({"on", "from", "do", "to", "next"}, {"on", "do", "to"})
BEAT_KEYS = ({"at", "function", "new", "meaning_before", "meaning_after", "before", "change", "after", "actions"}, {"at"})
INVARIANT_KEYS = ({"description", "constant", "path", "paths", "model", "value", "tolerance", "holds", "order", "during"}, set())
CAUSAL_KEYS = ({"proposition", "cause", "through", "effect", "proof", "prohibit", "visibility", "dependencies"},
               {"proposition", "cause", "through", "effect", "proof"})
LINK_KEYS = ({"state", "objects", "actions", "anchor", "required"}, {"state", "actions"})
PROOF_KEYS = ({"state", "observe"}, {"state"})
CAUSAL_VISIBILITY_KEYS = ({"cause_visible", "intermediate_visible", "effect_visible"}, set())
CAUSAL_DEPENDENCY_KEYS = ({"effect_after_cause", "intermediate_required"}, set())
TRUTH_KEYS = ({"statement", "truth", "source"}, {"statement", "truth"})
PRESERVE_KEYS = ({"beats", "objects", "events", "causal_chains", "ordering", "anchors", "models", "last_frame", "cross_scene"}, set())
LAST_FRAME_KEYS = ({"state", "end", "visible", "hidden", "also", "models", "text", "camera", "motion", "hold_seconds",
                    "handoff_objects", "next_scene", "next_scene_seed"}, {"state"})
LAYER_KEYS = ({"runtime", "purpose"}, {"runtime"})
FALLBACK_KEYS = ({"allowed"}, set())
REVIEW_KEYS = ({"questions", "evidence_states", "review"}, set())
PVM_TRANSITION_KEYS = ({"model", "from", "to"}, {"model", "to"})
OUTPUT_KEYS = ({"expected_media_type", "resolution", "fps", "duration_source", "first_frame_contract", "downstream_consumer"}, set())

RESERVED_SHOW, RESERVED_ANCHORS, RESERVED_RUNTIME = "requirements", "span", "hint"

RUNTIME_LAYERS = ("base_visual", "factual_source", "deterministic_graphics", "generated_media", "character",
                  "captions", "sound", "postprocess", "master_composite")

# Values the Bridge or the runtime produce: a Director writing them is an error (guide section 1).
SYSTEM_FIELDS = {
    "source_span", "char_start", "char_end", "entered_by", "exited_by", "consumes", "checks", "execution_graph",
    "lifecycle", "revision", "status", "locked_by", "locked_at", "generated_at",
    "script_sha256", "canonicalization_id", "fingerprint", "pvm_ref", "narration_sha256", "contract_ref",
    "anchor_id", "beat_id", "object_id", "state_id", "action_id", "event_id", "invariant_id", "causal_chain_id",
    "effective_must_preserve", "on_failure", "current_state", "state_history", "downstream_contract",
    "locked_direction_mutation", "semantic_fallback", "causal_contract_change", "mechanism_compatibility",
    "priority_policy", "schema_name", "schema_version", "artifact_role", "artifact_id",
}
# must_preserve core (D1): derived by the runtime for LOCKED scenes
PRESERVE_CORE = {"states", "actions", "invariants"}
# Not supported in v1.2 (an action completes when its last timeline operation ends; every action is required)
UNSUPPORTED_FIELDS = {"completion_state_id", "completion_condition", "completes_at", "completion", "must_execute", "occurrence_index"}

CONSTANT_FORMS = ("sum", "min", "max", "value")
ELEMENT_ROOTS = ("elements", "measures", "active", "view")
