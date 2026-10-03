# Director Authoring Guide — Visual Direction v1.2

Director가 쓰는 **사람용 연출안 문법**이다. 이 문서 하나로 40 `visual_direction_contract` 전체를 쓸 수 있고, 41 Persistent Visual Model의 세부 문법은 [`director-pvm-grammar.md`](director-pvm-grammar.md)에 따로 있다.

```
Director authoring (이 문법)
   → Director Authoring Bridge (결정적 변환, 8절)
   → 40 / 41 (schema-valid, canonical)
   → Planner는 창작 결정을 다시 해석하지 않는다
```

두 가지 실패를 막는 것이 목표다.
- **기계용 값이 사람용 문법에 섞이면 실패.** 문자 offset, hash, 접두어 붙은 ID, layer 소비 목록, 파생 그래프를 Director가 쓰면 안 된다 (1절).
- **창작 요구를 사람용 문법으로 표현할 수 없으면 실패.** 40/41이 잠글 수 있는 창작 결정은 모두 이 문법에 자리가 있다 (7절 매핑표).

---

## 1. Director가 쓰지 않는 것

아래는 모두 Bridge나 runtime이 만든다. 사람용 문서에 적으면 Bridge가 오류로 거부한다.

| 값 | 누가 만드나 |
|---|---|
| `SC009/A02` 같은 장면 접두어 ID | Bridge (장면 안에서는 `A02`만 쓴다) |
| 앵커 `source_span.char_start/char_end` | Bridge (`exact_text`를 canonical script에서 찾는다) |
| `canonicalization_id`, `script_sha256` | Bridge |
| `authority.pvm_ref.sha256`, fingerprint, `contract_ref` | Bridge / runtime |
| `lifecycle` (revision, status, locked_by/at) | Bridge의 잠금 단계 (사용자 승인) |
| `state.entered_by` / `exited_by` | Bridge (action의 from/to에서) |
| `execution_graph` | 쓰지 않는다. Bridge가 내부에서 계산해 검사만 하고 40에는 쓰지 않는다 (N8) |
| effective must_preserve core (LOCKED의 모든 state·action·invariant) | runtime 정규화 (D1) |
| `runtime_stack.*.consumes` | Bridge (8절 N9 규칙) |
| `qa_contract.checks` | 쓰지 않는다. 45는 적용 가능한 구조 검사를 항상 전부 실행한다 |
| action `completion_state_id` · `completion_condition` · `must_execute`, event `completion_condition` | 쓰지 않는다. v1.2에서 action 완료 = 그 action의 마지막 timeline 연산이 끝나는 시각이고, 모든 action은 필수다. 40에 앞의 둘이 있거나 `must_execute: false`면 contract 오류 |
| `qa_contract.review: auto`의 최종 판정 | runtime (D6) |
| `priority_policy`, `visual_identity.mechanism_compatibility`, `approval_scope`의 고정값, `downstream_contract` | Bridge (고정 상수 / 기본값) |
| 41 `current_state`, `state_history` | replay |
| 42 coverage, 43 binding, 45 receipt | 시스템 |

---

## 2. 파일 형식

사람용 연출안은 Markdown 파일 하나다 (`40_visual_direction_contract.md`, 원 설계 §34의 "사람용 view").

- `# PROJECT` 블록 하나, 그리고 장면마다 `## <장면 ID>` 블록 하나 (장면 ID는 `SC009`처럼 대문자로 시작).
- 블록 안은 `[섹션 이름]` 줄로 나뉘고, 각 섹션 본문은 **YAML**이다.
- `>`로 시작하는 줄은 Director 메모다. Bridge는 읽지 않는다 (기계 계약에 들어가지 않는다).
- **ID는 장면 안의 짧은 이름**(`AN01`, `S2`, `A02`, `META`)으로 쓴다. 다른 장면의 것을 가리킬 때만 `SC010/S0`처럼 장면을 붙인다. 모델과 모델 상태는 `CAPITAL_FLOW`, `CAPITAL_FLOW.REALLOCATED`.
- 41(PVM)은 별도 파일이다. 작성법은 `director-pvm-grammar.md`.

**Markdown은 사람용 껍데기이고, YAML 부분은 작은 DSL처럼 엄격하게 파싱된다.** Bridge는 모르는 구조를 조용히 무시하지 않는다:

- `[섹션]` 이름은 이 문서에 정의된 것만 인정한다 (프로젝트: `[PROJECT]` `[VIEWER JOURNEY]`, 장면: 4절의 섹션). 모르는 섹션 → 오류.
- 한 블록 안에서 같은 섹션이 두 번 나오면 오류. 같은 YAML mapping 안의 key 중복도 오류 (`AN01`을 두 번 쓰는 등).
- 섹션마다 허용된 key만 인정한다 (= 7절 매핑표의 사람용 열과 4절 예시의 key). 모르는 key → 오류.
- YAML anchor(`&`), alias(`*`), merge(`<<`), custom tag(`!`)는 금지 → 오류.
- boolean은 `true`/`false`만 인정한다 (YAML 1.2). `on`·`yes`·`no` 같은 낱말은 문자열이다 (`[EVENTS]`의 `on:` key가 이 덕분에 그대로 key로 읽힌다). 날짜처럼 보이는 값도 문자열로 남는다.
- 순서를 보존한다: 블록·섹션·mapping·목록은 쓴 순서대로 40에 옮겨진다.
- `>` Director 메모는 **섹션과 섹션 사이에서만** 허용된다. YAML 본문 안에서 `>`로 시작하는 줄은 메모가 아니라 오류다 (YAML folded scalar로 오해되지 않게).
- `# PROJECT`, `## <장면>`, `[섹션]` 머리, `>` 메모, 빈 줄 밖의 문장이 섹션 본문 바깥에 있으면 오류.

---

## 3. 프로젝트 블록

```markdown
# PROJECT
[PROJECT]
id: ai-capital-flow-mortgage-ko          # → artifact_id "<id>/visual-direction", project_id
script: examples/capital-competition/script.json   # 승인된 대본 (authority.script_ref)
narration: null                          # TTS 오디오가 생긴 뒤 (authority.narration_ref)
visual_identity: art-direction.md        # 선택
approval: {continue_pipeline: true, generated_media: true, cost_tools: false}

[VIEWER JOURNEY]
- id: J1
  scenes: [SC009, SC010]
  goal: 빅테크 채권 발행이 내 주담대 금리와 이어진다는 것을 이해한다
  feeling: 납득
```

