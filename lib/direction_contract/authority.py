"""Authority rules of the v1.2 contract: script canonicalization, contract identity, source identity.

Pure functions. The rules are fixed by id so a contract records which one it
was written against (``authority.canonicalization_id``); a later rule gets a
new id and old contracts stay reproducible.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

SCRIPT_SECTIONS_TEXT_V1 = "SCRIPT_SECTIONS_TEXT_V1"
CANONICALIZATIONS = {SCRIPT_SECTIONS_TEXT_V1}


def canonical_script_text(script: dict[str, Any], canonicalization_id: str = SCRIPT_SECTIONS_TEXT_V1) -> str:
    """SCRIPT_SECTIONS_TEXT_V1: sections[i].text in array order, CRLF/CR -> LF, NFC, joined by one LF, no trim."""
    if canonicalization_id != SCRIPT_SECTIONS_TEXT_V1:
        raise ValueError(f"unknown script canonicalization {canonicalization_id!r}")
    return "\n".join(
        unicodedata.normalize("NFC", str(section.get("text") or "").replace("\r\n", "\n").replace("\r", "\n"))
        for section in script.get("sections") or []
    )


def script_sha256(script: dict[str, Any], canonicalization_id: str = SCRIPT_SECTIONS_TEXT_V1) -> str:
    """SHA-256 of the canonical script text as UTF-8 without BOM."""
    return hashlib.sha256(canonical_script_text(script, canonicalization_id).encode("utf-8")).hexdigest()


def canonical_json_sha256(document: Any) -> str:
    """SHA-256 over canonical JSON (keys sorted, no whitespace, UTF-8) — artifact identity in 43/45 inputs."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(contract_doc: dict[str, Any], pvm_doc: dict[str, Any]) -> str:
    """Contract identity: sha256 over canonical JSON of {contract: 40 without lifecycle, pvm: 41}."""
    body = {"contract": {k: v for k, v in contract_doc.items() if k != "lifecycle"}, "pvm": pvm_doc}
    return "sha256:" + canonical_json_sha256(body)


def _segments(ref: str) -> list[str]:
    ref = unicodedata.normalize("NFC", str(ref).replace("\\", "/"))
    return [s for s in ref.split("/") if s not in ("", ".")]


def source_identical(contract_asset: str, cut_source: str) -> bool:
    """SOURCE_IDENTITY_V1: same reference, or the cut path ends with every path segment of the contract reference.

    Both sides are normalized (backslash -> slash, './' dropped, NFC). An
    asset-manifest id has no slash, so it compares as the whole last segment.
    """
    want, have = _segments(contract_asset), _segments(cut_source)
    return bool(want) and len(have) >= len(want) and have[-len(want):] == want
