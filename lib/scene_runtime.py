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

HyperFrames scenes keep the visual-direction contract: the direction bridge and
trace live in ``lib/direction_contract/binding/hyperframes.py``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

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
