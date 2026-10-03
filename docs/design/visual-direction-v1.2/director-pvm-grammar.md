# Director 문법: 41 Persistent Visual Model 작성법

이 문서는 **41 `persistent_visual_models` 전용**이다. 40 장면 연출(의미, 앵커, state·action·event, 마지막 화면, 보존·자유·금지)을 쓰는 법은 [`director-authoring-guide.md`](director-authoring-guide.md)에 있고, 여기서는 반복하지 않는다.

41은 **새 모델 표현법이 아니다.** OpenMontage가 이미 재생(replay)할 수 있는 모델 — `lib/direction_contract/contract.py`의 element 모델과 `timeline_rail` — 에 이름 붙은 상태·전이·handoff를 더한 것이다. 여기 없는 연산이나 상태 경로는 기계가 검증할 수 없으므로 쓰지 않는다.

## 0. 무엇을 쓰고 무엇을 쓰지 않는가

| Director가 쓴다 | 쓰지 않는다 (시스템이 만든다) |
|---|---|
| `definition` (id, type, grammar, initial_state, 선택: title, palette, labels, renderer) | `current_state`, `state_history` — 컴파일된 timeline을 replay해서 얻는다 |
| `semantic_role` (필수) | 40 `authority.pvm_ref.sha256`, fingerprint — Bridge가 계산 |
| `named_states` (필수, 1개 이상) | 장면별 진입 상태의 실제 값 — replay의 ENTRY_SIGNATURE |
| 필요할 때: `transitions`, `handoffs`, `persistence` | |

## 1. 모델 정의

```jsonc
"definition": {
  "id": "CAPITAL_FLOW",              // 대문자 스네이크. 40은 이 id로만 참조
  "type": "flow_network",            // 의미 이름(자유). timeline_rail만 전용 reducer가 있다
  "grammar": {"edge_value": "배분된 자금(총 100)"},   // 시각 속성이 이 영상에서 뜻하는 것
  "initial_state": {"elements": [ ... ]}
}
```

- **`type`**은 화면이 뜻하는 것(메커니즘)으로 고른다. renderer 지원 여부로 고르지 않는다. `timeline_rail`은 전용 reducer와 범용 renderer가 있고, 그 밖의 모든 type은 **element 모델**이다.
- **`renderer`**: `generic` = 공유 renderer가 그린다 (현재 `timeline_rail`만). `bespoke` = 공유 renderer가 없어 이 모델 전용 구현이 필요하다. 생략하면 type에 따라 정해진다. **`bespoke`는 "atelier가 그린다"는 뜻이 아니다.** 누가 어떤 runtime으로 실행하는지는 40 장면의 runtime 지정(`runtime_stack`)이 정하고, 실제로 실행된 것은 43 binding이 기록한다. (예시 CAPITAL_FLOW는 bespoke 모델이고 remotion `deterministic_graphics` layer에서 실행된다.)
- 모델은 41에만 정의한다. 40이나 visual_direction 1.2에서 다시 정의하면 오류다 (D4).

## 2. element 모델: element와 attr

element 하나:

| 필드 | 뜻 | 규칙 |
|---|---|---|
| `id` | element 이름 | 모델 안에서 유일. 40 object가 이 element를 가리킨다 |
| `kind` | `node` · `edge` · `value` · `label` · `group` · `region` … | renderer 어휘(자유). 생략 = `node`. edge는 `from`/`to` |
| `label` | 화면 글자 | 영상 언어로 |
| `visible` | 처음부터 보이는가 | **생략 = false.** 나중에 등장할 것은 false로 두고 REVEAL/ADD로 보이게 한다 |
| `attrs` | 숫자·상태 속성 | 검증하고 싶은 양은 반드시 숫자 attr로 (`value`, `size`, `emphasis` …) |

> 규칙: **나중에 바뀌는 양은 처음부터 attr로 둔다.** "메타로 가는 돈"이 0에서 10이 된다면 `ALLOC_META.attrs.value = 0`으로 시작한다. 없던 attr을 나중에 만들면 invariant 합계에서 빠진다.

## 3. 연산 — 모델 종류마다 다르다

Director는 40에서 **무엇이 어느 상태로 가는지**만 쓴다. 실제 연산(beat)은 Planner가 이 표에서 고른다. Director는 41의 element·attr(또는 rail item)이 이 연산들로 표현 가능한지만 확인한다.