**Viewer Journey**는 영상 전체의 연출 방향이다. 장면들을 묶어 "이 구간이 끝날 때 시청자가 얻어야 하는 것"을 적는다 (`viewer_journey[]`). 장면 단위의 Meaning Contract는 이 목표의 하위 단계여야 한다.

---

## 4. 장면 블록

섹션은 아래 순서로 쓴다. **필수 여부는 장면 종류마다 다르다** (5절 표).

### 4-1. `[SCENE]` — 중요도와 역할

```yaml
importance: REQUIRED_LOCKED     # REQUIRED_LOCKED | REQUIRED_FLEX | DISCRETIONARY
role: explanation               # establish_context, introduce_subject, build_tension, deliver_payload, transition,
                                # emotional_beat, evidence, comparison, resolution, call_to_action, immersion,
                                # explanation, breather, closure
mode: model                     # reality | model | evidence | text   (LOCKED·FLEX 필수)
```

- **REQUIRED_LOCKED**: 이해가 이 상태 변화에 달려 있다. 구현 자유만 있고 재해석은 없다.
- **REQUIRED_FLEX**: 보여야 할 것은 고정, 샷·크롭·미세 움직임은 자유.
- **DISCRETIONARY**: b-roll, 착지, 쉼.

### 4-2. `[MEANING CONTRACT]`

```yaml
before: 빅테크가 채권을 많이 발행한다는 사실만 안다
change: 같은 자금을 더 많은 채권이 나눠 갖는다
after: 자금 총량은 그대로인데 선택지가 늘어 같은 돈이 나뉘고, 그래서 발행자의 요구수익률이 오른다   # 필수
question: 빅테크가 채권을 많이 찍으면 왜 금리가 오르나?                                       # viewer_question
```

### 4-3. `[SHOW]` — 무엇을 보여줄지

장면이 보여주는 **대상**을 이름 붙여 적는다. 모델의 element면 `model`, 원본 자료면 `source`.

```yaml
POOL:       {model: CAPITAL_FLOW.POOL, role: 고정된 장기 투자자금, truth: METAPHORICAL, persistence: PVM, required: true}
META:       {model: CAPITAL_FLOW.META, role: "새 공급: 메타 채권", truth: METAPHORICAL, persistence: PVM}
YIELD_META: {model: CAPITAL_FLOW.YIELD_META, role: 메타가 제시해야 하는 요구수익률, truth: DERIVED}
RATE_TABLE: {type: document, role: 은행 혼합형 주담대 금리표, truth: SOURCE, source: kb_rate_table_capture.png, required: true}
```

| 키 | 뜻 | 40 |
|---|---|---|
| `model` | `<모델>.<element>` | `model_id` + `element_id` |
| `type` | document, footage, value … (선택) | `object_type` |
| `role` | 이 대상이 의미하는 것 (필수) | `semantic_role` |
| `truth` | 4-8 Truth 참조 | `truth_class` |
| `source` | 원본 파일/asset id. **정확한 출처 identity**로 비교된다 (SOURCE_IDENTITY_V1: 경로 끝 segment 전체가 같아야 하고, 파일명 일부만 같으면 다른 출처) | `source_asset` |
| `persistence` | SCENE · CROSS_SCENE · PVM | `persistence` |
| `required` / `removable` | 의미에 필수인가 / 지워도 되는가 | `semantic_necessity` |
| `layer` | 선택. 이 대상을 보이는 상태를 어떤 runtime layer가 맡는지 (N9 예외 routing) | `layer_id` |
| `parent` | 선택 | `parent_object` |

REQUIRED_FLEX 장면은 대상을 하나하나 잠그지 않고 보여야 할 것을 문장으로 쓴다:

```yaml
requirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]
```

### 4-4. `[ANCHORS]` — 타이밍

앵커는 **승인된 대본의 정확한 문구**다. 초(秒)는 쓰지 않는다. 시각은 TTS·정렬 뒤에 정해진다.

```yaml
AN01: 투자할 수 있는 장기 자금은 정해져 있습니다          # 기본 edge = START (문구가 시작되는 순간)
AN04: 더 높은 금리를 약속해야 했습니다
AN05: {text: 더 높은 금리를 약속해야 했습니다, edge: END}   # 문구가 끝나는 순간
AN02: {text: 메타와 아마존이 채권을 쏟아내기 시작했습니다, offset_ms: 200}
span: AN01..AN05                                         # 선택. 생략 시 N4 규칙
```

- 문구는 대본 그대로 쓴다. 공백·문장부호도 같아야 한다 (Bridge는 정규화하지 않는다).
- **문구가 대본 전체에서 두 번 이상 나오면 Bridge가 거부한다.** 출현 순번(`occurrence_index`)으로 고르지 않는다. 문구를 더 길게 써서 한 곳만 가리키게 한다.
- 같은 문구에 START와 END 앵커를 둘 다 둘 수 있다 (위 AN04/AN05).

### 4-5. `[PRESENTATION]` — 실제 화면 구성 (guidance)

```yaml
layers: [모델 다이어그램, 자막]
assets: []
source_pixels: 금리표는 크롭 없이 숫자 열이 읽히게
camera: 고정
text: 수치 라벨만, 문장 자막은 PhraseCaptions
sound: 재배분 순간 낮은 whoosh
readability: 모바일에서 숫자 판독 가능
transition_in: 직전 장면에서 컷
transition_out: 금리표로 매치컷
```

**Presentation은 안내이지 기계 판정 기준이 아니다.** 의미상 반드시 보여야 하는 것은 여기에만 적으면 잠기지 않는다. 그런 요구는 반드시 `[SHOW]`·`[STATES]`·`[LAST FRAME]`·`[MUST PRESERVE]` 중 맞는 곳에도 적는다. (예: "금리표 숫자가 읽혀야 한다"는 의미 요구면 RATE_TABLE을 `[SHOW]`의 SOURCE 대상으로, 상태의 `visible`로 잠근다.)

### 4-6. `[MOTION]` — 동적 Locked / 정적 Locked

