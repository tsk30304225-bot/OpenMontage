"""Direction deviations (44): what a stage could not implement, recorded instead of worked around.

A worker records; only the user decides (APPROVED / REJECTED). Approving a
deviation exempts exactly its affected ids; it never changes the contract —
changing the direction itself is a new contract revision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.direction_contract.contract_v12 import Contract, DirectionContractError
from schemas.direction_contract import validate as validate_schema

DEVIATIONS_FILE = "direction_deviations.json"
OPEN = {"PROPOSED"}


def _path(project_dir: str | Path) -> Path:
    return Path(project_dir) / DEVIATIONS_FILE


def load_deviations(project_dir: str | Path) -> dict[str, Any] | None:
    path = _path(project_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def record_deviation(project_dir: str | Path, contract: Contract, deviation: dict[str, Any]) -> dict[str, Any]:
    """Add (or replace, by deviation_id) one deviation in the project's 44 and return the updated 44."""
    scene = deviation.get("scene_id")
    if scene not in contract.scenes:
        raise DirectionContractError(f"deviation {deviation.get('deviation_id')}: scene {scene!r} is not in the contract")
    foreign = [cid for cid in deviation.get("affected_contract_ids") or [] if contract.scene_of(cid) != scene]
    if foreign:
        raise DirectionContractError(f"deviation {deviation.get('deviation_id')}: {foreign} are not ids of {scene}")
    doc = load_deviations(project_dir) or {"version": "1.2", "contract": contract.ref, "deviations": []}
    contract.check_ref("direction_deviations", doc.get("contract"))
    doc["deviations"] = [d for d in doc["deviations"] if d.get("deviation_id") != deviation.get("deviation_id")] + [dict(deviation)]
    validate_schema("direction_deviations", doc)
    path = _path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def open_deviations(project_dir: str | Path) -> list[dict[str, Any]]:
    """Deviations still waiting for the user's decision."""
    doc = load_deviations(project_dir) or {}
    return [d for d in doc.get("deviations") or [] if d.get("status") in OPEN]


def exempt_ids(deviations_doc: dict[str, Any] | None, statuses: set[str]) -> set[str]:
    return {cid for d in (deviations_doc or {}).get("deviations") or [] if d.get("status") in statuses
            for cid in d.get("affected_contract_ids") or []}
