"""Scene runtime override v1: one main runtime per scene.

The project keeps its default ``render_runtime`` (the master assembly). A scene
may override the runtime of its main picture:

- ``inherit``     — use the project default (same as leaving it out)
- ``remotion``    — structured graphics in the Remotion assembly
- ``hyperframes`` — a HyperFrames/GSAP clip rendered per scene, then placed in
                    the Remotion assembly as an ordinary video cut
- ``footage``     — a real video/still cut

This is not a layer compositor: a scene has one main runtime; the existing
caption/audio/overlay paths still apply on top of the assembly.

HyperFrames scenes keep the visual-direction contract: ``render_scene_runtimes``
writes each scene's direction bridge and requires every event to be placed
before the clip renders (``lib/direction_contract/binding/hyperframes.py``).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SCENE_RUNTIMES = ("inherit", "remotion", "hyperframes", "footage")
COMPOSITION_RUNTIMES = ("remotion", "hyperframes")  # need approval at proposal


# ---------------------------------------------------------------- resolution

def approved_runtimes(edit_or_plan: dict[str, Any], project_runtime: Optional[str]) -> set[str]:
    """Runtimes approved at proposal. Default: only the project runtime."""
    approved = edit_or_plan.get("approved_runtimes")
    out = {str(r).lower() for r in approved} if approved else set()
    if project_runtime:
        out.add(project_runtime.lower())
    return out


def resolve_scene_runtimes(
    scenes: Iterable[dict[str, Any]],
    project_runtime: str,
    approved: Iterable[str],
    unavailable: Iterable[str] = (),
) -> dict[str, Any]:
    """Compact per-scene runtime list for downstream stages.

    ``scenes`` are scene_plan scenes (``id``, optional ``runtime`` /
    ``runtime_reason``). A requested composition runtime that was not approved,
    or is unavailable on this machine, falls back to the project default with a
    warning — never silently.
    """
    approved_set = {a.lower() for a in approved}
    unavailable_set = {u.lower() for u in unavailable}
    out: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for scene in scenes:
        sid = scene.get("id") or scene.get("scene_id")
        requested = (scene.get("runtime") or "inherit").lower()
        reason = scene.get("runtime_reason") or ""
        runtime = project_runtime if requested == "inherit" else requested
        if requested not in SCENE_RUNTIMES:
            warnings.append({"code": "UNKNOWN_SCENE_RUNTIME", "scene_id": sid,
                             "message": f"scene {sid}: unknown runtime {requested!r}; using {project_runtime}"})
            runtime = project_runtime
        elif runtime in COMPOSITION_RUNTIMES and runtime not in approved_set:
            warnings.append({"code": "RUNTIME_NOT_APPROVED", "scene_id": sid, "runtime": runtime,
                             "message": f"scene {sid} fits {runtime} ({reason or 'no reason given'}) but {runtime} "
                                        f"was not approved at proposal; using {project_runtime}. Present it to "
                                        f"the user or record why it is excluded."})
            runtime = project_runtime
        elif runtime in unavailable_set:
            warnings.append({"code": "RUNTIME_UNAVAILABLE", "scene_id": sid, "runtime": runtime,
                             "message": f"scene {sid}: {runtime} is not available on this machine; using "
                                        f"{project_runtime}"})
            runtime = project_runtime
        row = {"scene_id": sid, "runtime": runtime, "reason": reason}
        if requested not in ("inherit", runtime):
            row["requested"] = requested
        out.append(row)
    return {"project_runtime": project_runtime, "scenes": out, "warnings": warnings}


def planned_runtime_gaps(scenes: Iterable[dict[str, Any]], cuts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soft warning: scenes planned as HyperFrames whose cuts render without it."""
    cuts = list(cuts)
    out: list[dict[str, Any]] = []
    for scene in scenes:
        if (scene.get("runtime") or "").lower() != "hyperframes":
            continue
        sid = scene.get("id") or scene.get("scene_id")
        mine = [c for c in cuts if c.get("scene_id") == sid]
        if not mine and scene.get("start_seconds") is not None and scene.get("end_seconds") is not None:
            lo, hi = float(scene["start_seconds"]), float(scene["end_seconds"])
            mine = [c for c in cuts if lo - 1e-3 <= float(c.get("in_seconds", -1)) < hi]
        if not any((c.get("runtime") or "").lower() == "hyperframes" for c in mine):
            out.append({"code": "PLANNED_RUNTIME_DROPPED", "scene_id": sid, "runtime": "hyperframes",
                        "message": f"scene {sid} was planned with runtime 'hyperframes' but its cuts render without it; "
                                   f"record the decision in decision_log or restore the HyperFrames scene"})
    return out


# ---------------------------------------------------------------- rendering

def is_media_source(source: Any) -> bool:
    return bool(source) and Path(str(source)).suffix.lower() in {
        ".mp4", ".mov", ".webm", ".mkv", ".avi", ".png", ".jpg", ".jpeg", ".webp"}


