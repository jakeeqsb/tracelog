# Benchmark v2 — Design Plan

> v1 결과와 논의를 통해 도출한 v2의 테스트 방향. 아직 구현 전.

---

## v1에서 배운 것

v1은 "로그만 주고 LLM이 버그 함수 이름을 맞추는가"를 측정했다.
이는 TraceLog의 실제 가치를 증명하지 못했다.

- Standard(A): 5/10, TraceLog(B): 6/10 — 차이가 1개
- 코드 없이 1-shot 진단은 어차피 둘 다 어렵다
- 로그 포맷 퀴즈를 테스트한 것이지, TraceLog의 가치를 테스트한 것이 아니다

---

## v2가 증명하려는 것

### Hypothesis 1: 진단 효율

> TraceLog 기반 로그가 Standard 로그보다 LLM이 더 빠르고, 정확하고,
> 적은 토큰으로 원인을 파악할 수 있다.

**핵심 차이 — 코드 탐색량:**

```
Standard log:  "TypeError in process_order"
               → 에이전트가 어느 파일인지 모름
               → 여러 함수 코드를 뒤짐 → 토큰 많이 씀

TraceLog:      "<< return '100 ea'  (fetch_inventory)"
               → 에이전트가 fetch_inventory 즉시 확인
               → 그 함수 코드만 보면 됨 → 토큰 적게 씀
```

**측정 지표:**
- 정확도 (root cause 식별)
- 총 토큰 수 (로그 + 에이전트가 요청한 코드)
- 에이전트 턴 수 (몇 번 왕복했는가)

**v1과의 차이:** 에이전트에게 코드를 요청할 수 있는 능력을 부여한다.
TraceLog는 "어느 함수를 봐야 하는지" 가리키고, 에이전트는 그 함수만 열면 된다.
Standard log는 어디를 봐야 하는지 모르므로 더 많은 코드를 읽어야 한다.

---

### Hypothesis 2: 이력 기반 방향 제시

> 과거 장애와 해결 방법이 RAG에 축적되면,
> 새 장애 발생 시 더 나은 해결 방향을 제시할 수 있다.

**RAG 저장 단위 (v1과 다른 핵심):**

```
v1 (잘못된 방식)
  → 과거 tracelog.log 청크만 저장
  → 에이전트가 "비슷한 로그"는 보지만 해결 방법은 모름

v2 (올바른 방식)
  → resolved incident report 저장
     {
       tracelog_chunk: "...",
       root_cause: "fetch_inventory_from_erp",
       fix: "ERP 응답 타입 검증 추가, int() 캐스팅",
       service: "warehouse-sync"
     }
  → 에이전트가 "이 패턴일 때 원인은 X, 해결책은 Y" 를 참조 가능
```

**측정 지표:**
- fix direction 정확도 (with RAG vs without RAG)
- 에이전트 턴 수

---

## 두 가설의 관계

```
Hypothesis 1: TraceLog → 어느 함수를 봐야 하는지 빠르게 가리킴
                                    ↓
              그 진단 결과가 resolved incident report로 RAG에 축적
                                    ↓
Hypothesis 2: 다음 번 같은 패턴 장애 → RAG가 "이전에 이런 경우 X가 원인이었음" 제시
```

TraceLog의 구조화된 포맷은 두 가설 모두에서 핵심 역할을 한다.
- Hypothesis 1: `<< return` 값이 코드 탐색 범위를 줄여줌
- Hypothesis 2: 구조화된 trace가 RAG 임베딩 품질을 높임

---

## 구현 우선순위

| 순서 | 내용 | 난이도 |
|------|------|--------|
| 1 | Hypothesis 2 데모 — resolved incident RAG, 같은 패턴 재발 시나리오 | 낮음 |
| 2 | Hypothesis 1 — 코드 포함, 토큰/턴 비교 (단순 버전) | 중간 |
| 3 | Hypothesis 1 — 에이전트 반복 루프 (실제 운영 시나리오) | 높음 |

---

## 미결 사항

- 시나리오는 hand-crafted로 작성 (AI 생성 방식 재검토)
- 에이전트가 코드를 요청하는 tool 설계 필요
- resolved incident report 스키마 확정 필요
