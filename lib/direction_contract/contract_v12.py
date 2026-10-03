"""Visual Direction v1.2 — the Director contract (40) and project visual models (41).

``load_contract`` validates 40/41 against the canonical runtime schemas
(schemas/direction_contract) and normalizes them into a ``Contract``:
effective must_preserve (D1), resolved review requirement (D6), layer
declarations (D10/D16), fingerprint (D3) and an id index. ``validate_contract``
adds the semantic rules the schemas cannot express (README §5), including the
script authority (D15). Assertion evaluation on model state signatures lives
here too; it is shared by lineage, state checks and QA.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.direction_contract.authority import (
    CANONICALIZATIONS,
    canonical_json_sha256,
    canonical_script_text,
    fingerprint,
    script_sha256,
)
from lib.direction_contract.contract import element_initial_state, model_initial_state, model_state_signature
from schemas.direction_contract import validate as validate_schema


class DirectionContractError(ValueError):
    """An artifact does not fit the approved contract (stale, unknown ids, broken rule)."""


LOCKED = "REQUIRED_LOCKED"
FLEX = "REQUIRED_FLEX"

# must_preserve keys that are not scene-qualified contract ids
_NOT_QUALIFIED = {"persistent_models", "cross_scene"}

# layers whose locked requirements are realized by placing source assets (edit_decisions cuts)
ASSET_LAYERS = {"factual_source", "base_visual", "generated_media"}


@dataclass
class Contract:
    doc: dict[str, Any]
    pvm: dict[str, Any]
    fingerprint: str
    scenes: dict[str, dict[str, Any]]
    models: dict[str, dict[str, Any]]                  # 41 entry by model id
    effective: dict[str, list[str]]                    # scene id -> effective must_preserve (D1)
    review_required: dict[str, bool]                   # scene id -> resolved qa_contract.review (D6)
    index: dict[str, tuple[str, str, dict[str, Any]]]  # qualified id -> (kind, scene id, object)
    layer_consumes: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # scene -> layer -> ids (explicit + implied)

    # --- identity -------------------------------------------------------------------------------
    @property
    def ref(self) -> dict[str, Any]:
        return {
            "artifact": "visual_direction_contract",
            "artifact_id": self.doc["artifact_id"],
            "revision": self.doc["lifecycle"]["revision"],
            "fingerprint": self.fingerprint,
        }

    @property
    def locked(self) -> bool:
        return self.doc["lifecycle"]["status"] == "LOCKED"

    def check_ref(self, artifact_name: str, ref: Any) -> None:
        """Raise when a downstream artifact names another contract (artifact, revision or fingerprint)."""
        if not isinstance(ref, dict):
            raise DirectionContractError(f"{artifact_name} has no contract reference")
        mine = self.ref
        wrong = [k for k in ("artifact", "revision", "fingerprint") if ref.get(k) != mine[k]]
        if ref.get("artifact_id") is not None and ref.get("artifact_id") != mine["artifact_id"]:
            wrong.append("artifact_id")
        if wrong:
            raise DirectionContractError(
                f"{artifact_name} was made for another contract ({', '.join(wrong)} differ: "
                f"{ {k: ref.get(k) for k in wrong} } vs this contract { {k: mine[k] for k in wrong} }); regenerate it"
            )

    # --- lookups --------------------------------------------------------------------------------
    def kind(self, cid: str) -> str | None:
        return self.index.get(cid, (None,))[0]

    def scene_of(self, cid: str) -> str | None:
        hit = self.index.get(cid)
        return hit[1] if hit else None

    def obj(self, cid: str) -> dict[str, Any] | None:
        hit = self.index.get(cid)
        return hit[2] if hit else None

    def definition(self, model_id: str) -> dict[str, Any]:
        return self.models[model_id]["definition"]

    def definitions(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(m["definition"]) for m in self.models.values()]

    def named_state(self, ref: str) -> list[dict[str, Any]]:
        model_id, name = ref.split(".", 1)
        entry = self.models[model_id]
        return next(n for n in entry.get("named_states") or [] if n["id"] == name)["assert"]

    def state_assertions(self, state_id: str) -> list[tuple[str, dict[str, Any]]]:
        """[(model_id, assertion)] a model state must satisfy; empty for a state outside every model."""
        st = self.obj(state_id) or {}
        out: list[tuple[str, dict[str, Any]]] = []
        if st.get("pvm_state"):
            model_id = st["pvm_state"].split(".", 1)[0]
            out += [(model_id, a) for a in self.named_state(st["pvm_state"])]
        for chk in st.get("object_states") or []:
            out += [(chk["model_id"], a) for a in chk["assert"]]
        return out

    def is_model_state(self, state_id: str) -> bool:
        return bool(self.state_assertions(state_id))

    def scene_models(self, scene_id: str) -> list[str]:
        scene = self.scenes[scene_id]
        ids = [m["model_id"] for m in scene.get("models") or []]
        ids += [a["model_id"] for a in scene.get("actions") or [] if a.get("model_id") and a["model_id"] not in ids]
        ids += [t["model_id"] for t in scene.get("pvm_transitions") or [] if t["model_id"] not in ids]
        return ids

    def declaring_layers(self, scene_id: str, cid: str) -> list[str]:
        """Layers of the scene's runtime_stack that must realize ``cid`` (explicit or implied consumes)."""
        return sorted(layer for layer, ids in (self.layer_consumes.get(scene_id) or {}).items() if cid in ids)

    def layer_runtime(self, scene_id: str, layer: str) -> str:
        return ((self.scenes[scene_id].get("runtime_stack") or {}).get(layer) or {}).get("runtime", "none")


