# Tool Routing — a short menu, one main runtime per scene

Tool choice stays light; scene execution stays flexible. Planning reads a
seven-line menu, not the registry or any audit detail.

## 1. Read the menu (planning)

```python
from tools.analysis.tool_router import ToolRouter
print(ToolRouter().execute({"operation": "menu",
                            "approved_runtimes": ["remotion", "hyperframes"]}).data["text"])
```

Each family line carries a state: `ROUTABLE` (output verified on this machine),
`APPROVAL_REQUIRED` (verified, but spends subscription/paid credits: use only
after the user approves that provider for this project), `AVAILABLE` (installed
and authenticated, output not verified here: do not select) or `UNAVAILABLE`.
Registry, proposal preflight and the approved runtimes stay authoritative.

## 2. Pick one main runtime per scene (scene director)

`scene_plan.scenes[].runtime` = `inherit` (project default) | `footage` |
`remotion` | `hyperframes`, plus a short `runtime_reason`.

| Runtime | Use for |
|---|---|
| `footage` | reality: places, people, industry, immersion / breather / closure |
| `remotion` | data, numbers, comparisons, causal diagrams, persistent models, state changes locked to narration |
| `hyperframes` | kinetic typography, strong reveals, hero moments, fast expressive motion, short transitions and emphasis |

Decide from the scene's meaning, not from habit. Most scenes can
`inherit`. Only use a runtime that the menu lists as available and that the
proposal approved. If a runtime fits but was not approved, record it: the
`scene_runtimes` step raises `RUNTIME_NOT_APPROVED` rather than dropping it
silently. `visual_need` is optional detail and never required.

## 3. Resolve (asset / edit director)

```python
ToolRouter().execute({"operation": "scene_runtimes",
                      "scene_plan": "projects/<p>/artifacts/scene_plan.json",
                      "master_runtime": "remotion",
                      "approved_runtimes": ["remotion", "hyperframes"]})
```

This returns one compact row per scene, `{scene_id, runtime, reason}`, plus any
warnings (`RUNTIME_NOT_APPROVED`, `RUNTIME_UNAVAILABLE`). Downstream stages
only need these rows.

## 4. Execute (edit_decisions)

The project `render_runtime` is still the master assembly, and in v1 it must
be `remotion` (templated or atelier). List every approved runtime in
`edit_decisions.approved_runtimes`. Then, per cut:

- `footage`: an ordinary video or image cut with `"runtime": "footage"`.
- `remotion`: an ordinary templated cut. `"runtime"` may be omitted.
- `hyperframes`: `{"runtime": "hyperframes", "scene_id": "sc3", "hyperframes": {"workspace": "<dir>"}}`.
  `video_compose` renders that workspace to a clip and places it as this
  cut. Captions, audio and the rest of the assembly stay unchanged.

**HyperFrames scenes keep the visual-direction contract.** Before rendering,
`video_compose` writes `om-direction.js` into the workspace. It holds the
scene's `visual_timeline` events in scene-local seconds. The authored
`index.html` must:

1. load it: `<script src="om-direction.js"></script>` before the timeline script;
2. place every event of the scene on the GSAP timeline:
   `tl.to("#headline", {...}, OM.at("ev-b1"))` (or `data-om-event="ev-b1"`);
3. set the root `data-duration` to the cut length (`out_seconds - in_seconds`).

A missing script, an unplaced event, a stale event id or a wrong duration
refuses the render. `direction_qa` traces the workspace and checks that the
picture changes at each event in the final MP4.

**Atelier assembly:** keep the HyperFrames scene cuts in `edit_decisions.cuts`.
`video_compose` renders them, copies the clips into the public dir and passes
`props.sceneClips` (`[{scene_id, src, start, end}]`). The bespoke composition
must place each clip, e.g.
`<Sequence from={start*fps}><OffthreadVideo src={staticFile(clip.src)} /></Sequence>`.
Their events are traced in the HyperFrames workspace, not in the bespoke
source. A composition that never reads `sceneClips` is refused.

This is not a layer compositor. A scene has one main runtime.

## Debug / audit only

Planning never needs any of this. Use it when a tool looks wrong or missing:

- `python scripts/tool_capability_audit.py [--smoke]`: the evidence ladder
  (DISCOVERED → AVAILABLE → SMOKE_TESTED → OUTPUT_VERIFIED →
  PRODUCTION_VERIFIED; routable from OUTPUT_VERIFIED). Smoke calls are free
  offers only unless a paid tier is approved. Evidence is kept in the
  machine-level audit dir (`~/.openmontage/tool_audit`); local-only tools
  declare offers in `local_offers.json` there.
- `tool_router` `route`: the full `tool_plan` (candidates, rejections,
  fallbacks) from `visual_need`.
- `tool_router` `usage_report` / `direction_qa` with `tool_plan`: soft warnings
  for routed tools that production ignored.

Add a tool to routing by declaring `route_offers` (with a one-line `notes`
"use for") and `routing_smoke` on the tool class. Leave the selector
`capability` string alone.

## Worktrees

Remove OpenMontage worktrees with `python scripts/safe_worktree_remove.py <dir>`,
never with `git worktree remove --force`. On Windows, git follows the
node_modules / local-overlay junctions and empties the shared targets.
