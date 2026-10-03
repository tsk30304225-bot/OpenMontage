# PROJECT
[PROJECT]
id: ai-capital-flow-mortgage-ko
script: examples/capital-competition/script.json
visual_identity: art-direction.md
approval: {continue_pipeline: true, generated_media: true, cost_tools: false}

> 사람용 Director 연출안 (director-authoring-guide.md). 40_visual_direction_contract.json은 이 문서를
> Director Authoring Bridge로 컴파일한 결과다: python -m lib.direction_contract.authoring

## SC009
[SCENE]
importance: REQUIRED_LOCKED
role: explanation
mode: model

[ANCHORS]
AN01: 투자할 수 있는 장기 자금은 정해져 있습니다
AN02: 메타와 아마존이 채권을 쏟아내기 시작했습니다
AN03: 같은 돈이 더 많은 채권 사이로 나뉘어 흘러갑니다
AN04: 더 높은 금리를 약속해야 했습니다
AN05: {text: 더 높은 금리를 약속해야 했습니다, edge: END}

[MEANING CONTRACT]
before: 빅테크가 채권을 많이 발행한다는 사실만 안다
change: 같은 자금을 더 많은 채권이 나눠 갖는다
after: 자금 총량은 그대로인데 선택지가 늘어 같은 돈이 나뉘고, 그래서 발행자의 요구수익률이 오른다
question: 빅테크가 채권을 많이 찍으면 왜 금리가 오르나?

[MOTION]
required: true
dependency: 총량이 그대로라는 것과 배분이 바뀌는 과정을 보지 못하면 금리 상승의 이유를 이해할 수 없다
temporal_logic: 공급 증가 → 재배분 → 수익률 상승의 시간 순서 자체가 인과 설명이다
causal: true
static_replacement_valid: false
decorative_motion_allowed: true

[BEATS]
B01:
  at: AN01
  function: 전제
  new: 투자 가능한 장기자금 총량 100
  after: S0
B02:
  at: AN02
  function: 원인
  new: 메타·아마존 채권 공급
  before: S0
  change: 채권 선택지 2개 → 4개
  after: S1
  actions: [A01]
B03:
  at: AN03
  function: 중간 반응
  new: 같은 돈의 재배분
  before: S1
  change: 배분이 바뀌고 총량은 유지
  after: S2
  actions: [A02]
B04:
  at: AN04
  function: 결과
  new: 요구수익률 상승
  before: S2
  change: 메타 요구수익률 4.5% → 5.2%
  after: S3
  actions: [A03]

[MODELS]
CAPITAL_FLOW: {enter: BASE, visibility: VISIBLE}

[SHOW]
POOL:
  type: value
  role: 고정된 장기 투자자금
  truth: METAPHORICAL
  model: CAPITAL_FLOW.POOL
  persistence: PVM
  required: true
  removable: false
UST: {type: node, role: 미국 국채, truth: METAPHORICAL, model: CAPITAL_FLOW.UST, persistence: PVM}
GOOG: {type: node, role: 구글 채권, truth: METAPHORICAL, model: CAPITAL_FLOW.GOOG, persistence: PVM}
META: {type: node, role: "새 공급: 메타 채권", truth: METAPHORICAL, model: CAPITAL_FLOW.META, persistence: PVM}
AMZN: {type: node, role: "새 공급: 아마존 채권", truth: METAPHORICAL, model: CAPITAL_FLOW.AMZN, persistence: PVM}
ALLOC_UST: {type: edge, role: 국채로 가는 자금, truth: METAPHORICAL, model: CAPITAL_FLOW.ALLOC_UST}
ALLOC_GOOG: {type: edge, role: 구글로 가는 자금, truth: METAPHORICAL, model: CAPITAL_FLOW.ALLOC_GOOG}
ALLOC_META: {type: edge, role: 메타로 가는 자금, truth: METAPHORICAL, model: CAPITAL_FLOW.ALLOC_META}
ALLOC_AMZN: {type: edge, role: 아마존으로 가는 자금, truth: METAPHORICAL, model: CAPITAL_FLOW.ALLOC_AMZN}
YIELD_META: {type: value, role: 메타가 제시해야 하는 요구수익률, truth: DERIVED, model: CAPITAL_FLOW.YIELD_META}

