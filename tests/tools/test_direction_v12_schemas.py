"""Visual Direction v1.2 — shipped schema integration (D14) and script authority (D15).

D14: schemas/artifacts/visual_direction.schema.json and visual_timeline.schema.json are
generated self-contained by schemas/direction_contract/generate_artifact_schemas.py, so the
plain upstream validate_artifact validates v1.0 and v1.2 documents with no registry.
D15: SCRIPT_SECTIONS_TEXT_V1 — the acceptance fixture's script hash and anchor spans.
D16: 43 is binding-centric. D18: 40–46 canonical runtime schemas live in schemas/direction_contract;
docs/design holds only the README and examples, and runtime code never reads docs/.
"""

import hashlib
import json
import unicodedata
from pathlib import Path

import jsonschema
import pytest

from schemas.artifacts import validate_artifact
from schemas.direction_contract import SCHEMA_DIR, SCHEMAS, validator
from schemas.direction_contract import generate_artifact_schemas as generator

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "design" / "visual-direction-v1.2"
EXAMPLE = DESIGN / "examples" / "capital-competition"
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"
LEGACY = REPO / "tests" / "fixtures" / "visual_direction" / "release_plan"
SHIPPED = ("visual_direction", "visual_timeline")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _shipped(name: str) -> dict:
    return _load(REPO / "schemas" / "artifacts" / f"{name}.schema.json")


def _refs(node, found):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                found.add(v)
            else:
                _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)
    return found


# --- D14: self-contained shipped schemas ----------------------------------------------------------

@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_schema_is_the_generator_output(name) -> None:
    assert _shipped(name) == generator.GENERATED[f"{name}.schema.json"]()


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_schema_has_no_external_ref(name) -> None:
    assert sorted(r for r in _refs(_shipped(name), set()) if not r.startswith("#/")) == []


def test_shared_definitions_are_identical_and_equal_to_direction_common() -> None:
    common = _load(SCHEMA_DIR / "direction_common.schema.json")["$defs"]
    vd, vt = (_shipped(n)["$defs"] for n in SHIPPED)
    shared = set(vd) & set(vt) & set(common)
    assert {"qualified_id", "contract_ref", "fingerprint"} <= shared
    for name in shared:
        assert vd[name] == vt[name] == common[name], name
    for defs in (vd, vt):  # every materialized common definition is verbatim
        for name in set(defs) & set(common):
            assert defs[name] == common[name], name


def test_v12_fixture_validates_with_plain_validate_artifact() -> None:
    for name in ("visual_direction.good.json", "visual_direction.as_produced.json"):
        validate_artifact("visual_direction", _load(FIX / name))


def test_v10_documents_still_validate() -> None:
    from lib.direction_contract.hooks import compile_timeline
    direction = _load(LEGACY / "visual_direction.json")
    validate_artifact("visual_direction", direction)
    validate_artifact("visual_timeline", compile_timeline(direction, _load(LEGACY / "alignment.json")))


def test_v12_requires_a_contract_and_forbids_model_definitions() -> None:
    good = _load(FIX / "visual_direction.good.json")
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("visual_direction", {k: v for k, v in good.items() if k != "contract"})
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("visual_direction", {**good, "visual_models": []})


def test_v10_documents_cannot_carry_v12_fields() -> None:
    direction = _load(LEGACY / "visual_direction.json")
    contract = _load(FIX / "visual_direction.good.json")["contract"]
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("visual_direction", {**direction, "contract": contract})
    beat_scene = next(s for s in direction["scenes"] if s.get("beats"))
    beat_scene["beats"][0]["action_id"] = "SC009/A01"
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("visual_direction", direction)


def test_v10_timeline_cannot_carry_v12_fields() -> None:
    from lib.direction_contract.hooks import compile_timeline
    timeline = compile_timeline(_load(LEGACY / "visual_direction.json"), _load(LEGACY / "alignment.json"))
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("visual_timeline", {**timeline, "anchor_resolution": {"resolved_anchors": [], "unresolved_anchors": []}})


