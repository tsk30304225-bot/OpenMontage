"""Visual Direction v1.2 — shipped schema integration (D14) and script authority (D15).

D14: schemas/artifacts/visual_direction.schema.json and visual_timeline.schema.json are
generated self-contained by docs/design/visual-direction-v1.2/derive_v12_schemas.py, so the
plain upstream validate_artifact validates v1.0 and v1.2 documents with no registry.
D15: SCRIPT_SECTIONS_TEXT_V1 — the acceptance fixture's script hash and anchor spans.
"""

import hashlib
import importlib.util
import json
import unicodedata
from pathlib import Path

import jsonschema
import pytest

from schemas.artifacts import validate_artifact

REPO = Path(__file__).resolve().parents[2]
DESIGN = REPO / "docs" / "design" / "visual-direction-v1.2"
FIX = REPO / "tests" / "fixtures" / "direction_v1_2" / "capital_competition"
LEGACY = REPO / "tests" / "fixtures" / "visual_direction" / "release_plan"
SHIPPED = ("visual_direction", "visual_timeline")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _derive():
    spec = importlib.util.spec_from_file_location("derive_v12_schemas", DESIGN / "derive_v12_schemas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert _shipped(name) == _derive().GENERATED[f"{name}.schema.json"]()


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_schema_has_no_external_ref(name) -> None:
    assert sorted(r for r in _refs(_shipped(name), set()) if not r.startswith("#/")) == []


def test_shared_definitions_are_identical_and_equal_to_direction_common() -> None:
    common = _load(DESIGN / "schemas" / "direction_common.schema.json")["$defs"]
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
    example = DESIGN / "examples" / "capital-competition"
    for name in ("40_visual_direction_contract.json", "41_persistent_visual_models.json", "42_direction_lineage.json",
                 "44_direction_deviations.json", "visual_direction.good.json", "visual_direction.as_produced.json",
                 "script.json"):
        assert _load(FIX / name) == _load(example / name), name


def test_design_examples_validate() -> None:
    import os
    import subprocess
    import sys
    run = subprocess.run([sys.executable, str(DESIGN / "validate_examples.py")], capture_output=True, text=True,
                         encoding="utf-8", cwd=REPO, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
