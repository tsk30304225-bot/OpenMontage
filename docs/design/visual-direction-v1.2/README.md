# Visual Direction v1.2 — machine schema 설계 (개정 5, 설계 정정)

상태: **설계 문서.** 이 폴더에는 README·예시(와 Director용 문법 가이드)만 있다. 40–46 canonical runtime 스키마와 생성·검증 스크립트는 포크 소유 `schemas/direction_contract/`에 있고 (D18), `visual_direction`/`visual_timeline` 1.2는 거기서 **self-contained로 생성**되어 `schemas/artifacts/`의 shipped 스키마가 된다 (D14). runtime은 이 폴더를 읽지 않는다. Phase 1 runtime: `lib/direction_contract/` (authority · contract_v12 · evaluate · lineage · states · binding/execution · qa · deviations · gate).
개정 4 (2026-10-02, Phase 1 착수 중 발견한 결함 정정): D14 스키마 통합, D15 script canonicalization.
개정 5 (2026-10-03): D16 43 binding-centric (원문 §18), D17 SOURCE_EVIDENCE·LAST_FRAME 판정, D18 스키마 위치.
Phase 1 이후 (2026-10-03): contract-conformance 정정 X1(transitions)·X2(handoff)·action 완료 의미, Director authoring guide (정정 기록 참고).
기준 코드: 포크 `origin/main` 4a9aed4 (Phase 0 병합 후).
기준 문서: 사용자 원문 「연출안 형식 설계.txt」 **전체 (§0–§35, v1.1→v1.2 표)** + 2026-10-02 확정 결정 D1–D13.

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
| D7 | 앵커 = **script digest + canonical script text의 exact span** (D15로 정밀화: `source_span` 필수, `occurrence_index` 폐지). fuzzy는 alignment(timeline)에서만. 잠긴 앵커가 다른 구간으로 resolve되면 deviation | 40 `anchors`, timeline `anchor_resolution`, 6절 |
| D8 | 번호: **40** contract · **41** PVM · **42** lineage · **43** execution_binding · **44** deviations · **45** direction_qa_report · **46** direction_review | 2절 |
| D9 | Director용 41 작성 문법 가이드 (새 엔진 아님, 기존 replay 모델의 표준 문법). 40 전체의 사람용 문법·40/41 매핑·Bridge 정규화 규칙은 authoring guide | `director-pvm-grammar.md`, `director-authoring-guide.md` |
| D10 | binding은 deterministic_graphics 전용이 아니다. 40 `runtime_stack`에서 **잠긴 요구를 `consumes`로 선언한 모든 layer**를 검사. 엔진은 primary runtime 중심이어도 스키마는 multi-runtime 유지 | 43 `bindings[]` (개정 5, D16으로 대체: 옛 `actions[].layer_bindings[]`) |
| D11 | 42 `transformed`(자유 문장) → **typed `transformations[]`**: SPLIT · MERGE · TIMING_RESOLUTION · ASSET_BINDING · RUNTIME_BINDING · IMPLEMENTATION_DETAIL. 의미 변경 타입은 없다 → LOCKED 의미 변경은 deviation + 새 승인 revision | 42 schema |
| D12 | `PIXEL_CHANGE`는 LOCKED의 필수 PASS 조건이 아니다. **보조 증거(role SUPPORTING)만**. 동적 LOCKED 완료 = 구조 QA(45) + 필요한 Direction Review(46) | 45 `checks[].role` (PIXEL_CHANGE는 SUPPORTING 강제) |
| D13 | `omitted_locked_ids`는 Planner 값을 믿지 않는다. **시스템이** 승인 contract의 effective must_preserve와 실제 lineage coverage(주장 ∩ 실제 구현)를 비교해 계산 → 42 `system_coverage`(computed_by=check_lineage, plan-derived). 45가 timeline + binding으로 **독립 재계산**(execution-derived)하고 두 coverage의 일치 여부를 기록 (12절) | 42 `system_coverage`, 45 receipt `effective_must_preserve`·`omitted`·`lineage_coverage_agrees` |

### 정정 결정 (2026-10-02, 개정 4)

| # | 결정 | 반영 위치 |
|---|---|---|
| D14 | **스키마 통합 = A.** `visual_direction`·`visual_timeline`은 checkpoint와 `visual_timeline_compiler`가 upstream `validate_artifact`(registry 없음)로 검증한다. 따라서 이 둘의 shipped 1.2 스키마는 **self-contained**: 외부 `$ref`·registry 요구 없음. 공통 정의는 손으로 복제하지 않고 authoring source(`direction_common`)에서 각 스키마의 `$defs`로 **materialize**(사용하는 정의의 전이 폐포, `#/$defs/<name>`로 재작성). 두 스키마의 공유 정의가 서로·원본과 동일한지 regression test로 고정. v1.0 문서는 그대로 유효, 1.2 필드는 additive + `version` 조건부 (1.2: `contract` 필수, 모델 정의 금지 / 1.0: 1.2 필드 금지) | `schemas/direction_contract/generate_artifact_schemas.py`, `schemas/direction_contract/base/`, 2절·14절 |
| D15 | **Script canonicalization = `SCRIPT_SECTIONS_TEXT_V1`.** script artifact(`schemas/artifacts/script`)의 `sections` 현재 배열 순서, 각 `sections[i].text`만, CRLF/CR → LF, Unicode NFC, section 사이 정확히 `\n` 하나, trim 없음 → `canonical_script_text`. UTF-8(BOM 없음) bytes의 SHA-256 = `script_sha256`. 앵커 `source_span`은 canonical text의 Unicode code-point offset (`char_start` inclusive, `char_end` exclusive)이고 `canonical_script_text[char_start:char_end] == exact_text`를 반드시 검사. 40 `authority.canonicalization_id`에 규칙 ID를 기록(LOCKED 필수). narration authority(`narration_ref`·`narration_sha256` = 오디오 bytes)는 script hash와 별개의 독립 authority로 유지 | 40 `authority`, common `anchor`·`script_canonicalization`, 6절 |