```yaml
required: true                      # motion_required (LOCKED 필수)
static_replacement_valid: false     # 정지 화면으로 대체해도 되는가 (LOCKED 필수)
causal: true                        # 순서 자체가 인과 설명인가 → [CAUSAL] 필수
dependency: 총량이 그대로라는 것과 배분이 바뀌는 과정을 보지 못하면 금리 상승의 이유를 이해할 수 없다
temporal_logic: 공급 증가 → 재배분 → 수익률 상승의 시간 순서 자체가 인과 설명이다
decorative_motion_allowed: true
```

- **동적 Locked** (`required: true`): 상태 2개 이상, action 1개 이상, event 1개 이상이 필요하다.
- **정적 Locked** (`required: false`): action·event 없이 상태 하나로 잠근다 (예: 원본 문서를 정확히 보여주는 증거 장면).

### 4-7. 상태 변화: `[MODELS]` `[STATES]` `[ACTIONS]` `[EVENTS]` `[BEATS]` `[INVARIANTS]` `[CAUSAL]`

동적 Locked 장면의 핵심이다. 필요할 때만 PVM을 쓴다 (모델 정의는 41).

```yaml
[MODELS]
CAPITAL_FLOW: {enter: BASE, visibility: VISIBLE}     # 선택. handoff를 받는 장면은 필수 (pvm-grammar 6절)

[STATES]
S0: {pvm: CAPITAL_FLOW.BASE, meaning: "자금 100, 채권 선택지 2개", initial: true}
S1: {pvm: CAPITAL_FLOW.MORE_SUPPLY, meaning: "자금 100, 채권 선택지 4개, 배분은 아직 그대로"}
S2: {pvm: CAPITAL_FLOW.REALLOCATED, meaning: 같은 자금 100이 더 많은 채권 사이로 나뉨, invariants: [INV01]}
S3:
  pvm: CAPITAL_FLOW.YIELD_PRESSURE
  meaning: 공급 증가 → 자금 재배분 → 수익률 압력이 한 화면에서 확인됨
  also: {CAPITAL_FLOW: [{path: elements.ALLOC_META.visible, op: eq, value: true}]}   # object_states

[ACTIONS]
A01: {from: S0, to: S1, at: AN02, until: AN03, targets: [META, AMZN], type: ADD, min_seconds: 0.6,
      role: 메타·아마존 채권이 투자 선택지에 추가된다}
A02: {from: S1, to: S2, at: AN03, until: AN04, targets: [ALLOC_UST, ALLOC_META, ALLOC_AMZN], type: REALLOCATE,
      after: {A01: complete}, sync: REALLOCATE, min_seconds: 1.0,
      role: 같은 장기자금이 더 많은 채권 사이로 실제로 재배분된다}
A03: {from: S2, to: S3, at: AN04, until: AN05, targets: [YIELD_META], type: RAISE, after: {A02: complete},
      min_seconds: 0.6, role: 자금을 끌어오기 위해 요구수익률이 오른다}

[EVENTS]
E01: {on: AN02, from: S0, do: [A01], to: S1, next: E02}
E02: {on: AN03, from: S1, do: [A02], to: S2, next: E03}
E03: {on: AN04, from: S2, do: [A03], to: S3}

[BEATS]                                              # 발췌
B01: {at: AN01, function: 전제, new: 투자 가능한 장기자금 총량 100, after: S0}
B02: {at: AN02, function: 원인, new: 메타·아마존 채권 공급, before: S0, change: 채권 선택지 2개 → 4개, after: S1, actions: [A01]}

[INVARIANTS]                                         # 발췌
INV01: {constant: sum, paths: [ALLOC_UST.value, ALLOC_GOOG.value, ALLOC_META.value, ALLOC_AMZN.value],
        model: CAPITAL_FLOW, value: 100, description: 배분된 장기자금의 합은 100으로 유지된다}
INV03: {order: [A01, A02, A03], description: 공급 증가 → 재배분 → 수익률 상승 순서}

[CAUSAL]
CC01:
  proposition: 빅테크 채권 공급이 늘면 같은 투자자금이 나뉘고, 자금을 끌어오려는 발행자의 요구수익률이 오른다
  cause:  {state: S1, objects: [META, AMZN], actions: [A01], anchor: AN02}
  through: [{state: S2, objects: [ALLOC_UST, ALLOC_META, ALLOC_AMZN], actions: [A02], required: true}]
  effect: {state: S3, objects: [YIELD_META], actions: [A03], anchor: AN04}
  proof: {state: S3, observe: [CAUSE, INTERMEDIATE, EFFECT]}
  prohibit: [SEQUENTIAL_HIGHLIGHT_ONLY, STATIC_ARROW_ONLY, TEXT_ONLY, REMOVE_INTERMEDIATE_REACTION, SINGLE_FADE_FOR_MULTIPLE_ACTIONS]
```

규칙
- **State**는 화면 상태다. 기계 의미는 셋 중 하나 이상: 41 named state(`pvm`), 추가 assertion(`also`), 모델 밖 대상이 보임(`visible: [RATE_TABLE]`).
- **Action**은 `STATE → ACTION → STATE`. 언제(`at` 앵커)·무엇을(`targets`)·어디서 어디로(`from`/`to`). 함께 일어나야 하는 변화(한쪽에서 빼서 다른 쪽에 넣는 재배분)는 같은 `sync` 이름을 준다: 같은 시각·같은 길이로 실행되고 invariant는 그룹 전체가 적용된 뒤에 평가된다.
- **Event**는 한 앵커에서 함께 시작되는 action 묶음이다. 동적 Locked 장면은 **지금은 Event를 직접 쓴다** (9절).
- **Beat**는 문장이 아니라 의미·화면 변화의 단위다. 의미 있는 상태 변화마다 앵커가 있는 beat나 event가 하나 이상 있어야 한다.
- **Invariant**: `constant`(합계·값 유지), `holds`(조건 유지), `order`(순서 유지). 범위는 기본 장면 전체이고, `during: {from: S1, to: S3}`처럼 **상태 ID**로 좁힐 수 있다. action ID는 쓰지 않는다: 현재 runtime은 from/to가 둘 다 도달한 모델 상태일 때만 구간을 좁히므로, action ID를 쓰면 오류 없이 장면 전체로 검사된다. 경로를 `ALLOC_UST.value`처럼 줄여 쓰면 element 모델의 `elements.ALLOC_UST.attrs.value`다 (N7).
- **Causal**: 원인 → 중간 반응 → 결과 상태가 화면에서 실제로 일어나야 한다는 계약. `[MOTION] causal: true`면 필수.
- 상태의 선택 키: `until`(이 action·앵커 뒤에는 끝나도 됨), `bookkeeping: true`(화면에 보일 필요 없는 기록용 상태. 인과 중간 상태에는 쓰지 않는다).
- Beat의 `before`/`after`는 상태 ID, `meaning_before`/`meaning_after`는 시청자 이해를 적는 문장이다.
- 예외 routing: 핵심 변화를 `deterministic_graphics`가 아닌 layer가 맡는 action에만 `layers: [deterministic_graphics, character]`처럼 쓴다. 이것은 40의 action 필드가 아니라 Bridge routing hint다 (N9). 평범한 장면에서는 쓰지 않는다.
- `entered_by`/`exited_by`, `execution_graph`, 완료 조건(`completion_state_id`·`completion_condition`), `must_execute`는 쓰지 않는다. action은 마지막 timeline 연산이 끝날 때 완료되고 항상 필수다. to_state 도달은 따로 검사된다.

