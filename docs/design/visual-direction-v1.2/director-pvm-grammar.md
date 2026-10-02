# Director 문법: 41 Persistent Visual Model 작성법

이 문서는 **새 모델 표현법이 아니다.** OpenMontage가 이미 재생(replay)할 수 있는 모델 — `lib/direction_contract/contract.py`의 element 모델과 `timeline_rail` — 을 Director가 안정적으로 쓰기 위한 표준 문법이다. 여기 없는 연산이나 상태 표현은 기계가 검증할 수 없으므로 쓰지 않는다.

## 1. 모델 = 이름 붙은 element들의 집합

```jsonc
"definition": {
  "id": "CAPITAL_FLOW",              // 대문자 스네이크. 40은 이 id로만 참조
  "type": "flow_network",            // 의미 이름(자유). timeline_rail만 전용 reducer가 있음
  "renderer": "bespoke",             // timeline_rail이 아니면 bespoke (atelier가 구현)
  "grammar": {"edge_value": "배분된 자금(총 100)"},   // 시각 속성이 이 영상에서 뜻하는 것
  "initial_state": {"elements": [ ... ]}
}
```

element 하나:

| 필드 | 뜻 | 규칙 |
|---|---|---|
| `id` | element 이름 | 모델 안에서 유일. 40 object가 `element_id`로 가리킴 |
| `kind` | `node` · `edge` · `value` · `label` · `group` · `region` … | 렌더러 어휘(자유). edge는 `from`/`to` 필수 |
| `label` | 화면 글자 | 영상 언어로 |
| `visible` | 처음부터 보이는가 | **기본 false**. 나중에 등장할 것은 false로 두고 REVEAL/ADD로 보이게 한다 |
| `attrs` | 숫자·상태 속성 | 검증하고 싶은 양은 반드시 숫자 attr로 (`value`, `size`, `emphasis` …) |

> 규칙: **나중에 바뀌는 양은 처음부터 attr로 둔다.** "메타로 가는 돈"이 0에서 10이 된다면 `ALLOC_META.attrs.value = 0`으로 시작한다. 없던 attr을 나중에 만들면 invariant 합계에서 빠진다.

## 2. 상태 변화 = 기존 연산 8개

Director는 40에서 **무엇이 어느 상태로 가는지**만 쓴다. 실제 연산(beat)은 Planner가 이 표에서 고른다. Director는 41의 element와 attr이 이 연산으로 표현 가능한지 확인하면 된다.

| 연산 | element 모델에서 하는 일 | 쓰는 곳 |
|---|---|---|
| `ADD` | element를 만들고 보이게 | 처음엔 없던 것 |
| `REVEAL` | 숨은 element를 보이게 (+attrs) | 미리 만들어 둔 것 등장 |
| `REMOVE` | 숨김 (상태는 남음) | 퇴장 |
| `CONNECT` | edge 생성/표시 | 관계 생김 |
| `EXPAND` | 숫자 attr을 `to` 또는 `by`만큼 | 양의 변화 (자금, 수익률) |
| `SHIFT` | attr 변경 / `target=view` 화면 변경 | 위치·강조·관점 |
| `PROPAGATE` | 경로를 따라 active 표시 | 전파 |
| `MEASURE` | 측정값 표시 | 수치 강조 |

## 3. 이름 붙은 상태 (`named_states`)

상태는 **state signature에 대한 assertion 묶음**이다. 쓸 수 있는 경로:

| 경로 | 뜻 |
|---|---|
| `elements.<id>.visible` | 보이는가 (true/false) |
| `elements.<id>.attrs.<attr>` | 숫자/값 속성 |
| `measures` | 표시 중인 측정값 목록 |
| `active` | PROPAGATE로 활성화된 element |
| `view.<key>` | 화면 수준 속성 |

연산자: `eq` `ne` `gt` `gte` `lt` `lte` `in` `exists` `absent`. 합계·최소·최대는 `aggregate`.

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
- 중간 상태도 이름을 붙인다. 이름 없는 중간 상태는 검증되지 않는다.

## 4. 전이 (`transitions`)와 handoff

- `transitions`: 허용되는 이동만 나열한다. 40의 action `from → to`가 여기 없으면 contract 오류.
- `handoffs`: 장면 경계에서 모델이 이어받는 상태. 다음 장면은 이 상태에서 시작해야 한다.
- 장면이 끝나도 모델은 끝나지 않는다. 화면에서 빠질 때는 40 장면의 `visibility: HIDDEN_BUT_ACTIVE`.

## 5. 40에서 상태·불변식을 쓰는 법

- 40 state는 `pvm_state: "CAPITAL_FLOW.REALLOCATED"`로 41을 참조하고, 그 장면만의 조건은 `object_states`로 덧붙인다.
- 모델 밖 대상(문서, 실사)은 `visible_objects`로. 이것은 replay가 아니라 렌더 후 binding + 출처 검증으로 판정된다.
- invariant
  - 총량 유지: `kind: CONSTANT` + `target.aggregate: sum` + `value`
  - 조건 유지: `kind: ASSERT` + `holds`
  - 순서 유지: `kind: ORDER` + `order: [A01, A02, A03]`
- **함께 일어나야 하는 변화**(한쪽에서 빼서 다른 쪽에 넣는 재배분)는 action에 `dependency.sync_group`을 준다. 같은 그룹의 연산은 같은 시각·같은 길이로 실행되고, invariant는 그룹 전체가 적용된 뒤에 평가된다. 그룹 없이 순차로 바꾸면 중간에 총량이 깨진 것으로 판정된다(실제로 화면에서도 깨진다).

## 6. 자주 하는 실수

| 실수 | 결과 | 고치는 법 |
|---|---|---|
| 나중에 나올 element를 `visible: true`로 시작 | 첫 상태 검증 실패, 결과가 미리 보임 | `false`로 시작, REVEAL |
| 양을 label 글자로만 표현 ("60%") | 숫자 검증 불가 | `attrs.value` 숫자로 |
| 중간 상태 생략 (S1 → S3) | REMOVE_INTERMEDIATE_STATE 검사 불가 | S2를 이름 붙여 둔다 |
| 재배분을 sync_group 없이 | 순간 총량 위반 | `sync_group` |
| 40에서 모델을 다시 정의 | 1.2에서 금지 | 41에만 정의 |

## 7. 사람용 템플릿과의 관계
원 설계 §34의 사람용 장면 템플릿([MEANING CONTRACT] … [QA])은 그대로 쓴다. 그 템플릿의 [STATES]·[INITIAL STATE]·[OBJECTS] 칸을 이 문서의 element / named_state / object 매핑으로 옮겨 적은 것이 40/41 JSON이다.