### 정정 결정 (2026-10-03, 개정 5)

| # | 결정 | 반영 위치 |
|---|---|---|
| D16 | **43은 binding-centric** (원문 §18). canonical 단위는 `bindings[]`: 한 production scene × 한 runtime layer. 각 binding = `production_scene_id` · `layer` · `runtime` · `consumes{action_ids, event_ids, state_ids}` · `locator` · `status`. `locator`는 `kind`로 구분되는 union: **CODE** (`implementation_path`, `component_or_block`, `refs[{file, line?, symbol, via}]` — line 선택) · **ASSET** (`cut_id`, `source_asset_ref`, `via` — line 없음) · **RUNTIME_OUTPUT** (`runtime_output_ref`, `via`). 43은 또 렌더된 production scene 창 `scene_windows[]`(edit_decisions의 primary cut을 순서대로 누적한 program time, video_compose와 같은 방식)를 가진다 — ACTIVE_AT_SCENE_END·LAST_FRAME·minimum_hold의 장면 끝은 이것이다. action 중심 `actions[].layer_bindings`는 폐지: action·state·event의 bound 여부는 bindings에서 **파생** (잠긴 id는 그것을 `consumes`로 선언한 모든 layer의 binding이 bound여야 bound). 개정 4까지는 state(예: 정적 증거 SC010/S0)를 binding할 자리가 없었다 | 43 schema, 10절·11절 |
| D17 | **SOURCE_EVIDENCE** = contract 객체의 `source_asset`과 실제 edit_decisions cut source의 identity 대조 (`SOURCE_IDENTITY_V1`, 6-1절). **LAST_FRAME**: cut이 장면 끝을 덮는다는 것은 `ACTIVE_AT_SCENE_END` 증거일 뿐 그 자체로 PASS가 아니다. `last_frame_contract`의 선언된 요구 (required_state, visible/hidden objects, object_states, persistent_states, visible_text, camera_state, motion_state, minimum_hold) **전부**가 충족돼야 PASS. 구조로 판정할 수 없는 요구(visible_text, camera_state, …)가 있으면 UNVERIFIED. SC010처럼 단순한 정적 증거 계약은 구조 검증만으로 PASS 가능 | 6-1절, 9절 |
| D18 | 40–46 canonical runtime 스키마 = 포크 소유 **`schemas/direction_contract/`** (`registry()`·`validator(name)` 제공, `base/`, 생성기, 예시 검증기). self-contained 생성물 `visual_direction`·`visual_timeline`은 기존대로 `schemas/artifacts/`. `docs/design/visual-direction-v1.2/`에는 README와 examples만 | 14절 |

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
| 42 | `direction_lineage` | Planner (`system_coverage`는 시스템) | scene_plan | production scene별 consumed ID(must_preserve 모든 범주), typed transformations. coverage는 시스템 계산 |
| — | `visual_direction` 1.2 | Planner | scene_plan | beat(모델 연산 1개) + `action_id` `state_after_id` `contract_event_id` `anchor_id` `sync_group` |
| — | `visual_timeline` 1.2 | `compile_timeline` | edit | event에 같은 ID + `anchor_resolution` |
| 43 | `execution_binding` | `bind()` | compose | `bindings[]`: production scene × layer마다 소비한 잠긴 id + locator (CODE / ASSET / RUNTIME_OUTPUT) (D16) |
| 44 | `direction_deviations` | 작업자 기록, **사용자 결정** | 어느 단계든 | 구현 불가 시 중단 |
| 45 | `direction_qa_report` | QA (자동) | compose | 구조 검사 + locked lineage receipt |
| 46 | `direction_review` | 사람 | compose 후 | 화면이 메커니즘을 실제로 보여주는가 |

- 모든 하위 artifact는 `contract_ref {artifact, artifact_id, revision, fingerprint}`를 가진다. 40/41이 바뀌면 stale → 게이트 실패.
- **Fingerprint**: `sha256` over canonical JSON `{"contract": 40 − lifecycle, "pvm": 41}` (key 정렬, 공백 없음, UTF-8). `lifecycle`(revision·status·잠금 메타)만 바뀌면 지문 불변.
- 40–46은 upstream 로더(`validate_artifact`)를 거치지 않는다. 교차 `$ref` 때문에 `schemas/direction_contract`의 registry로 검증 (D18).
- **`visual_direction`·`visual_timeline`은 예외** (개정 4에서 정정: 개정 3의 "v1.2 artifact는 upstream 로더를 거치지 않는다"는 이 둘에 대해 틀렸다). checkpoint `_validate_artifacts_for_stage`와 `visual_timeline_compiler`가 `validate_artifact`로 검증하므로, 이 둘의 1.2 스키마는 self-contained로 생성되어 `schemas/artifacts/visual_direction.schema.json`·`visual_timeline.schema.json`(포크 소유 파일)을 대체한다 (D14). `validate_artifact` 자체(upstream 파일)는 그대로 → **upstream 0줄** 유지.

## 3. 원문 대조표 (§별 반영 결과)

