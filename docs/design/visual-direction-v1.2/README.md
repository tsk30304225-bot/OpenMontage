# Visual Direction v1.2 — machine schema 설계 (개정 초안 2)

상태: **설계. 런타임 구현 없음.** 스키마는 이 폴더의 `schemas/`에만 있고 `schemas/artifacts/`, `lib/`, `tools/`는 바뀌지 않았다.
기준 코드: 포크 `origin/main` 4a9aed4 (Phase 0 병합 후).
기준 문서: 사용자 원문 「연출안 형식 설계.txt」 **전체 (§0–§35, v1.1→v1.2 표)** + 2026-10-02 확정 결정 9개.

## 0. 고정 전제

| # | 전제 | 출처 |
|---|---|---|
| P1 | 기존 Visual Direction 시스템을 확장한다 (새 병렬 시스템 금지) | Phase 0 |
| P2 | 40은 Planner 산출물이 아니라 **Director authority input** | Phase 0, 원문 §0·§1 |
| P3 | upstream `scene_plan`(`additionalProperties: false`)에 lineage를 넣지 않는다 → **42 / 43 독립 artifact** | Phase 0, 원문 §25 대체 |
| P4 | completion 강제 지점 = `checkpoint_hooks.validate_stage` | Phase 0 |
| P5 | atelier / HyperFrames trace는 43에서 공통 형식으로 정규화 | Phase 0 |
| P6 | state / invariant 검증 = `replay_model_states` 계열 (픽셀 없음) | Phase 0 |
| P7 | pixel semantic QA는 Phase 1 자동화 대상 아님 | Phase 0 |
| P8 | 정규 ID = scene-qualified `SC009/A02` | Phase 0 |

### 확정 결정 (2026-10-02)

| # | 결정 | 반영 위치 |
|---|---|---|
| D1 | LOCKED의 states / actions / invariants는 **정규화 단계에서 자동으로 must_preserve에 포함**. Director는 beat·object·event·causal chain·ordering·anchor·PVM·last-frame·cross-scene만 추가로 적는다. `must_preserve` 필드는 유지 | 40 `must_preserve`, 5절 |
| D2 | invariant는 **장면 시간 창 안에서만**, **sync group 전체 적용 후** 평가. 같은 그룹 = 같은 start·duration | 40 `action.dependency.sync_group`, 1.2 beat `sync_group`, 7절 |
| D3 | 40/41은 프로젝트 artifact. 권위 = artifact identity + revision + fingerprint (파일명 숫자 아님). `40_*/41_*` 파일명 허용 | `contract_ref`, 2절 |
| D4 | visual_direction 1.2에서 모델 정의 금지. 모델 권위는 41 하나 | 1.2 delta |
| D5 | REQUIRED_FLEX는 가볍게: meaning, 보여야 할 것(`requirements`), 사실·출처(`truth_requirements`), runtime/asset 참조 무결성. 참조한 PVM 전이(`pvm_transitions`)만 검사 | 40 scene, 9절 |
| D6 | 사람 리뷰(46)는 **조건부**: causal contract · action/state 시퀀스 · PVM 전이 · `static_replacement_valid=false`. 정적 증거 LOCKED는 45 + 출처 검증으로 완료 | 40 `qa_contract.review: auto`, 9절 |
| D7 | 앵커 = **script digest + 정규화(NFC·공백) exact text (+ script_span_id/char span)**. fuzzy는 alignment(timeline)에서만. 잠긴 앵커가 다른 구간으로 resolve되면 deviation | 40 `anchors`, timeline `anchor_resolution`, 8절 |
| D8 | 번호: **40** contract · **41** PVM · **42** lineage · **43** execution_binding · **44** deviations · **45** direction_qa_report · **46** direction_review | 2절 |
| D9 | Director용 41 작성 문법 가이드 (새 엔진 아님, 기존 replay 모델의 표준 문법) | `director-pvm-grammar.md` |

## 1. 흐름

```
40 Director Contract (LOCKED, script digest)
      ↓
41 Project PVM
      ↓
42 Planner Lineage  +  visual_direction 1.2 (beats에 contract ID)
      ↓                         gate(scene_plan): validate_contract · fingerprint · check_lineage
visual_timeline 1.2 (anchor_resolution, event에 contract ID)
      ↓                         gate(edit): check_states (상태·invariant·순서·sync·마지막 화면)
43 System Execution Binding  ←  Runtime (Remotion templated / atelier / HyperFrames)
      ↓
45 Structural Direction QA (locked lineage receipt)
      ↓
46 Human Direction Review (필요한 장면만)
      ↓                         gate(compose): completion_gate
Production Complete
```
40이 없는 프로젝트는 v1.0 동작 그대로.