### 4-8. `[TRUTH]` — 사실과 출처

```yaml
- statement: 표시되는 금리 수치는 원본 금리표와 같다
  truth: SOURCE
  source: kb_rate_table_capture.png
```

| truth | 언제 |
|---|---|
| `SOURCE` | 원본 문서·캡처·실제 화면을 **그 자체로** 보여준다 (source pixels). `source`가 있어야 출처 검증(SOURCE_EVIDENCE)이 된다 |
| `FACTUAL` | 실제 수치·지도·데이터·차트처럼 사실을 다시 그린 것 |
| `DERIVED` | 사실에서 계산·추론한 값 (예: 모델 속 요구수익률) |
| `METAPHORICAL` | 메커니즘을 설명하는 비유 그림 |
| `DECORATIVE` | 의미 없음 |

- 대상 단위의 사실 등급은 `[SHOW]`의 `truth`/`source`, 장면이 전달해야 하는 사실 문장은 `[TRUTH]`.
- LOCKED 장면의 SOURCE 대상은 실제 편집 cut의 출처와 대조된다. 잠기지 않은 장면의 `[TRUTH] source`는 현재 UNVERIFIED로 남는다.

### 4-9. `[MUST PRESERVE]` — 추가 보존 항목만

LOCKED 장면의 **모든 state·action·invariant는 자동으로 보존 대상**이다 (D1). 여기에 다시 쓰지 않는다. 그 밖에 반드시 지켜야 하는 것만 적는다:

```yaml
beats: [B02, B03, B04]
objects: [POOL, META, AMZN, YIELD_META]
events: []
causal_chains: [CC01]
ordering: []                     # 이 순서로 일어나야 하는 id들
anchors: [AN02, AN03, AN04]      # 반드시 연산을 구동해야 하는 앵커
models: [CAPITAL_FLOW]           # 장면에서 실제로 실행돼야 하는 PVM
last_frame: [POOL, META, AMZN, YIELD_META]
cross_scene: []                  # 이 장면이 지켜야 하는 다른 장면
```

LOCKED 장면은 이 섹션이 비어 있어도 된다 (core는 자동).

### 4-10. `[ALLOWED FREEDOM]` / `[PROHIBITED SIMPLIFICATION]`

```yaml
[ALLOWED FREEDOM]
[LAYOUT_COORDINATES, SPACING, COMPONENT_STRUCTURE, TYPOGRAPHY_SIZE, EASING_CHOICE, MICRO_MOTION, EXACT_PARTICLE_COUNT]

[PROHIBITED SIMPLIFICATION]
[REMOVE_REQUIRED_ACTION, MERGE_LOCKED_ACTIONS, REORDER_LOCKED_ACTIONS, REMOVE_INTERMEDIATE_STATE,
 REPLACE_CAUSAL_MODEL_WITH_TEXT, REPLACE_PVM_WITH_UNRELATED_BROLL, ALTER_INVARIANT]
```

- 자유: `LAYOUT_COORDINATES` `SPACING` `COMPONENT_STRUCTURE` `TYPOGRAPHY_SIZE` `EASING_CHOICE` `MICRO_MOTION` `BACKGROUND_TEXTURE` `EXACT_PARTICLE_COUNT` `SOURCE_CROP_MARGIN` `TECHNICAL_OPTIMIZATION` `SHOT_CHOICE` `ASSET_CHOICE`. 인과 순서·action 제거·병합·state 제거·앵커 변경은 **어떤 Locked 장면에도 줄 수 없다** (목록에 없다).
- 금지는 장면에 실제로 해당하는 것만 쓴다. PVM이 없는 장면에 `REPLACE_PVM_WITH_UNRELATED_BROLL`을 쓰지 않는다.
- LOCKED 장면은 두 섹션 모두 필수다 (빈 목록 가능).

### 4-11. `[LAST FRAME]`

```yaml
state: S3                                       # 필수
end: AN05
visible: [POOL, META, AMZN, YIELD_META]
hidden: []
also: {CAPITAL_FLOW: [...]}                     # 추가 assertion
models: [CAPITAL_FLOW.YIELD_PRESSURE]           # persistent_states
motion: HOLD                                    # HOLD | SETTLING | CONTINUOUS
hold_seconds: 1.5
text: []                                        # 화면에 남아야 하는 글자
camera: null
next_scene: SC010                               # 장면 간 편집상 연결 (PVM 상속 아님)
handoff_objects: []
next_scene_seed: null
```

| 요구 | 판정 |
|---|---|
| `state`, `visible`/`hidden`(모델 대상), `also`, `models`, `motion: HOLD`, `hold_seconds` | 구조로 판정 (replay + binding) |
| 출처 대상의 `visible` | 실제 cut이 장면 끝을 덮고 출처가 같은가 |
| `text`, `camera`, `motion: SETTLING/CONTINUOUS`, 출처 대상의 `hidden` | 렌더가 필요 → **UNVERIFIED** (Phase 2). 구조로 판정할 수 있는 요구만 있으면 Last Frame은 PASS 가능 |
| `next_scene`, `handoff_objects`, `next_scene_seed` | 장면 간 연결 기록. 모델 상태를 다음 장면이 **이어받아야** 한다면 이것이 아니라 41 handoff (pvm-grammar 6절) |