| 원문 | 반영 | 비고 / 의도적 차이 |
|---|---|---|
| §0 지위·헤더 | 40 `schema_name` `schema_version` `artifact_role` `artifact_id` `project_id` `lifecycle{revision,status DRAFT/LOCKED/SUPERSEDED}` `authority{script_ref,script_sha256,canonicalization_id,narration_ref,narration_sha256,plan_lock_ref}` | 40↔41 결합을 위해 `authority.pvm_ref` 추가. LOCKED는 `script_sha256`·`canonicalization_id` 필수 (D15) |
| §1 파이프라인 / 재요약 금지 | 1절 흐름, 42 `transformed`(의미 변경 불가) | |
| §2 우선순위 | 40 `priority_policy` (값 고정) | |
| §3·§33 중요도 | `importance` + 조건부 필수 | FLEX = D5 |
| §4 LOCKED 최소 | narration_span, meaning_contract, beats, motion_reason, initial_state, states, objects, must_preserve, prohibited_simplification, last_frame_contract, qa_contract 필수. **motion_required면** actions·events·states≥2 | **정적 증거 LOCKED**(motion_required=false)는 actions/events 면제 — D6과 일관. `dependencies`는 action.dependency로, `execution_graph`는 파생(아래) |
| §5 Narration authority | 40 scene `anchors[]` {anchor_id, script_span_id, exact_text, **source_span (필수)**, edge, offset_ms} | resolution(status·time·frame)은 **timeline 1.2 `anchor_resolution`**에 둔다 (40은 resolve 결과로 바뀌지 않음, D7). 출현 위치는 검색이 아니라 span이 정한다 → `occurrence_index` 폐지 (D15) |
| §6 Beat | `beat_id, anchor, narrative_function, meaning_before, new_information, meaning_after, visual_state_before/after, required_change, linked_actions` | `narration_span` → `anchor` 참조 |
| §7 State 일급 | `state_id, semantic_meaning, pvm_state / object_states / visible_objects, invariants, entered_by, exited_by, must_be_visible, valid_until` | `object_states` = 기계 판정 가능한 assertion. 모델 밖 대상은 `visible_objects`(렌더 후 판정) |
| §8 Invariant | `kind: CONSTANT`(target + value) · `ASSERT`(holds) · `ORDER`(order) + `during` | 원문 `CAUSAL_ORDER` = `ORDER` |
| §9 Object | `object_id, object_type, semantic_role, truth_class, model_id+element_id, layer_id, source_asset, parent_object, persistence, semantic_necessity` | `initial_state/lifecycle/actions`는 모델·state·action 쪽에서 표현 (중복 방지) |
| §10 Action | `action_id, semantic_role, action_type, model_id, target_objects, start_anchor, end_anchor, from_state_id, to_state_id, path, easing, dependency{after,before,with,wait_until,sync_group}, completion_condition, completion_state_id, implementation_freedom, must_execute, min_duration_seconds` | 원문 `from_state/to_state`(서술)는 state 객체가 대신함. **v1.2: action 완료 = 그 action의 마지막 timeline 연산 종료** (to_state 도달은 별도 검사). `completion_state_id`·`completion_condition`은 예약·미지원, `must_execute`는 생략/true만 (작성 시 contract 오류) |
| §11 Causal motion | `causal_motion_contracts[]` {causal_chain_id, proposition, cause, intermediate_reactions[], effect, dependencies, visibility, final_proof_state, prohibited_simplification(5종)} | 배열(장면에 인과 사슬 여러 개 가능). `motion_reason.causal_explanation=true`면 필수 |
| §12 Motion reason | `motion_required, understanding_dependency, temporal_logic, causal_explanation, static_replacement_valid, decorative_motion_allowed` | `causal_explanation` 추가 (§4 "인과 Scene이면"의 기계 판정용) |
| §13 Event | `events[]` {event_id, trigger_anchor, precondition_state, actions, resulting_state, completion_condition, next_event_dependency} | timeline의 event(=연산 1개)와 다른 개념 → timeline event에 `contract_event_id` |
| §14 Execution graph | 선택 필드. 파생 규칙은 beats/states/actions/events에서 (4절). runtime은 작성본을 검사하지 않으므로 Bridge는 내부 검사에만 쓰고 40에 쓰지 않는다 | 같은 정보를 두 번 쓰지 않게 |
| §15 must_preserve | 11개 키 + `cross_scene` | **D1**: core(states/actions/invariants) 자동 포함 |
| §16 allowed_freedom | 부여된 자유만 enum 배열로 | false 항목(causal_order, action_removal, action_merge, state_removal, narration_anchor_change)은 **LOCKED에서 절대 부여 불가**로 고정 (NEVER_FREE) |
| §17 prohibited_simplification | 9종 그대로 | |
| §18 Runtime stack | 40 `runtime_stack` 9개 층 {runtime, purpose, consumes} | 43 `bindings`가 **consumes를 선언한 모든 layer**를 production scene별로 검사 (D10·D16). 엔진에 실행 경로가 없는 layer는 `not_executed_by_engine` = 잠긴 ID에 대해 unbound |
| §19 Atelier boundary | `allowed_freedom` + NEVER_FREE + must_preserve로 표현 | 별도 필드 없음 |
| §20 Visual identity | 40 `visual_identity.mechanism_compatibility` (true 고정) | |
| §21 Truth | `truth_class` (object, truth_requirements) | |
| §22 PVM | 41: definition(=components), `semantic_role`, named_states, transitions, handoffs, persistence{first/last_scene, default_visibility VISIBLE/HIDDEN_BUT_ACTIVE} | `current_state/state_history`는 **replay로 파생**, 작성하지 않음. transitions 없음/빈 목록 = 제한 없음 (X1). handoff = from_scene 끝 상태 + to_scene이 이어받음 (X2) |
| §23 Last frame | `required_state_id, end_anchor, visible/hidden_objects, object_states, persistent_states, visible_text, camera_state, motion_state, minimum_hold_seconds, handoff_objects, handoff_to_scene, next_scene_seed` | `handoff_to_scene`·`handoff_objects`·`next_scene_seed` = 장면 간 편집 연결 기록 (PVM 상속은 41 handoff) |
| §24 Output contract | 40 `output_contract` | `embedded_lineage_metadata`는 43이 담당 |
| §25 Scene plan 역할 | **42 lineage + 43 binding**이 담당 (P3) | upstream scene_plan 무변경 |
| §26 Anchor resolution | timeline 1.2 `anchor_resolution{resolved_anchors[status EXACT/REVERSIBLE_NORMALIZATION/FUZZY, same_span], unresolved_anchors}` + `action_timing_binding`은 43 binding의 `timeline_event_ids`·start/end | |
| §27 Downstream lineage | 42 {contract_ref, consumed(beat/state/action/event/anchor/invariant/object/**causal_chain**/pvm), typed transformations, added_implementation_fields, **system_coverage**} | `omitted_locked_ids`는 Planner가 쓰지 않고 시스템이 계산 (D13). 원문 `transformed` = typed transformations (D11) |
| §28 Deviation | 44 {deviation_id, scene_id, affected_contract_ids, reason(+OTHER), semantic_impact NONE/MINOR/MATERIAL, proposed_change, approval_required, status PROPOSED/APPROVED/REJECTED/WITHDRAWN, decision} | MATERIAL → approval_required=true (스키마 강제). 잠긴 must_preserve에 닿으면 impact와 무관하게 승인 필요 |
| §29 Approval scope | 40 `approval_scope` (top + scene override). `locked_direction_mutation: false` 고정, semantic_fallback·causal_contract_change = requires_new_approval | 실행 승인 ≠ 연출 변경 승인 |
| §30 Direction QA | 45 `checks[]` {type: ACTION_EXISTENCE, ORDER, STATE_TRANSITION, INVARIANT, CAUSAL_CHAIN, ANCHOR_TIMING, PERSISTENT_STATE, LAST_FRAME, PROHIBITED_SIMPLIFICATION (+BINDING, SOURCE_EVIDENCE, PIXEL_CHANGE), **role REQUIRED/SUPPORTING**} result PASS/FAIL/UNVERIFIED | 기존 `direction_qa` 픽셀 검사 = `PIXEL_CHANGE`, **항상 SUPPORTING** (D12) |
| §31 Locked lineage receipt | 45 `scenes[].receipt` (LOCKED 필수) | `effective_must_preserve`, 독립 재계산 `omitted`, `lineage_coverage_agrees`, `deviated` 추가 |
| §32 완료 조건 | `completion_gate` (10절) | |
| §34 사람용 템플릿 | `40_*.md` view = `director-authoring-guide.md`의 사람용 문법. 필드 매핑은 그 문서 7절, 결정적 변환(Director Authoring Bridge)은 8절 | 원문 §34 텍스트는 이 저장소에 없어 원문과의 문자 대조는 하지 않았다 |
| §35 최종 Scene 필드 | 전부 대응 (`layers/assets/source_pixels/camera/text/sound/readability/transition_*` → `presentation`, `approval_scope/downstream_contract/fallback_contract/output_contract` 각 필드) | |