# ---------------------------------------------------------------------------
# Assertions on model state signatures
# ---------------------------------------------------------------------------

_MISSING = object()


def resolve_path(signature: Any, path: str) -> Any:
    cur = signature
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is _MISSING or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(op: str, actual: Any, expected: Any, tolerance: float | None) -> bool:
    if op == "exists":
        return actual is not _MISSING and actual is not None
    if op == "absent":
        return actual is _MISSING or actual is None
    if op == "in":
        return actual is not _MISSING and actual in (expected or [])
    a, e = _num(actual), _num(expected)
    if op in ("eq", "ne"):
        if a is not None and e is not None and not isinstance(expected, bool):
            same = abs(a - e) <= (tolerance or 1e-9)
        else:
            if actual is _MISSING and expected is False:
                actual = False  # an element that never appeared is not visible
            same = actual == expected
        return same if op == "eq" else not same
    if a is None or e is None:
        return False
    return {"gt": a > e, "gte": a >= e - 1e-9, "lt": a < e, "lte": a <= e + 1e-9}[op]


def aggregate_value(signature: Any, aggregate: str, paths: list[str]) -> float | None:
    values = [resolve_path(signature, p) for p in paths]
    if aggregate == "count_true":
        return float(sum(1 for v in values if v is True))
    nums = [_num(v) for v in values]
    nums = [0.0 if n is None else n for n in nums]  # an allocation that does not exist yet holds nothing
    return {"sum": sum, "min": min, "max": max}[aggregate](nums) if nums else None


def assertion_holds(assertion: dict[str, Any], signature: Any) -> bool:
    if "aggregate" in assertion:
        value = aggregate_value(signature, assertion["aggregate"], assertion["paths"])
        return _compare(assertion["op"], value, assertion["value"], assertion.get("tolerance"))
    return _compare(assertion["op"], resolve_path(signature, assertion["path"]), assertion.get("value"), assertion.get("tolerance"))


def target_value(target: dict[str, Any], signature: Any) -> float | None:
    if "paths" in target:
        return aggregate_value(signature, target["aggregate"], target["paths"])
    return _num(resolve_path(signature, target["path"]))


