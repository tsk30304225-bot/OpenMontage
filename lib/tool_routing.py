"""Capability-based tool routing.

Responsibilities are split the same way as the visual-direction contract:

- ``scene_plan.scenes[].visual_need`` — WHAT a scene needs, in tool-agnostic
  dimensions (reality, information_precision, ...). The scene director never
  names a tool.
- ``tool_plan`` (this module) — WHAT WITH: which verified tool offer fills each
  need, per scene / beat / track, with the rejected candidates and the reason.
- ``visual_direction`` / ``visual_timeline`` — WHAT changes and WHEN.
- atelier / templated composition — HOW it looks.

A tool takes part in routing only through ``BaseTool.route_offers``. The
selector-facing ``capability`` string is left alone: selectors discover
providers by it (e.g. ``pexels_video`` is ``video_generation`` so that
``video_selector`` can reach stock footage), so it cannot double as a routing
axis.

An offer is a routing candidate only when it is **routable**: its metadata is
complete and this machine holds evidence that it produces valid output
(``OUTPUT_VERIFIED`` or better). Evidence is machine-local and never committed.

This module only depends on the standard library; registry access is passed in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

# What a tool can be picked for. Independent of the selector `capability`.
CAPABILITY_AXES = (
    "reality_footage",      # real-world moving footage (stock / archive)
    "reality_still",        # real-world photographs
    "structured_graphics",  # precise information: numbers, labels, diagrams
    "expressive_motion",    # motion that carries meaning: kinetic type, reveals, transitions
    "synthetic_image",      # images of things that cannot be photographed
    "synthetic_video",      # footage of things that cannot be filmed
    "narration",            # spoken voice track
    "alignment",            # word-level timing of the narration
    "caption",              # on-screen narration captions
    "music",                # music bed
    "sfx",                  # sound accents
)

# Where an offer naturally applies.
SCOPES = ("project", "section", "scene", "beat", "track", "asset")

# Scene needs (tool-agnostic) -> the axes that can fill them, in preference
# order, the layer role the selection fills, and whether the need is routed
# once per project (track) or per scene.
NEEDS: dict[str, dict[str, Any]] = {
    "reality":               {"axes": ("reality_footage", "reality_still"), "role": "visual_source", "track": False},
    "impossible_visual":     {"axes": ("synthetic_video", "synthetic_image"), "role": "visual_source", "track": False},
    "information_precision": {"axes": ("structured_graphics",), "role": "base_composition", "track": False},
    "motion_expressiveness": {"axes": ("expressive_motion",), "role": "emphasis_overlay", "track": False},
    "rhythm_accent":         {"axes": ("sfx",), "role": "sound", "track": False},
    "narration":             {"axes": ("narration",), "role": "narration", "track": True},
    "word_sync":             {"axes": ("alignment",), "role": "sync", "track": True},
    "captions":              {"axes": ("caption",), "role": "captions", "track": True},
    "mood":                  {"axes": ("music",), "role": "music", "track": True},
}

NEED_LEVELS = {"none": 0, "low": 1, "medium": 2, "high": 3}
ROUTE_THRESHOLD = NEED_LEVELS["medium"]

# Scene cue vocabulary an offer can declare as a positive trigger.
CUES = (
    "location", "human_activity", "physical_object", "infrastructure", "nature",
    "data_value", "comparison", "process", "diagram", "timeline_axis", "label",
    "kinetic_text", "major_reveal", "chapter_transition", "metaphor",
    "not_filmable", "abstract_concept", "spoken_words", "impact", "ui_feedback",
    "emotional_shift",
)

COST_TIERS = ("free", "subscription", "paid")
COST_PENALTY = {"free": 0, "subscription": 2, "paid": 4}

# Evidence ladder (ordered). ROUTABLE is reported separately as a flag: an offer
# can be routable from OUTPUT_VERIFIED on, otherwise a tool that has never been
# used in production (the HyperFrames case) could never enter routing at all.
LEVELS = ("DISCOVERED", "AVAILABLE", "SMOKE_TESTED", "OUTPUT_VERIFIED", "PRODUCTION_VERIFIED")
ROUTABLE_FLOOR = "OUTPUT_VERIFIED"
LEVEL_BONUS = {"OUTPUT_VERIFIED": 1, "PRODUCTION_VERIFIED": 3}

EVIDENCE_MAX_AGE_DAYS = 30


def level_rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


# ---------------------------------------------------------------------------
# Route offers (declared on tools)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteOffer:
    """One thing a tool can be routed for.

    ``strengths`` scores the offer 1-5 against need dimensions (default 3).
    ``runtime`` names the composition runtime the layer needs ("remotion",
    "hyperframes"); the router refuses it unless that runtime was approved at
    proposal. ``fallback`` lists other offer ids to try when this one is not
    routable.
    """

    id: str
    axes: tuple[str, ...]
    scopes: tuple[str, ...]
    triggers: tuple[str, ...] = ()
    strengths: dict[str, int] = field(default_factory=dict)
    fallback: tuple[str, ...] = ()
    runtime: Optional[str] = None
    cost_tier: str = "free"
    authoring: str = "low"
    notes: str = ""

    def problems(self) -> list[str]:
        """Metadata problems that keep the offer out of routing."""
        out: list[str] = []
        if not self.id:
            out.append("missing id")
        if not self.axes:
            out.append("no capability axes")
        out += [f"unknown axis {a!r}" for a in self.axes if a not in CAPABILITY_AXES]
        if not self.scopes:
            out.append("no scopes")
        out += [f"unknown scope {s!r}" for s in self.scopes if s not in SCOPES]
        if not self.triggers:
            out.append("no positive triggers")
        out += [f"unknown trigger {t!r}" for t in self.triggers if t not in CUES]
        out += [f"unknown strength dimension {k!r}" for k in self.strengths if k not in NEEDS]
        out += [f"strength {k}={v} outside 1-5" for k, v in self.strengths.items() if not 1 <= int(v) <= 5]
        if self.cost_tier not in COST_TIERS:
            out.append(f"unknown cost tier {self.cost_tier!r}")
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RouteOffer":
        return cls(
            id=str(d.get("id", "")),
            axes=tuple(d.get("axes", ())),
            scopes=tuple(d.get("scopes", ())),
            triggers=tuple(d.get("triggers", ())),
            strengths={k: int(v) for k, v in (d.get("strengths") or {}).items()},
            fallback=tuple(d.get("fallback", ())),
            runtime=d.get("runtime"),
            cost_tier=d.get("cost_tier", "free"),
            authoring=d.get("authoring", "low"),
            notes=d.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "axes": list(self.axes),
            "scopes": list(self.scopes),
            "triggers": list(self.triggers),
            "strengths": dict(self.strengths),
            "fallback": list(self.fallback),
            "runtime": self.runtime,
            "cost_tier": self.cost_tier,
            "authoring": self.authoring,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def audit_dir() -> Path:
    """Machine-level audit directory, outside every checkout.

    Evidence describes the machine (keys, GPU, installed runtimes), not a
    checkout, so every worktree reads the same audit and nothing machine-specific
    can be committed to the public repo.
    """
    override = os.environ.get("OPENMONTAGE_TOOL_AUDIT_DIR")
    return Path(override) if override else Path.home() / ".openmontage" / "tool_audit"


def load_local_offers(root: Path) -> dict[str, list[tuple[RouteOffer, dict[str, Any]]]]:
    """Offers for machine-local tools that are not in the repo (``local_offers.json``).

    Format: ``{"<tool name>": [{<RouteOffer fields>, "smoke": {"inputs": {...},
    "key": "execute", "artifact_key": "output"}}]}``. ``{workdir}`` in smoke
    input strings is replaced with the offer's smoke directory.
    """
    path = root / "local_offers.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        tool: [(RouteOffer.from_dict(entry), dict(entry.get("smoke") or {})) for entry in entries]
        for tool, entries in raw.items()
        if not tool.startswith("//")
    }


def _fill_workdir(value: Any, workdir: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{workdir}", str(workdir))
    if isinstance(value, dict):
        return {k: _fill_workdir(v, workdir) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_workdir(v, workdir) for v in value]
    return value


def _evidence_path(root: Path, tool: str, offer: str) -> Path:
    return root / "evidence" / f"{tool}__{offer}.json"


def probe_artifact(path: str | os.PathLike | None) -> dict[str, Any]:
    """Minimal validity probe for a smoke artifact.

    Media files must be readable by ffprobe with a positive duration or real
    dimensions; JSON must parse; anything else must be non-empty.
    """
    if not path:
        return {"ok": False, "reason": "no artifact"}
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return {"ok": False, "reason": f"artifact missing or empty: {p.name}"}
    suffix = p.suffix.lower()
    if suffix == ".json":
        try:
            json.loads(p.read_text(encoding="utf-8"))
            return {"ok": True, "kind": "json", "bytes": p.stat().st_size}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": f"invalid json: {exc}"}
    media = {".mp4", ".mov", ".webm", ".mkv", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
             ".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if suffix not in media:
        return {"ok": True, "kind": "file", "bytes": p.stat().st_size}
    if not shutil.which("ffprobe"):
        return {"ok": False, "reason": "ffprobe not available to verify media"}
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
         "-of", "json", str(p)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if proc.returncode != 0:
        return {"ok": False, "reason": f"ffprobe failed: {proc.stderr.strip()[:200]}"}
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    duration = info.get("format", {}).get("duration")
    dims = [(s.get("width"), s.get("height")) for s in streams if s.get("width")]
    ok = bool(dims) or (duration not in (None, "N/A") and float(duration) > 0)
    return {
        "ok": ok,
        "kind": "media",
        "duration_seconds": float(duration) if duration not in (None, "N/A") else None,
        "dimensions": list(dims[0]) if dims else None,
        "reason": None if ok else "no duration and no video dimensions",
    }


def production_successes(tool: str, projects_roots: Iterable[Path]) -> int:
    """Successful real-project calls of ``tool`` recorded in Backlot events."""
    count = 0
    for root in projects_roots:
        if not root.is_dir():
            continue
        for events in root.glob("*/events.jsonl"):
            try:
                lines = events.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line in lines:
                if f'"{tool}"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("tool") == tool and ev.get("event") == "finish" and ev.get("success") is True:
                    count += 1
    return count


def load_evidence(root: Path, tool: str, offer: str, version: str) -> Optional[dict[str, Any]]:
    path = _evidence_path(root, tool, offer)
    if not path.is_file():
        return None
    try:
        ev = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if ev.get("tool_version") != version:
        return None
    if time.time() - float(ev.get("checked_at", 0)) > EVIDENCE_MAX_AGE_DAYS * 86400:
        return None
    return ev


def write_evidence(root: Path, tool: str, offer: str, record: dict[str, Any]) -> Path:
    path = _evidence_path(root, tool, offer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit_tools(
    tools: Iterable[Any],
    *,
    run_smoke: bool = False,
    allow_cost_tiers: Iterable[str] = ("free",),
    only: Optional[Iterable[str]] = None,
    projects_roots: Optional[Iterable[Path]] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Classify every route offer on the evidence ladder.

    ``tools`` are BaseTool instances (normally ``registry._tools.values()``).
    Smoke calls run only when ``run_smoke`` is set, only for offers whose cost
    tier is in ``allow_cost_tiers`` (default: free), and only for ``only`` tool
    names when given. Nothing paid ever runs by default.
    """
    root = root or audit_dir()
    allow = set(allow_cost_tiers)
    only_set = set(only) if only else None
    roots = list(projects_roots) if projects_roots is not None else [REPO_ROOT / "projects"]
    offers: list[dict[str, Any]] = []
    tools_without_offers: list[str] = []
    local = load_local_offers(root)

    for tool in sorted(tools, key=lambda t: t.name):
        route_offers = [(o, None) for o in getattr(tool, "route_offers", []) or []]
        declared = {o.id for o, _ in route_offers}
        route_offers += [(o, spec) for o, spec in local.get(tool.name, []) if o.id not in declared]
        if not route_offers:
            tools_without_offers.append(tool.name)
            continue
        status = tool.get_status().value
        available = status == "available"
        prod = production_successes(tool.name, roots)
        smoke_cache: dict[str, Any] = {}
        for offer, local_smoke in route_offers:
            problems = offer.problems()
            record: dict[str, Any] = {
                "offer": offer.id,
                "tool": tool.name,
                "provider": getattr(tool, "provider", None),
                "tool_version": getattr(tool, "version", None),
                **offer.to_dict(),
                "status": status,
                "metadata_problems": problems,
                "production_successes": prod,
                "smoke": None,
                "output_probe": None,
                "notes_audit": [],
                "declared_in": "tool class" if local_smoke is None else "local_offers.json",
            }
            record.pop("id")
            wanted = only_set is None or tool.name in only_set
            if available and run_smoke and wanted:
                if offer.cost_tier not in allow:
                    record["notes_audit"].append(
                        f"smoke skipped: cost tier {offer.cost_tier!r} not approved for this audit")
                else:
                    record["smoke"] = _run_smoke(tool, offer, root, smoke_cache, local_smoke)
                    if record["smoke"].get("ok"):
                        record["output_probe"] = probe_artifact(record["smoke"].get("artifact"))
                        write_evidence(root, tool.name, offer.id, {
                            "tool_version": tool.version,
                            "checked_at": time.time(),
                            "smoke": record["smoke"],
                            "output_probe": record["output_probe"],
                        })
            if record["smoke"] is None and available:
                ev = load_evidence(root, tool.name, offer.id, tool.version)
                if ev:
                    record["smoke"] = {**ev.get("smoke", {}), "from_evidence": True}
                    record["output_probe"] = ev.get("output_probe")

            # Backlot events name the tool, not the offer: production evidence
            # proves an offer only when the tool has no other offer.
            prod_for_offer = prod if len(route_offers) == 1 else 0
            if prod and not prod_for_offer:
                record["notes_audit"].append(
                    f"{prod} production call(s) are tool-level and do not show which of "
                    f"{len(route_offers)} offers ran; not counted for this offer")
            record["evidence_level"] = _level(available, record["smoke"], record["output_probe"], prod_for_offer)
            record["routable"] = (
                not problems and level_rank(record["evidence_level"]) >= level_rank(ROUTABLE_FLOOR)
            )
            record["blocked_by"] = _blocked_by(record)
            offers.append(record)

    summary = {
        "offers": len(offers),
        "routable": sum(1 for o in offers if o["routable"]),
        "by_level": {lvl: sum(1 for o in offers if o["evidence_level"] == lvl) for lvl in LEVELS},
        "axes_without_routable_offer": sorted(
            a for a in CAPABILITY_AXES if not any(o["routable"] and a in o["axes"] for o in offers)
        ),
        "tools_without_offers": len(tools_without_offers),
    }
    return {
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "routable_floor": ROUTABLE_FLOOR,
        "smoke_ran": run_smoke,
        "allowed_cost_tiers": sorted(allow),
        "offers": offers,
        "tools_without_offers": tools_without_offers,
        "summary": summary,
    }


