# Visual Direction v1.2 — machine schema 설계 (초안)

상태: **설계 초안. 구현 없음.** 스키마는 이 폴더의 `schemas/`에만 있고 런타임 경로(`schemas/artifacts/`, `lib/`)는 바뀌지 않았다.
기준: 포크 `origin/main` 4a9aed4 (Phase 0 병합 후). 원 설계: 사용자 문서 「연출안 형식 설계」(v1.2 Scene Schema, 섹션 1–30).

## 0. 고정 전제 (Phase 0 조사 결과로 확정)

1. 기존 Visual Direction 시스템을 **확장**한다. 새 병렬 시스템을 만들지 않는다.
2. 40 contract는 Planner의 산출물이 아니라 **Director가 주는 authority input**이다.
3. upstream `scene_plan`은 `additionalProperties: false` → lineage를 scene_plan에 넣지 않는다.
4. lineage / execution binding은 **독립 artifact**.
5. completion 강제 지점은 **`checkpoint_hooks.validate_stage`**.
6. atelier / HyperFrames trace는 execution binding에서 **공통 형식으로 정규화**.
7. state / invariant 검증은 **`replay_model_states` 계열**로 (렌더 없이 구조 검증).
8. pixel semantic QA는 Phase 1 자동화 대상이 아니다 → 잠긴 장면은 **사람 Direction Review**.
9. 정규 ID는 scene-qualified 형식 **`SC009/A02`**.

## 1. Artifact 지도 — 누가, 언제, 무엇을

| Artifact (registry 이름) | 파일 | 작성자 | 시점 | 권한 |
|---|---|---|---|---|
| `visual_direction_contract` (**40**) | `40_visual_direction_contract.json` | **Director** | script 승인 후, scene_plan 전 | 무엇이 어떤 순서로 변하는가 — 최종 권한 |
| `persistent_visual_models` (**41**) | `41_persistent_visual_models.json` | **Director** | 40과 함께 | PVM 정의·이름 붙은 상태·전이·handoff |
| `visual_direction` **1.2** (기존 확장) | `visual_direction.json` | Planner | scene_plan | production scene별 beat(모델 연산 1개) + `action_id`/`state_after_id` |
| `direction_lineage` | `direction_lineage.json` | Planner | scene_plan | production scene ↔ contract ID 대응표 |
| `visual_timeline` **1.2** (기존 확장) | `visual_timeline.json` | `compile_timeline` | edit | beat → 실제 초. event에 contract ID 유지 |
| `direction_binding` | `direction_binding.json` | `bind()` (자동) | compose | action → 장면·런타임·초·구현 코드 위치 |
| `direction_deviations` | `direction_deviations.json` | 작업자가 기록, **사용자가 결정** | 어느 단계든 | 구현 불가 시 중단 기록 |
| `direction_review` | `direction_review.json` | **사람** 리뷰어 | compose 후 | 잠긴 장면이 메커니즘을 실제로 보여주는가 |

- 40/41은 JSON이 실행 권한, `40_*.md`는 사람용 view.
- 모든 하위 artifact는 `contract_fingerprint`를 기록한다. 40/41이 바뀌면 하위 artifact는 **stale**이 되어 게이트를 통과하지 못한다.
- `visual_direction` 1.2에서는 `visual_models`가 **금지**된다. 모델은 41에서만 온다. Planner가 모델을 다시 정의할 수 없다.
- v1.2 artifact는 upstream 로더(`schemas/artifacts`, `validate_artifact`)를 쓰지 않는다. `direction_contract`가 자체 reference registry로 검증한다(교차 `$ref` 때문). → **upstream 파일 수정 0줄**.

## 2. 흐름

```
script(승인) ──▶ Director: 40 + 41 (approved, fingerprint)
                      │
scene_plan 단계 ──▶ Planner: scene_plan(upstream 그대로) + visual_direction 1.2 + direction_lineage
                      │  gate: validate_contract · fingerprint 일치 · check_lineage
edit 단계 ──▶ compile_timeline(+41 models) → visual_timeline 1.2 (action_id 유지)
                      │  gate: check_states (상태·invariant·순서·마지막 화면)
compose 단계 ──▶ render → traces → bind() → direction_binding · direction_qa · direction_review
                      │  gate: completion_gate (binding·QA·review·deviation)
                      ▼
               Production Complete
```
40이 없는 프로젝트는 지금(v1.0) 동작 그대로 간다.