## 4. 정규화 (`load_contract`가 하는 일)

1. 40·41 스키마 검증 (공통 registry).
2. **effective must_preserve** = 작성된 must_preserve ∪ (LOCKED면) 모든 state·action·invariant ID. (D1)
3. execution_graph: 파생 규칙 = BEAT→ACTION(linked_actions), STATE→ACTION(from), ACTION→STATE(to), EVENT→ACTION. **현재 runtime은 이 그래프를 파생하거나 작성본과 비교하지 않는다** (정정 기록). Director Authoring Bridge는 이 규칙으로 그래프를 내부에서 계산해 참조·순환만 검사하고 40에는 쓰지 않는다 (authoring guide N8).
4. 기본값: `review = auto`는 runtime이 적용. action 완료는 마지막 timeline 연산 종료로만 판정한다. `completion_state_id`·`completion_condition`은 v1.2 미지원, `must_execute`는 생략/true만 허용 (5절).
5. **review 해석** (D6): `auto` → causal contract 있음 · action 있음 · `pvm_transitions` 있음 · `static_replacement_valid=false` 중 하나면 required, 아니면 not_required. 그 경우 `not_required`를 쓰면 contract 오류.
6. fingerprint 계산, ID 색인 생성.

## 5. `validate_contract`의 의미 규칙 (스키마 밖)

- ID 유일성, 접두어 = 장면 ID (`SC009/…`는 SC009에만).
- 참조 해석: beat.anchor, action.start/end_anchor, from/to state, dependency, event.actions, invariant.order/during, causal link, last_frame, must_preserve, object.model_id+element_id(41에 존재), pvm_state(41 named_states에 존재).
- 앵커 (D15): `canonicalization_id`가 알려진 규칙, `sha256(canonical_script_text(script))` = `script_sha256`, 모든 앵커에서 `canonical_script_text[char_start:char_end] == exact_text`, narration_span 안에 beat·action 앵커가 문서 순서대로(span 순서).
- 상태 사슬: 41 `transitions`가 하나라도 있으면 action `from → to`가 그 목록에 있어야 한다 (없거나 빈 목록 = 제한 없음, X1). 모델의 첫 장면이면 initial_state가 41 initial_state에서 성립. `entered_by/exited_by`가 action과 일치.
- handoff (X2): to_scene이 from_scene 뒤, state는 named state, persistence first/last_scene이 from..to를 포함, to_scene이 모델을 `models`에 선언 (화면 밖이면 HIDDEN_BUT_ACTIVE, `survives_hidden: false`면 불가), to_scene의 `enter_state`와 모델 initial_state는 handoff 상태.
- causal: cause·intermediate·effect 상태가 action 순서와 일치, final_proof_state 존재.
- NEVER_FREE 항목이 allowed_freedom에 없음 (스키마 enum에 아예 없음).
- sync_group: 같은 그룹 action은 같은 start_anchor.
- runtime_stack: 잠긴 action·event·state는 적어도 한 layer의 `consumes`에 있어야 한다 (binding 대상이 없으면 contract 오류).
- action 완료 필드: `completion_state_id`·`completion_condition`이 있거나 `must_execute: false`면 contract 오류 (v1.2 미지원).