### 4-12. `[RUNTIME]` — 어떤 runtime이 어떤 layer를 맡는가

```yaml
deterministic_graphics: {runtime: remotion, purpose: CAPITAL_FLOW 모델}
captions: {runtime: remotion, purpose: PhraseCaptions}
```

- layer: `base_visual` `factual_source` `deterministic_graphics` `generated_media` `character` `captions` `sound` `postprocess` `master_composite`.
- runtime: `remotion` `hyperframes` `footage` `generated` `audio` `none`.
- **무엇을 소비하는지(`consumes`)는 쓰지 않는다.** Bridge가 N9 규칙으로 정한다: 모델 action은 `deterministic_graphics`, 출처 대상을 보이는 상태는 `factual_source`, 그 밖의 모델 밖 상태는 `base_visual`. 그 layer를 선언하지 않으면 Bridge 오류다. (모델 action을 HyperFrames로 돌리고 싶으면 `deterministic_graphics`의 runtime을 `hyperframes`로 쓴다.)
- 기본 routing이 맞지 않는 장면만 예외를 쓴다: action에 `layers: [...]`, 모델 밖 대상에 `[SHOW]`의 `layer`. **적은 layer는 모두 실제 binding이 있어야 한다** (하나라도 unbound면 그 id는 미구현).
- FLEX/DISCRETIONARY는 `hint: footage`처럼 한 줄 힌트만 써도 된다 (`runtime_hint`).

### 4-13. `[FALLBACK]` — 대체 / Deviation

```yaml
allowed: []        # 미리 승인한 대체 (allowed_fallbacks)
```

`allowed: []`는 써도 되지만 40에는 `allowed_fallbacks`가 쓰이지 않는다 (빈 목록 규칙, 8절). 비어 있는지 생략했는지로 같은 계약의 fingerprint가 달라지지 않게 하기 위해서다.

목록에 없는 대체는 전부 deviation(44)이다: 작업은 멈추고 사용자가 결정한다. 실행 승인은 연출 변경 승인이 아니다.

### 4-14. `[REVIEW]` — 사람 리뷰 질문

```yaml
questions:
  - 자금 총량이 변하지 않은 채 배분이 바뀌는 과정이 화면에 보이는가?
  - 수익률 상승이 재배분 뒤에 일어나는가?
evidence_states: [S1, S2, S3]      # 리뷰어에게 프레임으로 뽑아 줄 상태
review: required                   # 선택: 강제로 켤 때만. 생략 = auto
```

- 구조 검사(action 존재, 상태 전이, invariant, 순서, 인과 사슬, 앵커 타이밍, 마지막 화면, 출처)는 contract에서 자동으로 나온다. **검사 목록을 쓰지 않는다.**
- 사람 리뷰(46) 필요 여부는 자동 판정된다: causal 계약 · action · PVM 전이 · `static_replacement_valid: false` 중 하나라도 있으면 필요. 그런 장면에 `review: not_required`를 쓰면 오류다.

### 4-15. `[PVM TRANSITIONS]` — FLEX / DISCRETIONARY 장면

잠기지 않은 장면이 PVM을 쓴다면, 그 장면이 반드시 해야 하는 전이만 적는다. 잠기지 않은 장면에서는 이것만 검사된다.

```yaml
- {model: CAPITAL_FLOW, from: MORE_SUPPLY, to: REALLOCATED}
```

### 4-16. `[OUTPUT]` (선택)

`expected_media_type`, `resolution`, `fps`, `duration_source`, `first_frame_contract`, `downstream_consumer` — 기본값과 다를 때만.

---

## 5. 장면 종류별 필수 섹션

| 섹션 | 동적 LOCKED | 정적 LOCKED | FLEX | DISCRETIONARY |
|---|---|---|---|---|
| `[SCENE]` (mode 포함) | 필수 | 필수 | 필수 | 필수 (mode 선택) |
| `[MEANING CONTRACT]` after | 필수 | 필수 | 필수 | 필수 |
| `[ANCHORS]` | 필수 | 필수 | 필수 | 필수 |
| `[SHOW]` | 대상 1개 이상 | 대상 1개 이상 | `requirements` | 선택 |
| `[MOTION]` required · static_replacement_valid | 필수 | 필수 | — | — |
| `[STATES]` (initial 표시) | 2개 이상 | 1개 이상 | — | — |
| `[ACTIONS]` · `[EVENTS]` | 각 1개 이상 | — | — | — |
| `[BEATS]` | 1개 이상 | 1개 이상 | 선택 | 선택 |
| `[CAUSAL]` | `causal: true`면 | — | — | — |
| `[ALLOWED FREEDOM]` · `[PROHIBITED SIMPLIFICATION]` | 필수 | 필수 | 선택 | 선택 |
| `[LAST FRAME]` | 필수 | 필수 | 선택 | 선택 |
| `[RUNTIME]` | N9의 layer 필수 | N9의 layer 필수 | 선택 | 선택 |
| `[MUST PRESERVE]` · `[REVIEW]` | 선택 | 선택 | — | — |
| `[TRUTH]` · `[PRESENTATION]` · `[FALLBACK]` · `[MODELS]` | 필요할 때 | 필요할 때 | 필요할 때 | 필요할 때 |
| `[PVM TRANSITIONS]` | — | — | PVM을 쓰면 | PVM을 쓰면 |

---

## 6. 예시 (capital-competition)

SC009 동적 Locked 장면은 4-7절이 전부다. 정적 Locked와 FLEX:

```markdown
## SC010
[SCENE]
importance: REQUIRED_LOCKED
role: evidence
mode: evidence

[MEANING CONTRACT]
after: 모델 속 압력이 실제 은행 금리표에 나타난다

[SHOW]
RATE_TABLE: {type: document, role: 은행 혼합형 주담대 금리표, truth: SOURCE,
             source: kb_rate_table_capture.png, required: true, removable: false}

[ANCHORS]
AN01: 은행 금리표에는 이 변화가 그대로 찍혀 있습니다
AN02: {text: 은행 금리표에는 이 변화가 그대로 찍혀 있습니다, edge: END}

[MOTION]
required: false
static_replacement_valid: true
dependency: 실제 문서를 정확히 보여주는 것 자체가 핵심

[STATES]
S0: {visible: [RATE_TABLE], meaning: 금리표 원본이 읽을 수 있게 보인다, initial: true}

[BEATS]
B01: {at: AN01, function: 증거, after: S0}

[TRUTH]
- {statement: 표시되는 금리 수치는 원본 금리표와 같다, truth: SOURCE, source: kb_rate_table_capture.png}

[MUST PRESERVE]
objects: [RATE_TABLE]

[ALLOWED FREEDOM]
[SOURCE_CROP_MARGIN, LAYOUT_COORDINATES]

[PROHIBITED SIMPLIFICATION]
[]

[LAST FRAME]
state: S0
hold_seconds: 2.0

[RUNTIME]
factual_source: {runtime: remotion, purpose: 금리표 원본 캡처를 읽을 수 있게 배치}

## SC014
[SCENE]
importance: REQUIRED_FLEX
role: immersion
mode: reality

[MEANING CONTRACT]
after: 추상 설명에서 현실 세계로 착지한다

[SHOW]
requirements: [실제 데이터센터 외관, 와이드, 시설 규모가 느껴질 것]

[ANCHORS]
AN01: 이 모든 돈은 결국 거대한 데이터센터로 향합니다
AN02: {text: 이 모든 돈은 결국 거대한 데이터센터로 향합니다, edge: END}

[BEATS]
B01: {at: AN01}

[ALLOWED FREEDOM]
[SHOT_CHOICE, ASSET_CHOICE, SOURCE_CROP_MARGIN, MICRO_MOTION]

[RUNTIME]
hint: footage
base_visual: {runtime: footage, purpose: 데이터센터 외관 실사}
```

---

## 7. 사람용 필드 → 40 / 41 매핑

`<s>` = 장면 ID. "Bridge"는 Director가 쓰지 않고 Bridge가 채우는 값.

### 7-1. 프로젝트

| 사람용 | 40 | 비고 |
|---|---|---|
| — | `schema_name` · `schema_version` · `artifact_role` | Bridge 상수 |
| `[PROJECT] id` | `project_id`, `artifact_id = <id>/visual-direction` | |
| — | `lifecycle` | Bridge: 새 문서 DRAFT, revision은 이전 잠금본 + 1. 잠금(LOCKED, locked_by/at)은 사용자 승인 단계 |
| `script` | `authority.script_ref` | |
| — | `authority.canonicalization_id` · `script_sha256` | Bridge (N3) |
| `narration` | `authority.narration_ref` | `narration_sha256`은 Bridge (오디오 bytes) |
| — | `authority.pvm_ref` {artifact, sha256} | Bridge (41의 canonical JSON hash) |
| — | `priority_policy` | Bridge 상수 |
| `approval` | `approval_scope` | 고정값(`locked_direction_mutation: false`, `semantic_fallback`·`causal_contract_change: requires_new_approval`)은 Bridge |
| `visual_identity` | `visual_identity.ref` | `mechanism_compatibility`는 Bridge 상수 |
| `[VIEWER JOURNEY]` id · scenes · goal · feeling | `viewer_journey[]` id · scene_ids · viewer_goal · feeling | |

### 7-2. 장면

| 사람용 | 40 scene | 비고 |
|---|---|---|
| `## <s>` | `id` | |
| `[SCENE]` importance · role · mode | `importance` · `role` · `visual_mode` | |
| `[MEANING CONTRACT]` before · change · after | `meaning_contract.*` | |
| `[MEANING CONTRACT]` question | `viewer_question` | |
| `[ANCHORS] <id>` | `anchors[]` {anchor_id `<s>/<id>`, exact_text, edge, offset_ms} | `source_span`은 Bridge (N2) |
| `[ANCHORS] span` | `narration_span` | 생략 시 N4 |
| `[MOTION]` required · static_replacement_valid · causal · dependency · temporal_logic · decorative_motion_allowed | `motion_reason.motion_required` · `static_replacement_valid` · `causal_explanation` · `understanding_dependency` · `temporal_logic` · `decorative_motion_allowed` | |
| `[SHOW] <id>` | `objects[]` (4-3 표) | object_id `<s>/<id>` |
| `[SHOW] requirements` | `requirements` | FLEX |
| `[MODELS] <model>` enter · visibility | `models[]` {model_id, enter_state `<model>.<enter>`, visibility} | |
| `[STATES] <id>` pvm · also · visible · meaning · invariants · until · bookkeeping | `states[]` pvm_state · object_states · visible_objects · semantic_meaning · invariants · valid_until · must_be_visible=false | `entered_by`/`exited_by`는 Bridge (N5) |
| `[STATES] initial: true` | `initial_state` | 장면에 정확히 하나 |
| `[ACTIONS] <id>` | `actions[]` from_state_id · to_state_id · start_anchor(`at`) · end_anchor(`until`) · target_objects · action_type(`type`) · semantic_role(`role`) · model_id(`model`) · path · easing · min_duration_seconds(`min_seconds`) · implementation_freedom(`freedom`) | `model` 생략 시 N6. `completion_state_id`·`completion_condition`·`must_execute`는 사람용에 없다 (v1.2 미지원) |
| `[ACTIONS] <id>` layers | — (40 필드 아님) | Bridge routing hint → `runtime_stack.<layer>.consumes` (N9) |
| `[ACTIONS]` after · before · with · wait_until · sync | `dependency.after[{action, on}]` · `before` · `with` · `wait_until` · `sync_group` `<s>/<sync>` | |
| `[EVENTS] <id>` on · from · do · to · next | `events[]` trigger_anchor · precondition_state · actions · resulting_state · next_event_dependency | 9절. event `completion_condition`은 v1.2 미지원 (40에 있으면 contract 오류) |
| `[BEATS] <id>` at · function · new · meaning_before · meaning_after · before · change · after · actions | `beats[]` anchor · narrative_function · new_information · meaning_before · meaning_after · visual_state_before · required_change · visual_state_after · linked_actions | `before`/`after`는 상태 ID |
| `[INVARIANTS] <id>` | `invariants[]` (N7) | |
| `[CAUSAL] <id>` proposition · cause · through · effect · proof · prohibit · visibility · dependencies | `causal_motion_contracts[]` proposition · cause · intermediate_reactions · effect · final_proof_state{state_id, viewer_can_observe} · prohibited_simplification · visibility · dependencies | |
| — | `execution_graph` | 쓰지 않는다 (N8: Bridge 내부 검사 전용) |
| `[TRUTH]` | `truth_requirements[]` | |
| `[PRESENTATION]` | `presentation.*` | guidance |
| `[MUST PRESERVE]` beats · objects · events · causal_chains · ordering · anchors · models · last_frame · cross_scene | `must_preserve.beats` · `objects` · `events` · `causal_chains` · `ordering` · `narration_anchors` · `persistent_models` · `last_frame_elements` · `cross_scene` | core(states·actions·invariants)는 runtime (D1). Bridge는 쓰지 않는다 |
| `[ALLOWED FREEDOM]` / `[PROHIBITED SIMPLIFICATION]` | `allowed_freedom` / `prohibited_simplification` | |
| `[LAST FRAME]` state · end · visible · hidden · also · models · text · camera · motion · hold_seconds · handoff_objects · next_scene · next_scene_seed | `last_frame_contract.required_state_id` · `end_anchor` · `visible_objects` · `hidden_objects` · `object_states` · `persistent_states` · `visible_text` · `camera_state` · `motion_state` · `minimum_hold_seconds` · `handoff_objects` · `handoff_to_scene` · `next_scene_seed` | |
| `[RUNTIME] <layer>` runtime · purpose | `runtime_stack.<layer>` runtime · purpose | `consumes`는 Bridge (N9) |
| `[RUNTIME] hint` | `runtime_hint` | |
| `[FALLBACK] allowed` | `fallback_contract.allowed_fallbacks` | `on_failure`는 Bridge 상수 |
| `[REVIEW]` questions · evidence_states · review | `qa_contract.review_questions` · `evidence_states` · `review` | `review` 생략 = `auto` (N10). `checks`는 쓰지 않는다 |
| `[PVM TRANSITIONS]` model · from · to | `pvm_transitions[]` {model_id, from `<model>.<from>`, to `<model>.<to>`} | |
| `[OUTPUT]` | `output_contract.*` | |
| `[APPROVAL]` (장면별 override, 선택) | scene `approval_scope` | |
| — | `downstream_contract` | Bridge 기본값 (생략) |

