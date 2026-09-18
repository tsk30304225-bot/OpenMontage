# Visual Direction — Planning-to-Render Contract

## Why this exists

Explainers kept losing meaning between planning and rendering:

```
script -> good plan -> good scene idea -> weak handoff -> compose simplifies -> a row of static infographics
```

The scene plan described a change in prose ("the second task grows to five days and pushes everything after it"), and compose had to reinterpret that sentence into a picture. Two artifacts close the gap:

| Artifact | Written by | Answers | Contains seconds? |
|---|---|---|---|
| `visual_direction` | scene director, next to `scene_plan` | **What** must change on screen, **why**, and at which narration words | No |
| `visual_timeline` | edit director, after TTS + forced alignment | **When** each change fires | Yes |

Renderers execute `visual_timeline`. They do not invent motion from `scene_plan.description`.

The contract is topic-agnostic. Core code knows model types, generic state, operations, anchors and timing. Everything a particular video means — what an item is, its labels, colors, the grammar, which queue policy fits the subject — is written in that project's `visual_direction`.

Schemas: `schemas/artifacts/visual_direction.schema.json`, `schemas/artifacts/visual_timeline.schema.json`.
Tools: `visual_timeline_compiler` (validate / compile), `direction_qa` (post-render).
Reference implementation: `lib/visual_direction.py` (Python mirror) and `remotion-composer/src/components/visual-models/` (renderer).
Reference fixture: `tests/fixtures/visual_direction/release_plan/`.

## 1. Viewer journey first

Before choosing any visual, split the video into 4-6 stretches and write what the viewer must **feel, understand or believe** at the end of each (`viewer_journey[]`). Typical shape:

| Stretch | viewer_goal pattern |
|---|---|
| opening | "I recognise this situation" (immersion) |
| setup | the obvious explanation is not enough |
| mechanism | how the thing actually works |
| evidence | this is sourced, not a guess (trust) |
| consequence | the trade-off the people involved face |
| ending | the opening, reinterpreted (closure) |

Visual choices follow from the goal. Footage is chosen because a stretch needs immersion, not because a scene needs filling.

## 2. Roles: when *not* to use a graphic

Every scene carries `narrative_role` (shared enum with `scene_plan`) and `visual_mode`:

| narrative_role | Job | Typical visual_mode |
|---|---|---|
| `immersion` | Put the viewer in the situation | `reality` — footage of the real place or activity |
| `explanation` | Show the mechanism | `model` — a persistent visual model changing state |
| `evidence` | Make the claim believable | `evidence` — the real document, dataset, citation |
| `comparison` | Contrast two states | `model` in `left`/`right` regions, or split footage |
| `transition` | Move between topics | short reality or text |
| `breather` | Let the viewer rest; no new information | `reality`, 2-4 s up to a scene (a door opening, a corridor, hands at work) |
| `closure` | Visually answer the opening | `reality` — leave the place you entered, finish the action you started |

Rules:

- **Not every moment needs a graphic.** When the narration carries no mechanism, a breather keeps the viewer inside the world. Filling every second with cards makes the viewer feel permanently "in a lecture".
- **Rhythm:** alternate `REALITY -> MODEL -> MODEL EVOLUTION -> EVIDENCE -> REALITY`. The validator warns after six scenes without an immersion/breather/closure scene, and `direction_qa` warns after 75 s of graphics without reality.
- **Open and close in reality** when footage is available. If the opening enters a place, the closure leaves it.
- Zero-footage videos are valid: use `text`/`evidence` scenes as the breathers and keep the same rhythm.

### Footage continuity without an actor

Stock footage cannot keep one person across a story. Keep it continuous through **objects, point of view, faceless framing and place** instead (`broll_intent.continuity`):

- object — the same kind of object recurring (a phone, a ticket, a tool, a package)
- pov — walking, opening, reaching: the viewer's own movement through the space
- faceless — hands, backs, feet
- place — the same kind of space at different moments

Use `person` only when one consistent source exists (one generated character, one shoot). List what to avoid (faces, logos, private data) in `must_avoid`.

## 3. Persistent visual model

Ask: *can the video's core ideas be explained as states of one reusable picture?* If yes, declare it once in `visual_models[]` and let scenes change its state instead of drawing a new graphic per concept.

```
today:   concept A -> graphic A,  concept B -> graphic B,  concept C -> graphic C
target:  one model -> state A -> state B -> state C
```

The model's `grammar` states what each visual property means in this video (`x_axis: working days`, `block_width: task duration`, `delay_color: waiting`). Keep the grammar, palette and labels fixed for the whole video.

### Supported model types

| type | Picture | Status |
|---|---|---|
| `timeline_rail` | items planned on an axis above the rail where they actually happen; wait lanes, idle gaps, deadline | implemented (Remotion) |

Planned next, in order: quantity/bar, flow/network, split-comparison, map. Do not approximate a missing type with prose — plan a templated/atelier scene instead and leave `visual_model_id` unset.

### timeline_rail

Fits any subject where planned positions on an axis turn into actual positions: schedules, queues, pipelines, project plans, production runs, release trains, itineraries.

