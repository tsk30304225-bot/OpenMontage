"""Render-time guards: refuse to render when the direction contract would be lost.

Each runtime path binds the compiled visual_timeline before it renders:

- templated Remotion: ``attach_visual_timeline`` hands the timeline to the
  ``visual_model`` cuts (only ``timeline_rail`` has a generic renderer);
- atelier: ``prepare_atelier_direction`` traces every event to the bespoke
  source and hands the timeline to the composition;
- HyperFrames scene cuts inside an atelier render:
  ``scene_clips_unread_error`` requires the composition to place them.

A guard returns an error message (or an ``{"error": …}`` dict) instead of
letting the renderer improvise a static substitute.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.direction_contract.binding.hyperframes import hyperframes_cuts, without_scene_events
from lib.direction_contract.binding.remotion_source import build_trace
from lib.direction_contract.timeline import missing_timeline_file, read_timeline, unresolved_anchors_error


def attach_visual_timeline(props: dict[str, Any], composition_id: str) -> str | None:
    """Load visual_timeline for type: "visual_model" cuts.

    The renderer executes the compiled events; it must not guess a model
    from a scene description. Missing timelines, unknown model ids and
    unresolved anchors are errors rather than a silent static card.
    """
    model_cuts = [c for c in props.get("cuts") or [] if isinstance(c, dict) and c.get("type") == "visual_model"]
    timeline = props.pop("visual_timeline", None)
    if not model_cuts:
        if timeline is not None:
            props["visualTimeline"] = timeline if isinstance(timeline, dict) else None
        return None
    if composition_id != "Explainer":
        return (
            f"visual_model cuts render in the Explainer composition; renderer_family maps to {composition_id}. "
            "Use an explainer renderer_family for model scenes."
        )
    if isinstance(timeline, str):
        missing = missing_timeline_file(timeline)
        if missing:
            return missing
        try:
            timeline = read_timeline(timeline)
        except (OSError, ValueError) as exc:
            return f"Could not read visual_timeline {Path(timeline)}: {exc}"
    if not isinstance(timeline, dict):
        return "visual_model cuts need edit_decisions.visual_timeline (compiled by visual_timeline_compiler)."
    unresolved = unresolved_anchors_error(timeline)
    if unresolved:
        return unresolved
    models = {m.get("id"): m for m in timeline.get("models") or []}
    for cut in model_cuts:
        mid = (cut.get("visual_model") or {}).get("model_id")
        if mid not in models:
            return f"cut {cut.get('id')}: visual_model.model_id {mid!r} is not in visual_timeline models {sorted(models)}"
        if models[mid].get("type") != "timeline_rail" or models[mid].get("renderer") == "bespoke":
            return (
                f"cut {cut.get('id')}: model {mid!r} (type {models[mid].get('type')!r}) has no generic renderer. "
                "Render it in atelier (composition_mode='atelier') where the bespoke composition implements the "
                "same visual_timeline, or give those scenes runtime 'hyperframes' (HyperFrames scene clips place the "
                "events with OM.at); do not drop the model."
            )
    props["visualTimeline"] = {"models": timeline.get("models") or [], "events": timeline.get("events") or []}
    return None


def scene_clips_unread_error(entry_path: Path) -> str | None:
    """HyperFrames scene clips exist but the atelier composition never places them."""
    if any("sceneClips" in f.read_text(encoding="utf-8", errors="ignore")
           for f in entry_path.parent.rglob("*") if f.suffix in (".tsx", ".ts", ".jsx", ".js")
           and "node_modules" not in f.parts):
        return None
    return ("edit_decisions has HyperFrames scene cuts but the atelier composition never reads "
            "props.sceneClips; place each clip (<Sequence from={start*fps}><OffthreadVideo "
            "src={staticFile(clip.src)} /></Sequence>) at its scene window.")


def prepare_atelier_direction(
    entry_path: Path,
    edit_decisions: dict[str, Any],
    props_path: str | None,
    output_path: Path,
    scene_clips: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind an atelier render to the visual_direction / visual_timeline contract.

    Returns {"props_path": merged props with visualTimeline, "trace": …} or
    {"error": …}. A project whose visual_direction declares models must ship
    a compiled visual_timeline; every event must be implemented through the
    direction runtime (see lib/direction_contract/binding/remotion_source.py).
    """
    project_dir = entry_path.parent

    def merged_props(extra: dict[str, Any]) -> str:
        props: dict[str, Any] = json.loads(Path(props_path).read_text(encoding="utf-8")) if props_path else {}
        props.update(extra)
        if scene_clips:
            props["sceneClips"] = scene_clips
        merged = output_path.parent / f".{output_path.stem}.atelier_props.json"
        merged.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        return str(merged)

    timeline = edit_decisions.get("visual_timeline")
    missing = missing_timeline_file(timeline)
    if missing:
        return {"error": missing}
    timeline = read_timeline(timeline)
    if timeline is None:
        direction_path = project_dir / "artifacts" / "visual_direction.json"
        if direction_path.is_file():
            try:
                declared = json.loads(direction_path.read_text(encoding="utf-8")).get("visual_models") or []
            except (OSError, ValueError):
                declared = []
            if declared:
                return {"error": (
                    f"{direction_path} declares visual models {[m.get('id') for m in declared]} but "
                    "edit_decisions.visual_timeline is missing. Compile it with visual_timeline_compiler from the real "
                    "alignment; atelier implements the contract, it does not replace it."
                )}
        return {"props_path": merged_props({})} if scene_clips else {}
    if not isinstance(timeline, dict):
        return {"error": "edit_decisions.visual_timeline must be the compiled visual_timeline (object or path)"}
    unresolved = unresolved_anchors_error(timeline)
    if unresolved:
        return {"error": unresolved}

    # Events of HyperFrames scene cuts are implemented (and traced) in their workspaces.
    trace = build_trace(without_scene_events(timeline, hyperframes_cuts(edit_decisions)), project_dir)
    if trace["hard_failures"]:
        return {"error": "atelier composition does not implement the direction contract:\n"
                         + "\n".join(f"  • {f}" for f in trace["hard_failures"]), "trace": trace}

    visual = {"models": timeline.get("models") or [], "events": timeline.get("events") or []}
    return {"props_path": merged_props({"visualTimeline": visual}), "trace": trace}