### 7-3. 41

41은 사람용 문법이 곧 JSON이다 (`director-pvm-grammar.md`). Bridge는 41을 스키마·의미 검증만 하고 바꾸지 않는다. 40 `authority.pvm_ref.sha256`만 41에서 계산한다.

---

## 8. 결정적 정규화 규칙 (Director Authoring Bridge)

Bridge는 사람용 문서 + 41 + 승인된 script를 받아 40을 만든다. **같은 입력은 항상 같은 40을 만든다** (순서는 문서 순서, 시각·난수 없음). Bridge는 창작 결정을 만들지 않는다: Meaning Contract, State/Action/Event의 의미, PVM 구조, causal 계약, allowed freedom, prohibited simplification은 오직 Director 입력에서 온다. 규칙으로 정할 수 없는 경우 Bridge는 추측하지 않고 오류로 멈춘다.

| # | 규칙 |
|---|---|
| N1 | **ID 한정.** 장면 `<s>` 안의 짧은 ID `X`(앵커·beat·object·state·action·event·invariant·causal chain)는 `<s>/X`가 된다. `/`가 들어간 ID는 그대로 둔다. `sync` 이름도 `<s>/<sync>`. 모델 ID·모델 상태(`M.S`)·장면 ID는 한정하지 않는다. 한정 결과가 중복되거나 참조가 어떤 ID로도 풀리지 않으면 오류. |
| N2 | **앵커 span.** `canonical_script_text`(N3)에서 `exact_text`를 찾는다. 0회 → 오류 "대본에 없는 문구". **2회 이상 → 오류 "모호한 앵커: 더 긴 exact_text가 필요"** (occurrence_index는 쓰지 않는다). 1회 → `source_span = [위치, 위치 + len)` (Unicode code point). `exact_text`는 바꾸지 않는다. |
| N3 | **대본 authority.** `canonicalization_id = SCRIPT_SECTIONS_TEXT_V1`, `script_sha256 = sha256(utf8(canonical_script_text))`. narration이 있으면 `narration_sha256 = sha256(오디오 bytes)`. `authority.pvm_ref = {artifact: persistent_visual_models, sha256: canonical JSON sha256(41)}`. |
| N4 | **narration_span 기본값.** `span`이 없으면 start = edge START인 앵커 중 char_start가 가장 작은 것 (없으면 전체 중 가장 작은 것), end = edge END인 앵커 중 char_end가 가장 큰 것 (없으면 char_start가 가장 큰 것). 같은 위치가 여럿이면 문서 순서상 먼저 쓴 것. |
| N5 | **entered_by / exited_by.** 장면에서 state `S`를 `to`로 갖는 action이 정확히 하나면 `entered_by`, `from`으로 갖는 action이 정확히 하나면 `exited_by`. 둘 이상이면 비워 둔다 (sync group의 여러 action). Director가 적었으면 오류 (1절). |
| N6 | **action model_id.** `model`이 없고 `from`·`to` 상태가 같은 모델의 `pvm` 상태면 그 모델. 아니면 비워 둔다. |
| N7 | **invariant 경로 축약.** `constant: sum/min/max` + `paths` → `target{model_id, aggregate, paths}`. 경로 하나의 값 유지는 `constant: value` + `path` → `target{model_id, path}`. 둘 다 `model`이 필요하다. `holds`는 모델별 assertion 목록(전체 경로), `order`는 action·event·state ID 목록. `<element>.<attr>` → `elements.<element>.attrs.<attr>`, `<element>.visible` → `elements.<element>.visible` (element 모델만, rail은 전체 경로를 쓴다). `during` 생략 = `scene`. |
| N8 | **execution_graph (내부 전용).** Bridge는 그래프를 계산한다: 노드 = 장면의 모든 beat·state·action·event, 간선 BEAT→ACTION (`linked_actions`), STATE→ACTION (action.from), ACTION→STATE (action.to), EVENT→ACTION (event.actions). 참조 오류와 순환을 검사하고, 통과하면 버린다. **40 `execution_graph`에는 쓰지 않는다** — runtime이 작성된 그래프와 파생 그래프의 동일성을 검사하지 않으므로, 쓰면 원본과 파생본 두 개가 생긴다. runtime에 그 검사가 생긴 뒤에 다시 정한다. |
| N9 | **runtime consumes.** LOCKED 장면만. 기본: 모델 action(`model_id` 있음) → `deterministic_graphics`. 모델 밖 상태 중 SOURCE 대상(`truth: SOURCE` 또는 `source` 있음)을 `visible`로 갖는 상태 → `factual_source`. 그 밖의 모델 밖 상태 → `base_visual`. **예외**: action에 `layers`가 있으면 기본 대신 그 layer들이 모두 consume한다. 모델 밖 상태는 `visible` 대상에 `[SHOW] layer`가 있으면 기본 대신 그 layer들(대상마다, 중복 제거)이 consume한다. 적은 layer는 모두 실제 binding이 필요하다 (43은 consume을 선언한 모든 layer를 검사). event와 action의 from/to 상태는 runtime이 action에서 함께 유도하므로(`_layer_consumes`) 쓰지 않는다. 모델이 없는 action은 기본 routing이 없으므로 `layers`를 반드시 쓴다 (없으면 오류). 필요한 layer가 `[RUNTIME]`에 없으면 오류. 결과는 layer 이름과 id를 문서 순서로. FLEX/DISCRETIONARY는 consumes를 쓰지 않는다. |
| N10 | **QA metadata.** `qa_contract = {review: <[REVIEW] review, 없으면 auto>, review_questions, evidence_states}` (LOCKED는 항상 객체를 만든다). `checks`는 쓰지 않는다. |
| N11 | **must_preserve.** 사람용 `[MUST PRESERVE]`를 키 이름만 바꿔 그대로 옮기고 빈 목록은 생략한다 (7-2). core ID(LOCKED의 state·action·invariant)를 덧붙이지 않는다 — effective must_preserve는 runtime이 load 때 계산한다 (D1). 40에는 Director가 추가로 지정한 보존 항목만 기록된다. LOCKED는 섹션이 없어도 `{}`를 쓴다 (스키마 필수). |
| N12 | **상수와 기본값.** `schema_name/version/artifact_role`, `priority_policy`, `visual_identity.mechanism_compatibility`, `approval_scope` 고정값, `fallback_contract.on_failure = DIRECTION_DEVIATION`. action의 `completion_state_id`·`completion_condition`·`must_execute`는 쓰지 않는다: v1.2에서 action 완료 = 마지막 timeline 연산 종료, 모든 action 필수 (40에 앞의 둘이 있거나 `must_execute: false`면 contract 오류). |
| N13 | **검증.** 결과 40을 스키마(`visual_direction_contract`)와 `validate_contract(40, 41, script)`로 검증한다. 오류가 하나라도 있으면 40을 쓰지 않는다. |

