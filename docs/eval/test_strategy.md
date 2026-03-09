# TraceLog Real RAG Benchmark Strategy

## Goal

이 문서는 TraceLog를 **진짜로 평가하기 위한 유일한 테스트 전략**이다.

목표는 단순하다.

- 복잡한 실제 운영형 코드와 로그를 만든다.
- 같은 코드베이스에서 `standard logging` 과 `TraceLog` 를 각각 뽑는다.
- 두 결과를 **실제 RAG 파이프라인**에 태운다.
- 정답을 모르는 분석 에이전트가 원인을 찾게 한다.
- 별도의 Judge가 정답과 비교해 채점한다.

이 전략은 앞서 했던 간이 비교나 흉내 평가를 대체한다.

## Non-Negotiables

아래 조건은 반드시 지킨다.

1. **같은 코드베이스를 써야 한다.**
   `standard log` 버전과 `TraceLog` 버전은 기능적으로 같은 코드여야 한다. 로그 시스템만 달라야 한다.

2. **버그는 블랙박스여야 한다.**
   분석 에이전트는 물론이고, 실험 실행 시점의 운영 에이전트도 버그 정답을 직접 읽으면 안 된다.

3. **실제 RAG를 써야 한다.**
   lexical similarity, hand-crafted ranking, 가짜 retrieval은 금지한다.
   반드시 `Aggregator -> TraceTreeSplitter -> Indexer -> Retriever -> Diagnoser` 경로를 탄다.

4. **고난도 운영형 로그를 써야 한다.**
   toy example, 한두 줄 traceback 수준, 바로 눈에 띄는 예외 예제는 금지한다.
   로그는 길고, 반복이 있고, 동시성이 있고, noise가 있고, root cause와 surface error가 다를 수 있어야 한다.

   허용되는 구체 예시는 아래와 같다.

   - **이커머스 오더 파이프라인**
     `CheckoutOrchestrator -> PaymentService -> InventoryService -> PromotionService -> NotificationWorker`
     구조를 가진 코드.
     배치 주문, 재시도, background worker, DB lock, 외부 PG timeout, 쿠폰 계산, 배송비 계산이 섞여 있어야 한다.
     로그에는 성공한 item 처리 로그와 실패한 item 처리 로그가 길게 반복되어야 한다.

   - **멀티에이전트 물류/재고 동기화 시스템**
     여러 worker가 동시에 inventory reservation, restock sync, warehouse event consume를 수행하는 구조.
     race condition, duplicate consume, stale cache, dead-letter retry 로그가 같이 섞여야 한다.

   - **Maze / simulation 프로그램**
     단순 DFS 예제가 아니라, 여러 agent가 같은 grid를 탐색하고 path cache, heuristic scorer, async event queue를 공유하는 구조.
     surface error는 `IndexError` 또는 `KeyError` 처럼 단순해 보여도 실제 원인은 오래 전 잘못된 state mutation 또는 concurrent map update여야 한다.

   - **권한/세션이 섞인 API gateway + backend pipeline**
     `Gateway -> SessionVerifier -> UserProfile -> OrderService -> AsyncAuditWorker`
     형태.
     세션 만료, stale token cache, partial refresh, audit queue noise가 함께 존재해야 한다.

   아래 수준은 금지한다.

   - 함수 2~3개만 있는 작은 예제
   - traceback만 보면 바로 정답이 보이는 예제
   - unrelated noise가 거의 없는 예제
   - loop, retry, worker, async boundary가 없는 예제

5. **노트북이 중심이어야 한다.**
   실험은 Jupyter Notebook에서 orchestration, result review, reporting이 가능해야 한다.

6. **정답은 sealed truth로 분리해야 한다.**
   정답은 별도 truth artifact에 저장하고, Judge 단계 전까지 분석 입력에 섞이면 안 된다.

## What This Benchmark Must Prove

이 벤치마크는 아래 질문에 답해야 한다.

1. TraceLog 기반 RAG가 Standard Log 기반 RAG보다 root cause를 더 정확히 찾는가?
2. TraceLog 기반 RAG가 같은 root cause 사례를 더 잘 retrieval 하는가?
3. TraceLog 기반 RAG가 더 적은 시간 또는 더 적은 토큰으로 더 나은 결론에 도달하는가?
4. TraceLog가 특히 복잡한 동시성, 상태 누락, lexical ambiguity 시나리오에서 더 강한가?

## Required Agents

실험에는 최소 네 역할이 필요하다.

### 1. Generator Agent

역할:

- 상당히 복잡한 서비스 코드를 생성한다.
- 버그를 코드 내부에 블랙박스로 삽입한다.
- `ground_truth.json` 같은 sealed truth를 별도 저장한다.

규칙:

- 버그 정답은 analysis input에 절대 섞지 않는다.
- 버그는 표면 에러와 근본 원인이 다를 수 있어야 한다.
- 같은 surface error가 서로 다른 root cause로 나타나는 케이스를 만든다.

### 2. Instrumentation Agent

역할:

- 같은 코드베이스를 두 방식으로 실행한다.
- `standard logging` 출력 생성
- `TraceLog` 출력 생성

