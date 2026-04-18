"""scripts/seed_rag_demo.py — RAG demo data seeder.

7개 서비스 × 2~3 incident 변형 (~18개 incident) + postmortem을
로컬 Qdrant에 시딩합니다.

Usage:
    python scripts/seed_rag_demo.py            # upsert (idempotent)
    python scripts/seed_rag_demo.py --reset    # 컬렉션 초기화 후 재시딩
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Incident dumps (Trace-DSL format)
# ---------------------------------------------------------------------------

INCIDENT_DUMPS: dict[str, str] = {
    # ── payment-service ─────────────────────────────────────────────────────
    "ValueError_payment_api.log": """\
>> handle_payment_request
  request_id: "pay-8821"
  user_id: 304
  >> validate_payment_payload
    raw_amount: "1500"
    currency: "KRW"
    >> parse_payment_amount
      raw: "1500"
      !! ValueError: invalid literal for int() with base 10: '1500'
    << parse_payment_amount
  << validate_payment_payload
!! ValueError: invalid literal for int() with base 10: '1500'
<< handle_payment_request
""",
    "ValueError_payment_refund.log": """\
>> process_refund
  refund_id: "ref-0047"
  order_id: "ord-5512"
  >> compute_refund_amount
    original_amount: "89.90 USD"
    >> parse_currency_value
      raw: "89.90 USD"
      !! ValueError: could not convert string to float: '89.90 USD'
    << parse_currency_value
  << compute_refund_amount
!! ValueError: could not convert string to float: '89.90 USD'
<< process_refund
""",
    "ValueError_payment_subscription.log": """\
>> renew_subscription
  subscription_id: "sub-1193"
  plan: "premium"
  >> calculate_renewal_fee
    base_fee: "9,900"
    discount: "0.10"
    >> parse_base_fee
      raw: "9,900"
      !! ValueError: invalid literal for int() with base 10: '9,900'
    << parse_base_fee
  << calculate_renewal_fee
!! ValueError: invalid literal for int() with base 10: '9,900'
<< renew_subscription
""",

    # ── auth-service ─────────────────────────────────────────────────────────
    "KeyError_auth_session.log": """\
>> authenticate_request
  request_id: "req-9f3a"
  >> load_session
    session_store: redis
    >> fetch_session_data
      key: "session:tok-expired-7f2b"
      result: {}
      !! KeyError: 'user_id'
    << fetch_session_data
  << load_session
!! KeyError: 'user_id'
<< authenticate_request
""",
    "KeyError_auth_permissions.log": """\
>> authorize_resource_access
  user_id: 881
  resource: "admin-panel"
  >> load_user_permissions
    >> fetch_permissions_cache
      cache_key: "perms:881"
      result: {"groups": ["viewer"]}
      >> resolve_permission_flags
        raw_perms: {"groups": ["viewer"]}
        !! KeyError: 'roles'
      << resolve_permission_flags
    << fetch_permissions_cache
  << load_user_permissions
!! KeyError: 'roles'
<< authorize_resource_access
""",

    # ── inventory-service ───────────────────────────────────────────────────
    "ConnectionError_inventory_db.log": """\
>> reserve_stock
  sku: "ITEM-4421"
  quantity: 50
  >> acquire_db_connection
    pool: "inventory-primary"
    timeout_ms: 3000
    >> connect_to_replica
      host: "db-replica-03.internal"
      port: 5432
      !! ConnectionError: [Errno 110] Connection timed out
    << connect_to_replica
  << acquire_db_connection
!! ConnectionError: [Errno 110] Connection timed out
<< reserve_stock
""",
    "ConnectionError_inventory_cache.log": """\
>> get_inventory_snapshot
  warehouse_id: "WH-07"
  >> load_from_cache
    cache_host: "redis-inventory.internal"
    >> ping_cache
      !! ConnectionError: Redis connection refused at redis-inventory.internal:6379
    << ping_cache
  << load_from_cache
!! ConnectionError: Redis connection refused at redis-inventory.internal:6379
<< get_inventory_snapshot
""",

    # ── order-service ────────────────────────────────────────────────────────
    "TimeoutError_order_fulfillment.log": """\
>> fulfill_order
  order_id: "ord-8847"
  warehouse_id: "WH-02"
  >> call_warehouse_api
    endpoint: "POST /warehouse/allocate"
    timeout_s: 5
    >> send_http_request
      url: "http://warehouse-service.internal/allocate"
      !! TimeoutError: HTTPSConnectionPool read timed out after 5.0s
    << send_http_request
  << call_warehouse_api
!! TimeoutError: HTTPSConnectionPool read timed out after 5.0s
<< fulfill_order
""",
    "TimeoutError_order_payment_gateway.log": """\
