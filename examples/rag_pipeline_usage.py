"""examples/rag_pipeline_usage.py — End-to-end RAG pipeline demo.

Demonstrates the full incident → postmortem → retrieval cycle:

    Step 1  Index Incidents    — ingest Trace-DSL dumps into tracelog_incidents
    Step 2  Commit Postmortems — record resolved incidents in tracelog_postmortems
    Step 3  Retrieve           — search for similar past incidents (with enrichment)
    Step 4  Diagnose (opt.)    — LLM root cause analysis using RAG context

Run:
    # Basic (no LLM call)
    python examples/rag_pipeline_usage.py

    # With LLM diagnosis (requires OPENAI_API_KEY in .env)
    python examples/rag_pipeline_usage.py --diagnose

Notes:
    - Uses in-memory Qdrant by default (no server required).
      Set QDRANT_URL in .env to point at a real server instead.
    - Embeddings require OPENAI_API_KEY in .env.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# Allow running directly from the examples/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Sample Trace-DSL dumps
# Each string represents one incident dump file.
# ---------------------------------------------------------------------------

INCIDENT_DUMPS = {
    "ValueError_payment.log": """\
>> process_payment
  user_id: 101
  amount: "5000"
  >> validate_amount
    >> parse_amount
      raw_input: "5000"
      !! ValueError: invalid literal for int() with base 10: '5000'
    << parse_amount
  << validate_amount
!! ValueError: invalid literal for int() with base 10: '5000'
<< process_payment
""",
    "ValueError_checkout.log": """\
>> checkout_flow
  cart_id: 42
  >> apply_discount
    discount_code: "SAVE10"
    >> parse_discount_value
      raw_value: "10%"
      !! ValueError: could not convert string to float: '10%'
    << parse_discount_value
  << apply_discount
!! ValueError: could not convert string to float: '10%'
<< checkout_flow
""",
    "KeyError_session.log": """\
>> authenticate_request
  request_id: "req-9f3a"
  >> load_session
    session_store: redis
    >> fetch_session_data
      key: "session:expired-token"
      result: {}
      !! KeyError: 'user_id'
    << fetch_session_data
  << load_session
!! KeyError: 'user_id'
<< authenticate_request
""",
    "KeyError_config.log": """\
>> initialize_worker
  worker_id: 7
  >> load_config
    config_file: "worker.yaml"
    >> get_required_key
      key: "db_host"
      !! KeyError: 'db_host'
    << get_required_key
  << load_config
!! KeyError: 'db_host'
<< initialize_worker
""",
}

# Postmortems for resolved incidents (incident_id = "{file_name}::0")
POSTMORTEMS = [
    {
        "incident_id": "ValueError_payment.log::0",
        "root_cause": "Payment amount arrived as a string with no pre-processing. "
                      "The validate_amount function passed the raw form value directly "
                      "to int() without stripping non-numeric characters first.",
        "fix": "Added explicit int(str(amount).strip()) cast at the API boundary "
               "in validate_amount before passing to downstream processing.",
    },
    {
        "incident_id": "KeyError_session.log::0",
        "root_cause": "Expired sessions were being fetched from Redis but returned "
                      "as empty dicts {}. The load_session function assumed 'user_id' "
                      "always exists without checking for expiry or empty payload.",
        "fix": "Added session existence check after fetch_session_data. "
               "If the dict is empty or missing 'user_id', raise AuthExpiredError "
               "instead of propagating KeyError.",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def _print_chunk(chunk, idx: int) -> None:
    print(f"\n  [{idx}] score={chunk.score:.4f}  incident_id={chunk.incident_id}")
    print(f"      error_type={chunk.error_type}  has_error={chunk.has_error}")
    # Trim long chunk_text for readability
    preview = chunk.chunk_text[:120].replace("\n", " ↵ ")
    print(f"      chunk: {preview}...")
    if chunk.root_cause:
        print(f"      root_cause : {chunk.root_cause}")
    if chunk.fix:
        print(f"      fix        : {chunk.fix}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(run_diagnose: bool = False) -> None:
    from tracelog.rag.indexer import TraceLogIndexer
    from tracelog.rag.postmortem_indexer import PostmortemIndexer
    from tracelog.rag.retriever import TraceLogRetriever
    from tracelog.rag.stores.qdrant import QdrantStore

    incidents_col = os.environ["TRACELOG_INCIDENTS_COLLECTION"]
    postmortems_col = os.environ["TRACELOG_POSTMORTEMS_COLLECTION"]

    # ------------------------------------------------------------------
    # Step 1 — Index Incidents
    # ------------------------------------------------------------------
    _print_section("Step 1 — Index Incidents")

    incident_store = QdrantStore(collection_name=incidents_col)
    indexer = TraceLogIndexer(store=incident_store)

    with tempfile.TemporaryDirectory() as tmpdir:
        dump_dir = Path(tmpdir)
        for filename, content in INCIDENT_DUMPS.items():
            (dump_dir / filename).write_text(content, encoding="utf-8")

        total = indexer.index_directory(dump_dir)

    print(f"  Indexed {total} chunks from {len(INCIDENT_DUMPS)} dump files")
    print(f"  Collection '{incidents_col}' now holds {incident_store.count()} points")

    # ------------------------------------------------------------------
    # Step 2 — Commit Postmortems
    # ------------------------------------------------------------------
    _print_section("Step 2 — Commit Postmortems")

    postmortem_store = QdrantStore(collection_name=postmortems_col)
    pm_indexer = PostmortemIndexer(store=postmortem_store)

    for pm in POSTMORTEMS:
        pm_indexer.commit(
            incident_id=pm["incident_id"],
            root_cause=pm["root_cause"],
            fix=pm["fix"],
        )
        pm_indexer.update_incident_status(incident_store, pm["incident_id"])
        print(f"  Committed postmortem: {pm['incident_id']}")

    print(f"  Collection '{postmortems_col}' now holds {postmortem_store.count()} points")

    # Verify status update
    resolved = incident_store.fetch_by_filter({"status": "resolved"})
    open_incidents = incident_store.fetch_by_filter({"status": "open"})
    print(f"  Incidents — resolved: {len(resolved)}, open: {len(open_incidents)}")

    # ------------------------------------------------------------------
    # Step 3 — Retrieve with postmortem enrichment
    # ------------------------------------------------------------------
    _print_section("Step 3 — Retrieve Similar Incidents")

    retriever = TraceLogRetriever(
        store=incident_store,
        postmortem_store=postmortem_store,
    )

    query = """\