Bridge 오류 (사람용 문서를 고쳐야 하는 경우): 대본에 없는 앵커 · 모호한 앵커 · 풀리지 않는 참조 · 중복 ID · Director가 1절의 값을 씀 · `initial`이 0개 또는 2개 이상 · N9 layer 누락 · execution_graph 참조 오류·순환 · 파서 규칙 위반 (2절) · `validate_contract` 오류.

N1–N13 전체에 공통: **빈 목록과 빈 선택 객체는 쓰지 않는다** (스키마가 요구하는 LOCKED의 `must_preserve`, `allowed_freedom`, `prohibited_simplification`, `qa_contract`는 예외).

**round-trip 기준**: `examples/capital-competition/40_visual_direction_contract.md`를 Bridge로 컴파일한 결과가 `40_visual_direction_contract.json`과 같다 (lifecycle 시각은 고정 clock으로 맞춘다). `tests/tools/test_direction_authoring_bridge.py`가 이것을 검사한다.

```
python -m lib.direction_contract.authoring 40_visual_direction_contract.md --pvm 41_persistent_visual_models.json \
    --script script.json --out 40_visual_direction_contract.json [--lock-by user]
```

---

## 9. Event: 지금은 Director가 쓴다

동적 Locked 장면은 40 스키마가 Event 1개 이상을 요구하고, runtime은 Event를 다음에 쓴다: runtime layer의 암시적 소비 (action → 그 action의 event), lineage 구현 판정 (event의 action이 모두 구현되고 결과 상태가 구현되면 event 구현), ORDER invariant의 `contract_event_id`, 43 `consumes.event_ids`. 그래서 이번에는 Event를 Bridge 자동 생성 대상으로 바꾸지 않는다.

anchor + action으로 결정적 생성은 가능하다: 같은 `at` 앵커(또는 같은 `sync`)의 action을 한 event로 묶고, precondition = 첫 action의 from, resulting = 마지막 action의 to_state_id, next = 다음 묶음. 예시 E01–E03은 이 규칙으로 그대로 재현된다. 자동 생성으로 바꾸려면 먼저 필요하다:
1. 안정적인 event ID 규칙 (fingerprint와 기존 참조 보존),
2. 같은 앵커의 독립 action, `with`가 다른 앵커에 걸친 경우의 규칙,
3. 작성된 event와 파생 결과가 같아야 한다는 검사,
4. 테스트: 예시 재현, 42/43/45 결과 불변, ORDER의 event 참조 유지.

---

## 10. 원칙 요약

- Director는 **무엇이·어떤 순서로·어떤 불변식 아래** 변하는지 쓴다. 초·좌표·연산 이름·layer 소비·hash는 쓰지 않는다.
- 의미상 필수인 것은 반드시 기계가 판정하는 칸(state·object·last frame·must preserve)에 있어야 한다. Presentation은 안내다.
- 기계가 판정할 수 없는 요구(화면 글자, 카메라)는 쓸 수 있지만 Phase 1에서는 UNVERIFIED다.
- 바꿀 수 없는 것을 바꿔야 하면 deviation(44)으로 멈추고 새 승인을 받는다.