## 2. Artifact

| # | registry 이름 | 작성 | 단계 | 권한 |
|---|---|---|---|---|
| 40 | `visual_direction_contract` | Director | script 승인 후 | 무엇이·어떤 순서로·어떤 불변식 아래 변하는가 |
| 41 | `persistent_visual_models` | Director | 40과 함께 | 모델 정의(기존 `visual_model`) + 이름 붙은 상태·전이·handoff |
| 42 | `direction_lineage` | Planner | scene_plan | production scene별 consumed ID, transformed, `omitted_locked_ids: []` |
| — | `visual_direction` 1.2 | Planner | scene_plan | beat(모델 연산 1개) + `action_id` `state_after_id` `contract_event_id` `anchor_id` `sync_group` |
| — | `visual_timeline` 1.2 | `compile_timeline` | edit | event에 같은 ID + `anchor_resolution` |
| 43 | `execution_binding` | `bind()` | compose | action → 장면·런타임·초·구현 코드 위치(consumes/produces) |
| 44 | `direction_deviations` | 작업자 기록, **사용자 결정** | 어느 단계든 | 구현 불가 시 중단 |
| 45 | `direction_qa_report` | QA (자동) | compose | 구조 검사 + locked lineage receipt |
| 46 | `direction_review` | 사람 | compose 후 | 화면이 메커니즘을 실제로 보여주는가 |

- 모든 하위 artifact는 `contract_ref {artifact, artifact_id, revision, fingerprint}`를 가진다. 40/41이 바뀌면 stale → 게이트 실패.
- **Fingerprint**: `sha256` over canonical JSON `{"contract": 40 − lifecycle, "pvm": 41}` (key 정렬, 공백 없음, UTF-8). `lifecycle`(revision·status·잠금 메타)만 바뀌면 지문 불변.
- v1.2 artifact는 upstream 로더(`validate_artifact`)를 거치지 않는다. 교차 `$ref` 때문에 `direction_contract`가 자체 registry로 검증 → **upstream 0줄**.

## 3. 원문 대조표 (§별 반영 결과)