## 3. 핵심 설계 결정

### 3.1 STATE → ACTION → STATE를 기존 엔진 위에 얹는다
- **State** = 모델 state signature에 대한 assertion 묶음 (`elements.<id>.visible`, `elements.<id>.attrs.<k>`, `measures`, `view`). 41의 `named_states`에 이름을 붙여 두고, 40은 `pvm_state: "CAPITAL_FLOW.REALLOCATED"`로 참조하거나 `checks`를 인라인으로 덧붙인다.
- **Action** = 한 모델을 `from_state`에서 `to_state`로 옮기는 의미 단위. 기존 **beat(모델 연산 1개)** 여러 개로 구현될 수 있다 → beat에 `action_id`.
- **Invariant** = assertion이 장면 동안 계속 참. 합계 같은 집계는 `aggregate: sum`.
- 근거: `replay_model_states` + `model_state_signature`가 이미 결정적으로 상태를 계산한다. 픽셀 없이 검증 가능.

### 3.2 중요도별 필수 필드
| | REQUIRED_LOCKED | REQUIRED_FLEX | DISCRETIONARY |
|---|---|---|---|
| 필수 | visual_mode, motion_reason, beats, models, initial_state, states(≥2), actions(≥1), allowed_freedom, prohibited_simplification, last_frame_contract, qa_contract(review=required) | visual_mode, beats | narration_span, meaning_contract만 |
| 검사 | lineage·상태·invariant·순서·binding·사람 리뷰 | lineage(beat 대응)만 | 없음 |

### 3.3 must_preserve는 "그래프 밖의 것"만
잠긴 장면의 states / actions / invariants / causal chain은 **기본적으로 전부 보존 대상**이다. 중복 나열하지 않는다. `must_preserve`에는 그래프로 표현되지 않는 것만 적는다: 내레이션 앵커, 마지막 화면 요소, PVM.

### 3.4 Invariant 평가 규칙 (프로토타입으로 확인)
- **같은 시각에 일어나는 연산을 모두 적용한 뒤** 평가한다. 동시에 바뀌는 여러 값(자금 재배분)은 중간 연산 하나만 보면 합계가 깨지기 때문이다.
- 평가 범위는 **contract 장면의 시간 창**(lineage가 가리키는 production scene들) 안으로 제한한다.
- 같은 시각에 묶인 연산은 **시작 시각과 길이가 같아야** 한다. 다르면 애니메이션 중간 프레임에서 invariant가 깨진다 (validator 규칙).

### 3.5 ID
- Director 장면: `SC009`. 하위: `SC009/B02`(beat), `SC009/S1`(state), `SC009/A02`(action), `SC009/INV01`, `SC009/POOL`(object).
- PVM: `CAPITAL_FLOW`, 이름 붙은 상태 `CAPITAL_FLOW.REALLOCATED`.
- production scene ID(`sc16`)와 beat ID(`sc16-b3`)는 Planner 네임스페이스. 연결은 `action_id`와 lineage로만.
- 두 trace 패턴(`useEventProgress("…")`, `OM.at("…")`)이 `/`를 포함한 ID를 그대로 받는다 (Phase 0 확인).

### 3.6 Fingerprint
`sha256` over canonical JSON of `{"contract": 40에서 approval 제외, "pvm": 41}` — key 정렬, 공백 없음, UTF-8. 표기 `sha256:<hex>`. 승인 메타데이터를 바꿔도 지문은 그대로, 내용이 바뀌면 달라진다. (`validate_examples.py`에 규칙 구현)

### 3.7 visual_direction / visual_timeline 1.2 변경분 (기존 스키마 기준 diff)
`derive_v12_schemas.py`가 현재 v1.0 스키마에서 1.2 초안을 생성한다. 변경은 이것뿐:
- `version`: `"1.0" | "1.2"` — **기존 v1.0 문서는 그대로 유효** (기존 fixture로 확인).
- `contract_fingerprint` (1.2 필수), `visual_models` (1.2에서 금지).
- beat / event에 `action_id`, `state_after_id`.

## 4. 금지된 단순화 → 무엇이 잡는가