# ---------------------------------------------------------------------------
# Loading and normalization
# ---------------------------------------------------------------------------


def _read(source: Any) -> dict[str, Any]:
    if isinstance(source, dict):
        return copy.deepcopy(source)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _index(doc: dict[str, Any]) -> tuple[dict[str, tuple[str, str, dict[str, Any]]], list[str]]:
    index: dict[str, tuple[str, str, dict[str, Any]]] = {}
    dupes: list[str] = []
    kinds = (("anchors", "anchor_id", "anchor"), ("beats", "beat_id", "beat"), ("objects", "object_id", "object"),
             ("states", "state_id", "state"), ("actions", "action_id", "action"), ("events", "event_id", "event"),
             ("invariants", "invariant_id", "invariant"), ("causal_motion_contracts", "causal_chain_id", "causal_chain"))
    for scene in doc["scenes"]:
        for key, id_key, kind in kinds:
            for item in scene.get(key) or []:
                cid = item[id_key]
                if cid in index:
                    dupes.append(cid)
                index[cid] = (kind, scene["id"], item)
    return index, dupes


def effective_must_preserve(scene: dict[str, Any]) -> list[str]:
    """D1: a locked scene preserves every state, action and invariant plus every authored must_preserve id."""
    if scene.get("importance") != LOCKED:
        return []
    ids = {s["state_id"] for s in scene.get("states") or []}
    ids |= {a["action_id"] for a in scene.get("actions") or []}
    ids |= {i["invariant_id"] for i in scene.get("invariants") or []}
    for key, values in (scene.get("must_preserve") or {}).items():
        if key not in _NOT_QUALIFIED:
            ids |= set(values)
    return sorted(ids)


def review_needed(scene: dict[str, Any]) -> bool:
    """D6: does the scene's picture need a human Direction Review (46)?"""
    mode = (scene.get("qa_contract") or {}).get("review", "auto")
    if mode != "auto":
        return mode == "required"
    return auto_review(scene)


def auto_review(scene: dict[str, Any]) -> bool:
    reason = scene.get("motion_reason") or {}
    return bool(scene.get("causal_motion_contracts") or scene.get("actions") or scene.get("pvm_transitions")
                or reason.get("static_replacement_valid") is False)


def _layer_consumes(scene: dict[str, Any]) -> dict[str, list[str]]:
    """Explicit consumes plus what they imply: a layer that runs an action also realizes its contract
    events and the model states it leaves and enters."""
    actions = {a["action_id"]: a for a in scene.get("actions") or []}
    events_of: dict[str, list[str]] = {}
    for ev in scene.get("events") or []:
        for aid in ev.get("actions") or []:
            events_of.setdefault(aid, []).append(ev["event_id"])
    out: dict[str, list[str]] = {}
    for layer, spec in (scene.get("runtime_stack") or {}).items():
        ids = set(spec.get("consumes") or [])
        for aid in list(ids):
            if aid in actions:
                a = actions[aid]
                ids |= set(events_of.get(aid, []))
                ids |= {s for s in (a.get("from_state_id"), a.get("to_state_id")) if s}
        if ids:
            out[layer] = sorted(ids)
    return out


def load_contract(path_40: Any, path_41: Any) -> Contract:
    """Load, schema-validate and normalize the Director contract (40) and project visual models (41)."""
    doc, pvm = _read(path_40), _read(path_41)
    validate_schema("visual_direction_contract", doc)
    validate_schema("persistent_visual_models", pvm)
    index, dupes = _index(doc)
    if dupes:
        raise DirectionContractError(f"contract ids are not unique: {sorted(set(dupes))}")
    pvm_sha = ((doc.get("authority") or {}).get("pvm_ref") or {}).get("sha256")
    if pvm_sha and pvm_sha != canonical_json_sha256(pvm):
        raise DirectionContractError("authority.pvm_ref.sha256 does not match the persistent_visual_models given")
    scenes = {s["id"]: s for s in doc["scenes"]}
    return Contract(
        doc=doc,
        pvm=pvm,
        fingerprint=fingerprint(doc, pvm),
        scenes=scenes,
        models={m["definition"]["id"]: m for m in pvm["models"]},
        effective={sid: effective_must_preserve(s) for sid, s in scenes.items()},
        review_required={sid: review_needed(s) for sid, s in scenes.items()},
        index=index,
        layer_consumes={sid: _layer_consumes(s) for sid, s in scenes.items()},
    )