| 원문 | 반영 | 비고 / 의도적 차이 |
|---|---|---|
| §0 지위·헤더 | 40 `schema_name` `schema_version` `artifact_role` `artifact_id` `project_id` `lifecycle{revision,status DRAFT/LOCKED/SUPERSEDED}` `authority{script_ref,script_sha256,narration_ref,narration_sha256,plan_lock_ref}` | 40↔41 결합을 위해 `authority.pvm_ref` 추가. LOCKED는 `script_sha256` 필수 |
| §1 파이프라인 / 재요약 금지 | 1절 흐름, 42 `transformed`(의미 변경 불가) | |
| §2 우선순위 | 40 `priority_policy` (값 고정) | |
| §3·§33 중요도 | `importance` + 조건부 필수 | FLEX = D5 |
| §4 LOCKED 최소 | narration_span, meaning_contract, beats, motion_reason, initial_state, states, objects, must_preserve, prohibited_simplification, last_frame_contract, qa_contract 필수. **motion_required면** actions·events·states≥2 | **정적 증거 LOCKED**(motion_required=false)는 actions/events 면제 — D6과 일관. `dependencies`는 action.dependency로, `execution_graph`는 파생(아래) |
| §5 Narration authority | 40 scene `anchors[]` {anchor_id, script_span_id, exact_text, source_span, occurrence_index, edge, offset_ms} | resolution(status·time·frame)은 **timeline 1.2 `anchor_resolution`**에 둔다 (40은 resolve 결과로 바뀌지 않음, D7) |
| §6 Beat | `beat_id, anchor, narrative_function, meaning_before, new_information, meaning_after, visual_state_before/after, required_change, linked_actions` | `narration_span` → `anchor` 참조 |
| §7 State 일급 | `state_id, semantic_meaning, pvm_state / object_states / visible_objects, invariants, entered_by, exited_by, must_be_visible, valid_until` | `object_states` = 기계 판정 가능한 assertion. 모델 밖 대상은 `visible_objects`(렌더 후 판정) |
| §8 Invariant | `kind: CONSTANT`(target + value) · `ASSERT`(holds) · `ORDER`(order) + `during` | 원문 `CAUSAL_ORDER` = `ORDER` |
| §9 Object | `object_id, object_type, semantic_role, truth_class, model_id+element_id, layer_id, source_asset, parent_object, persistence, semantic_necessity` | `initial_state/lifecycle/actions`는 모델·state·action 쪽에서 표현 (중복 방지) |
| §10 Action | `action_id, semantic_role, action_type, model_id, target_objects, start_anchor, end_anchor, from_state_id, to_state_id, path, easing, dependency{after,before,with,wait_until,sync_group}, completion_condition, completion_state_id, implementation_freedom, must_execute, min_duration_seconds` | 원문 `from_state/to_state`(서술)는 state 객체가 대신함 |
| §11 Causal motion | `causal_motion_contracts[]` {causal_chain_id, proposition, cause, intermediate_reactions[], effect, dependencies, visibility, final_proof_state, prohibited_simplification(5종)} | 배열(장면에 인과 사슬 여러 개 가능). `motion_reason.causal_explanation=true`면 필수 |
| §12 Motion reason | `motion_required, understanding_dependency, temporal_logic, causal_explanation, static_replacement_valid, decorative_motion_allowed` | `causal_explanation` 추가 (§4 "인과 Scene이면"의 기계 판정용) |
| §13 Event | `events[]` {event_id, trigger_anchor, precondition_state, actions, resulting_state, completion_condition, next_event_dependency} | timeline의 event(=연산 1개)와 다른 개념 → timeline event에 `contract_event_id` |
| §14 Execution graph | 선택 필드. **정규화가 beats/states/actions/events에서 파생**, 작성됐다면 파생 결과와 같아야 함 + 비순환 | 같은 정보를 두 번 쓰지 않게 |
| §15 must_preserve | 11개 키 + `cross_scene` | **D1**: core(states/actions/invariants) 자동 포함 |
| §16 allowed_freedom | 부여된 자유만 enum 배열로 | false 항목(causal_order, action_removal, action_merge, state_removal, narration_anchor_change)은 **LOCKED에서 절대 부여 불가**로 고정 (NEVER_FREE) |
| §17 prohibited_simplification | 9종 그대로 | |
| §18 Runtime stack | 40 `runtime_stack` 9개 층 {runtime, purpose, consumes} | 실제 실행 결과는 43(`consumes/produces`). v1 장면 런타임은 장면당 1개 + 자막/오디오 — 아래 제약 참고 |
| §19 Atelier boundary | `allowed_freedom` + NEVER_FREE + must_preserve로 표현 | 별도 필드 없음 |
| §20 Visual identity | 40 `visual_identity.mechanism_compatibility` (true 고정) | |
| §21 Truth | `truth_class` (object, truth_requirements) | |
| §22 PVM | 41: definition(=components), `semantic_role`, named_states, transitions, handoffs, persistence{first/last_scene, default_visibility VISIBLE/HIDDEN_BUT_ACTIVE} | `current_state/state_history`는 **replay로 파생**, 작성하지 않음 |
| §23 Last frame | `required_state_id, end_anchor, visible/hidden_objects, object_states, persistent_states, visible_text, camera_state, motion_state, minimum_hold_seconds, handoff_objects, handoff_to_scene, next_scene_seed` | |
| §24 Output contract | 40 `output_contract` | `embedded_lineage_metadata`는 43이 담당 |
| §25 Scene plan 역할 | **42 lineage + 43 binding**이 담당 (P3) | upstream scene_plan 무변경 |
| §26 Anchor resolution | timeline 1.2 `anchor_resolution{resolved_anchors[status EXACT/REVERSIBLE_NORMALIZATION/FUZZY, same_span], unresolved_anchors}` + `action_timing_binding`은 43 action의 start/end | |
| §27 Downstream lineage | 42 {contract_ref, consumed(beat/state/action/event/anchor/invariant/object/pvm), transformed, added_implementation_fields, **omitted_locked_ids: maxItems 0**} | |
| §28 Deviation | 44 {deviation_id, scene_id, affected_contract_ids, reason(+OTHER), semantic_impact NONE/MINOR/MATERIAL, proposed_change, approval_required, status PROPOSED/APPROVED/REJECTED/WITHDRAWN, decision} | MATERIAL → approval_required=true (스키마 강제). 잠긴 must_preserve에 닿으면 impact와 무관하게 승인 필요 |
| §29 Approval scope | 40 `approval_scope` (top + scene override). `locked_direction_mutation: false` 고정, semantic_fallback·causal_contract_change = requires_new_approval | 실행 승인 ≠ 연출 변경 승인 |
| §30 Direction QA | 45 `checks[]` {type: ACTION_EXISTENCE, ORDER, STATE_TRANSITION, INVARIANT, CAUSAL_CHAIN, ANCHOR_TIMING, PERSISTENT_STATE, LAST_FRAME, PROHIBITED_SIMPLIFICATION (+BINDING, SOURCE_EVIDENCE, PIXEL_CHANGE)} result PASS/FAIL/UNVERIFIED | 기존 `direction_qa` 도구의 픽셀 검사는 `PIXEL_CHANGE` 보조 증거 |
| §31 Locked lineage receipt | 45 `scenes[].receipt` (LOCKED 필수) | `deviated` 추가 (승인된 deviation 면제분) |
| §32 완료 조건 | `completion_gate` (10절) | |
| §34 사람용 템플릿 | `40_*.md` view. 문법 가이드 7절이 매핑 | |
| §35 최종 Scene 필드 | 전부 대응 (`layers/assets/source_pixels/camera/text/sound/readability/transition_*` → `presentation`, `approval_scope/downstream_contract/fallback_contract/output_contract` 각 필드) | |

