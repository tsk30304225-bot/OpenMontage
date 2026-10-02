"""Validate the v1.2 design examples against the draft schemas.

    python docs/design/visual-direction-v1.2/validate_examples.py [--write-fingerprints]

Schema validation only (design check), plus the fingerprint rule the schemas
reference: sha256 over canonical JSON of {"contract": 40 without "approval",
"pvm": 41}, keys sorted, no whitespace, UTF-8. --write-fingerprints stamps it
into the downstream examples. Contract semantics (lineage, states, invariants,
order, binding) are not checked here — that is the job of the future API.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = HERE / "examples" / "capital-competition"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registry() -> Registry:
    schemas = [load(p) for p in (HERE / "schemas").glob("*.schema.json")]
    # The shipped v1.0 schema has a relative $id; register it under the absolute id the drafts reference.
    v10 = load(ROOT / "schemas" / "artifacts" / "visual_direction.schema.json")
    v10["$id"] = "urn:openmontage:schema:visual_direction"
    schemas.append(v10)
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)


def fingerprint(contract: dict, pvm: dict) -> str:
    body = {"contract": {k: v for k, v in contract.items() if k != "approval"}, "pvm": pvm}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


CASES = [
    ("visual_direction_contract", "40_visual_direction_contract.json"),
    ("persistent_visual_models", "41_persistent_visual_models.json"),
    ("visual_direction_v1_2", "visual_direction.good.json"),
    ("visual_direction_v1_2", "visual_direction.as_produced.json"),
    ("direction_lineage", "direction_lineage.json"),
]
IDS = {
    "visual_direction_contract": "urn:openmontage:schema:visual_direction_contract",
    "persistent_visual_models": "urn:openmontage:schema:persistent_visual_models",
    "visual_direction_v1_2": "urn:openmontage:schema:visual_direction_v1_2",
    "direction_lineage": "urn:openmontage:schema:direction_lineage",
}


def main() -> int:
    reg = registry()
    fp = fingerprint(load(EX / "40_visual_direction_contract.json"), load(EX / "41_persistent_visual_models.json"))
    if "--write-fingerprints" in sys.argv:
        for name in ("visual_direction.good.json", "visual_direction.as_produced.json", "direction_lineage.json"):
            doc = load(EX / name)
            doc["contract_fingerprint"] = fp
            (EX / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = 0
    for kind, name in CASES:
        schema = reg.get_or_retrieve(IDS[kind]).value.contents
        errors = sorted(Draft202012Validator(schema, registry=reg).iter_errors(load(EX / name)), key=lambda e: list(e.path))
        print(f"{'OK  ' if not errors else 'FAIL'} {name} against {kind}")
        for e in errors[:5]:
            print(f"     {'/'.join(map(str, e.path))}: {e.message[:160]}")
        failures += bool(errors)
    print("contract fingerprint:", fp)
    old = ROOT / "tests" / "fixtures" / "visual_direction" / "release_plan" / "visual_direction.json"
    if old.is_file():
        schema = reg.get_or_retrieve(IDS["visual_direction_v1_2"]).value.contents
        errs = list(Draft202012Validator(schema, registry=reg).iter_errors(load(old)))
        print(f"{'OK  ' if not errs else 'FAIL'} existing v1.0 fixture still valid under the v1.2 visual_direction schema")
        failures += bool(errs)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
