"""Director Authoring Bridge: human authoring document -> canonical 40 (guide section 8).

    doc_40 = compile_authoring(text, pvm_41, script, revision=1, generated_at=..., lock={"by": ..., "at": ...})

Pipeline: strict parse -> normalize (N1-N12, internal graph check) -> schema validation -> load_contract
(41 schema + pvm_ref) -> validate_contract. Every problem is collected; on any problem AuthoringError is
raised and no 40 is returned. Same inputs always give the same 40.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError

from lib.direction_contract.authoring.errors import AuthoringError, AuthoringIssue
from lib.direction_contract.authoring.normalize import Builder
from lib.direction_contract.authoring.syntax import parse_authoring
from lib.direction_contract.contract_v12 import DirectionContractError, load_contract, validate_contract
from schemas.direction_contract import validate as validate_schema


def compile_authoring(text: str, pvm: dict[str, Any], script: dict[str, Any], *, revision: int = 1,
                      generated_at: str | None = None, lock: dict[str, str] | None = None,
                      narration_audio: bytes | None = None) -> dict[str, Any]:
    """Compile the human authoring document into a schema-valid, validate_contract-clean 40."""
    doc, issues = parse_authoring(text)
    if issues:
        raise AuthoringError(issues)
    builder = Builder(doc, pvm, script, narration_audio)
    contract = builder.build(revision=revision, generated_at=generated_at, lock=lock)
    if builder.issues:
        raise AuthoringError(builder.issues)
    try:
        validate_schema("visual_direction_contract", contract)
    except ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path)
        raise AuthoringError([AuthoringIssue("CONTRACT_SCHEMA", f"{path}: {exc.message}")]) from None
    try:
        loaded = load_contract(contract, pvm)
    except (DirectionContractError, ValidationError) as exc:
        raise AuthoringError([AuthoringIssue("CONTRACT_SCHEMA", str(getattr(exc, "message", exc)))]) from None
    errors = validate_contract(loaded, script)["errors"]
    if errors:
        raise AuthoringError([AuthoringIssue("CONTRACT_SEMANTIC", e) for e in errors])
    return contract


def write_contract(contract: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
