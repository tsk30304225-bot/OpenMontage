"""Derive the v1.2 drafts of visual_direction and visual_timeline from the current v1.0 schemas.

The delta is the design: run this file to regenerate
schemas/visual_direction.v1.2.schema.json and schemas/visual_timeline.v1.2.schema.json.

    python docs/design/visual-direction-v1.2/derive_v12_schemas.py

What changes (everything else stays v1.0, and v1.0 documents keep validating):
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
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
COMMON = "urn:openmontage:schema:direction_common#/$defs/"


CONTRACT_IDS = {
    "action_id": {"$ref": COMMON + "qualified_id",
                  "description": "v1.2: contract action this operation implements (an action may span several operations)."},
    "state_after_id": {"$ref": COMMON + "qualified_id",
                       "description": "v1.2: contract state that must hold once this operation's sync group has applied."},
    "contract_event_id": {"$ref": COMMON + "qualified_id", "description": "v1.2: contract event (time group) this belongs to."},
    "anchor_id": {"$ref": COMMON + "qualified_id",
                  "description": "v1.2: contract anchor whose exact text this beat uses as narration_anchor."},
    "sync_group": {"type": "string",
                   "description": "v1.2: operations forming one change: same resolved start and duration; invariants are checked after the whole group."},
}

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
                "anchor_id": {"$ref": COMMON + "qualified_id"},
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
        "unresolved_anchors": {"type": "array", "items": {"$ref": COMMON + "qualified_id"}},
    },
}


def load(name: str) -> dict:
    return json.loads((ROOT / "schemas" / "artifacts" / f"{name}.schema.json").read_text(encoding="utf-8"))


def derive_visual_direction() -> dict:
    s = copy.deepcopy(load("visual_direction"))
    s["$id"] = "urn:openmontage:schema:visual_direction_v1_2"
    s["title"] = "Visual Direction (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract"] = {
        "$ref": COMMON + "contract_ref",
        "description": "v1.2: the locked 40+41 revision this direction implements.",
    }
    s["$defs"]["beat"]["properties"].update(CONTRACT_IDS)
    s.setdefault("allOf", []).append({
        "if": {"properties": {"version": {"const": "1.2"}}, "required": ["version"]},
        "then": {
            "required": ["contract"],
            "not": {"required": ["visual_models"]},
        },
    })
    return s


def derive_visual_timeline() -> dict:
    s = copy.deepcopy(load("visual_timeline"))
    s["$id"] = "urn:openmontage:schema:visual_timeline_v1_2"
    s["title"] = "Visual Timeline (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract"] = {"$ref": COMMON + "contract_ref"}
    s["properties"]["events"]["items"]["properties"].update(CONTRACT_IDS)
    s["properties"]["anchor_resolution"] = ANCHOR_RESOLUTION
    s["properties"]["models"]["description"] = (
        "v1.0: copied from visual_direction.visual_models. v1.2: copied from persistent_visual_models "
        "(definition of every model the timeline uses)."
    )
    return s


if __name__ == "__main__":
    out = HERE / "schemas"
    for name, schema in (("visual_direction.v1.2", derive_visual_direction()),
                         ("visual_timeline.v1.2", derive_visual_timeline())):
        (out / f"{name}.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", out / f"{name}.schema.json")
