"""Derive the v1.2 drafts of visual_direction and visual_timeline from the current v1.0 schemas.

The delta is the design: run this file to regenerate
schemas/visual_direction.v1.2.schema.json and schemas/visual_timeline.v1.2.schema.json.

    python docs/design/visual-direction-v1.2/derive_v12_schemas.py

What changes (everything else stays v1.0):
- version: "1.0" or "1.2". v1.0 documents keep validating unchanged.
- v1.2 visual_direction carries the contract fingerprint and takes its models
  from persistent_visual_models (41) instead of defining them: visual_models is
  forbidden, every model scene's visual_model_id must be a 41 model id.
- beats gain action_id / state_after_id (qualified contract ids). compile_timeline
  copies them onto the events, so the ids reach the renderer, the traces and the binding.
- visual_timeline gains contract_fingerprint and the same two event fields.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
COMMON = "urn:openmontage:schema:direction_common#/$defs/"


def load(name: str) -> dict:
    return json.loads((ROOT / "schemas" / "artifacts" / f"{name}.schema.json").read_text(encoding="utf-8"))


def derive_visual_direction() -> dict:
    s = copy.deepcopy(load("visual_direction"))
    s["$id"] = "urn:openmontage:schema:visual_direction_v1_2"
    s["title"] = "Visual Direction (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract_fingerprint"] = {
        "$ref": COMMON + "fingerprint",
        "description": "v1.2: the approved 40+41 this direction was compiled from.",
    }
    beat = s["$defs"]["beat"]["properties"]
    beat["action_id"] = {
        "$ref": COMMON + "qualified_id",
        "description": "v1.2: the contract action this beat (one model operation) implements. An action may span several beats.",
    }
    beat["state_after_id"] = {
        "$ref": COMMON + "qualified_id",
        "description": "v1.2: the contract state that must hold after this beat (checked by replay).",
    }
    s.setdefault("allOf", []).append({
        "if": {"properties": {"version": {"const": "1.2"}}, "required": ["version"]},
        "then": {
            "required": ["contract_fingerprint"],
            "not": {"required": ["visual_models"]},
        },
    })
    return s


def derive_visual_timeline() -> dict:
    s = copy.deepcopy(load("visual_timeline"))
    s["$id"] = "urn:openmontage:schema:visual_timeline_v1_2"
    s["title"] = "Visual Timeline (v1.0 or v1.2)"
    s["properties"]["version"] = {"type": "string", "enum": ["1.0", "1.2"]}
    s["properties"]["contract_fingerprint"] = {"$ref": COMMON + "fingerprint"}
    ev = s["properties"]["events"]["items"]["properties"]
    ev["action_id"] = {"$ref": COMMON + "qualified_id"}
    ev["state_after_id"] = {"$ref": COMMON + "qualified_id"}
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