[STATES]
S0:
  meaning: 자금 100, 채권 선택지 2개
  pvm: CAPITAL_FLOW.BASE
  initial: true
S1:
  meaning: 자금 100, 채권 선택지 4개, 배분은 아직 그대로
  pvm: CAPITAL_FLOW.MORE_SUPPLY
S2:
  meaning: 같은 자금 100이 더 많은 채권 사이로 나뉨
  pvm: CAPITAL_FLOW.REALLOCATED
  invariants: [INV01]
S3:
  meaning: 공급 증가 → 자금 재배분 → 수익률 압력이 한 화면에서 확인됨
  pvm: CAPITAL_FLOW.YIELD_PRESSURE
  also:
    CAPITAL_FLOW:
      - {path: elements.ALLOC_META.visible, op: eq, value: true}

[ACTIONS]
A01:
  role: 메타·아마존 채권이 투자 선택지에 추가된다
  type: ADD
  targets: [META, AMZN]
  at: AN02
  until: AN03
  from: S0
  to: S1
  min_seconds: 0.6
A02:
  role: 같은 장기자금이 더 많은 채권 사이로 실제로 재배분된다
  type: REALLOCATE
  targets: [ALLOC_UST, ALLOC_META, ALLOC_AMZN]
  at: AN03
  until: AN04
  from: S1
  to: S2
  after: {A01: complete}
  sync: REALLOCATE
  min_seconds: 1.0
A03:
  role: 자금을 끌어오기 위해 요구수익률이 오른다
  type: RAISE
  targets: [YIELD_META]
  at: AN04
  until: AN05
  from: S2
  to: S3
  after: {A02: complete}
  min_seconds: 0.6

[EVENTS]
E01: {on: AN02, from: S0, do: [A01], to: S1, next: E02}
E02: {on: AN03, from: S1, do: [A02], to: S2, next: E03}
E03: {on: AN04, from: S2, do: [A03], to: S3}

[INVARIANTS]
INV01:
  description: 배분된 장기자금의 합은 100으로 유지된다
  constant: sum
  model: CAPITAL_FLOW
  paths: [ALLOC_UST.value, ALLOC_GOOG.value, ALLOC_META.value, ALLOC_AMZN.value]
  value: 100
  during: scene
INV02:
  description: 투자 가능한 장기자금 총량은 100
  constant: value
  model: CAPITAL_FLOW
  path: POOL.value
  value: 100
  during: scene
INV03:
  description: 공급 증가 → 재배분 → 수익률 상승 순서
  order: [A01, A02, A03]

[CAUSAL]
CC01:
  proposition: 빅테크 채권 공급이 늘면 같은 투자자금이 나뉘고, 자금을 끌어오려는 발행자의 요구수익률이 오른다
  cause: {state: S1, objects: [META, AMZN], actions: [A01], anchor: AN02}
  through:
    - {state: S2, objects: [ALLOC_UST, ALLOC_META, ALLOC_AMZN], actions: [A02], required: true}
  effect: {state: S3, objects: [YIELD_META], actions: [A03], anchor: AN04}
  dependencies: {effect_after_cause: true, intermediate_required: true}
  visibility: {cause_visible: true, intermediate_visible: true, effect_visible: true}
  proof: {state: S3, observe: [CAUSE, INTERMEDIATE, EFFECT]}
  prohibit: [SEQUENTIAL_HIGHLIGHT_ONLY, STATIC_ARROW_ONLY, TEXT_ONLY, REMOVE_INTERMEDIATE_REACTION, SINGLE_FADE_FOR_MULTIPLE_ACTIONS]

