"""Validate the v1.2 design examples against the draft schemas.

    python -m schemas.direction_contract.validate_examples [--stamp]

Examples live in docs/design/visual-direction-v1.2/examples/; the schemas they are
checked against are the canonical runtime schemas in this package.

Design check only:
- every example validates against its draft schema (40–46: cross-file $refs
  resolved through one registry, the way direction_contract will validate them;
  visual_direction / visual_timeline 1.2: the generated SELF-CONTAINED schemas,
  validated with plain jsonschema and no registry, exactly as validate_artifact does);
- the generated schemas are current, have no external $ref, and materialize
  identical shared definitions;
- script authority (SCRIPT_SECTIONS_TEXT_V1): canonical_script_text is built from
  script.json sections, script.txt is that text, 40 script_sha256 is its SHA-256,
  and every 40 anchor satisfies canonical[char_start:char_end] == exact_text;
- the fingerprint rule: sha256 over canonical JSON of {"contract": 40 without
  "lifecycle", "pvm": 41}, keys sorted, no whitespace, UTF-8;
- the shipped v1.0 visual_direction fixture still validates under 1.2.
--stamp regenerates script.txt, writes the script sha256 into 40 and the
fingerprint into every downstream example. Contract semantics (lineage, states,
invariants, order, binding) are the future API's job, not this script's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

# the rules come from the runtime, so the examples are checked by exactly what production runs
from lib.direction_contract.authority import (
    SCRIPT_SECTIONS_TEXT_V1,
    canonical_script_text,
    fingerprint,
    script_sha256,
    source_identical,
)
from schemas.direction_contract import SCHEMA_DIR, URN
from schemas.direction_contract import generate_artifact_schemas as derive
from schemas.direction_contract import registry as runtime_registry

ROOT = SCHEMA_DIR.parents[1]
EX = ROOT / "docs" / "design" / "visual-direction-v1.2" / "examples" / "capital-competition"
LEGACY_VD = ROOT / "tests" / "fixtures" / "visual_direction" / "release_plan" / "visual_direction.json"

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
GENERATED_KIND = {"visual_direction_v1_2": derive.SHIPPED / "visual_direction.schema.json",
                  "visual_timeline_v1_2": derive.SHIPPED / "visual_timeline.schema.json"}
SCRIPT_CANONICALIZATION = SCRIPT_SECTIONS_TEXT_V1


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registry():
    return runtime_registry()


def validator(reg, kind: str) -> Draft202012Validator:
    if kind in GENERATED_KIND:  # self-contained: no registry, like validate_artifact
        return Draft202012Validator(load(GENERATED_KIND[kind]))
    return Draft202012Validator(reg.get_or_retrieve(URN + kind).value.contents, registry=reg)


def stamp() -> None:
    script = load(EX / "script.json")
    (EX / "script.txt").write_bytes(canonical_script_text(script).encode("utf-8"))  # derived view, never authored
    c = load(EX / "40_visual_direction_contract.json")
    c["authority"]["script_sha256"] = script_sha256(script)
    (EX / "40_visual_direction_contract.json").write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fp = fingerprint(c, load(EX / "41_persistent_visual_models.json"))
    for name in DOWNSTREAM:
        doc = load(EX / name)
        doc["contract"]["fingerprint"] = fp
        (EX / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report(ok: bool, label: str) -> int:
    print(f"{'OK  ' if ok else 'FAIL'} {label}")
    return 0 if ok else 1


def main() -> int:
    if "--stamp" in sys.argv:
        stamp()
    reg = registry()
    failures = 0
    for kind, name in CASES:
        errors = sorted(validator(reg, kind).iter_errors(load(EX / name)), key=lambda e: list(e.path))
        failures += report(not errors, f"{name} against {kind}")
        for e in errors[:6]:
            print(f"     {'/'.join(map(str, e.path))}: {e.message[:180]}")

    # generated 1.2 schemas: current, self-contained, identical shared definitions
    gen = {name: build() for name, build in derive.GENERATED.items()}
    stale_gen = [n for n, s in gen.items() if s != load(derive.SHIPPED / n)]
    external = sorted(r for s in gen.values() for r in derive._refs(s, set()) if not r.startswith("#/"))
    shared = sorted(set.intersection(*(set(s["$defs"]) & set(derive.COMMON) for s in gen.values())))
    differing = [d for d in shared if any(s["$defs"][d] != derive.COMMON[d] for s in gen.values())]
    failures += report(not stale_gen, "shipped schemas/artifacts visual_direction / visual_timeline == generator output" + (f" — stale {stale_gen}" if stale_gen else ""))
    failures += report(not external, "generated 1.2 schemas have no external $ref" + (f" — {external}" if external else ""))
    failures += report(not differing, f"shared definitions identical in both and equal to direction_common ({', '.join(shared)})"
                       + (f" — differ {differing}" if differing else ""))

    # script authority (SCRIPT_SECTIONS_TEXT_V1) and anchor spans
    contract = load(EX / "40_visual_direction_contract.json")
    script = load(EX / "script.json")
    canon = canonical_script_text(script)
    au = contract["authority"]
    anchors = [a for s in contract["scenes"] for a in s["anchors"]]
    bad_span = [a["anchor_id"] for a in anchors
                if canon[a["source_span"]["char_start"]:a["source_span"]["char_end"]] != a["exact_text"]]
    failures += report((EX / "script.txt").read_bytes() == canon.encode("utf-8"),
                       "script.txt == canonical_script_text(script.json) (UTF-8, no BOM)")
    failures += report(au.get("canonicalization_id") == SCRIPT_CANONICALIZATION and au.get("script_sha256") == script_sha256(script),
                       f"40 authority: {SCRIPT_CANONICALIZATION}, script_sha256 = sha256(canonical text)")
    failures += report(not bad_span, "canonical[char_start:char_end] == exact_text for every 40 anchor"
                       + (f" — mismatch {bad_span}" if bad_span else f" ({len(anchors)} anchors)"))
    span = anchors[0]["source_span"]
    failures += report(canon[span["char_start"] + 1:span["char_end"] + 1] != anchors[0]["exact_text"],
                       "rejects: anchor span shifted by one code point (span check)")
    crlf = dict(script, sections=[dict(s, text=s["text"].replace(" ", "\r\n", 1)) if i == 0 else s
                                  for i, s in enumerate(script["sections"])])
    failures += report("\r" not in canonical_script_text(crlf) and script_sha256(crlf) != script_sha256(script),
                       "CR/CRLF canonicalize to LF; a changed section text changes script_sha256")

    # D17: the 43 ASSET binding of the static evidence state names the contract's source asset
    sources = {o["object_id"]: o["source_asset"] for s in contract["scenes"] for o in s.get("objects", []) if o.get("source_asset")}
    states = {st["state_id"]: st for s in contract["scenes"] for st in s.get("states", [])}
    asset_bindings = [b for b in load(EX / "43_execution_binding.good.json")["bindings"] if b["locator"]["kind"] == "ASSET"]
    identity_ok = bool(asset_bindings) and all(
        source_identical(sources[obj], b["locator"]["source_asset_ref"])
        for b in asset_bindings for sid in b["consumes"].get("state_ids", [])
        for obj in states[sid].get("visible_objects", []) if obj in sources)
    failures += report(identity_ok, f"43 ASSET bindings match the contract source_asset (SOURCE_IDENTITY_V1, {len(asset_bindings)} binding)")
    failures += report(not source_identical("kb_rate_table_capture.png", "assets/evidence/other_table.png")
                       and not source_identical("rate.png", "assets/kb_rate.png"),
                       "SOURCE_IDENTITY_V1 rejects a different file and a partial file-name match")

    fp = fingerprint(contract, load(EX / "41_persistent_visual_models.json"))
    stale = [n for n in DOWNSTREAM if load(EX / n)["contract"]["fingerprint"] != fp]
    failures += report(not stale, f"downstream examples carry the contract fingerprint {fp[:19]}…"
                       + (f" — stale {stale}" if stale else ""))

    # Negative cases: each must be rejected by the schema alone.
    def must_fail(label: str, kind: str, source, mutate) -> int:
        doc = load(source if isinstance(source, Path) else EX / source)
        mutate(doc)
        return report(any(True for _ in validator(reg, kind).iter_errors(doc)), f"rejects: {label}")

    def sc(doc, sid):
        return next(s for s in doc["scenes"] if s["id"] == sid)

    def first_beat(doc):
        return next(s for s in doc["scenes"] if s.get("beats"))["beats"][0]

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
        ("LOCKED contract without canonicalization_id", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: d["authority"].pop("canonicalization_id")),
        ("unknown script canonicalization", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: d["authority"].update(canonicalization_id="NFC_WHITESPACE")),
        ("anchor without source_span", "visual_direction_contract", "40_visual_direction_contract.json",
         lambda d: sc(d, "SC009")["anchors"][0].pop("source_span")),
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
        ("bound binding without a locator", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][0].pop("locator")),
        ("binding that consumes no contract id", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][0].update(consumes={})),
        ("CODE locator without implementation_path", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][0]["locator"].pop("implementation_path")),
        ("ASSET locator without a cut", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][3]["locator"].pop("cut_id")),
        ("locator of unknown kind", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][3]["locator"].update(kind="SCREENSHOT")),
        ("deviated binding without a deviation_id", "execution_binding", "43_execution_binding.good.json",
         lambda d: d["bindings"][0].update(status="deviated")),
        ("legacy action-centric 43 (actions[] instead of bindings[])", "execution_binding", "43_execution_binding.good.json",
         lambda d: d.update(actions=[])),
        ("1.2 visual_direction defining its own models", "visual_direction_v1_2", "visual_direction.good.json",
         lambda d: d.update(visual_models=[])),
        ("1.2 visual_direction without a contract", "visual_direction_v1_2", "visual_direction.good.json",
         lambda d: d.pop("contract")),
        ("v1.0 visual_direction carrying a contract", "visual_direction_v1_2", LEGACY_VD,
         lambda d: d.update(contract=load(EX / "visual_direction.good.json")["contract"])),
        ("v1.0 beat carrying a contract action_id", "visual_direction_v1_2", LEGACY_VD,
         lambda d: first_beat(d).update(action_id="SC009/A01")),
        ("MATERIAL deviation without approval", "direction_deviations", "44_direction_deviations.json",
         lambda d: d["deviations"][0].update(approval_required=False)),
        ("APPROVED deviation without a decision", "direction_deviations", "44_direction_deviations.json",
         lambda d: d["deviations"][0].update(status="APPROVED")),
        ("locked scene in 45 without a receipt", "direction_qa_report", "45_direction_qa_report.good.json",
         lambda d: d["scenes"][0].pop("receipt")),
    ]
    for label, kind, source, mutate in negatives:
        failures += must_fail(label, kind, source, mutate)

    # 42 system coverage vs 45 independent recomputation (must agree)
    for tag in ("good", "as_produced"):
        lin = load(EX / f"42_direction_lineage.{tag}.json")["system_coverage"]["omitted_locked_ids"]
        qa = sorted(i for s in load(EX / f"45_direction_qa_report.{tag}.json")["scenes"] for i in (s.get("receipt") or {}).get("omitted", []))
        failures += report(sorted(lin) == qa, f"{tag}: 42 system_coverage omitted == 45 recomputed omitted ({len(qa)} ids)")

    errs = list(validator(reg, "visual_direction_v1_2").iter_errors(load(LEGACY_VD)))
    failures += report(not errs, f"legacy v1.0 fixture ({LEGACY_VD.relative_to(ROOT).as_posix()}) still valid under 1.2")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
