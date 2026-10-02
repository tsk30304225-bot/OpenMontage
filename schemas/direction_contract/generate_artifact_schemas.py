"""Generate the self-contained v1.2 schemas of visual_direction and visual_timeline.

    python -m schemas.direction_contract.generate_artifact_schemas

Authoring sources (edit these, never the generated files):
- schemas/base/visual_direction.v1.0.schema.json, schemas/base/visual_timeline.v1.0.schema.json:
  the v1.0 schemas as shipped before v1.2 (frozen base);
- schemas/direction_common.schema.json: shared definitions of 40–46;
- the v1.2 delta below.

Output (decision A, 2026-10-02): the SHIPPED schemas
schemas/artifacts/visual_direction.schema.json and schemas/artifacts/visual_timeline.schema.json
(fork-owned files, validated by the upstream validate_artifact). They are SELF-CONTAINED: every common
definition they use is materialized from direction_common into their own $defs
(transitive closure, refs rewritten to "#/$defs/<name>"), so the plain upstream
validate_artifact() validates them with no registry and no external $ref.
Both outputs materialize the same common definitions byte-for-byte; a regression
test (tests/tools/test_direction_v12_schemas.py) compares them and checks the shipped
files equal this generator's output.

What changes (additive and conditional; v1.0 documents keep validating):
- version: "1.0" or "1.2".
- v1.2 names the contract it consumed (contract: artifact + revision + fingerprint)
  and takes models only from 41: visual_models is forbidden in a 1.2 visual_direction.
- beats / timeline events gain the contract ids they implement: action_id,
  state_after_id, contract_event_id, anchor_id (the contract anchor whose exact
  text the beat uses) and sync_group (operations that form one change: same
  start, same duration; invariants are evaluated after the whole group).
- visual_timeline gains anchor_resolution: how every contract anchor resolved
  in the aligned narration. Fuzzy resolution is allowed here and only here;
  a locked anchor that resolves to a different span needs a deviation.
- a "1.0" document may not carry any v1.2 field (contract, contract ids on
  beats/events, anchor_resolution).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent          # schemas/direction_contract (authoring source)
SHIPPED = SCHEMAS.parent / "artifacts"
COMMON_URN = "urn:openmontage:schema:direction_common#/$defs/"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


COMMON = load(SCHEMAS / "direction_common.schema.json")["$defs"]


def common(name: str) -> dict:
    return {"$ref": COMMON_URN + name}


CONTRACT_IDS = {
    "action_id": {**common("qualified_id"),
                  "description": "v1.2: contract action this operation implements (an action may span several operations)."},
    "state_after_id": {**common("qualified_id"),
                       "description": "v1.2: contract state that must hold once this operation's sync group has applied."},
    "contract_event_id": {**common("qualified_id"), "description": "v1.2: contract event (time group) this belongs to."},
    "anchor_id": {**common("qualified_id"),
                  "description": "v1.2: contract anchor whose exact text this beat uses as narration_anchor."},
    "sync_group": {"type": "string",
                   "description": "v1.2: operations forming one change: same resolved start and duration; invariants are checked after the whole group."},
}
NOT_V12_ITEM = {"not": {"anyOf": [{"required": [k]} for k in CONTRACT_IDS]}}

ANCHOR_RESOLUTION = {
    "type": "object",
    "required": ["resolved_anchors", "unresolved_anchors"],
    "additionalProperties": False,
    "description": "v1.2 (original §26): every contract anchor resolved against the forced alignment.",
    "properties": {
        "source_word_count": {"type": "integer", "minimum": 0},
        "resolved_anchors": {"type": "array", "items": {
            "type": "object",
            "required": ["anchor_id", "status", "start_time", "end_time"],
            "additionalProperties": False,
            "properties": {
                "anchor_id": common("qualified_id"),
                "source_text": {"type": "string"},
                "word_ids": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                "start_time": {"type": "number", "minimum": 0},
                "end_time": {"type": "number", "minimum": 0},
                "start_frame": {"type": "integer", "minimum": 0},
                "end_frame": {"type": "integer", "minimum": 0},
                "status": {"enum": ["EXACT", "REVERSIBLE_NORMALIZATION", "FUZZY"]},
                "same_span": {"type": "boolean",
                              "description": "false = resolved to different words than the contract span: a deviation for a locked anchor"},
            },
        }},
        "unresolved_anchors": {"type": "array", "items": common("qualified_id")},
    },
}


def _refs(node, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                found.add(v)
            else:
                _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)
    return found


def _rewrite(node):
    """Point direction_common refs (external URN or the common file's own '#/$defs/') at local $defs."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith(COMMON_URN):
                out[k] = "#/$defs/" + v[len(COMMON_URN):]
            else:
                out[k] = _rewrite(v)
        return out
    if isinstance(node, list):
        return [_rewrite(v) for v in node]
    return node


def materialize(schema: dict) -> dict:
    """Copy the transitive closure of used direction_common definitions into schema['$defs']."""
    schema = _rewrite(schema)
    defs = schema.setdefault("$defs", {})
    pending = sorted(r[len("#/$defs/"):] for r in _refs(schema, set()) if r.startswith("#/$defs/") and r[len("#/$defs/"):] in COMMON)
    while pending:
        name = pending.pop()
        if name in defs:
            if name in COMMON and defs[name] != COMMON[name]:
                raise SystemExit(f"$defs/{name} of the base schema collides with direction_common/{name}")
            continue
        defs[name] = copy.deepcopy(COMMON[name])  # common's internal refs are already '#/$defs/<name>'
        pending += sorted(r[len("#/$defs/"):] for r in _refs(defs[name], set()) if r[len("#/$defs/"):] in COMMON)
    external = sorted(r for r in _refs(schema, set()) if not r.startswith("#/"))
    if external:
        raise SystemExit(f"generated schema still has external $ref: {external}")
    return schema


def _version_rules(v12_required: dict, v10_forbidden: dict) -> list[dict]:
    return [
        {"if": {"properties": {"version": {"const": "1.2"}}, "required": ["version"]}, "then": v12_required},
        {"if": {"properties": {"version": {"const": "1.0"}}, "required": ["version"]}, "then": v10_forbidden},
    ]


def derive_visual_direction() -> dict:
    s = copy.deepcopy(load(SCHEMAS / "base" / "visual_direction.v1.0.schema.json"))
    s["title"] = "Visual Direction (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract"] = {
        **common("contract_ref"),
        "description": "v1.2: the locked 40+41 revision this direction implements.",
    }
    s["$defs"]["beat"]["properties"].update(CONTRACT_IDS)
    s.setdefault("allOf", []).extend(_version_rules(
        {"required": ["contract"], "not": {"required": ["visual_models"]}},
        {"not": {"required": ["contract"]},
         "properties": {"scenes": {"items": {"properties": {"beats": {"items": NOT_V12_ITEM}}}}}},
    ))
    return materialize(s)


def derive_visual_timeline() -> dict:
    s = copy.deepcopy(load(SCHEMAS / "base" / "visual_timeline.v1.0.schema.json"))
    s["title"] = "Visual Timeline (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract"] = common("contract_ref")
    s["properties"]["events"]["items"]["properties"].update(CONTRACT_IDS)
    s["properties"]["anchor_resolution"] = ANCHOR_RESOLUTION
    s["properties"]["models"]["description"] = (
        "v1.0: copied from visual_direction.visual_models. v1.2: copied from persistent_visual_models "
        "(definition of every model the timeline uses)."
    )
    s.setdefault("allOf", []).extend(_version_rules(
        {"required": ["contract", "anchor_resolution"]},
        {"not": {"anyOf": [{"required": ["contract"]}, {"required": ["anchor_resolution"]}]},
         "properties": {"events": {"items": NOT_V12_ITEM}}},
    ))
    return materialize(s)


GENERATED = {
    "visual_direction.schema.json": derive_visual_direction,
    "visual_timeline.schema.json": derive_visual_timeline,
}


def render(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    for name, build in GENERATED.items():
        (SHIPPED / name).write_bytes(render(build()).encode("utf-8"))
        print("wrote", SHIPPED / name)
