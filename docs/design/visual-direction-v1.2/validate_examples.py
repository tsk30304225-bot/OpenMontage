"""Validate the v1.2 design examples against the draft schemas.

    python docs/design/visual-direction-v1.2/validate_examples.py [--stamp]

Design check only:
- every example validates against its draft schema (cross-file $refs resolved
  through one registry, the way direction_contract will validate them);
- every 40 anchor is exact text of the authority script after NFC + whitespace
  normalization, at its occurrence_index;
- the fingerprint rule: sha256 over canonical JSON of {"contract": 40 without
  "lifecycle", "pvm": 41}, keys sorted, no whitespace, UTF-8;
- the shipped v1.0 visual_direction fixture still validates under 1.2.
--stamp writes the script sha256 into 40 and the fingerprint into every
downstream example. Contract semantics (lineage, states, invariants, order,
binding) are the future API's job, not this script's.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = HERE / "examples" / "capital-competition"
URN = "urn:openmontage:schema:"

CASES = [
    ("visual_direction_contract", "40_visual_direction_contract.json"),
    ("persistent_visual_models", "41_persistent_visual_models.json"),
    ("direction_lineage", "42_direction_lineage.json"),
    ("direction_lineage", "42_direction_lineage.good.json"),
    ("direction_lineage", "42_direction_lineage.as_produced.json"),
    ("visual_direction_v1_2", "visual_direction.good.json"),
    ("visual_direction_v1_2", "visual_direction.as_produced.json"),
    ("execution_binding", "43_execution_binding.good.json"),
    ("direction_deviations", "44_direction_deviations.json"),
    ("direction_qa_report", "45_direction_qa_report.good.json"),
    ("direction_qa_report", "45_direction_qa_report.as_produced.json"),
]
DOWNSTREAM = [name for kind, name in CASES if not name.startswith(("40_", "41_"))]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def registry() -> Registry:
    schemas = [load(p) for p in (HERE / "schemas").glob("*.schema.json")]
    # The shipped v1.0 schema has a relative $id; register it under the id the drafts reference.
    v10 = load(ROOT / "schemas" / "artifacts" / "visual_direction.schema.json")
    v10["$id"] = URN + "visual_direction"
    schemas.append(v10)
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)


def fingerprint(contract: dict, pvm: dict) -> str:
    body = {"contract": {k: v for k, v in contract.items() if k != "lifecycle"}, "pvm": pvm}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def stamp() -> None:
    script = (EX / "script.txt").read_bytes()
    c = load(EX / "40_visual_direction_contract.json")
    c["authority"]["script_sha256"] = hashlib.sha256(script).hexdigest()
    (EX / "40_visual_direction_contract.json").write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fp = fingerprint(c, load(EX / "41_persistent_visual_models.json"))
    for name in DOWNSTREAM:
        doc = load(EX / name)
        doc["contract"]["fingerprint"] = fp
        (EX / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if "--stamp" in sys.argv:
        stamp()
    reg = registry()
    failures = 0
    for kind, name in CASES:
        schema = reg.get_or_retrieve(URN + kind).value.contents
        errors = sorted(Draft202012Validator(schema, registry=reg).iter_errors(load(EX / name)), key=lambda e: list(e.path))
        print(f"{'OK  ' if not errors else 'FAIL'} {name} against {kind}")
        for e in errors[:6]:
            print(f"     {'/'.join(map(str, e.path))}: {e.message[:180]}")
        failures += bool(errors)

    contract = load(EX / "40_visual_direction_contract.json")
    script_raw = (EX / "script.txt").read_bytes()
    sha_ok = contract["authority"].get("script_sha256") == hashlib.sha256(script_raw).hexdigest()
    script = normalize(script_raw.decode("utf-8"))
    missing = []
    for scene in contract["scenes"]:
        for a in scene["anchors"]:
            hits = [m.start() for m in re.finditer(re.escape(normalize(a["exact_text"])), script)]
            if len(hits) <= a.get("occurrence_index", 0):
                missing.append(a["anchor_id"])
    print(f"{'OK  ' if sha_ok else 'FAIL'} 40 authority.script_sha256 matches script.txt")
    print(f"{'OK  ' if not missing else 'FAIL'} every 40 anchor is exact normalized script text"
          + (f" — missing {missing}" if missing else f" ({sum(len(s['anchors']) for s in contract['scenes'])} anchors)"))
    failures += (not sha_ok) + bool(missing)

    fp = fingerprint(contract, load(EX / "41_persistent_visual_models.json"))
    stale = [n for n in DOWNSTREAM if load(EX / n)["contract"]["fingerprint"] != fp]
    print(f"{'OK  ' if not stale else 'FAIL'} downstream examples carry the contract fingerprint {fp[:19]}…"
          + (f" — stale {stale}" if stale else ""))
    failures += bool(stale)

    # Negative cases: each must be rejected by the schema alone.
    def must_fail(label: str, kind: str, name: str, mutate) -> int:
        doc = load(EX / name)
        mutate(doc)
        schema = reg.get_or_retrieve(URN + kind).value.contents
        rejected = any(True for _ in Draft202012Validator(schema, registry=reg).iter_errors(doc))
        print(f"{'OK  ' if rejected else 'FAIL'} rejects: {label}")
        return 0 if rejected else 1

    def sc(doc, sid):
        return next(s for s in doc["scenes"] if s["id"] == sid)

    negatives = [
        ("causal scene with review not_required (decision 6)", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009")["qa_contract"].update(review="not_required")),
        ("static_replacement_valid=false with review not_required", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: (sc(d, "SC010")["motion_reason"].update(static_replacement_valid=False), sc(d, "SC010")["qa_contract"].update(review="not_required"))),
        ("locked motion scene without actions", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009").pop("actions")),
        ("causal_explanation without causal_motion_contracts", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009").pop("causal_motion_contracts")),
        ("locked scene without must_preserve", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009").pop("must_preserve")),
        ("locked_direction_mutation=true in approval_scope", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: d["approval_scope"].update(locked_direction_mutation=True)),
        ("LOCKED contract without script_sha256", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: d["authority"].pop("script_sha256")),
        ("unqualified action id", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009")["actions"][0].update(action_id="A01")),
        ("semantic transformation in 42 (only production types exist)", "direction_lineage", "42_direction_lineage.json",
         lambda d: d["production_scenes"][1]["transformations"].append({"type": "SEMANTIC_CHANGE", "target_ids": ["SC009/A02"]})),
        ("system_coverage not computed by check_lineage", "direction_lineage", "42_direction_lineage.good.json",
         lambda d: d["system_coverage"].update(computed_by="planner")),
        ("PIXEL_CHANGE used as a REQUIRED check", "direction_qa_report", "45_direction_qa_report.good.json",
         lambda d: next(c for c in d["scenes"][0]["checks"] if c["type"] == "PIXEL_CHANGE").update(role="REQUIRED")),
        ("locked receipt without effective_must_preserve", "direction_qa_report", "45_direction_qa_report.good.json",
         lambda d: d["scenes"][0]["receipt"].pop("effective_must_preserve")),
        ("binding action without per-layer bindings", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["actions"][0].pop("layer_bindings")),
        ("1.2 visual_direction defining its own models", "visual_direction_v1_2", "visual_direction.good.json",
         lambda d: d.update(visual_models=[])),
        ("MATERIAL deviation without approval", "direction_deviations", "44_direction_deviations.json",
         lambda d: d["deviations"][0].update(approval_required=False)),
        ("APPROVED deviation without a decision", "direction_deviations", "44_direction_deviations.json",
         lambda d: d["deviations"][0].update(status="APPROVED")),
        ("locked scene in 45 without a receipt", "direction_qa_report", "45_direction_qa_report.good.json",
         lambda d: d["scenes"][0].pop("receipt")),
    ]
    for label, kind, name, mutate in negatives:
        failures += must_fail(label, kind, name, mutate)

    # 42 system coverage vs 45 independent recomputation (must agree)
    for tag in ("good", "as_produced"):
        lin = load(EX / f"42_direction_lineage.{tag}.json")["system_coverage"]["omitted_locked_ids"]
        qa = sorted(i for sc in load(EX / f"45_direction_qa_report.{tag}.json")["scenes"] for i in (sc.get("receipt") or {}).get("omitted", []))
        agree = sorted(lin) == qa
        print(f"{'OK  ' if agree else 'FAIL'} {tag}: 42 system_coverage omitted == 45 recomputed omitted ({len(qa)} ids)")
        failures += not agree

    old = ROOT / "tests" / "fixtures" / "visual_direction" / "release_plan" / "visual_direction.json"
    schema = reg.get_or_retrieve(URN + "visual_direction_v1_2").value.contents
    errs = list(Draft202012Validator(schema, registry=reg).iter_errors(load(old)))
    print(f"{'OK  ' if not errs else 'FAIL'} legacy v1.0 fixture ({old.relative_to(ROOT).as_posix()}) still valid under 1.2")
    failures += bool(errs)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