# --- D15: SCRIPT_SECTIONS_TEXT_V1 (rule restated here as the spec) ----------------------------------

def _canonical(script: dict) -> str:
    return "\n".join(unicodedata.normalize("NFC", s["text"].replace("\r\n", "\n").replace("\r", "\n"))
                     for s in script["sections"])


def test_fixture_script_hash_is_sha256_of_the_canonical_text() -> None:
    authority = _load(FIX / "40_visual_direction_contract.json")["authority"]
    canonical = _canonical(_load(FIX / "script.json"))
    assert authority["canonicalization_id"] == "SCRIPT_SECTIONS_TEXT_V1"
    assert authority["script_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert (FIX / "script.txt").read_bytes() == canonical.encode("utf-8")  # derived view, no BOM


def test_fixture_anchor_spans_are_exact() -> None:
    canonical = _canonical(_load(FIX / "script.json"))
    anchors = [a for s in _load(FIX / "40_visual_direction_contract.json")["scenes"] for a in s["anchors"]]
    assert len(anchors) == 9
    for a in anchors:
        span = a["source_span"]
        assert canonical[span["char_start"]:span["char_end"]] == a["exact_text"], a["anchor_id"]


def test_fixture_matches_the_design_example() -> None:
    example = EXAMPLE
    for name in ("40_visual_direction_contract.json", "41_persistent_visual_models.json", "42_direction_lineage.json",
                 "44_direction_deviations.json", "visual_direction.good.json", "visual_direction.as_produced.json",
                 "script.json"):
        assert _load(FIX / name) == _load(example / name), name


def test_design_examples_validate() -> None:
    import os
    import subprocess
    import sys
    run = subprocess.run([sys.executable, "-m", "schemas.direction_contract.validate_examples"], capture_output=True, text=True,
                         encoding="utf-8", cwd=REPO, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]


# --- D18: one canonical schema location; docs/design is documentation only -----------------------------

def test_design_folder_holds_only_documentation_and_examples() -> None:
    files = sorted(p.relative_to(DESIGN).as_posix() for p in DESIGN.rglob("*") if p.is_file())
    assert all(f.endswith(".md") or f.startswith("examples/") for f in files), files
    assert not any(f.endswith((".py", ".schema.json")) for f in files)


def test_runtime_code_never_reads_docs_design() -> None:
    offenders = [p.relative_to(REPO).as_posix() for root in ("lib", "tools", "schemas")
                 for p in (REPO / root).rglob("*.py")
                 if "docs/design" in p.read_text(encoding="utf-8", errors="ignore").replace("\\", "/")
                 or "visual-direction-v1.2" in p.read_text(encoding="utf-8", errors="ignore")]
    assert offenders == ["schemas/direction_contract/validate_examples.py"]  # the example checker, not runtime


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_canonical_schemas_are_valid_and_resolvable(name) -> None:
    v = validator(name)
    v.check_schema(v.schema)


# --- D16: binding-centric 43 ---------------------------------------------------------------------------

def test_43_example_is_binding_centric_and_records_the_static_evidence_state() -> None:
    binding = _load(EXAMPLE / "43_execution_binding.good.json")
    errors = list(validator("execution_binding").iter_errors(binding))
    assert errors == []
    sc18 = next(b for b in binding["bindings"] if b["production_scene_id"] == "sc18")
    assert sc18["consumes"] == {"state_ids": ["SC010/S0"]}
    assert sc18["locator"]["kind"] == "ASSET" and "line" not in sc18["locator"]


def test_43_code_ref_line_is_optional_and_asset_locator_has_no_line() -> None:
    binding = _load(EXAMPLE / "43_execution_binding.good.json")
    binding["bindings"][0]["locator"]["refs"][0].pop("line")
    assert list(validator("execution_binding").iter_errors(binding)) == []
    binding["bindings"][3]["locator"]["line"] = 1
    assert list(validator("execution_binding").iter_errors(binding)) != []