>> charge_order
  order_id: "ord-0293"
  gateway: "stripe"
  >> call_payment_gateway
    provider: "stripe"
    endpoint: "POST /v1/charges"
    timeout_s: 10
    >> execute_gateway_request
      !! TimeoutError: Stripe API did not respond within 10s
    << execute_gateway_request
  << call_payment_gateway
!! TimeoutError: Stripe API did not respond within 10s
<< charge_order
""",
    "TimeoutError_order_notification.log": """\
>> send_order_confirmation
  order_id: "ord-3391"
  channel: "email"
  >> dispatch_notification
    provider: "sendgrid"
    >> call_sendgrid_api
      endpoint: "POST /v3/mail/send"
      !! TimeoutError: SendGrid API timeout after 8s
    << call_sendgrid_api
  << dispatch_notification
!! TimeoutError: SendGrid API timeout after 8s
<< send_order_confirmation
""",

    # ── warehouse-sync ───────────────────────────────────────────────────────
    "RuntimeError_warehouse_lock.log": """\
>> sync_inventory_batch
  batch_id: "batch-0091"
  worker_count: 4
  >> acquire_sync_lock
    lock_key: "inventory:sync:WH-01"
    >> try_acquire_distributed_lock
      ttl_s: 30
      !! RuntimeError: Failed to acquire distributed lock after 3 retries
    << try_acquire_distributed_lock
  << acquire_sync_lock
!! RuntimeError: Failed to acquire distributed lock after 3 retries
<< sync_inventory_batch
""",
    "RuntimeError_warehouse_stale_data.log": """\
>> apply_inventory_delta
  delta_id: "delta-4420"
  >> validate_delta_version
    current_version: 42
    delta_base_version: 39
    >> check_version_continuity
      gap: 3
      !! RuntimeError: Delta version gap detected (base=39, current=42) — stale update rejected
    << check_version_continuity
  << validate_delta_version
!! RuntimeError: Delta version gap detected (base=39, current=42) — stale update rejected
<< apply_inventory_delta
""",
    "RuntimeError_warehouse_worker_crash.log": """\
>> run_warehouse_worker
  worker_id: "worker-07"
  >> process_task_queue
    queue: "warehouse-tasks"
    >> handle_task
      task_id: "task-0812"
      task_type: "recount"
      >> execute_recount_task
        !! RuntimeError: Worker process terminated unexpectedly (signal 11)
      << execute_recount_task
    << handle_task
  << process_task_queue
!! RuntimeError: Worker process terminated unexpectedly (signal 11)
<< run_warehouse_worker
""",

    # ── notification-service ─────────────────────────────────────────────────
    "IOError_notification_rate_limit.log": """\
>> send_push_notification
  notification_id: "notif-7721"
  channel: "fcm"
  >> call_fcm_api
    endpoint: "POST https://fcm.googleapis.com/v1/messages"
    >> execute_http_post
      response_status: 429
      !! IOError: FCM rate limit exceeded — HTTP 429 Too Many Requests
    << execute_http_post
  << call_fcm_api
!! IOError: FCM rate limit exceeded — HTTP 429 Too Many Requests
<< send_push_notification
""",
    "IOError_notification_email_quota.log": """\
>> send_bulk_email
  campaign_id: "camp-0044"
  recipient_count: 50000
  >> call_ses_api
    service: "AWS SES"
    >> submit_send_batch
      batch_size: 1000
      !! IOError: AWS SES sending quota exceeded — daily limit reached
    << submit_send_batch
  << call_ses_api
!! IOError: AWS SES sending quota exceeded — daily limit reached
<< send_bulk_email
""",

    # ── data-pipeline ────────────────────────────────────────────────────────
    "TypeError_pipeline_schema.log": """\
>> transform_user_event
  event_id: "evt-3312"
  source: "mobile-app"
  >> apply_schema_transform
    schema_version: "v3"
    >> map_event_fields
      raw_event: {"user_id": "u-881", "ts": "2026-04-10T14:00:00"}
      >> cast_timestamp_field
        raw_ts: "2026-04-10T14:00:00"
        !! TypeError: unsupported operand type(s) for -: 'str' and 'datetime'
      << cast_timestamp_field
    << map_event_fields
  << apply_schema_transform
!! TypeError: unsupported operand type(s) for -: 'str' and 'datetime'
<< transform_user_event
""",
    "TypeError_pipeline_aggregation.log": """\
>> run_daily_aggregation
  date: "2026-04-17"
  metric: "total_revenue"
  >> aggregate_transactions
    >> sum_revenue_values
      values: [1200, "N/A", 850, 0]
      >> reduce_sum
        !! TypeError: unsupported operand type(s) for +: 'int' and 'str'
      << reduce_sum
    << sum_revenue_values
  << aggregate_transactions