## 4. 정규화 (`load_contract`가 하는 일)

1. 40·41 스키마 검증 (공통 registry).
2. **effective must_preserve** = 작성된 must_preserve ∪ (LOCKED면) 모든 state·action·invariant ID. (D1)
3. execution_graph 파생: BEAT→ACTION(linked_actions), STATE→ACTION(from), ACTION→STATE(to), EVENT→ACTION. 작성본이 있으면 동일성 검사, 비순환·미해결 의존 검사.
4. 기본값: `completion_state_id = to_state_id`, `must_execute = true`, `occurrence_index = 0`, `review = auto`.
5. **review 해석** (D6): `auto` → causal contract 있음 · action 있음 · `pvm_transitions` 있음 · `static_replacement_valid=false` 중 하나면 required, 아니면 not_required. 그 경우 `not_required`를 쓰면 contract 오류.
6. fingerprint 계산, ID 색인 생성.

## 5. `validate_contract`의 의미 규칙 (스키마 밖)

- ID 유일성, 접두어 = 장면 ID (`SC009/…`는 SC009에만).
- 참조 해석: beat.anchor, action.start/end_anchor, from/to state, dependency, event.actions, invariant.order/during, causal link, last_frame, must_preserve, object.model_id+element_id(41에 존재), pvm_state(41 named_states에 존재).
- 앵커: script_sha256 일치, exact_text가 정규화 script의 `occurrence_index`번째 출현으로 존재, char span이 있으면 일치, narration_span 안에 beat·action 앵커가 문서 순서대로.
- 상태 사슬: action `from → to`가 41 `transitions`에 허용, initial_state가 enter_state(또는 handoff) assertion을 만족(41 initial_state로 계산), `entered_by/exited_by`가 action과 일치.
- causal: cause·intermediate·effect 상태가 action 순서와 일치, final_proof_state 존재.
- NEVER_FREE 항목이 allowed_freedom에 없음 (스키마 enum에 아예 없음).
- sync_group: 같은 그룹 action은 같은 start_anchor.

## 6. 앵커 (D7)
- contract: exact authority reference. 바뀌지 않는다.
- alignment(compile_timeline): EXACT → REVERSIBLE_NORMALIZATION → FUZZY 순으로 resolve하고 결과를 timeline `anchor_resolution`에 기록.
- **잠긴 앵커가 FUZZY로, `same_span: false`로 resolve되면 경고가 아니라 deviation(44) 대상.** contract를 fuzzy 결과로 조용히 고치지 않는다.

## 7. Invariant · sync 평가 (D2, 프로토타입으로 확인)
- 평가 시점: 같은 sync group(없으면 같은 시각)의 연산을 **모두 적용한 뒤**.
- 평가 범위: contract 장면의 시간 창 = 42가 그 장면에 대응시킨 production scene들의 첫 연산 ~ 마지막 연산 종료.
- 같은 sync group 연산의 resolved start·duration이 다르면 위반 (애니메이션 중간 프레임에서 실제로 깨지기 때문).
- `CONSTANT`의 `value` 생략 시 범위 시작 시점 값이 기준.

## 8. 금지된 단순화 → 판정