>> process_order
  order_id: 88
  >> parse_unit_price
    raw_price: "29.99 USD"
    !! ValueError: could not convert string to float: '29.99 USD'
  << parse_unit_price
!! ValueError: could not convert string to float: '29.99 USD'
<< process_order
"""
    print(f"\n  Query (new incident):\n  {query[:100].replace(chr(10), ' ↵ ')}...")
    results = retriever.search(query, top_k=3)

    print(f"\n  Retrieved {len(results)} chunks:")
    for i, chunk in enumerate(results, 1):
        _print_chunk(chunk, i)

    enriched = [c for c in results if c.root_cause or c.fix]
    print(f"\n  Enriched with postmortem: {len(enriched)}/{len(results)} chunks")

    # ------------------------------------------------------------------
    # Step 4 — Search past fixes by similarity (independent postmortem search)
    # ------------------------------------------------------------------
    _print_section("Step 4 — Search Past Fixes by Similarity")

    fix_query = "string could not be converted to numeric type"
    print(f"\n  Query: \"{fix_query}\"\n")

    fix_results = retriever.search_fixes(fix_query, top_k=3)
    for i, fix in enumerate(fix_results, 1):
        print(f"  [{i}] score={fix.score:.4f}  incident_id={fix.incident_id}")
        print(f"      root_cause : {fix.root_cause}")
        print(f"      fix        : {fix.fix}")

    # ------------------------------------------------------------------
    # Step 5 — Diagnose (optional, requires OPENAI_API_KEY + LLM call)
    # ------------------------------------------------------------------
    if run_diagnose:
        _print_section("Step 5 — LLM Diagnosis")
        from tracelog.rag.diagnoser import TraceLogDiagnoser

        diagnoser = TraceLogDiagnoser()
        result = diagnoser.diagnose(current_chunk=query, similar_chunks=results)
        meta = result.pop("_meta", {})
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n  model={meta.get('model')}  "
              f"input_tokens={meta.get('input_tokens')}  "
              f"output_tokens={meta.get('output_tokens')}  "
              f"chunks_used={meta.get('similar_chunks_used')}")
    else:
        print("\n  (Skipping LLM diagnosis — run with --diagnose to enable)")

    _print_section("Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TraceLog RAG pipeline demo")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run Step 4: LLM diagnosis (requires OPENAI_API_KEY)",
    )
    args = parser.parse_args()

    if args.diagnose and not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set in environment / .env", file=sys.stderr)
        sys.exit(1)

    main(run_diagnose=args.diagnose)