| 코드 | 잡는 검사 | 단계 | 자동? |
|---|---|---|---|
| REMOVE_REQUIRED_ACTION | check_lineage (action에 beat 없음) + binding unbound | scene_plan / compose | 자동 |
| REMOVE_INTERMEDIATE_STATE | check_states (state_after 미도달 / assertion 실패) | edit | 자동 |
| REORDER_LOCKED_ACTIONS | compile_timeline 단조 커서(앵커 unmatched) + check_states 순서 | edit | 자동 |
| ALTER_INVARIANT | check_states invariant (같은 시각 그룹 단위) | edit | 자동 |
| MERGE_LOCKED_ACTIONS | 각 action의 event 시간 구간이 분리됐는지 + min_duration | edit | 자동 |
| COLLAPSE_MULTIPLE_BEATS_TO_SINGLE_REVEAL | contract beat마다 서로 다른 앵커 시각 | edit | 자동 |
| REPLACE_CAUSAL_MODEL_WITH_TEXT | lineage 장면의 visual_mode가 model이 아님 + 상태 미도달 | scene_plan / edit | 자동 |
| REPLACE_PVM_WITH_UNRELATED_BROLL | 같은 규칙 + 구현 trace 없음 | scene_plan / compose | 자동 |
| REPLACE_MOTION_WITH_HIGHLIGHT | 구조로는 일부만(연산 종류·길이). 최종 판단은 | compose | **사람 리뷰** |

"화면이 실제로 그렇게 보이는가"는 자동화하지 않는다. `qa_contract.review_questions` + `evidence_states`의 프레임으로 사람이 판정한다(`direction_review`).

## 5. 프로토타입 확인 결과 (버리는 스크립트, 저장소 밖)

예시: `examples/capital-competition/` — 실제 실패한 영상의 SC009(자금 경쟁)를 40/41로 쓰고, Planner 출력 두 가지를 비교.
기존 `compile_timeline` + `replay_model_states`만으로 검사를 흉내 냈다.

| 변형 | lineage | 중간 상태 | invariant | 순서 | 마지막 화면 |
|---|---|---|---|---|---|
| `good` (올바른 구현) | OK | S1·S2·S3 OK | OK | OK | OK |
| `as_produced` (A02를 비교 카드로 — **실제 제작**) | **A02 누락** | **S2 미도달** | OK | **A02 없음** | **실패** |
| 자금 총량 120 (META 30) | OK | OK | **위반** | OK | OK |
| 재배분 중 순간 80 | OK | OK | **위반 (7.16s)** | OK | OK |
| 수익률이 재배분보다 먼저 | OK | **S3 미도달** | OK | **unmatched** | **실패** |

→ 실제 실패는 네 가지 독립 검사에 걸린다. invariant는 상태 검사가 놓치는 경우(총량 변화, 순간 누락)를 잡으므로 필수.
→ 스키마 검증만으로는 `as_produced`도 통과한다. 의미 검사는 API의 몫이다.

## 6. API ↔ 데이터 대조 (구현 전 확정할 시그니처)

| API (소비자 경계) | 스키마가 요구하는 입력 | 현재 표의 시그니처와 차이 | 제안 |
|---|---|---|---|
| `load_contract` | 40 + 41 파일 | 없음 | `load_contract(path_40, path_41) → Contract` (contract, pvm, fingerprint, ID 색인). `40_*` 파일명과 artifact 이름 모두 허용 |
| `validate_contract` | 40 + 41 + **script** (앵커가 승인된 대본에 실제로 있는지, 순서) | **script 필요** | `validate_contract(contract, script) → {errors, warnings}` |
| `contract_fingerprint` | 40 + 41 | 없음 | 3.6 규칙 |
| `check_lineage` | contract + **direction_lineage** + visual_direction + scene_plan | **lineage artifact가 빠져 있음** | `check_lineage(contract, lineage, visual_direction, scene_plan) → coverage` |
| `compile_timeline` (기존) | visual_direction + alignment + **41 models** | **모델 출처 추가** (1.2에서 visual_models 금지) | `compile_timeline(direction, alignment, *, models=None, ...)` — 추가 인자만, v1.0 호출 그대로. event에 `action_id`/`state_after_id` 복사 |
| `bind` | contract + timeline + **edit_decisions**(컷별 런타임·장면 창) + 런타임별 raw trace | **edit_decisions 필요** | `bind(contract, timeline, edit_decisions, traces) → direction_binding` |
| `check_states` | contract(+41) + timeline + **장면 시간 창**(lineage + scene_plan/cuts) | **시간 창 필요** (invariant 범위) | `check_states(contract, timeline, lineage, scene_windows) → violations` |
| `record_deviation` / `open_deviations` | direction_deviations + fingerprint | 없음 | 프로젝트 디렉터리 기준, append-only |
| `completion_gate` | 위 artifact 전부 + **direction_qa 결과** | **direction_qa 결과가 지금은 artifact가 아님** (도구 출력 / final_review 안) | `completion_gate(stage, status, artifacts, pipeline_type)` — `validate_stage`와 같은 모양. direction_qa 결과를 artifact(`direction_qa_report`)로 남기거나 final_review에서 읽도록 결정 필요 |