### 3-1. element 모델 (8개)

| 연산 | 하는 일 |
|---|---|
| `ADD` | element를 만들고 보이게 (이미 있으면 갱신) |
| `REVEAL` | 숨은 element를 보이게 (+attrs) |
| `REMOVE` | 숨김 (element와 attr은 남는다) |
| `CONNECT` | edge 생성/표시 (`from`, `to`) |
| `EXPAND` | 숫자 attr을 `to`로 바꾸거나 `by`만큼 더함 (기본 attr `value`) |
| `SHIFT` | attr 변경, 또는 `target=view`로 화면 수준 속성 변경 |
| `PROPAGATE` | 경로의 element에 active 표시 |
| `MEASURE` | 측정값 표시 (`clear`로 지움) |

예약 target: `view`, `all`.

### 3-2. `timeline_rail` (6개)

| 연산 | 하는 일 |
|---|---|
| `ADD` | item 추가/갱신 (present) |
| `REMOVE` | item 제외 (present = false) |
| `EXPAND` | item 길이를 `to` 또는 `by`만큼. `propagate: deferred`면 뒤 item을 잠시 고정 |
| `SHIFT` | item 계획 시작·준비 시각, `slot_interval`, 또는 `view`(축·deadline·표시) |
| `PROPAGATE` | 고정을 풀어 결과가 화면에 나타나게 |
| `MEASURE` | wait · idle_before · duration · overrun 측정 표시 |

**`REVEAL`과 `CONNECT`는 rail에 없다.** 예약 target: `slot_interval`, `view`, `all`.

## 4. 이름 붙은 상태 (`named_states`)

상태는 **모델 상태 signature에 대한 assertion 묶음**이다. 40은 `<model_id>.<state id>`로 참조한다. assertion 경로는 모델 종류에 따라 다르다.

### 4-1. element 모델 경로

| 경로 | 뜻 |
|---|---|
| `elements.<id>.visible` | 보이는가 (true/false) |
| `elements.<id>.attrs.<attr>` | 숫자/값 속성 |
| `elements.<id>.label` · `.kind` · `.from` · `.to` | 글자·종류·연결 (필요할 때만) |
| `measures` | 표시 중인 측정값 목록 |
| `active` | PROPAGATE로 활성화된 element id 목록 |
| `view.<key>` | 화면 수준 속성 |

### 4-2. `timeline_rail` 경로

| 경로 | 뜻 |
|---|---|
| `items.<id>.present` | 포함되어 있는가 |
| `items.<id>.planned_start` · `.ready` · `.actual_start` · `.actual_end` | 계획·준비·실제 시각 |
| `axis.<key>` · `deadline` | 축과 마감 |
| `measures` | 표시 중인 측정값 목록 |
| `show` | `[계획 표시, 실제 표시]` |

rail에는 `elements`, `active`, `view` 경로가 없다.

연산자: `eq` `ne` `gt` `gte` `lt` `lte` `in` `exists` `absent` (`tolerance`는 숫자 eq/ne). 합계·최소·최대·참 개수는 `aggregate` (`sum` `min` `max` `count_true`) + `paths`.

```jsonc
{"id": "REALLOCATED", "description": "같은 자금 100이 더 많은 채권 사이로 나뉨",
 "assert": [
   {"path": "elements.ALLOC_META.visible", "op": "eq", "value": true},
   {"path": "elements.ALLOC_META.attrs.value", "op": "gt", "value": 0},
   {"path": "elements.ALLOC_UST.attrs.value", "op": "lt", "value": 60}
 ]}
```

규칙
- **상태는 "보이는 차이"로 쓴다.** 의미 설명은 `description`에, 검증은 `assert`에.
- 정확한 숫자를 고정할 필요가 없으면 `gt`/`lt`로 방향만 잠근다 (구현 자유를 남긴다).
- **이름은 의미상 중요하거나 검증해야 하는 상태에만 붙인다.** 모든 중간 프레임에 이름을 붙일 필요는 없다. 다만 이름 없는 중간 상태는 검증되지 않는다: 원인과 결과 사이의 반응처럼 생략되면 안 되는 중간 상태는 이름을 붙여야 `REMOVE_INTERMEDIATE_STATE`를 잡을 수 있다.

## 5. 전이 (`transitions`)