def contract_fingerprint(contract: Any, pvm: Any = None) -> str:
    """``contract_fingerprint(Contract)`` or ``contract_fingerprint(doc_40, doc_41)``."""
    if isinstance(contract, Contract):
        return contract.fingerprint
    return fingerprint(_read(contract), _read(pvm))


# ---------------------------------------------------------------------------
# Semantic validation (README §5)
# ---------------------------------------------------------------------------


def _initial_signature(contract: Contract, model_id: str) -> Any:
    model = contract.definition(model_id)
    return model_state_signature(model, model_initial_state(model))


def validate_contract(contract: Contract, script: dict[str, Any]) -> dict[str, list[str]]:
    """Semantic rules of 40/41 beyond the schemas. Errors block the scene_plan gate; warnings do not."""
    errors: list[str] = []
    warnings: list[str] = []
    doc = contract.doc
    err = errors.append

    # --- script authority (D15) -----------------------------------------------------------------
    authority = doc.get("authority") or {}
    canon_id = authority.get("canonicalization_id")
    canonical = None
    if canon_id not in CANONICALIZATIONS:
        err(f"authority.canonicalization_id {canon_id!r} is not a known script canonicalization")
    elif not isinstance(script, dict) or not script.get("sections"):
        err("validate_contract needs the script artifact (sections[].text) the contract was written against")
    else:
        canonical = canonical_script_text(script, canon_id)
        if authority.get("script_sha256") and authority["script_sha256"] != script_sha256(script, canon_id):
            err("authority.script_sha256 does not match the canonical text of this script (the script changed after the contract was locked)")
    if not contract.locked:
        warnings.append(f"contract status is {doc['lifecycle']['status']}: only a LOCKED contract passes a gate")

    def known(cid: str | None, kinds: tuple[str, ...], where: str) -> bool:
        if cid is None:
            return False
        if contract.kind(cid) not in kinds:
            err(f"{where}: {cid} is not a {'/'.join(kinds)} of this contract")
            return False
        return True

    for scene in doc["scenes"]:
        sid = scene["id"]
        prefix = sid + "/"
        for cid, (kind, owner, _) in contract.index.items():
            if owner == sid and not cid.startswith(prefix):
                err(f"{cid} ({kind}) lives in {sid} but is not qualified with {prefix}")
        anchors = {a["anchor_id"]: a for a in scene.get("anchors") or []}

        # anchors: exact canonical spans
        if canonical is not None:
            for a in anchors.values():
                span = a["source_span"]
                if span["char_end"] <= span["char_start"] or canonical[span["char_start"]:span["char_end"]] != a["exact_text"]:
                    err(f"{a['anchor_id']}: canonical_script_text[{span['char_start']}:{span['char_end']}] != exact_text {a['exact_text']!r}")

        def at(anchor_id: str | None) -> int | None:
            a = anchors.get(anchor_id) if anchor_id else None
            return a["source_span"]["char_start"] if a else None

        span = scene.get("narration_span") or {}
        for key in ("start_anchor", "end_anchor"):
            known(span.get(key), ("anchor",), f"{sid}.narration_span.{key}")
        lo, hi = at(span.get("start_anchor")), at(span.get("end_anchor"))

        def inside(anchor_id: str | None, where: str) -> None:
            pos = at(anchor_id)
            if pos is not None and lo is not None and hi is not None and not lo <= pos <= hi:
                err(f"{where}: anchor {anchor_id} lies outside the scene's narration_span")

        last_beat = -1
        for beat in scene.get("beats") or []:
            if known(beat.get("anchor"), ("anchor",), f"{beat['beat_id']}.anchor"):
                inside(beat["anchor"], beat["beat_id"])
                pos = at(beat["anchor"])
                if pos is not None and pos < last_beat:
                    err(f"{beat['beat_id']}: beats are not in narration order")
                last_beat = max(last_beat, pos if pos is not None else -1)
            for key in ("visual_state_before", "visual_state_after"):
                if beat.get(key):
                    known(beat[key], ("state",), f"{beat['beat_id']}.{key}")
            for aid in beat.get("linked_actions") or []:
                known(aid, ("action",), f"{beat['beat_id']}.linked_actions")

        for obj in scene.get("objects") or []:
            if obj.get("model_id"):
                if obj["model_id"] not in contract.models:
                    err(f"{obj['object_id']}: model {obj['model_id']} is not in persistent_visual_models")
                else:
                    elements = {str(e["id"]) for e in element_initial_state(contract.definition(obj["model_id"]))["elements"].values()}
                    if obj.get("element_id") not in elements:
                        err(f"{obj['object_id']}: model {obj['model_id']} has no element {obj.get('element_id')!r}")

        for model in scene.get("models") or []:
            if model["model_id"] not in contract.models:
                err(f"{sid}: model {model['model_id']} is not in persistent_visual_models")

        states = {s["state_id"]: s for s in scene.get("states") or []}
        for st in states.values():
            if st.get("pvm_state"):
                mid, name = st["pvm_state"].split(".", 1)
                entry = contract.models.get(mid)
                if entry is None or name not in {n["id"] for n in entry.get("named_states") or []}:
                    err(f"{st['state_id']}: pvm_state {st['pvm_state']} is not a named state in persistent_visual_models")
            for oid in st.get("visible_objects") or []:
                known(oid, ("object",), f"{st['state_id']}.visible_objects")
            for key in ("entered_by", "exited_by"):
                if st.get(key):
                    known(st[key], ("action",), f"{st['state_id']}.{key}")
        if scene.get("initial_state"):
            known(scene["initial_state"], ("state",), f"{sid}.initial_state")

        actions = {a["action_id"]: a for a in scene.get("actions") or []}
        for a in actions.values():
            aid = a["action_id"]
            for key in ("start_anchor", "end_anchor"):
                if known(a.get(key), ("anchor",), f"{aid}.{key}"):
                    inside(a[key], aid)
            frm, to = a.get("from_state_id"), a.get("to_state_id")
            ok_from = known(frm, ("state",), f"{aid}.from_state_id")
            ok_to = known(to, ("state",), f"{aid}.to_state_id")
            if ok_from and ok_to:
                p_from, p_to = states[frm].get("pvm_state"), states[to].get("pvm_state")
                if p_from and p_to and p_from.split(".")[0] == p_to.split(".")[0]:
                    mid = p_from.split(".")[0]
                    # absent or empty transitions = unrestricted; a non-empty list is an allowlist (41 schema)
                    pairs = {(t["from"], t["to"]) for t in contract.models[mid].get("transitions") or []}
                    if pairs and (p_from.split(".")[1], p_to.split(".")[1]) not in pairs:
                        err(f"{aid}: {p_from} -> {p_to} is not a transition of {mid} in persistent_visual_models")
                if states[to].get("entered_by") not in (None, aid):
                    err(f"{aid} enters {to} but {to}.entered_by is {states[to]['entered_by']}")
                if states[frm].get("exited_by") not in (None, aid):
                    err(f"{aid} leaves {frm} but {frm}.exited_by is {states[frm]['exited_by']}")
            dep = a.get("dependency") or {}
            for rel in ("after", "before", "with"):
                for d in dep.get(rel) or []:
                    known(d["action"] if isinstance(d, dict) else d, ("action",), f"{aid}.dependency.{rel}")
            if a.get("model_id") and a["model_id"] not in contract.models:
                err(f"{aid}: model {a['model_id']} is not in persistent_visual_models")
            # v1.2: an action completes when its last timeline operation ends; nothing else is interpreted
            for key in ("completion_state_id", "completion_condition"):
                if key in a:
                    err(f"{aid}: {key} is reserved and unsupported in v1.2 (an action completes when its last timeline operation ends)")
            if a.get("must_execute") is False:
                err(f"{aid}: must_execute false is unsupported in v1.2 (every contract action is required)")
        groups: dict[str, set[str | None]] = {}
        for a in actions.values():
            g = (a.get("dependency") or {}).get("sync_group")
            if g:
                groups.setdefault(g, set()).add(a.get("start_anchor"))
        for g, starts in groups.items():
            if len(starts) > 1:
                err(f"{sid}: actions of sync_group {g} start at different anchors {sorted(s or '-' for s in starts)}")

        for ev in scene.get("events") or []:
            known(ev.get("trigger_anchor"), ("anchor",), f"{ev['event_id']}.trigger_anchor")
            for key in ("precondition_state", "resulting_state"):
                if ev.get(key):
                    known(ev[key], ("state",), f"{ev['event_id']}.{key}")
            for aid in ev.get("actions") or []:
                known(aid, ("action",), f"{ev['event_id']}.actions")

        order_of = {aid: i for i, aid in enumerate(actions)}
        for inv in scene.get("invariants") or []:
            iid = inv["invariant_id"]
            if inv["kind"] == "ORDER":
                for x in inv["order"]:
                    known(x, ("action", "event", "state"), f"{iid}.order")
            for chk in ([inv["target"]] if inv.get("target") else []) + (inv.get("holds") or []):
                if chk["model_id"] not in contract.models:
                    err(f"{iid}: model {chk['model_id']} is not in persistent_visual_models")

        for cc in scene.get("causal_motion_contracts") or []:
            ccid = cc["causal_chain_id"]
            parts = [cc["cause"]] + list(cc.get("intermediate_reactions") or []) + [cc["effect"]]
            positions = []
            for part in parts:
                known(part.get("state_id"), ("state",), f"{ccid} state")
                for aid in part.get("actions") or []:
                    if known(aid, ("action",), f"{ccid} action"):
                        positions.append(order_of.get(aid, -1))
            if positions != sorted(positions):
                err(f"{ccid}: cause, intermediate reactions and effect are not in the scene's action order")
            proof = (cc.get("final_proof_state") or {}).get("state_id")
            known(proof, ("state",), f"{ccid}.final_proof_state")

        lf = scene.get("last_frame_contract") or {}
        if lf:
            known(lf.get("required_state_id"), ("state",), f"{sid}.last_frame_contract.required_state_id")
            for key in ("visible_objects", "hidden_objects", "handoff_objects"):
                for oid in lf.get(key) or []:
                    known(oid, ("object",), f"{sid}.last_frame_contract.{key}")
            for ref in lf.get("persistent_states") or []:
                mid, name = ref.split(".", 1)
                if mid not in contract.models or name not in {n["id"] for n in contract.models[mid].get("named_states") or []}:
                    err(f"{sid}.last_frame_contract: {ref} is not a named state in persistent_visual_models")

        for key, values in (scene.get("must_preserve") or {}).items():
            if key in _NOT_QUALIFIED:
                if key == "persistent_models":
                    for mid in values:
                        if mid not in contract.models:
                            err(f"{sid}.must_preserve.persistent_models: {mid} is not in persistent_visual_models")
                continue
            for cid in values:
                if cid not in contract.index:
                    err(f"{sid}.must_preserve.{key}: {cid} is not an id of this contract")

        # initial state must hold on the model's 41 initial state when the scene enters it
        init = scene.get("initial_state")
        if init in states and contract.is_model_state(init):
            for mid, assertion in contract.state_assertions(init):
                if mid in contract.models and not assertion_holds(assertion, _initial_signature(contract, mid)):
                    first = (contract.models[mid].get("persistence") or {}).get("first_scene")
                    if first in (None, sid):
                        err(f"{sid}: initial_state {init} does not hold on {mid}'s initial state ({assertion})")

        # review (D6): auto would require a review, the scene says not_required
        if (scene.get("qa_contract") or {}).get("review") == "not_required" and auto_review(scene):
            err(f"{sid}: review not_required, but the scene has causal motion / actions / PVM transitions / static_replacement_valid=false")

        # runtime_stack (D10): every locked action, event and state has a layer that realizes it
        if scene.get("importance") == LOCKED:
            covered = set().union(*(set(v) for v in contract.layer_consumes[sid].values())) if contract.layer_consumes[sid] else set()
            model_layers = any(set(v) & set(actions) for v in contract.layer_consumes[sid].values())
            for cid in list(actions) + [e["event_id"] for e in scene.get("events") or []] + list(states):
                if cid in covered:
                    continue
                if contract.kind(cid) == "state" and contract.is_model_state(cid) and model_layers:
                    continue  # a model state is realized by the layer that runs the model
                err(f"{sid}: locked {contract.kind(cid)} {cid} is consumed by no runtime_stack layer (nothing would bind it)")
            for layer, spec in (scene.get("runtime_stack") or {}).items():
                for cid in spec.get("consumes") or []:
                    if contract.scene_of(cid) != sid:
                        err(f"{sid}.runtime_stack.{layer}.consumes: {cid} is not an id of this scene")

    # --- 41 handoffs: cross-scene continuity (to_scene inherits the state) -------------------------
    order = {sid: i for i, sid in enumerate(contract.scenes)}
    for mid, entry in contract.models.items():
        persistence = entry.get("persistence") or {}
        names = {n["id"] for n in entry.get("named_states") or []}
        for handoff in entry.get("handoffs") or []:
            frm, to, state = handoff["from_scene"], handoff["to_scene"], handoff["state"]
            where = f"{mid} handoff {frm} -> {to}"
            if state not in names:
                err(f"{where}: {state} is not a named state of {mid}")
            if frm not in order or to not in order:
                err(f"{where}: {frm if frm not in order else to} is not a scene of this contract")
                continue
            if order[to] <= order[frm]:
                err(f"{where}: to_scene must come after from_scene")
            first, last = persistence.get("first_scene"), persistence.get("last_scene")
            if first in order and order[first] > order[frm]:
                err(f"{where}: persistence.first_scene {first} starts after from_scene")
            if last in order and order[last] < order[to]:
                err(f"{where}: persistence.last_scene {last} ends before to_scene")
            target = contract.scenes[to]
            declared = next((m for m in target.get("models") or [] if m["model_id"] == mid), None)
            if declared is None:
                err(f"{where}: {to} does not declare {mid} in models (VISIBLE, or HIDDEN_BUT_ACTIVE when off screen)")
                continue
            if declared.get("enter_state") not in (None, f"{mid}.{state}"):
                err(f"{where}: {to} enter_state {declared['enter_state']} is not the handed-off {mid}.{state}")
            if declared.get("visibility") == "HIDDEN_BUT_ACTIVE" and persistence.get("survives_hidden") is False:
                err(f"{where}: {to} keeps {mid} HIDDEN_BUT_ACTIVE but persistence.survives_hidden is false")
            init = (contract.obj(target.get("initial_state") or "") or {}).get("pvm_state")
            if init and init.split(".", 1)[0] == mid and init != f"{mid}.{state}":
                err(f"{where}: {to} initial_state is {init}, not the handed-off {mid}.{state}")
    return {"errors": errors, "warnings": warnings}