def _run_smoke(tool: Any, offer: RouteOffer, root: Path, cache: dict[str, Any],
               local_smoke: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    workdir = root / "smoke" / tool.name
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        if local_smoke is None:
            outcome = tool.routing_smoke(offer.id, workdir, cache)
        elif not local_smoke.get("inputs"):
            outcome = None
        else:
            outcome = smoke_via_execute(tool, _fill_workdir(local_smoke["inputs"], workdir), cache,
                                        key=local_smoke.get("key", "execute"),
                                        artifact_key=local_smoke.get("artifact_key", "output"))
    except Exception as exc:  # a failing smoke is evidence, not a crash
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "seconds": round(time.monotonic() - started, 1)}
    if outcome is None:
        return {"ok": False, "error": "no smoke test defined for this offer",
                "seconds": round(time.monotonic() - started, 1)}
    return {"ok": True, "artifact": outcome.get("artifact"), "detail": outcome.get("detail", ""),
            "seconds": round(time.monotonic() - started, 1)}


def smoke_via_execute(tool: Any, inputs: dict[str, Any], cache: dict[str, Any], key: str = "execute",
                      artifact_key: str = "output") -> dict[str, Any]:
    """Run ``tool.execute(inputs)`` once per audit (shared by the tool's offers).

    Raises when the call fails; returns ``{"artifact", "detail", "data"}``.
    """
    if key not in cache:
        try:
            result = tool.execute(inputs)
        except Exception as exc:
            cache[key] = exc
        else:
            cache[key] = result
    result = cache[key]
    if isinstance(result, Exception):
        raise result
    if not result.success:
        raise RuntimeError(result.error or "tool returned success=False")
    artifact = result.data.get(artifact_key) or inputs.get("output_path")
    return {"artifact": artifact, "detail": f"{tool.name}.execute ok", "data": result.data}