추가로 필요해 보이는 것 (선택): `review_packet(contract, timeline, render)` — `evidence_states`의 시각을 `state_at`으로 구해 프레임을 뽑아 `direction_review` 초안을 만든다. 없으면 사람이 시각을 직접 찾아야 한다.

## 7. 단계별 게이트 (`checkpoint_hooks.validate_stage`)
40이 있을 때만 적용. 없으면 v1.0 게이트 그대로.

- **scene_plan 완료**: 40/41 스키마 유효 · `approval.status=approved` · `validate_contract` 오류 0 · visual_direction 1.2 / lineage의 fingerprint 일치 · `check_lineage` 누락 0 (누락은 open deviation이 있어야만 허용, 그 경우에도 compose에서 막힘)
- **edit 완료**: timeline 1.2 · unmatched 0 · `check_states` 위반 0 (잠긴 장면)
- **compose 완료**: 잠긴 action 전부 `bound` 또는 approved deviation · direction_qa hard failure 0 · review 필요한 장면 전부 PASS (같은 render sha256, 같은 fingerprint) · open/rejected deviation 0

## 8. 결정이 필요한 것

1. **must_preserve 기본값** (3.3): 잠긴 장면의 그래프 전체를 기본 보존으로 보는 것에 동의?
2. **invariant 평가 단위** (3.4): "같은 시각 그룹 적용 후 + 장면 시간 창 안"과 "동시 연산은 시작·길이 동일" 규칙.
3. **40/41 보관 위치**: 프로젝트 `artifacts/visual_direction_contract.json`, `persistent_visual_models.json`으로 저장하고 Director의 `40_`/`41_` 파일명은 `load_contract`가 받아들인다.
4. **visual_direction 1.2에서 visual_models 금지** (모델은 41에서만).
5. **REQUIRED_FLEX 검사 범위**: beat 대응(lineage)만 볼지, 상태 검사도 선택적으로 할지.
6. **사람 리뷰 필수 범위**: 모든 REQUIRED_LOCKED 장면에 review=required(스키마에 고정). 장면 수가 많으면 비용이 크다.
7. **앵커 정확도**: contract 검증은 대본에 **정확히(정규화 후) 존재**해야 통과, compile 단계는 기존처럼 0.8 유사도 허용.
8. **direction_qa 결과의 위치** (6절 completion_gate 행).
9. Director 출력 스키마: Director가 41의 `initial_state`와 `named_states`를 **element 단위로** 써야 한다. Director 쪽에 PVM을 element/attr로 쓰는 문법(가이드)이 필요하다.

## 9. 이 폴더

```
schemas/
  direction_common.schema.json            ID · assertion · 금지 코드 · deviation 사유 · fingerprint
  visual_direction_contract.schema.json   40
  persistent_visual_models.schema.json    41 (모델 정의는 기존 visual_model을 $ref)
  direction_lineage.schema.json
  direction_binding.schema.json
  direction_deviations.schema.json
  direction_review.schema.json
  visual_direction.v1.2.schema.json       생성물 (derive_v12_schemas.py)
  visual_timeline.v1.2.schema.json        생성물
examples/capital-competition/              40, 41, visual_direction(good / as_produced), lineage
derive_v12_schemas.py                      v1.0 → v1.2 변경분 정의 + 생성
validate_examples.py                       스키마 검증 + fingerprint 규칙
```

```bash
python docs/design/visual-direction-v1.2/derive_v12_schemas.py
python docs/design/visual-direction-v1.2/validate_examples.py
```

## 10. 이번 단계에서 하지 않은 것
API 구현, 런타임 스키마 등록, checkpoint 게이트 연결, Director 프롬프트 변경, 렌더 경로 변경. 프로토타입 검사 코드는 저장소에 넣지 않았다.