**State** (`initial_state`):
- `axis {start, end, tick, format: number|clock, unit_suffix}` — `clock` renders values as HH:MM (value = minutes after midnight)
- `items[] {id, label, slot | planned_start, duration, ready_offset, present}`
- `slot_interval`, `deadline`, `resource_available_at`, `show_planned`, `show_actual`

**Model configuration** (chosen per video, not by core):
- `queue.policy`
  - `independent` — items happen at their own ready time; no shared resource (Gantt)
  - `sequential` — one shared resource, planned order (default)
  - `ready_first` — one shared resource that, when free, takes the earliest-planned item among those already ready, idling until the next item is ready
- `labels {planned, actual, wait, idle, overrun, deadline, duration, unit_suffix}` in the video's language
- `palette {background, ink, planned, delay, rule, idle}` from the video's visual identity

Waits, idle gaps and overrun are **derived** from state and policy, never drawn by hand.

| Operation | target | params | On screen |
|---|---|---|---|
| `ADD` | new item id | `item {…}` | a planned card and its actual block appear; later blocks move per policy |
| `REMOVE` | item id | — | planned card struck through, block disappears, the rail recovers |
| `EXPAND` | item id | `to` or `by` (may shrink), `propagate: immediate \| deferred` | block resizes |
| `SHIFT` | `slot_interval` / `view` / item id | `interval` · `start, end, tick, deadline, show_planned, show_actual` · `by` (re-plan) or `ready_by` (becomes ready later) | plan re-spaced, range or deadline moves, one item moves |
| `PROPAGATE` | item id or `all` | — | after a deferred `EXPAND`, later blocks slide to their consequences |
| `MEASURE` | item id or `all` | `metric: wait \| idle_before \| duration \| overrun`, `label?`, `exclusive?`, `clear?` | bracket with the derived value |

Use `EXPAND … propagate: deferred` + a later `PROPAGATE` when the narration separates cause and consequence ("testing takes five days … but every task after it slides").

## 4. Beats: events, not pictures

A scene with a model lists `beats[]`, one per change in narration meaning (a 10-20 s scene with one static state is a failure). Each beat:

| Field | Meaning |
|---|---|
| `narration_anchor` | exact script words where the change starts (must occur in the script, any language) |
| `operation`, `target`, `params` | the state change |
| `state_before`, `state_after` | human-readable states, for review |
| `takeaway` | what the viewer should conclude from this change |
| `anchor_at` / `offset_seconds` / `duration_seconds` | optional timing nudges |

```json
{
  "id": "b3",
  "narration_anchor": "testing takes five days",
  "operation": "EXPAND", "target": "testing",
  "params": {"to": 5, "propagate": "deferred"},
  "state_before": "2d", "state_after": "5d",
  "takeaway": "one estimate was wrong"
}
```

Anchors are matched in order with a moving cursor, so a phrase repeated later binds to the right occurrence. Pick anchors of 3-8 words, specific enough to be unique after the previous beat. Matching ignores case, spacing and punctuation; small spoken drift is accepted with a score below 1.0.

## 5. Pipeline flow

```
script
  -> scene_plan + visual_direction          (scene director; visual_timeline_compiler operation=validate)
  -> assets: narration WAV + forced alignment (e.g. qwen3_tts timestamps_path), footage, evidence
  -> edit: visual_timeline                  (visual_timeline_compiler operation=compile, alignment=<timestamps JSON>)
           edit_decisions.visual_timeline + cuts type=visual_model {model_id, region, caption}
  -> compose: video_compose renders Explainer; state = f(absolute time), so cuts on one model read as one graphic
  -> direction_qa                            (hard gate + soft warnings + anchor frames)
```

Scene timing in `scene_plan` stays approximate; exact times come only from the alignment.

## 6. Direction QA

`direction_qa` inputs: `video_path`, `visual_timeline`, `edit_decisions`, optionally `visual_direction`, `scene_plan`.

**Hard failures (block delivery):** unmatched anchor; event that changes nothing; event with no `visual_model` cut for its model on screen; rendered picture unchanged across the anchor (luma change below floor, caption band excluded).

**Warnings (reviewer judgement, never blocking):** weak visible change; a model holding still longer than 12 s; consecutive cuts switching models; all changes of a scene in its first 15 % (information revealed before it is narrated); long stretches without reality.

It writes `anchor_before` / `anchor_after` frames per event. Look at them: *did the change the narration describes happen, at that moment, and only then?* Pixels changing is necessary, not sufficient.

## Common failures

- A `model` scene whose beats do not change the state — the compiler reports `ineffective_events`.
- Anchors paraphrased instead of copied from the script — `validate` rejects them.
- Drawing a new chart for a consequence the model can show with one operation (`REMOVE`, `EXPAND`, `SHIFT`).
- Using graphics for a moment of movement through the world — that is a breather.
- A side-by-side comparison authored as one model with two meanings — use two models in `left` and `right` regions (the right cut uses `layer: overlay`).
- Choosing `queue.policy` by habit: pick the one that matches how the subject really behaves, and state it in `grammar`.