def _level(available: bool, smoke: Optional[dict], probe: Optional[dict], prod: int) -> str:
    if not available:
        return "DISCOVERED"
    if prod > 0:
        return "PRODUCTION_VERIFIED"
    if smoke and smoke.get("ok"):
        return "OUTPUT_VERIFIED" if probe and probe.get("ok") else "SMOKE_TESTED"
    return "AVAILABLE"


def _blocked_by(record: dict[str, Any]) -> list[str]:
    if record["routable"]:
        return []
    out = [f"metadata: {p}" for p in record["metadata_problems"]]
    level = record["evidence_level"]
    if level == "DISCOVERED":
        out.append(f"tool status is {record['status']!r} on this machine")
    elif level == "AVAILABLE":
        smoke = record.get("smoke")
        out.append(f"smoke failed: {smoke['error']}" if smoke and smoke.get("error")
                   else "no smoke evidence (run the audit with smoke enabled)")
    elif level == "SMOKE_TESTED":
        probe = record.get("output_probe") or {}
        out.append(f"output not verified: {probe.get('reason', 'no artifact')}")
    out += record.get("notes_audit", [])
    return out


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def need_level(value: Any) -> int:
    """none|low|medium|high -> 0..3 (anything else counts as none)."""
    return NEED_LEVELS.get(str(value).lower(), 0)