| 코드 | 판정 | 단계 | 자동 |
|---|---|---|---|
| REMOVE_REQUIRED_ACTION | action에 beat 없음 / 42 consumed와 불일치 / 43 unbound | scene_plan·compose | ✓ |
| REMOVE_INTERMEDIATE_STATE | state 미도달·assertion 실패 (replay) | edit | ✓ |
| REORDER_LOCKED_ACTIONS | ORDER invariant · dependency · 앵커 단조성 | edit | ✓ |
| ALTER_INVARIANT | CONSTANT/ASSERT 위반 (sync group 단위) | edit | ✓ |
| MERGE_LOCKED_ACTIONS | action별 연산 시간 구간 분리 + min_duration | edit | ✓ |
| COLLAPSE_MULTIPLE_BEATS_TO_SINGLE_REVEAL | contract beat마다 서로 다른 resolved 시각 | edit | ✓ |
| REPLACE_CAUSAL_MODEL_WITH_TEXT / _PVM_WITH_UNRELATED_BROLL | 대응 장면 visual_mode가 model 아님 + 상태 미도달 + binding 없음 | scene_plan·edit·compose | ✓ |
| REPLACE_MOTION_WITH_HIGHLIGHT (+ 원문 §11 5종) | 구조로는 연산 종류·길이까지. 최종 판정은 46 | compose | 사람 |

## 9. 장면 유형별 완료 조건

| 유형 | 45 (구조) | 46 (사람) | 기타 |
|---|---|---|---|
| LOCKED · 동적 (causal / action / PVM 전이 / static_replacement_valid=false) | receipt PASS | **PASS 필요** | 43 전부 bound 또는 승인된 deviation |
| LOCKED · 정적 증거 | receipt PASS (SOURCE_EVIDENCE·LAST_FRAME은 렌더 후) | 불필요 | 출처 일치 |
| REQUIRED_FLEX | requirements·truth·참조 무결성, 참조한 PVM 전이만 | 불필요 | |
| DISCRETIONARY | 없음 | 불필요 | |

## 10. 단계별 게이트 (`checkpoint_hooks.validate_stage` → `completion_gate`)
40이 있을 때만. 
- **scene_plan 완료**: 40 `LOCKED` · `validate_contract` 오류 0 · 42/visual_direction 1.2의 contract_ref 일치 · `check_lineage` (omitted 0, PROPOSED deviation이 있으면 통과는 하되 compose에서 막힘)
- **edit 완료**: timeline 1.2 · 잠긴 앵커 unresolved 0 · same_span=false는 deviation 존재 · `check_states` 위반 0
- **compose 완료**: 43 잠긴 action 전부 bound/deviated(APPROVED) · 45 verdict PASS (LOCKED receipt 전부 PASS) · 46 필요한 장면 전부 PASS (같은 render sha256·contract revision) · PROPOSED/REJECTED deviation 0

## 11. API (시그니처 확정안 — 구현 전)

| API | 입력 | 출력 | 이전 표 대비 |
|---|---|---|---|
| `load_contract(path_40, path_41)` | 40, 41 | `Contract` (정규화본: effective must_preserve, 파생 graph, review 해석, fingerprint, ID 색인) | 정규화 포함 명시 |
| `validate_contract(contract, script)` | Contract, script 원문 | `{errors, warnings}` | **script 추가** |
| `contract_fingerprint(contract)` | 40, 41 | `sha256:…` | — |
| `check_lineage(contract, lineage, visual_direction, scene_plan)` | +42, scene_plan | coverage (`consumed` vs beats, omitted, transformed 위반) | **lineage, scene_plan 추가** |
| `compile_timeline(direction, alignment, *, models=None, contract=None, ...)` | +41 models, +contract(앵커) | timeline 1.2 (ID 복사, anchor_resolution) | **키워드 인자 추가만** (v1.0 호출 불변) |
| `check_states(contract, timeline, lineage, scene_windows)` | +42, 장면 시간 창 | violations (state·invariant·sync·order·last frame) | **lineage, scene_windows 추가** |
| `bind(contract, timeline, edit_decisions, traces)` | +edit_decisions(컷별 런타임·창), 런타임별 raw trace | 43 | **edit_decisions 추가** |
| `record_deviation(project_dir, contract, deviation)` / `open_deviations(project_dir)` | 44 | 갱신된 44 / 미결 목록 | contract 추가 (contract_ref 기록) |
| `qa_report(contract, lineage_result, state_result, binding, pixel_qa=None)` | 위 결과들 | **45** | **신규 필요** (45 조립) |
| `review_packet(contract, timeline, render)` | evidence_states 시각(state_at) | 46 초안 + 프레임 | 신규(선택) |
| `completion_gate(stage, status, artifacts, pipeline_type)` | 40–46 by name | 통과 / CheckpointValidationError | `validate_stage`와 같은 모양 |

