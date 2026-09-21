# Tool Routing — needs first, verified tools second

## Why this exists

Installed tools were going unused. A tool could report `available`, but nothing
said *when* to use it, so planning fell back to the familiar runtime: every scene
became Remotion, and stock footage, HyperFrames, generated media and SFX sat idle.
Tool routing fixes this in two parts:

1. The scene director says **what a scene needs**, never which tool to use.
2. The router picks **verified** tools for each need. One scene can use several
   tools, e.g. stock footage + a precise graphic + an expressive overlay +
   narration + captions.

| Artifact | Answers | Written by |
|---|---|---|
| `scene_plan.scenes[].visual_need` | WHAT the scene needs (tool-agnostic) | scene director |
| `visual_direction` | WHAT changes, on which narration words | scene director |
| `tool_plan` | WHAT WITH: which verified tool fills each need | `tool_router route` |
| `visual_timeline` | WHEN (keeps `tool_layers` from the tool_plan) | edit director |
| composition | HOW it looks | templated / atelier |

Code: `lib/tool_routing.py`, `tools/analysis/tool_router.py`,
`scripts/tool_capability_audit.py`.

## 1. visual_need (scene director)

Each scene rates every relevant dimension `none | low | medium | high`.
`medium` or `high` is routed; `low` is only recorded.

| Need | Meaning | Fills role |
|---|---|---|
| `reality` | real places, people, objects, actions must be seen | visual_source |
| `impossible_visual` | something that cannot be filmed must be seen | visual_source |
| `information_precision` | exact numbers, labels, axes, diagrams | base_composition |
| `motion_expressiveness` | the motion itself carries the meaning | emphasis_overlay |
| `rhythm_accent` | a sound accent marks the beat | sound |
| `narration` / `word_sync` / `captions` / `mood` | project tracks | narration / sync / captions / music |

Add `cues` for the content type: `location`, `human_activity`,
`physical_object`, `infrastructure`, `nature`, `data_value`, `comparison`,
`process`, `diagram`, `timeline_axis`, `label`, `kinetic_text`, `major_reveal`,
`chapter_transition`, `metaphor`, `not_filmable`, `abstract_concept`,
`spoken_words`, `impact`, `ui_feedback`, `emotional_shift`.

```json
"visual_need": {"reality": "high", "information_precision": "medium",
                "motion_expressiveness": "high", "narration": "high",
                "word_sync": "high", "captions": "high",
                "cues": ["infrastructure", "data_value", "major_reveal"]}
```

**Do not name tools** in `visual_need`; the schema rejects unknown keys. Don't
name them in the scene description either, or the router raises
`TOOL_NAMED_IN_SCENE_PLAN`. Rate the need honestly: a scene about a real
place is `reality: high` even if you expect to draw it.

## 2. Capability audit: what this machine can actually do

A tool is routed only when it is **routable**. That means its route offer
metadata is complete and this machine has evidence that it produces valid
output. The evidence levels:

| Level | Evidence |
|---|---|
| DISCOVERED | registered with a route offer |
| AVAILABLE | dependencies / keys present (`get_status`) |
| SMOKE_TESTED | the smallest real call succeeded |
| OUTPUT_VERIFIED | that call's artifact exists and probes valid (ffprobe / JSON) → **routable** |
| PRODUCTION_VERIFIED | successful real-project calls in `projects/*/events.jsonl` (single-offer tools only; events do not name the offer) |

```bash
python scripts/tool_capability_audit.py            # levels from status + stored evidence, no calls
python scripts/tool_capability_audit.py --smoke    # + smallest real call per FREE offer
```

Paid and subscription offers are **never** called by the audit unless you pass
`--allow-cost-tier paid|subscription`, and you need the user's approval first.
The report and evidence live in the machine-level audit dir
(`~/.openmontage/tool_audit`, or `$OPENMONTAGE_TOOL_AUDIT_DIR`). Every checkout
and worktree shares it, and it is never committed. Evidence expires after 30
days or when the tool's version changes.

Tools that only exist on this machine (for example local Qwen3-TTS) declare
their offers in `<audit dir>/local_offers.json`, including a declarative smoke
call. The repo cannot carry them.

## 3. Route (asset director, before any spend)

```python
from tools.analysis.tool_router import ToolRouter
ToolRouter().execute({
    "operation": "route",
    "scene_plan": "projects/<project>/artifacts/scene_plan.json",
    "master_runtime": "remotion",                    # the approved render_runtime
    "approved_runtimes": ["remotion", "hyperframes"],  # every runtime the user approved at proposal
    "output_path": "projects/<project>/artifacts/tool_plan.json",
})
```

- Each scene gets `layers`, plus the `rejected` candidates and why, plus
  `unmet` needs with the unverified candidates that were blocked.
- `RUNTIME_NOT_APPROVED`: a verified offer fits these scenes, but its runtime
  was not approved. This follows the proposal-stage runtime rule in
  AGENT_GUIDE, so present it to the user. Do not quietly drop it.
- `NEED_UNMET`: no routable tool exists for the need. Either run the audit
  smoke for the blocked candidate (paid ones need approval), or tell the user
  this dimension will be missing.
- Selection is deterministic: strength for the need, cue matches, evidence
  level and cost tier, with ties broken by offer id.

## 4. Execute or override

Produce each layer with the chosen tool. For assets, record `source_tool` (and
`provider` when a selector delegates) with `scene_id` in `asset_manifest`, so
usage can be checked. If you deliberately skip a layer, append it to
`tool_plan.overrides` as `{scene_id, offer, reason}`. A reason like "user
supplied footage" is fine; silence is not.

Pass `tool_plan` to `visual_timeline_compiler` `compile`. It keeps
`tool_layers` on the timeline.

## 5. Usage QA (soft warnings)

`direction_qa` accepts `tool_plan` + `asset_manifest`. You can also call
`tool_router` with `operation: "usage_report"`. Possible warnings:

- `ROUTED_LAYER_IGNORED`: a routed layer was never used, and no override
  gives a reason.
- `REAL_WORLD_BROLL_UNDERUSED`, `EXPRESSIVE_RUNTIME_UNDERUSED`,
  `SYNTHETIC_VISUAL_UNDERUSED`, `SFX_UNDERUSED`,
  `STRUCTURED_GRAPHICS_UNDERUSED`: fewer than half of the scenes that needed
  it were honoured.
- `ROUTED_TRACK_IGNORED` and `NEED_UNMET`.

These warnings never block a render. The reviewer must address each one.
Static-screen excess is scored by `lib/slideshow_risk.py`, not here.

## Adding a tool to routing

Declare `route_offers = [RouteOffer(...)]` on the tool class, with axes,
scopes, triggers, strengths, fallback, runtime and cost tier. Implement
`routing_smoke(offer_id, workdir, cache)` as the cheapest real call that
writes an artifact. Leave the selector `capability` string alone: selectors
discover providers by it. Then run the audit with `--smoke`.