def route_scenes(
    scene_plan: dict[str, Any],
    capability: dict[str, Any],
    *,
    approved_runtimes: Optional[Iterable[str]] = None,
    master_runtime: Optional[str] = None,
    tool_names: Iterable[str] = (),
) -> dict[str, Any]:
    """Pick verified tool offers for every scene need. Deterministic.

    ``capability`` is an ``audit_tools`` report. ``approved_runtimes`` are the
    composition runtimes the user approved at proposal; an offer that needs
    another runtime is rejected with that reason instead of being chosen
    silently. ``None`` means only ``master_runtime`` is approved (when given).
    """
    offers = capability.get("offers", [])
    approved = set(approved_runtimes) if approved_runtimes is not None else (
        {master_runtime} if master_runtime else None)
    scenes_out: list[dict[str, Any]] = []
    track_demand: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []

    for scene in scene_plan.get("scenes", []):
        need = scene.get("visual_need")
        sid = scene.get("id")
        if not isinstance(need, dict):
            warnings.append({"code": "SCENE_WITHOUT_VISUAL_NEED", "scene_id": sid,
                             "message": "scene has no visual_need; nothing was routed for it"})
            continue
        cues = [c for c in need.get("cues", []) if c in CUES]
        entry = {"scene_id": sid, "need": {k: v for k, v in need.items() if k in NEEDS},
                 "cues": cues, "layers": [], "rejected": [], "unmet": []}
        roles_filled: dict[str, str] = {}
        # Stronger needs claim a shared role (visual_source) first; ties keep NEEDS order.
        ordered = sorted((k for k in NEEDS if k in need), key=lambda k: -need_level(need[k]))
        for key in ordered:
            level = need_level(need[key])
            if level < ROUTE_THRESHOLD:
                continue
            spec = NEEDS[key]
            if spec["track"]:
                demand = track_demand.setdefault(key, {"level": 0, "scenes": [], "cues": set()})
                demand["level"] = max(demand["level"], level)
                demand["scenes"].append(sid)
                demand["cues"].update(cues)
                continue
            if spec["role"] in roles_filled:
                entry["rejected"].append({"need": key, "offer": None, "tool": None,
                                          "reason": f"role {spec['role']} already filled by need "
                                                    f"{roles_filled[spec['role']]!r}"})
                continue
            pick = _select(key, level, cues, offers, approved, scope_any=("scene", "beat", "asset"))
            if not pick["chosen"]:
                pick["chosen"] = _fallback(key, pick, offers, approved, scope_any=("scene", "beat", "asset"))
            entry["rejected"] += pick["rejected"]
            if pick["chosen"]:
                entry["layers"].append(pick["chosen"])
                roles_filled[spec["role"]] = key
            else:
                entry["unmet"].append({"need": key, "level": level, "blocked": pick["blocked"],
                                       "rejected": [r for r in pick["rejected"] if r["need"] == key]})
        scenes_out.append(entry)

    tracks: list[dict[str, Any]] = []
    unmet_tracks: list[dict[str, Any]] = []
    for key in (k for k in NEEDS if k in track_demand):
        demand = track_demand[key]
        pick = _select(key, demand["level"], sorted(demand["cues"]), offers, approved,
                       scope_any=("track", "project", "section"))
        if pick["chosen"]:
            tracks.append({**pick["chosen"], "scenes": demand["scenes"], "rejected": pick["rejected"]})
        else:
            unmet_tracks.append({"need": key, "level": demand["level"], "scenes": demand["scenes"],
                                 "blocked": pick["blocked"], "rejected": pick["rejected"]})

    for scene in scenes_out:
        for unmet in scene["unmet"]:
            warnings.append({"code": "NEED_UNMET", "scene_id": scene["scene_id"], "need": unmet["need"],
                             "message": _unmet_message(unmet)})
    for unmet in unmet_tracks:
        warnings.append({"code": "NEED_UNMET", "scene_id": None, "need": unmet["need"],
                         "message": _unmet_message(unmet)})
    # A fitting, verified offer lost only because its runtime was not approved:
    # say so once per offer, so the proposal can present it instead of it
    # silently never being used.
    blocked_runtime: dict[tuple[str, str], list[Any]] = {}
    for scene in scenes_out:
        for r in scene["rejected"]:
            if "was not approved at proposal" in r["reason"]:
                blocked_runtime.setdefault((r["offer"], r["reason"]), []).append(scene["scene_id"])
    for (offer, reason), sids in sorted(blocked_runtime.items()):
        warnings.append({"code": "RUNTIME_NOT_APPROVED", "offer": offer, "scenes": sids,
                         "message": f"{offer} fits {len(sids)} scene(s) but {reason}; present it to the user "
                                    f"at proposal or record why it is excluded"})
    warnings += tool_name_leaks(scene_plan, [o["offer"] for o in offers] + list(tool_names))

    layers_by_role: dict[str, int] = {}
    for scene in scenes_out:
        for layer in scene["layers"]:
            layers_by_role[layer["role"]] = layers_by_role.get(layer["role"], 0) + 1
    unmet_by_need: dict[str, int] = {}
    for scene in scenes_out:
        for unmet in scene["unmet"]:
            unmet_by_need[unmet["need"]] = unmet_by_need.get(unmet["need"], 0) + 1
    for unmet in unmet_tracks:
        unmet_by_need[unmet["need"]] = unmet_by_need.get(unmet["need"], 0) + 1

    return {
        "version": "1.0",
        "master_runtime": master_runtime,
        "approved_runtimes": sorted(approved) if approved is not None else None,
        "capability_generated_at": capability.get("generated_at"),
        "scenes": scenes_out,
        "tracks": tracks,
        "unmet_tracks": unmet_tracks,
        "overrides": [],
        "warnings": warnings,
        "summary": {
            "scenes": len(scenes_out),
            "layers_by_role": layers_by_role,
            "unmet_by_need": unmet_by_need,
        },
    }


