# Art Direction — caffeine-clock ("오후 3시 커피의 시계")

## Subject
A cup of coffee drunk at 3 p.m. is a clock that keeps running long after the cup is empty.
The visual problem: make *time inside the body* feel physical — minutes of absorption,
hours of masking, a half-life that outlives the afternoon — and let the light of the day
itself cool from roast-gold to night-blue as caffeine lingers.

## Palette
- `#120B07` espresso — base for all graphic scenes (deep, warm black, never pure black)
- `#2A1A10` roast — dial face, secondary surfaces
- `#E9B872` crema gold — the absorption arc and the hero numerals
- `#F6EDE1` steamed milk — body text, dial ticks
- `#FF8A3D` caffeine amber — the masking arc and the active "now" marker
- `#22304F` → `#0E1424` dusk/night — sc5 background shifts toward this as evening arrives
Warm-to-cool drift across the piece *is* the story: the afternoon ends, the caffeine doesn't.

## Type personality
- Heading / numerals: **Hahmlet** (Korean serif with confident display weights) — feels like a
  café menu board printed in good ink; numerals 15:00, 45분, 50% set huge.
- Labels / UI / captions: **Noto Sans KR** — quiet, legible, never competes.
- No third face. Weight and scale do the accenting.

## Motion character
Slow pour, firm settle. Arcs *draw* like liquid filling a groove (ease-in-out cubic over the
contract's event duration, then a soft spring overshoot of 2–3 % on the leading edge).
Numbers count up with an `Easing.out(Easing.exp)` curve. Camera on the dial is a slow push
(scale 1.00 → 1.06 over a scene) — never whip. Footage gets a gentle 3 % push-in and warm
grade. Transitions are 12-frame cross-dissolves through espresso, except the HyperFrames
sc4 beat, which is the one *hard*, kinetic moment in the film.

## Layout & rhythm
- Footage scenes: full bleed, lower-left title block in Hahmlet, captions bottom-center.
- Dial scenes: the dial sits right-of-centre (cx = 62 % width), a tall typographic column on
  the left carries the one idea of that scene (big numeral + short label). Negative space
  above the dial is deliberate — the eye rests on the arc being filled.
- Rhythm: reality (7 s) → dial (7 s) → dial + veil (7 s) → HF slam (2.6 s) → night dial (6 s)
  → reality close (8 s).

## Signature device
**The caffeine clock dial** — a 6-hour arc (15:00 → 21:00) drawn like the rim of a coffee cup
seen from above, with the "liquid" (arcs) poured into it as the contract events fire.
It appears only in the three model scenes, each framed differently:
sc2 close crop on the 15:00–16:00 quadrant (absorption + the 45분 bracket),
sc3 full dial + the left-column "피로" word slowly covered by a frosted veil (masking),
sc5 the dial at night: a clock hand sweeps to 20:00 (half-life marker) and the arc pours on
past it into 21:00 ("남은 절반"), while a giant **50%** sits in the left column.

## Anti-references
- v1 of this same video: a flat Gantt rail in the top third with tiny labels and dead space.
- Generic "infographic" blue/purple gradients, neon glows, stock icon sets.
- Card-after-card explainer decks: no scene here may be "title text on a plain background".