- **없거나 빈 목록이면 named state 사이의 어떤 이동도 허용된다.**
- **하나라도 적으면 허용 목록이다.** 40 action의 `from → to`(같은 모델의 두 named state)가 목록에 없으면 contract 오류.
- 원인 → 중간 반응 → 결과처럼 **순서 자체가 주장인 인과 모델**(LOCKED 장면에서 causal 연출을 받는 모델)은 목록을 적는 것을 권장한다. 잘못된 지름길(BASE → YIELD_PRESSURE)을 contract 단계에서 막는다.
- `meaning`은 사람이 읽는 설명이다.

## 6. 장면을 넘는 연속성: `handoffs`와 `persistence`

모델은 장면이 끝나도 끝나지 않는다. 상태는 화면에서 빠져 있어도 replay로 이어진다.

### 6-1. handoff = 장면 간 연속성 계약

```jsonc
"handoffs": [{"from_scene": "SC020", "to_scene": "SC021", "state": "YIELD_PRESSURE"}]
```

handoff는 **두 가지를 동시에** 약속한다.
1. `from_scene`이 끝날 때 모델이 `state`에 있다.
2. `to_scene`은 그 상태를 **이어받아 시작한다.**

그래서 handoff를 적으면:
- `to_scene`은 40에서 이 모델을 `models`에 선언해야 한다. 화면에 보이면 `VISIBLE`, 화면에는 없지만 상태가 이어져야 하면 **`HIDDEN_BUT_ACTIVE`**.
- `to_scene`이 진입 상태(`enter_state`)를 적는다면 handoff 상태와 같아야 한다. 생략하면 handoff 상태다.
- `to_scene`의 initial_state가 이 모델의 상태라면 handoff 상태여야 한다.
- `to_scene`은 `from_scene`보다 뒤여야 한다.
- 검증 (45 PERSISTENT_STATE): `from_scene` 끝의 상태, 그리고 `to_scene`의 **ENTRY_SIGNATURE** — 그 장면 자신의 첫 연산이 적용되기 전의 replay 상태. 첫 앵커에서 action이 바로 시작해도 그 연산은 진입 상태에 들어가지 않는다.

handoff는 **다음 장면이 모델 상태를 실제로 이어받을 때만** 쓴다. 다음 장면이 모델을 쓰지 않고 내레이션·편집으로만 이어진다면 handoff가 아니라 40 마지막 화면의 장면 연결(`handoff_to_scene`, `next_scene_seed`)로 쓴다. (예시: SC009 → SC010은 금리표 증거 장면으로의 편집상 연결이고 PVM handoff가 아니다.)

### 6-2. persistence

| 필드 | 뜻 |
|---|---|
| `first_scene` · `last_scene` | 모델의 수명 범위. 적었다면 모든 handoff의 `from_scene`..`to_scene`을 포함해야 한다 |
| `survives_hidden` | 화면 밖에서도 상태가 유지되는가 (기본 true). **false인 모델은 handoff 목적지에서 `HIDDEN_BUT_ACTIVE`로 둘 수 없다** |
| `default_visibility` | 장면이 모델을 선언할 때의 기본 가시성 (기록용. 현재 기계 검사 대상 아님) |

## 7. 자주 하는 실수

| 실수 | 결과 | 고치는 법 |
|---|---|---|
| 나중에 나올 element를 `visible: true`로 시작 | 첫 상태 검증 실패, 결과가 미리 보임 | 생략(false)으로 시작, REVEAL |
| 양을 label 글자로만 표현 ("60%") | 숫자 검증 불가 | `attrs.value` 숫자로 |
| 생략되면 안 되는 중간 반응에 이름이 없음 | REMOVE_INTERMEDIATE_STATE 검사 불가 | 그 상태만 이름 붙인다 |
| rail 모델에 REVEAL/CONNECT, `elements.*` 경로 | contract 오류 / assertion이 항상 실패 | 3-2·4-2 표 |
| 다음 장면이 모델을 쓰지 않는데 handoff | 목적지 미선언 contract 오류 | 장면 연결은 40 `handoff_to_scene` |
| `survives_hidden: false` 모델을 숨긴 채 넘김 | contract 오류 | VISIBLE로 넘기거나 survives_hidden 재검토 |
| 40에서 모델을 다시 정의 | 1.2에서 금지 | 41에만 정의 |