def _select(need: str, level: int, cues: list[str], offers: list[dict[str, Any]],
            approved: Optional[set], *, scope_any: tuple[str, ...]) -> dict[str, Any]:
    axes = NEEDS[need]["axes"]
    matching = [o for o in offers if set(o["axes"]) & set(axes)]
    scored: list[tuple[float, str, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for o in matching:
        if not o.get("routable"):
            blocked.append({"offer": o["offer"], "tool": o["tool"], "evidence_level": o["evidence_level"],
                            "blocked_by": o.get("blocked_by", [])})
            continue
        if not set(o["scopes"]) & set(scope_any):
            rejected.append({"need": need, "offer": o["offer"], "tool": o["tool"],
                             "reason": f"scope {o['scopes']} does not cover {list(scope_any)}"})
            continue
        if o.get("runtime") and approved is not None and o["runtime"] not in approved:
            rejected.append({"need": need, "offer": o["offer"], "tool": o["tool"],
                             "reason": f"runtime {o['runtime']!r} was not approved at proposal"})
            continue
        axis_bonus = len(axes) - min(axes.index(a) for a in o["axes"] if a in axes)
        score = (int(o.get("strengths", {}).get(need, 3)) * 10
                 + 5 * len(set(cues) & set(o.get("triggers", [])))
                 + LEVEL_BONUS.get(o["evidence_level"], 0)
                 + axis_bonus
                 - COST_PENALTY.get(o.get("cost_tier", "free"), 0))
        scored.append((score, o["offer"], o))
    scored.sort(key=lambda s: (-s[0], s[1]))
    if not scored:
        return {"chosen": None, "rejected": rejected, "blocked": blocked}
    best_score, _, best = scored[0]
    for score, _, o in scored[1:]:
        rejected.append({"need": need, "offer": o["offer"], "tool": o["tool"],
                         "reason": f"lower score ({score} < {best_score})"})
    hits = sorted(set(cues) & set(best.get("triggers", [])))
    reason = (f"{need}={_level_name(level)}; axis {sorted(set(best['axes']) & set(axes))}; "
              f"{best['evidence_level']}; {best.get('cost_tier', 'free')}"
              + (f"; cues {hits}" if hits else ""))
    return {
        "chosen": {"role": NEEDS[need]["role"], "need": need, "offer": best["offer"], "tool": best["tool"],
                   "provider": best.get("provider"), "runtime": best.get("runtime"),
                   "score": best_score, "reason": reason},
        "rejected": rejected,
        "blocked": blocked,
    }


def _fallback(need: str, pick: dict[str, Any], offers: list[dict[str, Any]], approved: Optional[set],
              *, scope_any: tuple[str, ...]) -> Optional[dict[str, Any]]:
    """Try the declared fallbacks of the candidates that could not be used."""
    by_id = {o["offer"]: o for o in offers}
    losers = [(b["offer"], f"below the floor ({b['evidence_level']})") for b in pick["blocked"]]
    losers += [(r["offer"], r["reason"]) for r in pick["rejected"] if r.get("offer")]
    for loser, why in losers:
        for fid in by_id.get(loser, {}).get("fallback", []):
            o = by_id.get(fid)
            if (not o or not o.get("routable") or not set(o["scopes"]) & set(scope_any)
                    or (o.get("runtime") and approved is not None and o["runtime"] not in approved)):
                continue
            return {"role": NEEDS[need]["role"], "need": need, "offer": o["offer"], "tool": o["tool"],
                    "provider": o.get("provider"), "runtime": o.get("runtime"), "score": 0,
                    "reason": f"fallback for {loser} ({why}); {o['evidence_level']}"}
    return None


def _level_name(level: int) -> str:
    return {v: k for k, v in NEED_LEVELS.items()}[level]


def _unmet_message(unmet: dict[str, Any]) -> str:
    blocked = unmet.get("blocked") or []
    rejected = unmet.get("rejected") or []
    if not blocked and not rejected:
        return f"need {unmet['need']!r} has no tool offer on any matching axis"
    parts = []
    if rejected:
        parts.append("verified candidates rejected: " + "; ".join(f"{r['offer']} ({r['reason']})" for r in rejected))
    if blocked:
        parts.append("candidates below the floor: " + "; ".join(f"{b['offer']} ({b['evidence_level']})" for b in blocked))
    return f"need {unmet['need']!r} has no routable tool; " + "; ".join(parts)


_LEAK_FIELDS = ("description", "overlay_notes", "shot_intent", "shot_language")
_RUNTIME_WORDS = ("remotion", "hyperframes", "pexels", "pixabay", "unsplash", "qwen3", "phrasecaptions")


def tool_name_leaks(scene_plan: dict[str, Any], names: Iterable[str]) -> list[dict[str, Any]]:
    """Soft warning when the scene plan names tools instead of needs."""
    words = {n.lower() for n in names if n and len(n) > 3} | set(_RUNTIME_WORDS)
    out: list[dict[str, Any]] = []
    for scene in scene_plan.get("scenes", []):
        text = " ".join(str(scene.get(f, "")) for f in _LEAK_FIELDS).lower()
        hits = sorted(w for w in words if w in text)
        if hits:
            out.append({"code": "TOOL_NAMED_IN_SCENE_PLAN", "scene_id": scene.get("id"),
                        "message": f"scene plan names tools {hits}; describe the need (visual_need) and let "
                                   f"the router choose"})
    return out


# ---------------------------------------------------------------------------
# Timeline and usage QA
# ---------------------------------------------------------------------------

def tool_layers_by_scene(tool_plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Compact per-scene selection kept on the visual_timeline."""
    return {
        s["scene_id"]: [{"role": l["role"], "need": l["need"], "offer": l["offer"], "tool": l["tool"]}
                        for l in s.get("layers", [])]
        for s in tool_plan.get("scenes", [])
        if s.get("layers")
    }


UNDERUSE_CODES = {
    "reality": "REAL_WORLD_BROLL_UNDERUSED",
    "motion_expressiveness": "EXPRESSIVE_RUNTIME_UNDERUSED",
    "impossible_visual": "SYNTHETIC_VISUAL_UNDERUSED",
    "rhythm_accent": "SFX_UNDERUSED",
    "information_precision": "STRUCTURED_GRAPHICS_UNDERUSED",
}
UNDERUSE_RATIO = 0.5


def tool_usage_report(
    tool_plan: dict[str, Any],
    asset_manifest: Optional[dict[str, Any]] = None,
    edit_decisions: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Did production use the tools the router picked? Soft warnings only.

    A planned layer counts as used when an asset for that scene came from the
    chosen tool or provider, or (for a runtime layer) when the edit renders in
    that runtime. A layer the executor deliberately skipped must be listed in
    ``tool_plan.overrides`` with a reason; unexplained skips are reported.
    """
    assets = (asset_manifest or {}).get("assets", [])
    edit = edit_decisions or {}
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        by_scene.setdefault(str(a.get("scene_id")), []).append(a)
    render_runtime = edit.get("render_runtime")
    subtitles = edit.get("subtitles") or {}
    overrides = {(o.get("scene_id"), o.get("offer")): o.get("reason", "")
                 for o in tool_plan.get("overrides", []) if o.get("reason")}

    def used(scene_id: Optional[str], layer: dict[str, Any]) -> bool:
        pool = assets if scene_id is None else by_scene.get(str(scene_id), [])
        for a in pool:
            if a.get("source_tool") == layer.get("tool") or (
                    layer.get("provider") and a.get("provider") == layer.get("provider")):
                return True
        if layer.get("role") == "captions":
            return bool(subtitles) and subtitles.get("enabled", True) is not False
        if layer.get("runtime") and layer["runtime"] == render_runtime:
            # the whole edit is composed in this runtime; a precise-graphics base
            # layer is honoured by construction, an overlay still needs an asset
            return layer.get("role") == "base_composition"
        return False

    warnings: list[dict[str, Any]] = []
    tally: dict[str, dict[str, int]] = {}
    ignored: list[dict[str, Any]] = []
    for scene in tool_plan.get("scenes", []):
        for layer in scene.get("layers", []):
            t = tally.setdefault(layer["need"], {"planned": 0, "used": 0, "overridden": 0})
            t["planned"] += 1
            key = (scene["scene_id"], layer["offer"])
            if used(scene["scene_id"], layer):
                t["used"] += 1
            elif key in overrides:
                t["overridden"] += 1
            else:
                ignored.append({"scene_id": scene["scene_id"], "need": layer["need"], "offer": layer["offer"],
                                "tool": layer["tool"]})
    for item in ignored:
        warnings.append({"code": "ROUTED_LAYER_IGNORED", **item,
                         "message": f"router chose {item['offer']} for {item['need']} but no asset or render "
                                    f"used it and tool_plan.overrides gives no reason"})
    for need, t in tally.items():
        code = UNDERUSE_CODES.get(need)
        honoured = t["used"] + t["overridden"]
        if code and t["planned"] >= 2 and honoured / t["planned"] < UNDERUSE_RATIO:
            warnings.append({"code": code, "need": need, **t,
                             "message": f"{t['used']} of {t['planned']} scenes that needed {need} used the "
                                        f"routed tool ({t['overridden']} with a stated reason)"})
    for track in tool_plan.get("tracks", []):
        if not used(None, track):
            warnings.append({"code": "ROUTED_TRACK_IGNORED", "need": track["need"], "offer": track["offer"],
                             "tool": track["tool"],
                             "message": f"track {track['role']} was routed to {track['offer']} but not used"})
    for w in tool_plan.get("warnings", []):
        if w.get("code") == "NEED_UNMET":
            warnings.append(w)
    return {"tally": tally, "ignored": ignored, "warnings": warnings,
            "static_screens": "scored by lib/slideshow_risk.py, not duplicated here"}


def need_counts(scene_plan: dict[str, Any]) -> dict[str, int]:
    """How many scenes need each dimension at medium or above (for reports)."""
    out = {k: 0 for k in NEEDS}
    for s in scene_plan.get("scenes", []):
        need = s.get("visual_need") or {}
        for k in NEEDS:
            if k in need and need_level(need[k]) >= ROUTE_THRESHOLD:
                out[k] += 1
    return out


# ---------------------------------------------------------------------------
# Context-light menu (what planning stages read)
# ---------------------------------------------------------------------------

MENU_FAMILIES = (
    ("footage", "Footage", ("reality_footage", 'reality_still'), 'scene runtime "footage"'),
    ("remotion", "Remotion", ("structured_graphics",), 'scene runtime "remotion"'),
    ("hyperframes", "HyperFrames", ("expressive_motion",), 'scene runtime "hyperframes"'),
    ("generated", "Generated image / video", ("synthetic_image", "synthetic_video"), "a generated asset in a footage scene"),
    ("tracks", "Voice / captions / music", ("narration", "alignment", "caption", "music", "sfx"), "project tracks"),
)


def creative_menu(capability: Optional[dict[str, Any]], approved_runtimes: Optional[Iterable[str]] = None
                  ) -> dict[str, Any]:
    """Short tool menu for directors: families, what they are for, available or not.

    Built from the audit report's routable offers (and their one-line
    ``notes``). Verification history, scores, candidates and the registry are
    deliberately left out; ask ``tool_router`` for ``audit`` when debugging.
    """
    offers = (capability or {}).get("offers", [])
    families = []
    lines = ["Creative tools on this machine (pick one main runtime per scene):"]
    for key, label, axes, use_as in MENU_FAMILIES:
        fam = [o for o in offers if set(o["axes"]) & set(axes)]
        ready = [o for o in fam if o.get("routable")]
        tools = sorted({o["tool"] for o in ready})
        use_for = next((o.get("notes") for o in sorted(ready or fam, key=lambda o: -max(o.get("strengths", {}).values() or [3]))
                        if o.get("notes")), "")
        families.append({"family": key, "available": bool(ready), "tools": tools, "use_for": use_for})
        if key == "tracks":
            missing = sorted({a for a in axes if not any(a in o["axes"] and o.get("routable") for o in fam)})
            lines.append(f"- {label}: {', '.join(tools) or 'none verified'}"
                         + (f" (missing: {', '.join(missing)})" if missing else ""))
        elif ready:
            lines.append(f"- {label} ({', '.join(tools)}): {use_for} -> {use_as}")
        else:
            lines.append(f"- {label}: {use_for or 'no tool'} -> UNAVAILABLE here, do not select")
    if approved_runtimes is not None:
        lines.append(f"Approved runtimes: {', '.join(sorted(approved_runtimes))}. "
                     "A fitting runtime that is not approved: say so (RUNTIME_NOT_APPROVED), do not use it.")
    if not capability:
        lines.append("No capability audit on this machine yet: run scripts/tool_capability_audit.py --smoke.")
    return {"text": "\n".join(lines), "families": families}
