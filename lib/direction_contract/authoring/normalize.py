"""Deterministic normalization (director-authoring-guide.md section 8, N1-N12): AuthoringDoc -> 40 dict.

The builder never invents creative content. It qualifies ids, locates anchors, hashes authorities, derives
entered_by/exited_by, action model_id and runtime consumes, expands invariant paths, and maps the human
keys onto the 40 fields in schema order. Anything it cannot decide by rule becomes an AuthoringIssue.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from lib.direction_contract.authority import SCRIPT_SECTIONS_TEXT_V1, canonical_json_sha256, canonical_script_text, script_sha256
from lib.direction_contract.authoring import grammar as g
from lib.direction_contract.authoring.errors import AuthoringIssue
from lib.direction_contract.authoring.graph import find_cycle, scene_edges
from lib.direction_contract.authoring.syntax import AuthoringDoc, Block, Section

LOCAL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
ID_SECTIONS = (("ANCHORS", "anchor", g.RESERVED_ANCHORS), ("SHOW", "object", g.RESERVED_SHOW), ("STATES", "state", None),
               ("ACTIONS", "action", None), ("EVENTS", "event", None), ("BEATS", "beat", None),
               ("INVARIANTS", "invariant", None), ("CAUSAL", "causal_chain", None))
ANY_KIND = ("anchor", "beat", "object", "state", "action", "event", "invariant", "causal_chain")

PRIORITY_POLICY = {"mechanism_over_style": True, "meaning_over_aesthetics": True,
                   "contract_over_runtime_convenience": True, "if_conflict": "preserve_higher_authority"}
APPROVAL_CONSTANTS = {"locked_direction_mutation": False, "semantic_fallback": "requires_new_approval",
                      "causal_contract_change": "requires_new_approval"}
PRESENTATION_ORDER = ("layers", "assets", "source_pixels", "camera", "text", "sound", "readability", "transition_in", "transition_out")
OUTPUT_ORDER = ("expected_media_type", "resolution", "fps", "duration_source", "first_frame_contract", "downstream_consumer")
MECHANISM_COMPATIBILITY = {"style_must_not_reduce_state_visibility": True, "style_must_not_hide_causal_motion": True}


def _put(target: dict[str, Any], key: str, value: Any) -> None:
    """Optional field: absent, None, empty list and empty dict are not written (guide N1-N13 common rule)."""
    if value is None or value == [] or value == {}:
        return
    target[key] = value


class _Ctx:
    def __init__(self, scene: str | None, section: Section | None):
        self.scene, self.section = scene, section

    @property
    def where(self) -> dict[str, Any]:
        return {"scene": self.scene, "section": self.section.name if self.section else None,
                "line": self.section.line if self.section else None}


class Builder:
    def __init__(self, doc: AuthoringDoc, pvm: dict[str, Any], script: dict[str, Any], narration_audio: bytes | None):
        self.doc, self.pvm, self.script, self.narration_audio = doc, pvm, script, narration_audio
        self.issues: list[AuthoringIssue] = []
        self.canonical = canonical_script_text(script)
        self.models = {m["definition"]["id"]: m for m in pvm.get("models") or [] if isinstance(m, dict) and "definition" in m}
        self.scene_ids = [b.id for b in doc.scenes]
        self.index: dict[str, tuple[str, str]] = {}          # qualified id -> (kind, scene)
        self.hints: dict[str, dict[str, Any]] = {}           # Bridge-only routing hints, keyed by qualified id

    # --- issues and typed reads -----------------------------------------------------------------------
    def issue(self, code: str, message: str, ctx: _Ctx | None = None) -> None:
        self.issues.append(AuthoringIssue(code, message, **(ctx.where if ctx else {})))

    def keys(self, data: Any, spec: tuple[set[str], set[str]], ctx: _Ctx, what: str) -> bool:
        if not isinstance(data, dict):
            self.issue("KEY_TYPE", f"{what} must be a mapping", ctx)
            return False
        allowed, required = spec
        for key in data:
            if not isinstance(key, str):
                self.issue("KEY_TYPE", f"{what}: key {key!r} is not a string", ctx)
            elif key in g.UNSUPPORTED_FIELDS:
                self.issue("UNSUPPORTED_FIELD", f"{what}.{key}", ctx)
            elif key in g.SYSTEM_FIELDS:
                self.issue("SYSTEM_FIELD", f"{what}.{key}", ctx)
            elif key not in allowed:
                self.issue("KEY_UNKNOWN", f"{what}.{key}", ctx)
        for key in sorted(required - set(data)):
            self.issue("KEY_REQUIRED", f"{what}.{key}", ctx)
        for key in sorted(k for k in required & set(data) if data[k] is None):
            self.issue("KEY_REQUIRED", f"{what}.{key} is null (a required value must be written)", ctx)
        return True

    def text(self, value: Any, ctx: _Ctx, what: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            self.issue("KEY_TYPE", f"{what} must be text", ctx)
            return None
        return value

    def strings(self, value: Any, ctx: _Ctx, what: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.issue("KEY_TYPE", f"{what} must be a list of text", ctx)
            return []
        return list(value)

    def flag(self, value: Any, ctx: _Ctx, what: str) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            self.issue("KEY_TYPE", f"{what} must be true or false", ctx)
            return None
        return value

    def number(self, value: Any, ctx: _Ctx, what: str) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.issue("KEY_TYPE", f"{what} must be a number", ctx)
            return None
        return value

    def mapping(self, value: Any, ctx: _Ctx, what: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.issue("KEY_TYPE", f"{what} must be a mapping", ctx)
            return {}
        return value

    # --- ids (N1) -------------------------------------------------------------------------------------
    def ref(self, value: Any, kinds: tuple[str, ...], ctx: _Ctx, what: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            self.issue("KEY_TYPE", f"{what} must be an id", ctx)
            return None
        qualified = value if "/" in value else f"{ctx.scene}/{value}"
        hit = self.index.get(qualified)
        if hit is None or hit[0] not in kinds:
            found = f" (it is a {hit[0]})" if hit else ""
            self.issue("REF_UNRESOLVED", f"{what}: {value} is not a {'/'.join(kinds)}{found}", ctx)
            return None
        return qualified

    def refs(self, value: Any, kinds: tuple[str, ...], ctx: _Ctx, what: str) -> list[str]:
        out = [self.ref(v, kinds, ctx, what) for v in self.strings(value, ctx, what)]
        return [v for v in out if v]

    def scene_ref(self, value: Any, ctx: _Ctx, what: str) -> str | None:
        value = self.text(value, ctx, what)
        if value is not None and value not in self.scene_ids:
            self.issue("REF_UNRESOLVED", f"{what}: {value} is not a scene of this document", ctx)
            return None
        return value

    def model_ref(self, value: Any, ctx: _Ctx, what: str) -> str | None:
        value = self.text(value, ctx, what)
        if value is not None and value not in self.models:
            self.issue("REF_UNRESOLVED", f"{what}: model {value} is not in persistent_visual_models", ctx)
            return None
        return value

    def index_ids(self) -> None:
        for block in self.doc.scenes:
            seen: dict[str, str] = {}
            for name, kind, reserved in ID_SECTIONS:
                section = block.sections.get(name)
                if section is None or not isinstance(section.body, dict):
                    continue
                ctx = _Ctx(block.id, section)
                for local in section.body:
                    if local == reserved:
                        continue
                    if not isinstance(local, str) or not LOCAL_ID.match(local):
                        self.issue("ID_INVALID", f"{local!r}", ctx)
                        continue
                    if local in seen:
                        self.issue("ID_DUPLICATE", f"{local} is both a {seen[local]} and a {kind}" if seen[local] != kind
                                   else f"{local} is written twice", ctx)
                        continue
                    seen[local] = kind
                    self.index[f"{block.id}/{local}"] = (kind, block.id)

    # --- document -------------------------------------------------------------------------------------
    def build(self, *, revision: int, generated_at: str | None, lock: dict[str, str] | None) -> dict[str, Any]:
        project = self.project()
        self.index_ids()
        scenes = [self.scene(block) for block in self.doc.scenes]
        lifecycle: dict[str, Any] = {"revision": revision, "status": "LOCKED" if lock else "DRAFT"}
        _put(lifecycle, "generated_at", generated_at)
        if lock:
            lifecycle["locked_by"], lifecycle["locked_at"] = lock["by"], lock["at"]
        doc: dict[str, Any] = {
            "schema_name": "OpenMontage_Visual_Direction",
            "schema_version": "1.2",
            "artifact_role": "CANONICAL_EXECUTION_CONTRACT",
            "artifact_id": f"{project.get('id')}/visual-direction",
            "project_id": project.get("id"),
            "lifecycle": lifecycle,
            "authority": self.authority(project),
            "priority_policy": dict(PRIORITY_POLICY),
        }
        _put(doc, "approval_scope", project.get("approval_scope"))
        _put(doc, "visual_identity", project.get("visual_identity"))
        _put(doc, "viewer_journey", project.get("viewer_journey"))
        doc["scenes"] = scenes
        for scene in scenes:
            cycle = find_cycle(scene_edges(scene)) if scene.get("actions") is not None else None
            if cycle:
                self.issue("GRAPH_CYCLE", " -> ".join(cycle), _Ctx(scene["id"], None))
        return doc

    def project(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        block = self.doc.project
        if block is None:
            return out
        section = block.sections.get("PROJECT")
        if section is None:
            self.issue("KEY_REQUIRED", "[PROJECT] section", _Ctx(None, None))
            return out
        ctx = _Ctx(None, section)
        body = section.body
        if not self.keys(body, g.PROJECT_KEYS, ctx, "PROJECT"):
            return out
        out["id"] = self.text(body.get("id"), ctx, "PROJECT.id")
        out["script"] = self.text(body.get("script"), ctx, "PROJECT.script")
        out["narration"] = self.text(body.get("narration"), ctx, "PROJECT.narration")
        if body.get("approval") is not None:
            out["approval_scope"] = self.approval(body["approval"], ctx, "PROJECT.approval")
        ref = self.text(body.get("visual_identity"), ctx, "PROJECT.visual_identity")
        if ref is not None:
            out["visual_identity"] = {"ref": ref, "mechanism_compatibility": dict(MECHANISM_COMPATIBILITY)}
        journey = block.sections.get("VIEWER JOURNEY")
        if journey is not None:
            jctx = _Ctx(None, journey)
            items = []
            if not isinstance(journey.body, list):
                self.issue("KEY_TYPE", "[VIEWER JOURNEY] must be a list", jctx)
            else:
                for item in journey.body:
                    if not self.keys(item, g.JOURNEY_KEYS, jctx, "VIEWER JOURNEY item"):
                        continue
                    entry = {"id": self.text(item.get("id"), jctx, "id"),
                             "scene_ids": [s for s in (self.scene_ref(v, jctx, "scenes") for v in self.strings(item.get("scenes"), jctx, "scenes")) if s],
                             "viewer_goal": self.text(item.get("goal"), jctx, "goal")}
                    _put(entry, "feeling", self.text(item.get("feeling"), jctx, "feeling"))
                    items.append(entry)
            out["viewer_journey"] = items
        return out

    def approval(self, data: Any, ctx: _Ctx, what: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.keys(data, g.APPROVAL_KEYS, ctx, what):
            for key in ("continue_pipeline", "generated_media", "cost_tools"):
                _put(out, key, self.flag(data.get(key), ctx, f"{what}.{key}"))
        out.update(APPROVAL_CONSTANTS)
        return out

    def authority(self, project: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"script_ref": project.get("script"), "script_sha256": script_sha256(self.script),
                               "canonicalization_id": SCRIPT_SECTIONS_TEXT_V1}
        if project.get("narration") is not None:
            out["narration_ref"] = project["narration"]
            if self.narration_audio is None:
                self.issue("INPUT", "PROJECT.narration is set but no narration audio bytes were given to the Bridge")
            else:
                out["narration_sha256"] = hashlib.sha256(self.narration_audio).hexdigest()
        out["pvm_ref"] = {"artifact": "persistent_visual_models", "sha256": canonical_json_sha256(self.pvm)}
        return out

    # --- scene ----------------------------------------------------------------------------------------
    def scene(self, block: Block) -> dict[str, Any]:
        sid = block.id
        S = block.sections
        head = S.get("SCENE")
        out: dict[str, Any] = {"id": sid}
        if head is None:
            self.issue("KEY_REQUIRED", "[SCENE] section", _Ctx(sid, None))
            return out
        hctx = _Ctx(sid, head)
        importance = None
        if self.keys(head.body, g.SCENE_KEYS, hctx, "SCENE"):
            importance = self.text(head.body.get("importance"), hctx, "importance")
            if importance not in g.ALL:
                self.issue("KEY_TYPE", f"importance must be one of {sorted(g.ALL)}", hctx)
                importance = None
            out["importance"] = importance
            out["role"] = self.text(head.body.get("role"), hctx, "role")
            _put(out, "visual_mode", self.text(head.body.get("mode"), hctx, "mode"))
        if importance is not None:
            for name, section in S.items():
                if importance not in g.SCENE_SECTION_SCOPE[name]:
                    self.issue("PARSE_SECTION_NOT_APPLICABLE", f"[{name}] in a {importance} scene", _Ctx(sid, section))
        locked = importance == g.LOCKED

        def ctx(name: str) -> _Ctx:
            return _Ctx(sid, S.get(name))

        out.update(self.anchors(S.get("ANCHORS"), ctx("ANCHORS")))
        meaning = S.get("MEANING CONTRACT")
        if meaning is None:
            self.issue("KEY_REQUIRED", "[MEANING CONTRACT] section", _Ctx(sid, None))
        elif self.keys(meaning.body, g.MEANING_KEYS, ctx("MEANING CONTRACT"), "MEANING CONTRACT"):
            m = ctx("MEANING CONTRACT")
            contract: dict[str, Any] = {}
            for key in ("before", "change", "after"):
                _put(contract, key, self.text(meaning.body.get(key), m, key))
            out["meaning_contract"] = contract
            _put(out, "viewer_question", self.text(meaning.body.get("question"), m, "question"))
        if S.get("MOTION") is not None:
            out["motion_reason"] = self.motion(S["MOTION"], ctx("MOTION"))
        beats = self.beats(S.get("BEATS"), ctx("BEATS"))
        _put(out, "beats", beats)
        _put(out, "models", self.scene_models(S.get("MODELS"), ctx("MODELS")))
        objects, requirements = self.objects(S.get("SHOW"), ctx("SHOW"))
        _put(out, "objects", objects)
        states, initial = self.states(S.get("STATES"), ctx("STATES"))
        _put(out, "initial_state", initial)
        actions = self.actions(S.get("ACTIONS"), ctx("ACTIONS"), states)
        self.derive_transitions(states, actions)
        _put(out, "states", states)
        _put(out, "actions", actions)
        _put(out, "events", self.events(S.get("EVENTS"), ctx("EVENTS")))
        _put(out, "invariants", self.invariants(S.get("INVARIANTS"), ctx("INVARIANTS")))
        _put(out, "causal_motion_contracts", self.causal(S.get("CAUSAL"), ctx("CAUSAL")))
        if locked:
            out["must_preserve"] = self.preserve(S.get("MUST PRESERVE"), ctx("MUST PRESERVE"))
        for name, key in (("ALLOWED FREEDOM", "allowed_freedom"), ("PROHIBITED SIMPLIFICATION", "prohibited_simplification")):
            section = S.get(name)
            if section is None:
                continue
            values = self.strings(section.body, ctx(name), name)
            if locked:
                out[key] = values          # schema-required for LOCKED, so an empty list stays
            else:
                _put(out, key, values)
        runtime_stack, hint = self.runtime(S.get("RUNTIME"), ctx("RUNTIME"), locked, states, actions, objects)
        _put(out, "runtime_stack", runtime_stack)
        _put(out, "presentation", self.flat(S.get("PRESENTATION"), ctx("PRESENTATION"), g.PRESENTATION_KEYS, "PRESENTATION",
                                            PRESENTATION_ORDER, lists=("layers", "assets")))
        if S.get("LAST FRAME") is not None:
            out["last_frame_contract"] = self.last_frame(S["LAST FRAME"], ctx("LAST FRAME"))
        _put(out, "output_contract", self.flat(S.get("OUTPUT"), ctx("OUTPUT"), g.OUTPUT_KEYS, "OUTPUT", OUTPUT_ORDER, numbers=("fps",)))
        if S.get("FALLBACK") is not None:
            out["fallback_contract"] = self.fallback(S["FALLBACK"], ctx("FALLBACK"))
        if S.get("APPROVAL") is not None:
            out["approval_scope"] = self.approval(S["APPROVAL"].body, ctx("APPROVAL"), "APPROVAL")
        if locked:
            out["qa_contract"] = self.review(S.get("REVIEW"), ctx("REVIEW"))
        _put(out, "requirements", requirements)
        _put(out, "truth_requirements", self.truth(S.get("TRUTH"), ctx("TRUTH")))
        _put(out, "pvm_transitions", self.pvm_transitions(S.get("PVM TRANSITIONS"), ctx("PVM TRANSITIONS")))
        _put(out, "runtime_hint", hint)
        return out

    # --- anchors (N2, N4) -----------------------------------------------------------------------------
    def anchors(self, section: Section | None, ctx: _Ctx) -> dict[str, Any]:
        if section is None:
            self.issue("KEY_REQUIRED", "[ANCHORS] section", ctx)
            return {}
        body = self.mapping(section.body, ctx, "ANCHORS")
        anchors, spans = [], []
        for order, (local, spec) in enumerate(body.items()):
            if local == g.RESERVED_ANCHORS:
                continue
            aid = f"{ctx.scene}/{local}"
            if isinstance(spec, str):
                spec = {"text": spec}
            if not self.keys(spec, g.ANCHOR_KEYS, ctx, f"ANCHORS.{local}"):
                continue
            text = self.text(spec.get("text"), ctx, f"{local}.text")
            if text is None:
                continue
            hits = [i for i in range(len(self.canonical)) if self.canonical.startswith(text, i)]
            if not hits:
                self.issue("ANCHOR_NOT_FOUND", f"{local}: {text!r} is not in the canonical script", ctx)
                continue
            if len(hits) > 1:
                self.issue("ANCHOR_AMBIGUOUS", f"{local}: {text!r} occurs {len(hits)} times in the canonical script", ctx)
                continue
            start = hits[0]
            edge = self.text(spec.get("edge"), ctx, f"{local}.edge")
            if edge is None:
                edge = "START"   # default only when omitted; an explicit value goes to schema validation
            anchor: dict[str, Any] = {"anchor_id": aid}
            _put(anchor, "script_span_id", self.text(spec.get("script_span_id"), ctx, f"{local}.script_span_id"))
            anchor.update({"exact_text": text, "source_span": {"char_start": start, "char_end": start + len(text)}, "edge": edge})
            _put(anchor, "offset_ms", self.number(spec.get("offset_ms"), ctx, f"{local}.offset_ms"))
            anchors.append(anchor)
            spans.append((aid, start, start + len(text), edge, order))
        out: dict[str, Any] = {"anchors": anchors}
        span = body.get(g.RESERVED_ANCHORS)
        if span is not None:
            parts = span.split("..") if isinstance(span, str) else []
            if len(parts) != 2:
                self.issue("KEY_TYPE", "span must look like AN01..AN05", ctx)
            else:
                lo, hi = self.ref(parts[0].strip(), ("anchor",), ctx, "span"), self.ref(parts[1].strip(), ("anchor",), ctx, "span")
                if lo and hi:
                    out["narration_span"] = {"start_anchor": lo, "end_anchor": hi}
        elif spans:
            starts = [s for s in spans if s[3] == "START"] or spans
            ends = [s for s in spans if s[3] == "END"]
            first = min(starts, key=lambda s: (s[1], s[4]))
            last = min(ends, key=lambda s: (-s[2], s[4])) if ends else min(spans, key=lambda s: (-s[1], s[4]))
            out["narration_span"] = {"start_anchor": first[0], "end_anchor": last[0]}
        return out

    # --- simple sections ------------------------------------------------------------------------------
    def flat(self, section: Section | None, ctx: _Ctx, spec: tuple[set[str], set[str]], what: str, order: tuple[str, ...],
             lists: tuple[str, ...] = (), numbers: tuple[str, ...] = ()) -> dict[str, Any]:
        if section is None or not self.keys(section.body, spec, ctx, what):
            return {}
        out: dict[str, Any] = {}
        for key in order:
            if key not in section.body:
                continue
            value = section.body[key]
            if key in lists:
                _put(out, key, self.strings(value, ctx, f"{what}.{key}"))
            elif key in numbers:
                _put(out, key, self.number(value, ctx, f"{what}.{key}"))
            else:
                _put(out, key, self.text(value, ctx, f"{what}.{key}"))
        return out

    def motion(self, section: Section, ctx: _Ctx) -> dict[str, Any]:
        body = section.body
        if not self.keys(body, g.MOTION_KEYS, ctx, "MOTION"):
            return {}
        out: dict[str, Any] = {}
        _put(out, "motion_required", self.flag(body.get("required"), ctx, "required"))
        _put(out, "understanding_dependency", self.text(body.get("dependency"), ctx, "dependency"))
        _put(out, "temporal_logic", self.text(body.get("temporal_logic"), ctx, "temporal_logic"))
        _put(out, "causal_explanation", self.flag(body.get("causal"), ctx, "causal"))
        _put(out, "static_replacement_valid", self.flag(body.get("static_replacement_valid"), ctx, "static_replacement_valid"))
        _put(out, "decorative_motion_allowed", self.flag(body.get("decorative_motion_allowed"), ctx, "decorative_motion_allowed"))
        return out

    def scene_models(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        out = []
        for model_id, spec in self.mapping(section.body if section else None, ctx, "MODELS").items():
            if not self.keys(spec, g.MODEL_KEYS, ctx, f"MODELS.{model_id}"):
                continue
            mid = self.model_ref(model_id, ctx, "MODELS")
            if mid is None:
                continue
            entry: dict[str, Any] = {"model_id": mid}
            enter = self.text(spec.get("enter"), ctx, f"{model_id}.enter")
            _put(entry, "enter_state", f"{mid}.{enter}" if enter else None)
            _put(entry, "visibility", self.text(spec.get("visibility"), ctx, f"{model_id}.visibility"))
            out.append(entry)
        return out

    def objects(self, section: Section | None, ctx: _Ctx) -> tuple[list[dict[str, Any]], list[str]]:
        body = self.mapping(section.body if section else None, ctx, "SHOW")
        out = []
        for local, spec in body.items():
            if local == g.RESERVED_SHOW:
                continue
            if not self.keys(spec, g.OBJECT_KEYS, ctx, f"SHOW.{local}"):
                continue
            oid = f"{ctx.scene}/{local}"
            obj: dict[str, Any] = {"object_id": oid}
            _put(obj, "object_type", self.text(spec.get("type"), ctx, f"{local}.type"))
            obj["semantic_role"] = self.text(spec.get("role"), ctx, f"{local}.role")
            _put(obj, "truth_class", self.text(spec.get("truth"), ctx, f"{local}.truth"))
            model = self.text(spec.get("model"), ctx, f"{local}.model")
            if model is not None:
                parts = model.split(".")
                if len(parts) != 2 or not all(parts):
                    self.issue("KEY_TYPE", f"{local}.model must be <MODEL>.<element>", ctx)
                elif self.model_ref(parts[0], ctx, f"{local}.model"):
                    obj["model_id"], obj["element_id"] = parts
            layer = self.text(spec.get("layer"), ctx, f"{local}.layer")
            if layer is not None and layer not in g.RUNTIME_LAYERS:
                self.issue("KEY_TYPE", f"{local}.layer must be one of {list(g.RUNTIME_LAYERS)}", ctx)
                layer = None
            _put(obj, "layer_id", layer)
            _put(obj, "source_asset", self.text(spec.get("source"), ctx, f"{local}.source"))
            _put(obj, "parent_object", self.ref(spec.get("parent"), ("object",), ctx, f"{local}.parent"))
            _put(obj, "persistence", self.text(spec.get("persistence"), ctx, f"{local}.persistence"))
            necessity: dict[str, Any] = {}
            _put(necessity, "required_for_meaning", self.flag(spec.get("required"), ctx, f"{local}.required"))
            _put(necessity, "removable", self.flag(spec.get("removable"), ctx, f"{local}.removable"))
            _put(obj, "semantic_necessity", necessity)
            out.append(obj)
        requirements = self.strings(body.get(g.RESERVED_SHOW), ctx, "SHOW.requirements")
        return out, requirements

    def assertions_by_model(self, value: Any, ctx: _Ctx, what: str) -> list[dict[str, Any]]:
        out = []
        for model_id, asserts in self.mapping(value, ctx, what).items():
            mid = self.model_ref(model_id, ctx, what)
            if mid is None:
                continue
            if not isinstance(asserts, list) or not asserts or not all(isinstance(a, dict) for a in asserts):
                self.issue("KEY_TYPE", f"{what}.{model_id} must be a non-empty list of assertions", ctx)
                continue
            out.append({"model_id": mid, "assert": asserts})
        return out

    # --- states, actions (N5, N6) ---------------------------------------------------------------------
    def states(self, section: Section | None, ctx: _Ctx) -> tuple[list[dict[str, Any]], str | None]:
        out, initial = [], []
        for local, spec in self.mapping(section.body if section else None, ctx, "STATES").items():
            if not self.keys(spec, g.STATE_KEYS, ctx, f"STATES.{local}"):
                continue
            stid = f"{ctx.scene}/{local}"
            st: dict[str, Any] = {"state_id": stid, "semantic_meaning": self.text(spec.get("meaning"), ctx, f"{local}.meaning")}
            _put(st, "pvm_state", self.text(spec.get("pvm"), ctx, f"{local}.pvm"))
            _put(st, "object_states", self.assertions_by_model(spec.get("also"), ctx, f"{local}.also"))
            _put(st, "invariants", self.refs(spec.get("invariants"), ("invariant",), ctx, f"{local}.invariants"))
            if self.flag(spec.get("bookkeeping"), ctx, f"{local}.bookkeeping"):
                st["must_be_visible"] = False
            _put(st, "valid_until", self.ref(spec.get("until"), ("action", "anchor"), ctx, f"{local}.until"))
            _put(st, "visible_objects", self.refs(spec.get("visible"), ("object",), ctx, f"{local}.visible"))
            if self.flag(spec.get("initial"), ctx, f"{local}.initial"):
                initial.append(stid)
            out.append(st)
        if section is not None and len(initial) != 1:
            self.issue("INITIAL_STATE", f"{len(initial)} states are marked initial", ctx)
        return out, initial[0] if len(initial) == 1 else None

    def actions(self, section: Section | None, ctx: _Ctx, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pvm_of = {s["state_id"]: s.get("pvm_state") for s in states}
        out = []
        for local, spec in self.mapping(section.body if section else None, ctx, "ACTIONS").items():
            if not self.keys(spec, g.ACTION_KEYS, ctx, f"ACTIONS.{local}"):
                continue
            aid = f"{ctx.scene}/{local}"
            frm = self.ref(spec.get("from"), ("state",), ctx, f"{local}.from")
            to = self.ref(spec.get("to"), ("state",), ctx, f"{local}.to")
            model = self.model_ref(spec.get("model"), ctx, f"{local}.model")
            if model is None and spec.get("model") is None:
                a, b = pvm_of.get(frm), pvm_of.get(to)
                if a and b and a.split(".")[0] == b.split(".")[0]:
                    model = a.split(".")[0]          # N6
            act: dict[str, Any] = {"action_id": aid, "semantic_role": self.text(spec.get("role"), ctx, f"{local}.role")}
            _put(act, "action_type", self.text(spec.get("type"), ctx, f"{local}.type"))
            _put(act, "model_id", model)
            act["target_objects"] = self.refs(spec.get("targets"), ("object",), ctx, f"{local}.targets")
            act["start_anchor"] = self.ref(spec.get("at"), ("anchor",), ctx, f"{local}.at")
            _put(act, "end_anchor", self.ref(spec.get("until"), ("anchor",), ctx, f"{local}.until"))
            act["from_state_id"], act["to_state_id"] = frm, to
            _put(act, "path", self.text(spec.get("path"), ctx, f"{local}.path"))
            _put(act, "easing", self.text(spec.get("easing"), ctx, f"{local}.easing"))
            dep: dict[str, Any] = {}
            after = []
            for other, on in self.mapping(spec.get("after"), ctx, f"{local}.after").items():
                ref = self.ref(other, ("action",), ctx, f"{local}.after")
                if on not in ("start", "complete"):
                    self.issue("KEY_TYPE", f"{local}.after.{other} must be start or complete", ctx)
                elif ref:
                    after.append({"action": ref, "on": on})
            _put(dep, "after", after)
            _put(dep, "before", self.refs(spec.get("before"), ("action",), ctx, f"{local}.before"))
            _put(dep, "with", self.refs(spec.get("with"), ("action",), ctx, f"{local}.with"))
            _put(dep, "wait_until", self.ref(spec.get("wait_until"), ("state",), ctx, f"{local}.wait_until"))
            sync = self.text(spec.get("sync"), ctx, f"{local}.sync")
            _put(dep, "sync_group", f"{ctx.scene}/{sync}" if sync else None)
            _put(act, "dependency", dep)
            _put(act, "min_duration_seconds", self.number(spec.get("min_seconds"), ctx, f"{local}.min_seconds"))
            _put(act, "implementation_freedom", self.strings(spec.get("freedom"), ctx, f"{local}.freedom"))
            layers = self.strings(spec.get("layers"), ctx, f"{local}.layers")
            if "layers" in spec and not layers:
                self.issue("KEY_TYPE", f"{local}.layers must list at least one runtime layer (leave it out for the default routing)", ctx)
            for layer in layers:
                if layer not in g.RUNTIME_LAYERS:
                    self.issue("KEY_TYPE", f"{local}.layers: {layer} is not a runtime layer", ctx)
            if spec.get("layers") is not None:
                self.hints[aid] = {"layers": layers}     # Bridge routing hint, never written to 40
            out.append(act)
        return out

    @staticmethod
    def derive_transitions(states: list[dict[str, Any]], actions: list[dict[str, Any]]) -> None:
        """N5: entered_by / exited_by when exactly one action enters / leaves the state."""
        for st in states:
            sid = st["state_id"]
            entering = [a["action_id"] for a in actions if a.get("to_state_id") == sid]
            leaving = [a["action_id"] for a in actions if a.get("from_state_id") == sid]
            derived = {}
            if len(entering) == 1:
                derived["entered_by"] = entering[0]
            if len(leaving) == 1:
                derived["exited_by"] = leaving[0]
            if derived:   # keep schema field order: ... invariants, entered_by, exited_by, must_be_visible ...
                rebuilt: dict[str, Any] = {}
                for key in ("state_id", "semantic_meaning", "pvm_state", "object_states", "invariants"):
                    if key in st:
                        rebuilt[key] = st[key]
                rebuilt.update(derived)
                for key in ("must_be_visible", "valid_until", "visible_objects"):
                    if key in st:
                        rebuilt[key] = st[key]
                st.clear()
                st.update(rebuilt)

    def events(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        out = []
        for local, spec in self.mapping(section.body if section else None, ctx, "EVENTS").items():
            if not self.keys(spec, g.EVENT_KEYS, ctx, f"EVENTS.{local}"):
                continue
            ev: dict[str, Any] = {"event_id": f"{ctx.scene}/{local}",
                                  "trigger_anchor": self.ref(spec.get("on"), ("anchor",), ctx, f"{local}.on")}
            _put(ev, "precondition_state", self.ref(spec.get("from"), ("state",), ctx, f"{local}.from"))
            ev["actions"] = self.refs(spec.get("do"), ("action",), ctx, f"{local}.do")
            ev["resulting_state"] = self.ref(spec.get("to"), ("state",), ctx, f"{local}.to")
            _put(ev, "next_event_dependency", self.ref(spec.get("next"), ("event",), ctx, f"{local}.next"))
            out.append(ev)
        return out

    def beats(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        out = []
        for local, spec in self.mapping(section.body if section else None, ctx, "BEATS").items():
            if not self.keys(spec, g.BEAT_KEYS, ctx, f"BEATS.{local}"):
                continue
            beat: dict[str, Any] = {"beat_id": f"{ctx.scene}/{local}", "anchor": self.ref(spec.get("at"), ("anchor",), ctx, f"{local}.at")}
            _put(beat, "narrative_function", self.text(spec.get("function"), ctx, f"{local}.function"))
            _put(beat, "meaning_before", self.text(spec.get("meaning_before"), ctx, f"{local}.meaning_before"))
            _put(beat, "new_information", self.text(spec.get("new"), ctx, f"{local}.new"))
            _put(beat, "meaning_after", self.text(spec.get("meaning_after"), ctx, f"{local}.meaning_after"))
            _put(beat, "visual_state_before", self.ref(spec.get("before"), ("state",), ctx, f"{local}.before"))
            _put(beat, "required_change", self.text(spec.get("change"), ctx, f"{local}.change"))
            _put(beat, "visual_state_after", self.ref(spec.get("after"), ("state",), ctx, f"{local}.after"))
            _put(beat, "linked_actions", self.refs(spec.get("actions"), ("action",), ctx, f"{local}.actions"))
            out.append(beat)
        return out

    # --- invariants (N7) ------------------------------------------------------------------------------
    def expand_path(self, model_id: str, path: str) -> str:
        definition = (self.models.get(model_id) or {}).get("definition") or {}
        if definition.get("type") == "timeline_rail":
            return path                       # rail models use their full signature paths
        parts = path.split(".")
        if parts[0] in g.ELEMENT_ROOTS or len(parts) != 2:
            return path
        element, attr = parts
        return f"elements.{element}.visible" if attr == "visible" else f"elements.{element}.attrs.{attr}"

    def invariants(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        out = []
        for local, spec in self.mapping(section.body if section else None, ctx, "INVARIANTS").items():
            if not self.keys(spec, g.INVARIANT_KEYS, ctx, f"INVARIANTS.{local}"):
                continue
            forms = [k for k in ("constant", "holds", "order") if k in spec]
            if len(forms) != 1:
                self.issue("KEY_REQUIRED", f"{local}: write exactly one of constant / holds / order", ctx)
                continue
            inv: dict[str, Any] = {"invariant_id": f"{ctx.scene}/{local}"}
            _put(inv, "description", self.text(spec.get("description"), ctx, f"{local}.description"))
            form = forms[0]
            if form == "constant":
                inv["kind"] = "CONSTANT"
                how = spec.get("constant")
                model = self.model_ref(spec.get("model"), ctx, f"{local}.model")
                if spec.get("model") is None:
                    self.issue("KEY_REQUIRED", f"{local}.model", ctx)
                if how not in g.CONSTANT_FORMS:
                    self.issue("KEY_TYPE", f"{local}.constant must be one of {list(g.CONSTANT_FORMS)}", ctx)
                elif model:
                    if how == "value":
                        path = self.text(spec.get("path"), ctx, f"{local}.path")
                        if path is None or "paths" in spec:
                            self.issue("KEY_REQUIRED", f"{local}: constant: value takes one path", ctx)
                        else:
                            inv["target"] = {"model_id": model, "path": self.expand_path(model, path)}
                    else:
                        paths = self.strings(spec.get("paths"), ctx, f"{local}.paths")
                        if not paths or "path" in spec:
                            self.issue("KEY_REQUIRED", f"{local}: constant: {how} takes paths", ctx)
                        else:
                            inv["target"] = {"model_id": model, "aggregate": how, "paths": [self.expand_path(model, p) for p in paths]}
                _put(inv, "value", self.number(spec.get("value"), ctx, f"{local}.value"))
                _put(inv, "tolerance", self.number(spec.get("tolerance"), ctx, f"{local}.tolerance"))
            elif form == "holds":
                inv["kind"] = "ASSERT"
                for key in ("path", "paths", "model", "value"):
                    if key in spec:
                        self.issue("KEY_UNKNOWN", f"{local}.{key} (holds takes assertions per model)", ctx)
                inv["holds"] = self.assertions_by_model(spec.get("holds"), ctx, f"{local}.holds")
            else:
                inv["kind"] = "ORDER"
                for key in ("path", "paths", "model", "value", "tolerance"):
                    if key in spec:
                        self.issue("KEY_UNKNOWN", f"{local}.{key} (order takes ids only)", ctx)
                inv["order"] = self.refs(spec.get("order"), ("action", "event", "state"), ctx, f"{local}.order")
            during = spec.get("during")
            if during is not None:
                if during == "scene":
                    inv["during"] = "scene"
                elif isinstance(during, dict) and set(during) == {"from", "to"}:
                    ends = {}
                    for key in ("from", "to"):
                        ref = self.ref(during[key], ANY_KIND, ctx, f"{local}.during.{key}")
                        if ref and self.index[ref][0] != "state":
                            self.issue("DURING_NOT_STATE", f"{local}.during.{key}: {during[key]} is a {self.index[ref][0]}", ctx)
                        elif ref:
                            ends[key] = ref
                    if len(ends) == 2:
                        inv["during"] = ends
                else:
                    self.issue("KEY_TYPE", f"{local}.during must be 'scene' or {{from: <state>, to: <state>}}", ctx)
            out.append(inv)
        return out

    def causal(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        out = []
        for local, spec in self.mapping(section.body if section else None, ctx, "CAUSAL").items():
            if not self.keys(spec, g.CAUSAL_KEYS, ctx, f"CAUSAL.{local}"):
                continue

            def link(data: Any, what: str) -> dict[str, Any] | None:
                if not self.keys(data, g.LINK_KEYS, ctx, what):
                    return None
                item: dict[str, Any] = {"state_id": self.ref(data.get("state"), ("state",), ctx, f"{what}.state")}
                _put(item, "objects", self.refs(data.get("objects"), ("object",), ctx, f"{what}.objects"))
                item["actions"] = self.refs(data.get("actions"), ("action",), ctx, f"{what}.actions")
                _put(item, "narration_anchor", self.ref(data.get("anchor"), ("anchor",), ctx, f"{what}.anchor"))
                _put(item, "required", self.flag(data.get("required"), ctx, f"{what}.required"))
                return item

            cc: dict[str, Any] = {"causal_chain_id": f"{ctx.scene}/{local}",
                                  "proposition": self.text(spec.get("proposition"), ctx, f"{local}.proposition"),
                                  "cause": link(spec.get("cause"), f"{local}.cause")}
            through = spec.get("through")
            if not isinstance(through, list):
                self.issue("KEY_TYPE", f"{local}.through must be a list", ctx)
                through = []
            cc["intermediate_reactions"] = [x for x in (link(t, f"{local}.through") for t in through) if x]
            cc["effect"] = link(spec.get("effect"), f"{local}.effect")
            deps = spec.get("dependencies")
            if deps is not None and self.keys(deps, g.CAUSAL_DEPENDENCY_KEYS, ctx, f"{local}.dependencies"):
                d: dict[str, Any] = {}
                for key in ("effect_after_cause", "intermediate_required"):
                    _put(d, key, self.flag(deps.get(key), ctx, f"{local}.dependencies.{key}"))
                _put(cc, "dependencies", d)
            vis = spec.get("visibility")
            if vis is not None and self.keys(vis, g.CAUSAL_VISIBILITY_KEYS, ctx, f"{local}.visibility"):
                v: dict[str, Any] = {}
                for key in ("cause_visible", "intermediate_visible", "effect_visible"):
                    _put(v, key, self.flag(vis.get(key), ctx, f"{local}.visibility.{key}"))
                _put(cc, "visibility", v)
            proof = spec.get("proof")
            if self.keys(proof, g.PROOF_KEYS, ctx, f"{local}.proof"):
                p: dict[str, Any] = {"state_id": self.ref(proof.get("state"), ("state",), ctx, f"{local}.proof.state")}
                _put(p, "viewer_can_observe", self.strings(proof.get("observe"), ctx, f"{local}.proof.observe"))
                cc["final_proof_state"] = p
            _put(cc, "prohibited_simplification", self.strings(spec.get("prohibit"), ctx, f"{local}.prohibit"))
            out.append(cc)
        return out

    # --- preservation, last frame, runtime, review ----------------------------------------------------
    def preserve(self, section: Section | None, ctx: _Ctx) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if section is None:
            return out
        body = section.body
        if isinstance(body, dict):
            for key in g.PRESERVE_CORE & set(body):
                self.issue("SYSTEM_FIELD", f"MUST PRESERVE.{key}: the LOCKED core (states/actions/invariants) is derived (D1)", ctx)
            body = {k: v for k, v in body.items() if k not in g.PRESERVE_CORE}
        if not self.keys(body, g.PRESERVE_KEYS, ctx, "MUST PRESERVE"):
            return out
        _put(out, "beats", self.refs(body.get("beats"), ("beat",), ctx, "beats"))
        _put(out, "objects", self.refs(body.get("objects"), ("object",), ctx, "objects"))
        _put(out, "events", self.refs(body.get("events"), ("event",), ctx, "events"))
        _put(out, "causal_chains", self.refs(body.get("causal_chains"), ("causal_chain",), ctx, "causal_chains"))
        _put(out, "ordering", self.refs(body.get("ordering"), ANY_KIND, ctx, "ordering"))
        _put(out, "narration_anchors", self.refs(body.get("anchors"), ("anchor",), ctx, "anchors"))
        _put(out, "persistent_models", [m for m in (self.model_ref(v, ctx, "models") for v in self.strings(body.get("models"), ctx, "models")) if m])
        _put(out, "last_frame_elements", self.refs(body.get("last_frame"), ("object",), ctx, "last_frame"))
        _put(out, "cross_scene", [s for s in (self.scene_ref(v, ctx, "cross_scene") for v in self.strings(body.get("cross_scene"), ctx, "cross_scene")) if s])
        return out

    def last_frame(self, section: Section, ctx: _Ctx) -> dict[str, Any]:
        body = section.body
        if not self.keys(body, g.LAST_FRAME_KEYS, ctx, "LAST FRAME"):
            return {}
        out: dict[str, Any] = {"required_state_id": self.ref(body.get("state"), ("state",), ctx, "state")}
        _put(out, "end_anchor", self.ref(body.get("end"), ("anchor",), ctx, "end"))
        _put(out, "visible_objects", self.refs(body.get("visible"), ("object",), ctx, "visible"))
        _put(out, "hidden_objects", self.refs(body.get("hidden"), ("object",), ctx, "hidden"))
        _put(out, "object_states", self.assertions_by_model(body.get("also"), ctx, "also"))
        _put(out, "persistent_states", self.strings(body.get("models"), ctx, "models"))
        _put(out, "visible_text", self.strings(body.get("text"), ctx, "text"))
        _put(out, "camera_state", self.text(body.get("camera"), ctx, "camera"))
        _put(out, "motion_state", self.text(body.get("motion"), ctx, "motion"))
        _put(out, "minimum_hold_seconds", self.number(body.get("hold_seconds"), ctx, "hold_seconds"))
        _put(out, "handoff_objects", self.refs(body.get("handoff_objects"), ("object",), ctx, "handoff_objects"))
        _put(out, "handoff_to_scene", self.scene_ref(body.get("next_scene"), ctx, "next_scene"))
        _put(out, "next_scene_seed", self.text(body.get("next_scene_seed"), ctx, "next_scene_seed"))
        return out

    def runtime(self, section: Section | None, ctx: _Ctx, locked: bool, states: list[dict[str, Any]],
                actions: list[dict[str, Any]], objects: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
        """Layers as written, plus N9 consumes for LOCKED scenes (default routing or a Bridge hint)."""
        body = self.mapping(section.body if section else None, ctx, "RUNTIME")
        hint = self.text(body.get(g.RESERVED_RUNTIME), ctx, "RUNTIME.hint")
        declared: dict[str, dict[str, Any]] = {}
        for layer, spec in body.items():
            if layer == g.RESERVED_RUNTIME:
                continue
            if layer not in g.RUNTIME_LAYERS:
                self.issue("KEY_UNKNOWN", f"RUNTIME.{layer} is not a runtime layer", ctx)
                continue
            if not self.keys(spec, g.LAYER_KEYS, ctx, f"RUNTIME.{layer}"):
                continue
            entry: dict[str, Any] = {"runtime": self.text(spec.get("runtime"), ctx, f"{layer}.runtime")}
            _put(entry, "purpose", self.text(spec.get("purpose"), ctx, f"{layer}.purpose"))
            declared[layer] = entry
        if not locked:
            return declared, hint
        consumes: dict[str, list[str]] = {}

        def route(cid: str, layers: list[str]) -> None:
            for layer in layers:
                if layer not in declared:
                    self.issue("ROUTING_LAYER_MISSING", f"{cid} is routed to {layer}, which [RUNTIME] does not declare", ctx)
                    continue
                if cid not in consumes.setdefault(layer, []):
                    consumes[layer].append(cid)

        for act in actions:
            hint_layers = (self.hints.get(act["action_id"]) or {}).get("layers")
            if hint_layers:
                route(act["action_id"], hint_layers)
            elif act.get("model_id"):
                route(act["action_id"], ["deterministic_graphics"])
            else:
                self.issue("ROUTING_UNKNOWN", f"{act['action_id']} has no model and no layers", ctx)
        by_id = {o["object_id"]: o for o in objects}
        for st in states:
            if st.get("pvm_state") or st.get("object_states"):
                continue   # model states are realized by the layer that runs the model's actions
            layers: list[str] = []
            for oid in st.get("visible_objects") or []:
                obj = by_id.get(oid) or {}
                layer = obj.get("layer_id") or ("factual_source" if obj.get("truth_class") == "SOURCE" or obj.get("source_asset") else "base_visual")
                if layer not in layers:
                    layers.append(layer)
            route(st["state_id"], layers)
        for layer, entry in declared.items():
            _put(entry, "consumes", consumes.get(layer))
        return declared, hint

    def fallback(self, section: Section, ctx: _Ctx) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.keys(section.body, g.FALLBACK_KEYS, ctx, "FALLBACK"):
            _put(out, "allowed_fallbacks", self.strings(section.body.get("allowed"), ctx, "allowed"))
        out["on_failure"] = "DIRECTION_DEVIATION"
        return out

    def review(self, section: Section | None, ctx: _Ctx) -> dict[str, Any]:
        out: dict[str, Any] = {"review": "auto"}
        if section is None or not self.keys(section.body, g.REVIEW_KEYS, ctx, "REVIEW"):
            return out
        body = section.body
        review = self.text(body.get("review"), ctx, "review")
        out["review"] = "auto" if review is None else review   # explicit values go to schema validation
        _put(out, "review_questions", self.strings(body.get("questions"), ctx, "questions"))
        _put(out, "evidence_states", self.refs(body.get("evidence_states"), ("state",), ctx, "evidence_states"))
        return out

    def truth(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        if section is None:
            return []
        if not isinstance(section.body, list):
            self.issue("KEY_TYPE", "[TRUTH] must be a list", ctx)
            return []
        out = []
        for item in section.body:
            if not self.keys(item, g.TRUTH_KEYS, ctx, "TRUTH item"):
                continue
            entry: dict[str, Any] = {"statement": self.text(item.get("statement"), ctx, "statement"),
                                     "truth_class": self.text(item.get("truth"), ctx, "truth")}
            _put(entry, "source", self.text(item.get("source"), ctx, "source"))
            out.append(entry)
        return out

    def pvm_transitions(self, section: Section | None, ctx: _Ctx) -> list[dict[str, Any]]:
        if section is None:
            return []
        if not isinstance(section.body, list):
            self.issue("KEY_TYPE", "[PVM TRANSITIONS] must be a list", ctx)
            return []
        out = []
        for item in section.body:
            if not self.keys(item, g.PVM_TRANSITION_KEYS, ctx, "PVM TRANSITIONS item"):
                continue
            mid = self.model_ref(item.get("model"), ctx, "model")
            if mid is None:
                continue
            entry: dict[str, Any] = {"model_id": mid}
            frm = self.text(item.get("from"), ctx, "from")
            _put(entry, "from", f"{mid}.{frm}" if frm else None)
            entry["to"] = f"{mid}.{self.text(item.get('to'), ctx, 'to')}"
            out.append(entry)
        return out