규칙:

- 코드 로직은 동일해야 한다.
- 차이는 instrumentation뿐이어야 한다.
- developer가 일부러 수동 enriched log를 써서 baseline을 과도하게 강화하면 안 된다.

### 3. Analyst Agent

역할:

- 정답을 모르는 상태에서 원인을 분석한다.
- 입력은 실험군/통제군별로 동일한 규칙 아래 제공한다.

비교 조건:

1. `Standard Log + RAG`
2. `TraceLog + RAG`

선택적 보조 조건:

3. `Standard Log Direct`
4. `TraceLog Direct`

직접 주입 실험은 보조 비교로만 쓰고, 주평가는 반드시 RAG 조건으로 한다.

### 4. Judge Agent

역할:

- sealed truth와 Analyst 결과를 비교한다.
- 정량 점수와 판정을 남긴다.

## Scenario Design

`int_docs/eval`은 **난이도와 스타일 참고용**으로만 사용한다.
기존 데이터를 그대로 재사용하지 않는다.

새 시나리오는 최소 아래 계열을 포함해야 한다.

1. **Deep propagated state bug**
   상위 함수에서 잘못 만든 값이 깊은 하위 함수에서 폭발하는 케이스

2. **Async or thread race**
   여러 worker 로그가 섞이고, surface error는 재고/락/timeout으로 보이지만 실제 원인은 상위 orchestration 또는 missing lock인 케이스

3. **Doppelganger error**
   같은 `TimeoutError` 또는 같은 `ValueError`가 서로 다른 root cause에서 발생하는 케이스

4. **Hidden bad input**
   겉보기엔 validation failure지만 실제 원인은 훨씬 앞선 request shaping 또는 state mutation인 케이스

5. **Background worker propagation**
   parent-child span reconstruction 없이는 causal chain을 잃는 케이스

6. **Long noisy batch flow**
   반복 루프, 다수 item, 중간 success logs, unrelated subsystem chatter가 포함된 케이스

### Concrete Scenario Blueprints

실제 생성 대상은 최소 아래 중 3개 이상이어야 한다.

#### Blueprint A. E-commerce Bulk Checkout

구성:

- `process_bulk_checkout(cart_id, user_id, items)`
- `verify_session()`
- `price_cart()`
- `reserve_inventory()`
- `charge_payment()`
- `emit_receipt_worker()`

필수 복잡도:

- 아이템 30~100개 반복 처리
- 일부 item은 성공, 일부는 warning, 마지막 일부에서 실패
- payment, inventory, notification 로그가 섞임
- background worker 로그가 끼어듦

숨길 수 있는 버그 예시:

- coupon normalization 버그로 음수 금액 생성
- missing lock 때문에 inventory double decrement
- expired session이 중간 batch item에서만 surface

#### Blueprint B. Warehouse Sync and Reservation

구성:

- `consume_order_event()`
- `reserve_bin_stock()`
- `sync_warehouse_snapshot()`
- `reconcile_delta()`
- `publish_dead_letter()`

필수 복잡도:

- queue consumer와 sync worker가 동시에 동작
- retry 로그, stale snapshot 로그, partial success 로그가 같이 존재
- root cause는 reconciliation mismatch인데 surface error는 reservation timeout으로 보이게 설계

숨길 수 있는 버그 예시:

- 오래된 snapshot version 사용
- duplicate event dedupe key collision
- async retry state leak

#### Blueprint C. Multi-Agent Maze Simulator

구성:

- `run_simulation()`
- `assign_agent_route()`
- `update_shared_grid_state()`
- `compute_escape_score()`
- `flush_agent_metrics()`

필수 복잡도:

- 여러 탐색 agent가 같은 grid/state를 공유
- pathfinding 로그, heuristic score 로그, metrics flush 로그가 섞임
- 실패는 late-stage evaluation에서 터지지만 원인은 초기 state mutation

숨길 수 있는 버그 예시:

- shared grid cell overwrite race
- heuristic cache key corruption
- stale path replay causing invalid coordinate

#### Blueprint D. API Gateway + Async Audit

구성:

- `handle_request()`
- `verify_token()`
- `load_profile()`
- `execute_business_action()`
- `push_audit_event()`
- `audit_worker_consume()`

필수 복잡도:

- request path와 audit path가 동시에 존재
- auth, profile, audit, config logs가 길게 섞임
- root cause는 token refresh ordering bug인데 surface error는 downstream permission failure로 보이게 설계

숨길 수 있는 버그 예시:

- stale token cache reuse
- parent context propagation loss in audit worker
- partial refresh after tenant switch

## Dataset Structure

각 incident는 아래 자산을 가져야 한다.

- `scenario_id`
- `scenario_family`
- `variant_id`
- `difficulty`
- `root_cause_id`
- `root_cause_function`
- `surface_error_function`
- `error_type`
- `code_path`
- `truth_path`
- `standard_log_path`
- `tracelog_dump_path`
- `aggregated_trace_path`
- `query_split`
- `historical_split`

추천 디렉토리 구조:

```text
docs/eval/
  test_strategy.md
  benchmark/
    scenarios/
    generated_code/
    datasets/
      historical/
      query/
    prompts/
    notebooks/
    results/
    truth/
```

## Execution Flow

실험은 아래 순서로 진행한다.

1. Generator Agent가 복잡한 코드와 블랙박스 버그를 생성한다.
2. Generator Agent는 sealed truth를 별도 파일에 저장한다.
3. Instrumentation Agent가 같은 코드에서 `standard log` 와 `TraceLog` 결과를 각각 생성한다.
4. TraceLog 쪽은 `Aggregator`로 unified trace를 만든다.
5. Historical incidents를 corpus로 만들어 인덱싱한다.
6. Query incidents는 holdout으로 남긴다.
7. `Standard Log + RAG` 조건으로 retrieval + diagnosis를 수행한다.
8. `TraceLog + RAG` 조건으로 retrieval + diagnosis를 수행한다.
9. Analyst 결과를 Judge가 sealed truth와 비교해 채점한다.
10. Notebook에서 결과를 시각화하고 최종 보고를 작성한다.

## RAG Conditions

이 벤치마크에서 RAG는 반드시 아래와 같이 작동해야 한다.

### Standard Log Path

- standard log를 chunking한다
- historical standard incidents를 vector store에 인덱싱한다
- query standard log로 retrieval 한다
- retrieved context + current log를 diagnosis model에 넣는다

### TraceLog Path

- TraceLog JSON dump를 aggregation 한다
- unified Trace-DSL을 TraceTreeSplitter로 chunking 한다
- historical TraceLog incidents를 vector store에 인덱싱한다
- query Trace-DSL로 retrieval 한다
- retrieved context + current trace를 diagnosis model에 넣는다

## Ground Truth Rules

Ground truth는 최소 아래를 포함해야 한다.

- `root_cause_function`
- `root_cause_type`
- `surface_error_function`
- `expected_error_surface_chain`
- `expected_evidence_markers`
- `expected_fix_region`

Judge는 최소 아래를 평가한다.

- root cause function correctness
- error surface correctness
- evidence grounding
- actionability

선택 평가:

- root cause type correctness

이 항목은 scenario마다 type schema가 안정적으로 정의될 때만 사용한다.

## Primary Metrics

아래 지표만 기본 지표로 사용한다.

원칙:

- 실제로 계산 가능한 지표만 넣는다.
- Judge가 점수화할 수 없는 모호한 표현은 기본 지표에서 제외한다.
- RAG 성능 지표는 retrieval/diagnosis 단계에 직접 대응되는 것만 쓴다.

### Retrieval

- `SameRootCauseHit@1`
- `SameRootCauseHit@3`
- `MRR`
- `nDCG@3`

### Diagnosis

- `root_cause_accuracy`
- `surface_accuracy`
- `evidence_match`
- `actionability`

### Operational

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `retrieval_latency`
- `diagnosis_latency`
- `time_to_verdict`

선택 지표:

- `cost_per_correct_diagnosis`

단, 모델 단가와 실행 시점 가격 기준을 함께 기록할 수 있을 때만 사용한다.

## Fairness Constraints

공정성을 위해 아래를 고정한다.

- 동일 query incident
- 동일 historical corpus size
- 동일 model family
- 동일 temperature
- 동일 judge rubric
- 동일 number of retrieved items

그리고 아래는 금지한다.

- 표준 로그 쪽에만 수동 enriched context 추가
- TraceLog 쪽에만 truth에 가까운 힌트 삽입
- query incident를 historical corpus에 그대로 중복 인덱싱

## Notebook Requirements

주피터 노트북은 최소 아래 섹션을 가져야 한다.

1. 실험 설정
2. scenario inventory
3. dataset generation status
4. historical/query split 확인
5. retrieval evaluation
6. diagnosis evaluation
7. failure case review
8. token/latency/cost summary
9. final verdict

노트북은 아래 두 모드 중 하나를 지원해야 한다.

- `analysis mode`: 기존 산출물 읽기
- `run mode`: generator와 RAG benchmark를 실제 실행

## Exit Criteria

이 벤치마크에서 TraceLog가 통과했다고 보려면 최소 아래를 만족해야 한다.

1. `TraceLog + RAG` 의 `root_cause_accuracy` 가 `Standard Log + RAG` 보다 높아야 한다.
2. `TraceLog + RAG` 의 `SameRootCauseHit@3` 가 `Standard Log + RAG` 보다 높아야 한다.
3. 개선은 특정 시나리오 하나가 아니라 여러 scenario family에서 반복돼야 한다.
4. token 또는 latency가 증가하더라도 운영적으로 감당 가능한 범위여야 한다.

## Immediate Next Step

이 문서를 기준으로 다음 구현을 시작한다.

1. advanced scenario generator 설계
2. sealed truth schema 정의
3. standard vs TraceLog dual runner 작성
4. real RAG benchmark notebook 작성
5. judge rubric 고정

이후의 모든 평가 코드는 이 문서의 제약을 따라야 한다.