## 6-1. 출처 identity · 마지막 화면 (D17)
- **`SOURCE_IDENTITY_V1`**: 두 참조를 `\` → `/`, 앞의 `./` 제거, Unicode NFC로 정규화한다. contract `source_asset`과 cut `source`가 같거나, cut source의 경로 segment 끝이 contract `source_asset`의 segment 전체와 같으면 같은 출처. (asset-manifest id처럼 `/`가 없으면 사실상 동일 문자열 비교.)
- **SOURCE_EVIDENCE** (truth_class SOURCE 객체마다): 그 객체가 보이는 잠긴 state를 `consumes`로 선언한 layer의 binding이 bound ASSET이고 `source_asset_ref`가 identity 일치 → PASS. ASSET binding이 없거나 다른 출처 → FAIL. 객체에 `source_asset`이 없으면 UNVERIFIED.
- **ACTIVE_AT_SCENE_END**: ASSET binding의 cut 구간이 contract 장면 창(42가 대응시킨 production scene들)의 끝을 덮는다. 증거 하나일 뿐이다.
- **LAST_FRAME** (장면 끝 시점, 선언된 요구마다 판정 → 하나라도 FAIL이면 FAIL, 판정 불가가 있으면 UNVERIFIED, 전부 충족일 때만 PASS):
  - `required_state_id`: 모델 state면 replay 상태가 assertion을 만족, 모델 밖 state면 그 `visible_objects`가 전부 보임(아래)
  - `visible_objects` / `hidden_objects`: 모델 객체는 replay의 `elements.<id>.visible`, 출처 객체는 identity가 맞는 ASSET binding이 ACTIVE_AT_SCENE_END (hidden 출처 객체는 UNVERIFIED)
  - `object_states` · `persistent_states`: replay assertion
  - `motion_state`: HOLD = required state 도달 뒤 장면 끝까지 그 장면 모델 연산 없음. SETTLING/CONTINUOUS는 UNVERIFIED
  - `minimum_hold_seconds`: 장면 끝 − required state 도달 시각(모델: 마지막 연산 종료, 출처: cut 시작과 장면 시작 중 늦은 쪽) ≥ 값
  - `visible_text` · `camera_state`: 렌더가 필요 → UNVERIFIED (Phase 2)
  - `handoff_to_scene` · `handoff_objects` · `next_scene_seed`: 마지막 화면 요구가 아니라 장면 간 편집 연결 기록이고 판정하지 않는다. 모델 상태 상속은 41 handoff → PERSISTENT_STATE (from_scene 끝 + to_scene의 ENTRY_SIGNATURE, X2)

## 6. 앵커 (D7, D15)
- **canonical script text (`SCRIPT_SECTIONS_TEXT_V1`)**: `"\n".join(NFC(sections[i].text with CRLF/CR → LF) for i in array order)`, trim 없음. `script_sha256 = sha256(utf8(canonical_script_text))`, BOM 없음. 다른 필드(id·시간)는 hash에 들어가지 않는다. 규칙이 바뀌면 새 ID를 만들고 기존 contract는 기록된 ID로 재현한다.
- span = code-point offset, `[char_start, char_end)`. `exact_text`는 canonical text의 verbatim slice (공백 정규화 없음).
- narration authority는 별개: `narration_sha256`은 TTS 오디오 bytes의 hash이고 script hash에서 파생되지 않는다. alignment가 script와 narration을 잇는다.
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
| REPLACE_MOTION_WITH_HIGHLIGHT (+ 원문 §11 5종) | 구조로는 연산 종류·길이까지. 최종 판정은 46. `PIXEL_CHANGE`는 보조 증거일 뿐 (D12) | compose | 사람 |

## 9. 장면 유형별 완료 조건

| 유형 | 45 (구조) | 46 (사람) | 기타 |
|---|---|---|---|
| LOCKED · 동적 (causal / action / PVM 전이 / static_replacement_valid=false) | receipt PASS (REQUIRED 검사만; PIXEL_CHANGE 제외) | **PASS 필요** | 43: 선언한 모든 layer bound 또는 승인된 deviation |
| LOCKED · 정적 증거 | receipt PASS: SOURCE_EVIDENCE(출처 identity) · LAST_FRAME(선언 요구 전부, D17) · 43 binding | 불필요 | 단순 계약이면 구조 검증만으로 PASS |
| REQUIRED_FLEX | requirements·truth·참조 무결성, 참조한 PVM 전이만 | 불필요 | |
| DISCRETIONARY | 없음 | 불필요 | |

## 10. 단계별 게이트 (`checkpoint_hooks.validate_stage` → `completion_gate`)
40이 있을 때만. 
- **scene_plan 완료**: 40 `LOCKED` · `validate_contract` 오류 0 · 42/visual_direction 1.2의 contract_ref 일치 · `check_lineage`가 계산한 `system_coverage.omitted_locked_ids`가 비었거나 전부 deviation으로 덮임 (PROPOSED면 통과는 하되 compose에서 막힘). Planner가 써 넣은 coverage 값은 무시하고 덮어쓴다
- **edit 완료**: timeline 1.2 · 잠긴 앵커 unresolved 0 · same_span=false는 deviation 존재 · `check_states` 위반 0
- **compose 완료**: 43에서 잠긴 action·event·state마다 그것을 선언한 모든 layer의 binding이 bound 또는 deviated(APPROVED) (D16) · 45 verdict PASS (LOCKED receipt PASS, 독립 재계산 `omitted`가 비고 `lineage_coverage_agrees=true`) · 46 필요한 장면 전부 PASS (같은 render sha256·contract revision) · PROPOSED/REJECTED deviation 0

## 11. API (시그니처 확정안 — 구현 전)

| API | 입력 | 출력 | 이전 표 대비 |
|---|---|---|---|
| `load_contract(path_40, path_41)` | 40, 41 | `Contract` (정규화본: effective must_preserve, 파생 graph, review 해석, fingerprint, ID 색인) | 정규화 포함 명시 |
| `validate_contract(contract, script)` | Contract, script artifact (`sections[]`) | `{errors, warnings}` (canonical hash·span 검사 포함, D15) | **script 추가** |
| `contract_fingerprint(contract)` | 40, 41 | `sha256:…` | — |
| `check_lineage(contract, lineage, visual_direction, scene_plan)` | +42, scene_plan | 42 `system_coverage` (effective must_preserve vs 주장∩실제 타임라인, `claimed_but_not_implemented`) + transformation 규칙 위반 | **lineage, scene_plan 추가 · coverage는 반환값, Planner 값 불신 (D13)** |
| `compile_timeline(direction, alignment, *, models=None, contract=None, ...)` | +41 models, +contract(앵커) | timeline 1.2 (ID 복사, anchor_resolution) | **키워드 인자 추가만** (v1.0 호출 불변) |
| `check_states(contract, timeline, lineage, scene_windows)` | +42, 장면 시간 창 | violations (state·invariant·sync·order·last frame) | **lineage, scene_windows 추가** |
| `bind(contract, timeline, edit_decisions, traces)` | +edit_decisions(컷별 런타임·창·source), `traces`: **layer별** raw trace | 43 `bindings[]` (CODE는 trace에서, ASSET은 edit_decisions cut에서, RUNTIME_OUTPUT은 runtime 산출물에서; D16) | **edit_decisions 추가 · traces를 layer 단위로 (D10)** |
| `record_deviation(project_dir, contract, deviation)` / `open_deviations(project_dir)` | 44 | 갱신된 44 / 미결 목록 | contract 추가 (contract_ref 기록) |
| `qa_report(contract, lineage, visual_direction, timeline, binding, pixel_qa=None)` | 원 artifact (이전 단계 결과값이 아니라) | **45**: coverage **독립 재계산** 후 42 `system_coverage`와 비교, `pixel_qa`는 SUPPORTING으로만 | **신규 필요** (D12·D13) |
| `review_packet(contract, timeline, render)` | evidence_states 시각(state_at) | 46 초안 + 프레임 | 신규(선택) |
| `completion_gate(stage, status, artifacts, pipeline_type)` | 40–46 by name | 통과 / CheckpointValidationError | `validate_stage`와 같은 모양 |

## 12. 검증 결과 (개정 5)

`python -m schemas.direction_contract.validate_examples`
- 스키마: 40 · 41 · 42 (Planner 작성본 / good·as_produced system coverage 포함본) · visual_direction 1.2 (good / as_produced) · 43 · 44 · 45 (good / as_produced) — **11/11 통과**
- 생성 스키마(`visual_direction`/`visual_timeline` 1.2): 최신, **외부 `$ref` 0**, 공유 정의(contract_ref · fingerprint · qualified_id)가 두 스키마와 `direction_common`에서 동일. 1.2 예시는 registry 없이 plain jsonschema로 검증
- script authority: `script.txt` = `canonical_script_text(script.json)`, 40 `canonicalization_id = SCRIPT_SECTIONS_TEXT_V1`·`script_sha256` 일치, **앵커 9개 전부 `canonical[char_start:char_end] == exact_text`**, span 1 이동은 검출, CR/CRLF → LF
- 하위 예시 전부 같은 contract fingerprint
- 43 예시: SC010/S0 정적 증거가 `sc18/factual_source` ASSET binding으로 기록되고 출처 identity가 contract `source_asset`과 일치
- **legacy v1.0 fixture** (`tests/fixtures/visual_direction/release_plan/visual_direction.json`) 1.2 스키마에서 그대로 유효
- **42 `system_coverage` = 45 독립 재계산** (good 0개 · as_produced 6개 일치)
- 스키마만으로 거부되어야 할 입력 **30/30 거부** (개정 5 추가: bound binding에 locator 없음 · 아무 id도 소비하지 않는 binding · CODE locator에 implementation_path 없음 · ASSET locator에 cut 없음 · 알 수 없는 locator kind · deviated에 deviation_id 없음 · 옛 action 중심 43. 개정 4 추가: LOCKED인데 canonicalization_id 없음 · 알 수 없는 canonicalization · 앵커 source_span 없음 · 1.2인데 contract 없음 · v1.0인데 contract · v1.0 beat에 action_id). 기존: causal 장면 review=not_required · static_replacement_valid=false인데 not_required · motion 장면 actions 없음 · causal_explanation인데 causal contract 없음 · LOCKED must_preserve 없음 · locked_direction_mutation=true · LOCKED인데 script_sha256 없음 · 비정규 action ID · **42 의미 변경 transformation** · **system_coverage를 check_lineage 아닌 주체가 작성** · **PIXEL_CHANGE를 REQUIRED로** · **receipt에 effective_must_preserve 없음** · 1.2가 모델 정의 · MATERIAL deviation 승인 불요 · APPROVED에 decision 없음 · LOCKED 장면 receipt 없음

Phase 1 runtime 결과 (`lib/direction_contract`, acceptance fixture `tests/fixtures/direction_v1_2/capital_competition`; 42 system coverage · 43 · 45 예시는 이 runtime의 출력이다):

| 시나리오 | SC009 (LOCKED·인과) | 시스템 계산 omitted (45) | SC010 (LOCKED·정적 증거) | SC014 (FLEX) |
|---|---|---|---|---|
| 정상 | 구조 REQUIRED 전부 PASS → **PASS**. 완료는 46 PASS가 있어야 (review_required). PIXEL_CHANGE는 SUPPORTING·UNVERIFIED | **없음** | **PASS**: 출처 identity (cut c-sc18 = `kb_rate_table_capture.png`) + `sc18/factual_source` ASSET binding + LAST_FRAME(2.0 s hold), **리뷰 불필요** | **PASS** |
| **카드 대체 (실제 제작)** | **FAIL**: ACTION_EXISTENCE A02 · STATE S2·S3 · ORDER · CAUSAL_CHAIN · LAST_FRAME · ANCHOR AN03 · BINDING A02/E02/S2 (`sc16` unbound) | A02 · AN03 · B03 · B04 · CC01 · INV03 · S2 · S3 | PASS | PASS |
| 총량 변경 (META 30) | **INVARIANT INV01만 FAIL** | INV01 | PASS | PASS |
| 재배분 중 순간 80 | **INV01만 FAIL** (sync group이 동시에 일어나지 않음) | INV01 | PASS | PASS |
| 순서 변경 (수익률 먼저) | **FAIL**: A03 타임라인 미실행 · S3 · ORDER · CAUSAL · LAST_FRAME · AN04 · BINDING(sc17) | A03 · AN04 · B04 · CC01 · INV03 · S3 · YIELD_META | PASS | PASS |
| 출처 불일치 (sc18 cut이 다른 금리표) | 영향 없음 | — | **SOURCE_EVIDENCE FAIL** | — |
| cut이 장면 끝을 덮지만 `visible_text` 요구 | 영향 없음 | — | **LAST_FRAME UNVERIFIED** (ACTIVE_AT_SCENE_END만으로 PASS 안 됨, D17) | — |

`lineage_coverage_agrees` = **plan-derived coverage와 execution-derived coverage의 일치 여부**. 42 `system_coverage`는 scene_plan 시점에 Planner 산출물(beat를 문서 순서로 replay)로, 45 receipt `omitted`는 컴파일된 timeline + execution binding으로 계산한다. `false`의 원인은 42가 stale이거나 손으로 고쳐진 경우만이 아니다: **timing resolution**(앵커가 다른 곳으로 resolve, sync group이 시간상 갈라짐 — 순간 80, 순서 변경)이나 **실제 실행 실패**(binding unbound 등)로 계획에 있던 것이 실행에서 빠져도 `false`다. 어느 경우든 compose 게이트는 막힌다.

Phase 1 한계 (Phase 2): 렌더가 필요한 판정(`visible_text`, `camera_state`, `SETTLING/CONTINUOUS`, 픽셀 의미)은 UNVERIFIED. 잠기지 않은 장면의 `truth_requirements.source`는 43 binding 대상이 아니라 UNVERIFIED.

검증 중 발견해 고친 것
- 42 `consumed`에 `causal_chain_ids`가 없어 must_preserve의 인과 사슬을 커버할 방법이 없었다 → 추가. 원칙: **must_preserve의 모든 범주는 42에 대응 칸이 있다.**
- action 존재는 beat가 아니라 **컴파일된 타임라인 event**로 판정 (beat가 있어도 앵커가 안 맞으면 실행되지 않는다).
- sync group 위반은 그 그룹이 건드린 element를 대상으로 하는 invariant에만 귀속.
- 모델 밖 상태(문서가 보임)는 replay가 아니라 렌더 후 binding + SOURCE_EVIDENCE로 판정.

### 정정 기록 (2026-10-03, 개정 5 이후)
- **fixture 문장 간격 0.8 s → 1.2 s.** 개정 5 커밋(7eb0476) 메시지는 "0.8 s 간격이면 SC009가 마지막 화면을 1.5 s 유지한다"고 적었으나 계산 실수였다: 0.8 s에서 SC009 마지막 연산(`ev-sc17-b2`, AN04 + 0.5 s, EXPAND 1.2 s) 종료 후 sc17 끝까지는 1.2 s로 `minimum_hold_seconds` 1.5 s에 못 미친다. Phase 1 runtime 커밋(e230e30)에서 간격을 1.2 s로 바꿔 유지 시간이 1.6 s가 됐다. contract·스키마는 바뀌지 않았고, 커밋 이력은 고치지 않는다.
- **`lineage_coverage_agrees` 정의.** 45 스키마 설명의 "불일치 = 42 stale/조작"을 "plan-derived와 execution-derived coverage의 일치 여부"로 정정 (필드·타입·필수 여부는 그대로).
- **X1: 41 `transitions` 없음/빈 목록 = 제한 없음.** 스키마는 그렇게 정의했지만 `validate_contract`는 빈 허용 목록으로 취급해 같은 모델 안의 모든 이동을 거부했다. runtime을 스키마에 맞췄다 (스키마 무변경). regression 4종 (`tests/tools/test_direction_v12_conformance.py`).
- **X2: handoff = 장면 간 연속성 계약 (양 끝 검사).** 이전 runtime은 from_scene 끝 상태만 검사했고 to_scene, `models[].enter_state/visibility`, persistence를 읽지 않았다. 이제 5절 규칙을 `validate_contract`가 검사하고, 45는 handoff를 받는 장면(중요도 무관)에 PERSISTENT_STATE를 추가한다: 판정 대상은 **ENTRY_SIGNATURE** = 그 장면 자신의 첫 연산 적용 전 replay 상태 (첫 앵커에서 바로 시작하는 action은 진입 상태에 들어가지 않는다). `default_visibility`는 검사하지 않는다 (범위 밖).
- **예시 SC009 → SC010 PVM handoff 삭제.** SC010은 금리표 증거 장면이고 CAPITAL_FLOW를 쓰지 않으며 이후 장면도 모델을 다시 쓰지 않는다. 41 handoff 삭제(`last_scene: SC009` 유지), SC010의 `REPLACE_PVM_WITH_UNRELATED_BROLL` 삭제, SC009 `handoff_to_scene: SC010`은 편집상 연결로 유지. fingerprint 재계산 (`sha256:2649e346…`), 42/43/45 예시 재생성: 내용 변화는 SC009의 handoff PERSISTENT_STATE 행이 빠진 것뿐. 이전 45 예시의 `inputs.lineage_sha256`은 함께 실린 42 예시와 맞지 않았다(시각을 고정하지 않은 lineage의 hash) — 재생성으로 일치.
- **action 완료 의미 확정.** runtime은 `completion_state_id`·`completion_condition`·`must_execute`를 읽은 적이 없다 (작성해도 무시됐다). v1.2의 정식 의미: action 완료 = 그 action에 속한 마지막 timeline 연산의 종료 시각 (`dependency.after … on: complete`도 이것). to_state 도달은 STATE_TRANSITION으로 따로 검사. 앞의 두 필드는 예약·미지원, `must_execute: false`도 미지원 → 작성 시 contract 오류. 스키마 구조·version은 그대로, description만 정정.
- **예시 SC010 `qa_contract.checks` 삭제.** runtime이 읽지 않는 목록이라 "이 검사만 한다"는 오해만 만들었다. fingerprint `sha256:ad20a2fa…`로 재계산, 42/43/45 재생성: hash만 바뀌고 QA 결과는 동일.
- **4절 서술 정정.** "execution_graph 파생·동일성 검사"와 "completion_state_id/must_execute 기본값 채움"은 runtime에 구현된 적이 없다. 서술을 실제 동작에 맞췄다. execution_graph는 Director Authoring Bridge가 내부 검사에만 쓰고 40에 serialize하지 않는다 (런타임 동일성 검사가 생기면 다시 정한다).
- **`visual_timeline_compiler` 1.2 production path.** 1.2 연출안은 LOCKED 40/41을 함께 받아야 하고 (없으면 legacy fallback 없이 실패), revision/fingerprint를 확인한 뒤 `compile_timeline(..., models=41, contract=40)`으로 컴파일하며 `anchor_resolution`을 timeline과 결과에 보존한다.

## 13. 남은 질문
없음. 개정 2의 세 질문은 D10–D12로 확정.

## 14. 파일
```
docs/design/visual-direction-v1.2/
  README.md                                  이 문서
  director-authoring-guide.md                Director 사람용 문법 전체, 40/41 매핑, Bridge 정규화 규칙
  director-pvm-grammar.md                    D9: Director용 41 작성 문법 (문서)
  examples/capital-competition/              script.json (authority: sections), script.txt (생성: canonical text), 40, 41,
                                             42 (Planner 작성본 + good/as_produced system coverage), visual_direction good/as_produced,
                                             43 good, 44, 45 good/as_produced