!! TypeError: unsupported operand type(s) for +: 'int' and 'str'
<< run_daily_aggregation
""",
    "TypeError_pipeline_join.log": """\
>> join_user_session_data
  pipeline_id: "pipe-0017"
  >> merge_datasets
    left_schema: "sessions_v2"
    right_schema: "users_v1"
    >> validate_join_key_types
      left_key_type: int
      right_key_type: str
      !! TypeError: Cannot join on columns with incompatible types: int vs str
    << validate_join_key_types
  << merge_datasets
!! TypeError: Cannot join on columns with incompatible types: int vs str
<< join_user_session_data
""",
}

# ---------------------------------------------------------------------------
# Postmortems (resolved incidents only)
# file_name::chunk_index 형식 — 모두 단일 청크라 ::0
# ---------------------------------------------------------------------------

POSTMORTEMS = [
    # payment-service
    {
        "incident_id": "ValueError_payment_api.log::0",
        "root_cause": (
            "결제 금액이 폼 입력에서 문자열로 그대로 넘어왔다. "
            "validate_payment_payload이 non-numeric 문자 제거 없이 int()에 직접 전달했음."
        ),
        "fix": (
            "API 경계에서 int(re.sub(r'[^0-9]', '', amount)) 캐스트를 추가. "
            "빈 문자열이면 ValueError 대신 InvalidAmountError를 명시적으로 raise."
        ),
    },
    {
        "incident_id": "ValueError_payment_refund.log::0",
        "root_cause": (
            "환불 금액에 통화 단위('USD')가 붙어 있어 float() 변환이 실패. "
            "parse_currency_value가 숫자 부분만 추출하는 로직 없이 raw 값을 그대로 사용."
        ),
        "fix": (
            "정규식으로 숫자와 소수점만 추출: float(re.sub(r'[^0-9.]', '', raw)). "
            "통화 코드는 별도 필드로 분리."
        ),
    },
    # auth-service
    {
        "incident_id": "KeyError_auth_session.log::0",
        "root_cause": (
            "만료된 세션이 Redis에서 빈 dict {}로 반환됐고, "
            "load_session이 'user_id' 키 존재 여부를 확인하지 않아 KeyError 발생."
        ),
        "fix": (
            "fetch_session_data 직후 빈 dict 또는 'user_id' 누락 시 "
            "SessionExpiredError를 raise. KeyError를 외부로 전파하지 않음."
        ),
    },
    # inventory-service
    {
        "incident_id": "ConnectionError_inventory_db.log::0",
        "root_cause": (
            "inventory-primary DB 커넥션 풀이 고갈된 상태에서 replica 직접 연결을 시도. "
            "timeout_ms=3000이 너무 짧아 네트워크 지연 시 즉시 실패."
        ),
        "fix": (
            "커넥션 풀 exhaustion 감지 시 exponential backoff(최대 3회) 재시도 추가. "
            "timeout_ms를 10000으로 상향 조정하고 회로 차단기 패턴 적용."
        ),
    },
    # order-service
    {
        "incident_id": "TimeoutError_order_fulfillment.log::0",
        "root_cause": (
            "warehouse-service 응답 지연이 5초를 초과. "
            "재고 할당 로직에서 무거운 DB 쿼리가 병목으로 작용."
        ),
        "fix": (
            "동기 HTTP 호출을 비동기(asyncio) + 큐 기반 처리로 전환. "
            "타임아웃을 15초로 늘리고 partial success 시 재시도 로직 추가."
        ),
    },
    {
        "incident_id": "TimeoutError_order_payment_gateway.log::0",
        "root_cause": (
            "Stripe API 호출이 피크 타임에 10초를 넘어섬. "
            "단일 동기 호출에 fallback 없이 실패를 그대로 전파."
        ),
        "fix": (
            "idempotency key 기반 재시도(최대 2회, 지수 대기) 추가. "
            "Stripe webhook으로 최종 상태 확인하도록 결제 상태 머신 보강."
        ),
    },
    # warehouse-sync
    {
        "incident_id": "RuntimeError_warehouse_lock.log::0",
        "root_cause": (
            "동시에 여러 sync 워커가 동일 lock_key를 경쟁. "
            "TTL=30s 잠금이 해제되기 전 이전 워커가 크래시해 잠금이 유지됨."
        ),
        "fix": (
            "잠금 TTL을 워커 heartbeat(5s)와 연동하여 자동 갱신. "
            "워커 크래시 시 잠금 강제 해제 API 추가. 잠금 경쟁 시 jitter 포함 backoff 적용."
        ),
    },
    # data-pipeline
    {
        "incident_id": "TypeError_pipeline_schema.log::0",
        "root_cause": (
            "모바일 앱이 timestamp를 ISO 문자열로 전송하는데 "
            "transform 코드가 datetime 객체로 오인하고 산술 연산 시도."
        ),
        "fix": (
            "map_event_fields 진입 시 모든 타임스탬프 필드를 datetime으로 parse. "
            "cast_timestamp_field에서 isinstance(raw_ts, str) 확인 후 fromisoformat() 적용."
        ),
    },
    {
        "incident_id": "TypeError_pipeline_aggregation.log::0",
        "root_cause": (
            "거래 데이터에 'N/A' 문자열이 섞여 있어 sum 연산 중 int + str TypeError 발생. "
            "데이터 정제 단계가 없었음."
        ),
        "fix": (
            "aggregate_transactions 진입 전 값 정제 단계 추가: "
            "숫자로 변환 불가한 값은 0으로 대체하고 정제 건수를 메트릭으로 기록."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def _reset_collections(incidents_col: str, postmortems_col: str) -> None:
    """Drop and recreate both Qdrant collections."""
    from qdrant_client import QdrantClient

    url = os.getenv("QDRANT_URL", "")
    api_key = os.getenv("QDRANT_API_KEY")

    if url:
        client = QdrantClient(url=url, api_key=api_key)
    else:
        print("  QDRANT_URL not set — cannot reset in-memory client. Skipping reset.")
        return

    for col in [incidents_col, postmortems_col]:
        try:
            client.delete_collection(col)
            print(f"  Dropped collection: {col}")
        except Exception:
            print(f"  Collection not found (skip): {col}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(reset: bool = False) -> None:
    from tracelog.rag.indexer import TraceLogIndexer
    from tracelog.rag.postmortem_indexer import PostmortemIndexer
    from tracelog.rag.retriever import TraceLogRetriever
    from tracelog.rag.stores.qdrant import QdrantStore

    incidents_col = os.environ.get("TRACELOG_INCIDENTS_COLLECTION", "tracelog_incidents")
    postmortems_col = os.environ.get("TRACELOG_POSTMORTEMS_COLLECTION", "tracelog_postmortems")

    if reset:
        _section("Reset — dropping collections")
        _reset_collections(incidents_col, postmortems_col)

    # ------------------------------------------------------------------
    # Step 1 — Index Incidents
    # ------------------------------------------------------------------
    _section("Step 1 — Indexing incidents")

    incident_store = QdrantStore(collection_name=incidents_col)
    indexer = TraceLogIndexer(store=incident_store)

    with tempfile.TemporaryDirectory() as tmpdir:
        dump_dir = Path(tmpdir)
        for filename, content in INCIDENT_DUMPS.items():
            (dump_dir / filename).write_text(content, encoding="utf-8")
        total_chunks = indexer.index_directory(dump_dir)

    print(f"\n  Indexed {total_chunks} chunks from {len(INCIDENT_DUMPS)} files")
    print(f"  Collection '{incidents_col}': {incident_store.count()} points total")

    # ------------------------------------------------------------------
    # Step 2 — Commit Postmortems
    # ------------------------------------------------------------------
    _section("Step 2 — Committing postmortems")

    postmortem_store = QdrantStore(collection_name=postmortems_col)
    pm_indexer = PostmortemIndexer(store=postmortem_store)
    retriever = TraceLogRetriever(store=incident_store, postmortem_store=postmortem_store)

    for pm in POSTMORTEMS:
        pm_indexer.commit(
            incident_id=pm["incident_id"],
            root_cause=pm["root_cause"],
            fix=pm["fix"],
        )
        pm_indexer.update_incident_status(incident_store, pm["incident_id"])
        print(f"  ✓ {pm['incident_id']}")

    print(f"\n  Collection '{postmortems_col}': {postmortem_store.count()} points total")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _section("Summary")

    resolved = incident_store.fetch_by_filter({"status": "resolved"})
    open_incidents = incident_store.fetch_by_filter({"status": "open"})

    print(f"\n  {'Collection':<40} {'Points':>8}  {'Resolved':>10}  {'Open':>6}")
    print(f"  {'─'*40}  {'─'*8}  {'─'*10}  {'─'*6}")
    print(
        f"  {incidents_col:<40} {incident_store.count():>8}  "
        f"{len(resolved):>10}  {len(open_incidents):>6}"
    )
    print(f"  {postmortems_col:<40} {postmortem_store.count():>8}")

    print("\n  Done. Run `python scripts/rag_repl.py` to start querying.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed TraceLog RAG demo data")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate both Qdrant collections before seeding",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    main(reset=args.reset)