[MUST PRESERVE]
beats: [B02, B03, B04]
objects: [POOL, META, AMZN, YIELD_META]
causal_chains: [CC01]
anchors: [AN02, AN03, AN04]
models: [CAPITAL_FLOW]
last_frame: [POOL, META, AMZN, YIELD_META]

[ALLOWED FREEDOM]
[LAYOUT_COORDINATES, SPACING, COMPONENT_STRUCTURE, TYPOGRAPHY_SIZE, EASING_CHOICE, MICRO_MOTION, EXACT_PARTICLE_COUNT]

[PROHIBITED SIMPLIFICATION]
[REMOVE_REQUIRED_ACTION, MERGE_LOCKED_ACTIONS, REORDER_LOCKED_ACTIONS, REMOVE_INTERMEDIATE_STATE,
 REPLACE_CAUSAL_MODEL_WITH_TEXT, REPLACE_PVM_WITH_UNRELATED_BROLL, ALTER_INVARIANT]

[RUNTIME]
deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델}
captions: {runtime: remotion, purpose: PhraseCaptions}

[LAST FRAME]
state: S3
end: AN05
visible: [POOL, META, AMZN, YIELD_META]
models: [CAPITAL_FLOW.YIELD_PRESSURE]
motion: HOLD
hold_seconds: 1.5
next_scene: SC010

[FALLBACK]
allowed: []

[REVIEW]
questions:
  - 자금 총량이 변하지 않은 채 배분이 바뀌는 과정이 화면에 보이는가?
  - 수익률 상승이 재배분 뒤에 일어나는가?
evidence_states: [S1, S2, S3]

## SC010
[SCENE]
importance: REQUIRED_LOCKED
role: evidence
mode: evidence

[ANCHORS]
AN01: 은행 금리표에는 이 변화가 그대로 찍혀 있습니다
AN02: {text: 은행 금리표에는 이 변화가 그대로 찍혀 있습니다, edge: END}

[MEANING CONTRACT]
after: 모델 속 압력이 실제 은행 금리표에 나타난다

[MOTION]
required: false
dependency: 실제 문서를 정확히 보여주는 것 자체가 핵심
static_replacement_valid: true

[BEATS]
B01: {at: AN01, function: 증거, after: S0}

[SHOW]
RATE_TABLE:
  type: document
  role: 은행 혼합형 주담대 금리표
  truth: SOURCE
  source: kb_rate_table_capture.png
  required: true
  removable: false

[STATES]
S0:
  meaning: 금리표 원본이 읽을 수 있게 보인다
  visible: [RATE_TABLE]
  initial: true

[MUST PRESERVE]
objects: [RATE_TABLE]

[ALLOWED FREEDOM]
[SOURCE_CROP_MARGIN, LAYOUT_COORDINATES]

[PROHIBITED SIMPLIFICATION]
[]

[RUNTIME]
factual_source: {runtime: remotion, purpose: 금리표 원본 캡처를 읽을 수 있게 배치}

[LAST FRAME]
state: S0
hold_seconds: 2.0

[TRUTH]
- {statement: 표시되는 금리 수치는 원본 금리표와 같다, truth: SOURCE, source: kb_rate_table_capture.png}

## SC014
[SCENE]
importance: REQUIRED_FLEX
role: immersion
mode: reality

[ANCHORS]
AN01: 이 모든 돈은 결국 거대한 데이터센터로 향합니다
AN02: {text: 이 모든 돈은 결국 거대한 데이터센터로 향합니다, edge: END}

[MEANING CONTRACT]
after: 추상 설명에서 현실 세계로 착지한다

[BEATS]
B01: {at: AN01}

[SHOW]
requirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]

[ALLOWED FREEDOM]
[SHOT_CHOICE, ASSET_CHOICE, SOURCE_CROP_MARGIN, MICRO_MOTION]

[RUNTIME]
hint: footage
base_visual: {runtime: footage, purpose: 데이터센터 외관 실사}