schemas/direction_contract/                  canonical runtime 스키마 (D18) — runtime은 여기만 읽는다
  __init__.py                                registry() · validator(name) · validate(name, doc)
  direction_common.schema.json               ID · contract_ref · anchor · script_canonicalization · assertion · enum
  visual_direction_contract.schema.json      40
  persistent_visual_models.schema.json       41 (모델 정의는 v1.0 visual_model을 $ref)
  direction_lineage.schema.json              42 (typed transformations, system_coverage)
  execution_binding.schema.json              43 (bindings[] + CODE/ASSET/RUNTIME_OUTPUT locator)
  direction_deviations.schema.json           44
  direction_qa_report.schema.json            45 (locked lineage receipt 포함)
  direction_review.schema.json               46
  base/visual_direction.v1.0.schema.json     v1.0 원본 (생성 입력, 고정)
  base/visual_timeline.v1.0.schema.json      v1.0 원본 (생성 입력, 고정)
  generate_artifact_schemas.py               v1.0 → 1.2 변경분 + common 정의 materialize → schemas/artifacts/visual_{direction,timeline}.schema.json
  validate_examples.py                       스키마·생성물·canonical script/span·출처 identity·fingerprint·legacy·부정 사례 검증
schemas/artifacts/visual_direction.schema.json · visual_timeline.schema.json   생성물 (self-contained, 손으로 고치지 않는다)
```

Phase 1에서 구현: README §11 API 전부 (`lib/direction_contract/hooks.py`가 공개), 게이트 연결 (`checkpoint_hooks.validate_stage` → `completion_gate`). `visual_timeline_compiler` 도구의 1.2 production path도 Phase 1에 포함 (정정 기록 참고). 하지 않은 것: Director 프롬프트·스킬 변경, 렌더 경로 변경, 자동 의미 vision QA (Phase 2).