## 12. 검증 결과

`python docs/design/visual-direction-v1.2/validate_examples.py`
- 스키마: 40, 41, 42, visual_direction 1.2 (good / as_produced), 44, 45 (good / as_produced) — **8/8 통과**
- 40 `script_sha256` 일치, **앵커 9개 전부 정규화 script의 exact text**
- 하위 예시 전부 같은 contract fingerprint
- **legacy v1.0 fixture** (`tests/fixtures/visual_direction/release_plan/visual_direction.json`) 1.2 스키마에서 그대로 유효
- 스키마만으로 거부되어야 할 입력 **13/13 거부**: causal 장면 review=not_required · static_replacement_valid=false인데 not_required · motion 장면 actions 없음 · causal_explanation인데 causal contract 없음 · LOCKED must_preserve 없음 · locked_direction_mutation=true · LOCKED인데 script_sha256 없음 · 비정규 action ID · omitted_locked_ids 비어 있지 않음 · 1.2가 모델 정의 · MATERIAL deviation 승인 불요 · APPROVED에 decision 없음 · LOCKED 장면 receipt 없음

의미 검사 프로토타입 (저장소 밖, 버리는 코드 — 기존 `compile_timeline` + `replay_model_states`만 사용; 45 예시 2개가 이 출력):

| Planner 출력 | SC009 (LOCKED·인과) | SC010 (LOCKED·정적 증거) | SC014 (FLEX) |
|---|---|---|---|
| good | 구조 검사 전부 통과 → **UNVERIFIED** (binding·사람 리뷰 대기), review_required=true | 출처·마지막 화면 렌더 후 판정 → UNVERIFIED, **review_required=false** | **PASS** |
| **as_produced (실제 제작: A02 → 비교 카드)** | **FAIL 6건**: ACTION_EXISTENCE(A02), STATE S2·S3 미도달, ORDER, CAUSAL_CHAIN, LAST_FRAME | UNVERIFIED | PASS |
| 총량 120 (META 30) | **INVARIANT만 FAIL** (상태 검사는 통과) | | |
| 재배분 중 순간 80 | **INVARIANT만 FAIL** | | |
| 수익률이 재배분보다 먼저 | 앵커 unmatched → S3 미도달·ORDER·CAUSAL·LAST_FRAME FAIL | | |

## 13. 남은 질문 (작음)
1. **런타임 스택 vs v1 장면 런타임**: 40 `runtime_stack`은 장면에 여러 층을 허용하지만 현재 엔진은 장면당 주 런타임 1개(+자막·오디오). v1.2 Phase 1은 `deterministic_graphics` 층만 binding 검사하고 나머지는 안내로 둘지.
2. 42 `transformed`의 허용 범위를 enum으로 좁힐지 (현재 자유 문장 + "의미·상태·순서 변경 불가" 규칙).
3. `PIXEL_CHANGE`(기존 direction_qa)를 LOCKED 동적 장면의 필수 보조 증거로 할지, 선택으로 둘지.

## 14. 파일
```
README.md                                  이 문서
director-pvm-grammar.md                    D9: Director용 41 작성 문법
schemas/
  direction_common.schema.json             ID · contract_ref · anchor · assertion · numeric_target · enum
  visual_direction_contract.schema.json    40
  persistent_visual_models.schema.json     41 (모델 정의는 기존 visual_model을 $ref)
  direction_lineage.schema.json            42
  execution_binding.schema.json            43
  direction_deviations.schema.json         44
  direction_qa_report.schema.json          45 (locked lineage receipt 포함)
  direction_review.schema.json             46
  visual_direction.v1.2.schema.json        생성물 (derive_v12_schemas.py)
  visual_timeline.v1.2.schema.json         생성물
examples/capital-competition/              script.txt, 40, 41, 42, visual_direction good/as_produced, 44, 45 good/as_produced
derive_v12_schemas.py                      v1.0 → 1.2 변경분 정의 + 생성
validate_examples.py                       스키마·앵커·fingerprint·legacy·부정 사례 검증
```

이번 단계에서 하지 않은 것: API 구현, 런타임 스키마 등록, 게이트 연결, Director 프롬프트 변경, 렌더 경로 변경. 프로토타입 코드는 저장소에 넣지 않았다.
