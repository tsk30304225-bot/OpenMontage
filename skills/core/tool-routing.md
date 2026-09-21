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

## 5. Generated assets (not a scene runtime)

`codex_image`, `grok_cli_image` and `grok_cli_video` are **asset generation
tools**, not scene runtimes. A scene still picks `footage`, `remotion` or
`hyperframes`; a generated still or clip is an asset you make for that scene
(usually placed like footage). Nothing selects them automatically.

In the menu they show as `APPROVAL_REQUIRED`. That means they work on this
machine but spend the user's subscription credits: never call them without the
user's approval for that provider in this project (log it in `decision_log`,
then pass `subscription_approved: true`). Without approval, do not plan around
them and do not call them. Approval for Grok does not cover Codex, and vice versa.

Order:

1. Stock first. If Pexels/Pixabay footage or stills can show it, use stock.
2. Only when stock cannot show it, consider a generated asset:
   - readable text, labels, explanatory illustration, editing an existing image → `codex_image`
   - photoreal still of something that cannot be filmed → `grok_cli_image`
   - short generated shot → **still first, then video**: make and approve the start
     frame with `grok_cli_image` (or pick an existing image), then animate it
     with `grok_cli_video` (image-to-video only, 6 or 10 s, one camera move)
3. Read the tool's skill before the first call. These are local-overlay skills,
   present only on machines where the overlay is installed (the tool is missing
   from the registry otherwise):
   - `.agents/skills/codex-image/SKILL.md`
   - `.agents/skills/grok-cli-media/SKILL.md`

**Selector limit:** `image_selector` / `video_selector` discover these tools
but do not pass `subscription_approved`, so a selector call is refused by the
approval gate. After approval, call the tool directly, for example
`GrokCliVideo().execute({"prompt": ..., "image_path": ..., "duration": 6,
"subscription_approved": True, "output_path": ...})`, and record the asset
in `asset_manifest` with `source_tool` and `scene_id`.

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
