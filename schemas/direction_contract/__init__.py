"""Canonical runtime schemas of the Visual Direction v1.2 contract (artifacts 40–46).

Fork-owned. These files are the single source: lib/direction_contract validates
40–46 through ``validator(name)``, never through docs/. They reference each other
by ``urn:openmontage:schema:<name>`` ids and are resolved through one registry.

visual_direction and visual_timeline are different: checkpoint and
visual_timeline_compiler validate them with the upstream ``validate_artifact``
(no registry), so ``generate_artifact_schemas.py`` writes them self-contained
into schemas/artifacts/ from ``base/`` + ``direction_common``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent
URN = "urn:openmontage:schema:"

# registry name -> file (artifact numbers 40–46)
SCHEMAS = {
    "direction_common": "direction_common.schema.json",
    "visual_direction_contract": "visual_direction_contract.schema.json",    # 40
    "persistent_visual_models": "persistent_visual_models.schema.json",      # 41
    "direction_lineage": "direction_lineage.schema.json",                    # 42
    "execution_binding": "execution_binding.schema.json",                    # 43
    "direction_deviations": "direction_deviations.schema.json",              # 44
    "direction_qa_report": "direction_qa_report.schema.json",                # 45
    "direction_review": "direction_review.schema.json",                      # 46
}


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / SCHEMAS[name]).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources = [(URN + name, load_schema(name)) for name in SCHEMAS]
    # 41 reuses the v1.0 visual_model definition: the frozen v1.0 base, under the id 41 references.
    v10 = json.loads((SCHEMA_DIR / "base" / "visual_direction.v1.0.schema.json").read_text(encoding="utf-8"))
    resources.append((URN + "visual_direction", {**v10, "$id": URN + "visual_direction"}))
    return Registry().with_resources((uri, Resource.from_contents(s)) for uri, s in resources)


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name), registry=registry())


def validate(name: str, document: Any) -> None:
    """Raise jsonschema.ValidationError (the most relevant one) when ``document`` is not a valid ``name``."""
    from jsonschema.exceptions import best_match

    error = best_match(validator(name).iter_errors(document))
    if error is not None:
        raise error
