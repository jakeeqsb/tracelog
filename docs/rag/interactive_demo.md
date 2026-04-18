# RAG Interactive Demo — Seed + REPL

## Goal

Provide a local dev playground for exploring the TraceLog RAG pipeline hands-on:
seed the vector store with rich, diverse incidents and postmortems, then query them
interactively from a REPL without writing any code.

## Components

### 1. `scripts/seed_rag_demo.py` — Data Seeder

Populates `tracelog_incidents` and `tracelog_postmortems` collections in the local Qdrant
instance with a realistic, varied dataset.

**Dataset: 7 services × 2–3 incident variants = ~18 incidents**

| Service | Error Type | # Incidents | Postmortem? |
|---|---|---|---|
| `payment-service` | ValueError (string→numeric) | 3 | 2 resolved |
| `auth-service` | KeyError (missing session field) | 2 | 1 resolved |
| `inventory-service` | ConnectionError (DB timeout) | 2 | 1 resolved |
| `order-service` | TimeoutError (downstream call) | 3 | 2 resolved |
| `warehouse-sync` | RuntimeError (thread lock / data race) | 3 | 1 resolved |
| `notification-service` | IOError (HTTP 429 rate limit) | 2 | 0 resolved |
| `data-pipeline` | TypeError (schema mismatch) | 3 | 2 resolved |

각 incident dump은 실제적인 Trace-DSL 로그 (multi-level 콜스택, 인자 캡처,
`!!` 에러 마커). Postmortem에는 `root_cause`와 `fix`가 담겨 retriever가 함께 서빙.

**Behavior:**
- `.env`의 `QDRANT_URL` 사용 (기본 localhost)
- 결정론적 ID로 upsert (재실행 safe — 중복 없음)
- 완료 후 요약 테이블 출력: `collection | count | resolved | open`
- `--reset` 플래그: 두 컬렉션을 드롭 후 재생성

### 2. `scripts/rag_repl.py` — Interactive Query REPL

readline 기반 REPL로 retriever/diagnoser 전체 기능을 인터랙티브하게 탐색.

**Commands:**

| Command | Description |
|---|---|
| `search <text>` | `tracelog_incidents` 벡터 서치 (top-5, error-only) |
| `fixes <text>` | `tracelog_postmortems` 직접 벡터 서치 |
| `diagnose <text>` | `search` + LLM 단발 호출 (`TraceLogDiagnoser`) |
| `list [open\|resolved]` | 전체 incident 스크롤, status 필터 옵션 |
| `show <incident_id>` | incident 1건 + 연결된 postmortem 출력 |
| `count` | 두 컬렉션 현재 포인트 수 출력 |
| `help` | 명령 목록 출력 |
| `quit` / `exit` / Ctrl-D | REPL 종료 |

**`search` 출력 예시:**
```
[1] score=0.9231  incident_id=ValueError_payment_api.log::0
    error_type=ValueError  status=resolved
    chunk: >> process_payment  user_id: 101  amount: "5000" ↵  !! ValueError...
    root_cause : Payment amount arrived as a string ...
    fix        : Added explicit int(str(amount).strip()) cast ...
```

**`diagnose` 출력 예시:**
```
--- LLM Diagnosis ---
root_cause_function : parse_unit_price
root_cause_type     : ValueError
fix_hint            : Strip non-numeric suffix before float() conversion
confidence          : high
actionable          : true
model=gpt-4o-mini  input_tokens=842  output_tokens=120  chunks_used=3
```

## 파일 위치

```
scripts/
  seed_rag_demo.py      ← 데이터 시더
  rag_repl.py           ← 인터랙티브 REPL
```

`tracelog/` 패키지 코드 변경 없음. 독립 dev 스크립트.

## 의존성

신규 의존성 없음. 기존 `tracelog` 패키지 + `readline` (stdlib) 사용.

## 실행 방법

```bash
# 1. 데이터 시딩 (최초 or --reset 후)
python scripts/seed_rag_demo.py

# 2. REPL 시작
python scripts/rag_repl.py

# 컬렉션 초기화 후 재시딩
python scripts/seed_rag_demo.py --reset
```

## Notes

- 두 스크립트 모두 `.env` 읽음 — `OPENAI_API_KEY`, `QDRANT_URL`, collection names
- Seeder는 idempotent (결정론적 ID upsert) — 여러 번 실행 safe
- `diagnose`는 실제 LLM 호출 (토큰 소비 / `OPENAI_API_KEY` 필요)
- `search`와 `fixes`는 순수 벡터 DB 쿼리 — LLM 호출 없음, 즉각 응답