def render_scene_runtimes(
    edit_decisions: dict[str, Any],
    cuts: list[dict[str, Any]],
    output_path: Path,
    inputs: dict[str, Any],
    render_hyperframes: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Render every ``runtime: "hyperframes"`` cut to a scene clip.

    Each clip replaces its cut as an ordinary video cut of the same length,
    so the Remotion assembly, captions and audio work unchanged. The scene's
    visual_timeline events are written into the workspace (om-direction.js)
    and every one must be placed by the authored code before it renders.

    ``render_hyperframes`` runs one HyperFrames render (the HyperFramesCompose
    tool's execute) and returns its ToolResult. Returns {"cuts", "report"} or
    {"error", "data"}.
    """
    from lib.direction_contract.hooks import scene_events, trace_workspace, write_bridge
    from lib.direction_contract.timeline import read_timeline

    approved = approved_runtimes(edit_decisions, "remotion")
    timeline = edit_decisions.get("visual_timeline")
    if isinstance(timeline, str):
        try:
            timeline = read_timeline(timeline)
        except (OSError, ValueError) as exc:
            return {"error": f"Could not read visual_timeline for scene runtimes: {exc}", "data": {}}
    clip_dir = output_path.parent / "scene_clips"
    out_cuts: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    for cut in cuts:
        runtime = (cut.get("runtime") or "remotion").lower()
        row = {"cut_id": cut.get("id"), "scene_id": cut.get("scene_id"), "runtime": runtime}
        if runtime != "hyperframes":
            if runtime == "footage" and not is_media_source(cut.get("source")):
                return {"error": (
                    f"cut {cut.get('id')}: runtime 'footage' needs a video or image source, got "
                    f"{cut.get('source')!r}"), "data": {}}
            out_cuts.append(cut)
            report.append(row)
            continue
        if "hyperframes" not in approved:
            return {"error": (
                f"RUNTIME_NOT_APPROVED: cut {cut.get('id')} uses runtime 'hyperframes' but approved runtimes are "
                f"{sorted(approved)}. Approve HyperFrames at proposal (edit_decisions.approved_runtimes) or "
                "author this scene in Remotion."), "data": {}}
        spec = cut.get("hyperframes") or {}
        workspace = Path(str(spec.get("workspace") or ""))
        if not spec.get("workspace") or not (workspace / "index.html").is_file():
            return {"error": (
                f"cut {cut.get('id')}: runtime 'hyperframes' needs hyperframes.workspace with an authored "
                f"index.html (got {spec.get('workspace')!r})"), "data": {}}
        duration = float(cut["out_seconds"]) - float(cut["in_seconds"])
        events = scene_events(timeline, cut)
        write_bridge(workspace, cut, events)
        trace = trace_workspace(workspace, events, expected_duration=duration)
        if trace["hard_failures"]:
            return {"error": (
                f"HyperFrames scene {cut.get('id')} does not implement its visual direction: "
                + "; ".join(trace["hard_failures"])), "data": {"trace": trace}}
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip = clip_dir / f"{cut.get('id') or 'scene'}.mp4"
        result = render_hyperframes({
            "operation": "render_existing",
            "workspace_path": str(workspace),
            "output_path": str(clip),
            "quality": spec.get("quality", "standard"),
            "skip_contrast": spec.get("skip_contrast", True),
            **({"profile": inputs["profile"]} if inputs.get("profile") else {}),
        })
        if not result.success:
            return {"error": f"HyperFrames scene {cut.get('id')} failed: {result.error}", "data": result.data}
        placed = {k: v for k, v in cut.items() if k not in ("runtime", "hyperframes", "type")}
        placed.update({"source": str(clip), "source_in_seconds": 0})
        out_cuts.append(placed)
        report.append({**row, "clip": str(clip), "events": len(events), "implemented": trace["implemented"],
                       "trace": trace["events"]})
    return {"cuts": out_cuts, "report": report}


def place_atelier_scene_clips(
    hf_cuts: list[dict[str, Any]],
    rendered_cuts: list[dict[str, Any]],
    public_root: Path,
) -> list[dict[str, Any]]:
    """Copy rendered HyperFrames scene clips into the atelier public dir as props.sceneClips."""
    (public_root / "scene_clips").mkdir(parents=True, exist_ok=True)
    scene_clips = []
    for cut, placed in zip(hf_cuts, rendered_cuts):
        dest = public_root / "scene_clips" / Path(placed["source"]).name
        shutil.copy2(placed["source"], dest)
        scene_clips.append({"scene_id": cut.get("scene_id"), "cut_id": cut.get("id"),
                            "src": dest.relative_to(public_root).as_posix(),
                            "start": float(cut["in_seconds"]), "end": float(cut["out_seconds"])})
    return scene_clips
