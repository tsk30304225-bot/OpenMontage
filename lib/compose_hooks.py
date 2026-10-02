"""Fork seam for tools/video/video_compose.py.

video_compose.py is an upstream file. Everything this fork adds to its render
paths lives behind the functions below, so the upstream file only carries a
few calls (search it for ``compose_hooks``). When merging upstream, keep those
calls at the same points of each render path; the logic here does not change.

Each function returns plain data; video_compose turns ``{"error", "data"}``
into a failed ToolResult.

- ``templated_props``        Remotion templated path, before render: phrase captions
                             (lib/phrase_captions.py), then the visual_timeline guard
- ``atelier_direction``      atelier path, before render: HyperFrames scene clips +
                             direction contract binding
- ``templated_scene_runtimes`` templated path, before the pre-compose gate:
                             planned-runtime warnings + HyperFrames scene clips
- ``atelier_stock_import`` / ``ATELIER_IMPORT_SPEC_RE``
                             atelier doctrine scan (lib/atelier_policy.py)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lib import scene_runtime
from lib.atelier_policy import IMPORT_SPEC_RE as ATELIER_IMPORT_SPEC_RE
from lib.atelier_policy import classify_import
from lib.direction_contract.hooks import (
    attach_visual_timeline,
    hyperframes_cuts,
    prepare_atelier_direction,
    scene_clips_unread_error,
)
from lib.phrase_captions import attach_phrase_captions

__all__ = [
    "ATELIER_IMPORT_SPEC_RE",
    "atelier_direction",
    "atelier_stock_import",
    "templated_props",
    "templated_scene_runtimes",
]


def _render_hyperframes(params: dict[str, Any]) -> Any:
    from tools.video.hyperframes_compose import HyperFramesCompose

    return HyperFramesCompose().execute(params)


def templated_props(props: dict[str, Any], composition_id: str) -> str | None:
    """Bind captions, then the visual_timeline, into stock-composition props; error message or None."""
    caption_error = attach_phrase_captions(props, composition_id)
    if caption_error:
        return caption_error
    return attach_visual_timeline(props, composition_id)


def atelier_direction(
    entry_path: Path,
    composer_dir: Path,
    bespoke: dict[str, Any],
    edit_decisions: dict[str, Any],
    props_path: str | None,
    output_path: Path,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Direction contract for an atelier render.

    The bespoke composition implements visual_timeline events; it does not
    re-decide them. Refuse to render when the contract is missing or
    unimplemented, and hand the resolved timeline to the composition as
    props.visualTimeline. Scene runtime overrides: HyperFrames scene cuts
    render to clips the bespoke composition places from props.sceneClips.

    Returns {"error", "data"}, or {"props_path"?, "trace"?} (empty when there
    is nothing to bind).
    """
    scene_clips = None
    hf_cuts = hyperframes_cuts(edit_decisions)
    if hf_cuts:
        unread = scene_clips_unread_error(entry_path)
        if unread:
            return {"error": unread, "data": {}}
        rendered = scene_runtime.render_scene_runtimes(edit_decisions, hf_cuts, output_path, inputs,
                                                       _render_hyperframes)
        if "error" in rendered:
            return rendered
        pd = bespoke.get("public_dir")
        public_root = Path(pd).resolve() if pd else composer_dir / "public"
        scene_clips = scene_runtime.place_atelier_scene_clips(hf_cuts, rendered["cuts"], public_root)
    direction = prepare_atelier_direction(entry_path, edit_decisions, props_path, output_path,
                                          scene_clips=scene_clips)
    if direction.get("error"):
        return {"error": direction["error"], "data": {"direction_trace": direction.get("trace")}}
    return direction


def templated_scene_runtimes(
    inputs: dict[str, Any],
    cuts: list[dict[str, Any]],
    resolved_cuts: list[dict[str, Any]],
    render_runtime: str,
    edit_decisions: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Scene runtime overrides on the templated path.

    Planned-vs-executed runtime (soft): a planned HyperFrames scene that the
    edit renders without it is reported, never blocked. Then every
    ``runtime: "hyperframes"`` cut renders to a scene clip.

    Returns {"error", "data"} or {"gaps": [...], "scene_runtimes": None | {"cuts", "report"}}.
    """
    plan_input = inputs.get("scene_plan")
    plan_scenes = plan_input.get("scenes", []) if isinstance(plan_input, dict) else (plan_input or [])
    runtime_gaps = scene_runtime.planned_runtime_gaps(plan_scenes, cuts)
    for gap in runtime_gaps:
        logging.getLogger("video_compose").warning(gap["message"])

    scene_runtimes = None
    if any(c.get("runtime") for c in resolved_cuts):
        if render_runtime != "remotion":
            return {"error": (
                "Scene runtime overrides (cut.runtime) are assembled by the Remotion templated path in v1; "
                f"this edit renders with {render_runtime!r}."), "data": {}}
        scene_runtimes = scene_runtime.render_scene_runtimes(edit_decisions, resolved_cuts, output_path, inputs,
                                                             _render_hyperframes)
        if "error" in scene_runtimes:
            return scene_runtimes
    return {"gaps": runtime_gaps, "scene_runtimes": scene_runtimes}


def atelier_stock_import(spec: str) -> str | None:
    """'stock', 'shared_infra' or None for one import specifier in a bespoke project."""
    return classify_import(spec)
