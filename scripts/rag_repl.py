"""scripts/rag_repl.py — TraceLog RAG 인터랙티브 REPL.

시딩된 벡터 DB에 직접 쿼리를 던져볼 수 있는 readline 기반 REPL입니다.

Usage:
    python scripts/rag_repl.py

Commands:
    agent <question>           자연어 질문 → TraceLogAgent (추천)
    search <text>              incident 벡터 서치 (top-5, Trace-DSL 유사도)
    ask <question>             자연어 질문 → LLM이 기술 쿼리로 변환 후 서치
    fixes <text>               postmortem 직접 벡터 서치
    diagnose <text>            search + LLM 단발 진단
    list [open|resolved]       전체 incident 목록
    show <incident_id>         단건 상세 + 연결된 postmortem
    count                      두 컬렉션 포인트 수
    help                       명령 목록
    quit / exit / Ctrl-D       종료
"""

import os
import sys
import readline  # noqa: F401 — enables arrow-key history in input()
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

BANNER = """\
╔══════════════════════════════════════════════════════════════╗
║          TraceLog RAG — Interactive Query REPL               ║
║  Type  help  to see available commands.                      ║
╚══════════════════════════════════════════════════════════════╝"""

HELP_TEXT = """\
Commands:
  agent <question>           자연어 질문 → TraceLogAgent (추천 ★)
  search <text>              incident 벡터 서치 (Trace-DSL 유사도, LLM 없음)
  ask <question>             자연어 질문 → LLM 쿼리 변환 후 서치 (자연어 OK)
  fixes <text>               postmortem 벡터 서치 (fix 유사도)
  diagnose <text>            search + LLM 진단 (토큰 소모 / API key 필요)
  list [open|resolved]       전체 incident 목록 (status 필터 선택)
  show <incident_id>         incident 단건 + linked postmortem 출력
  count                      두 컬렉션 현재 포인트 수
  help                       이 도움말 출력
  quit / exit / Ctrl-D       REPL 종료

Tips:
  - agent   : 가장 강력. 툴을 조합해 맥락 파악 후 자연어로 답변 (한국어 OK)
  - search  : 새 에러 트레이스로 유사 과거 incident 찾기 (Trace-DSL 형식 권장)
  - ask     : "DB 연결 이슈 뭐 있어?", "타임아웃 원인은?" 같은 자연어 질문
  - fixes   : LLM 호출 없음, 즉시 응답
  - diagnose: 실제 OpenAI API 호출 (gpt-4o-mini)
  - incident_id 형식 예: ValueError_payment_api.log::0
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 64) -> str:
    return char * width


def _print_chunk(chunk, idx: int) -> None:
    status_tag = f"  status={getattr(chunk, 'status', '?')}" if hasattr(chunk, "status") else ""
    print(f"\n  [{idx}] score={chunk.score:.4f}  {chunk.incident_id}{status_tag}")
    print(f"       error_type={chunk.error_type}  has_error={chunk.has_error}")
    preview = chunk.chunk_text[:160].replace("\n", " ↵ ")
    print(f"       chunk : {preview}...")
    if chunk.root_cause:
        print(f"       root_cause : {chunk.root_cause}")
    if chunk.fix:
        print(f"       fix        : {chunk.fix}")


def _print_fix(fix, idx: int) -> None:
    print(f"\n  [{idx}] score={fix.score:.4f}  incident_id={fix.incident_id}")
    print(f"       root_cause : {fix.root_cause}")
    print(f"       fix        : {fix.fix}")
    if fix.resolved_at:
        print(f"       resolved_at: {fix.resolved_at}")


def _print_incident_detail(payload: dict) -> None:
    print(f"\n  incident_id : {payload.get('incident_id')}")
    print(f"  error_type  : {payload.get('error_type')}")
    print(f"  status      : {payload.get('status')}")
    print(f"  occurred_at : {payload.get('occurred_at')}")
    print(f"\n  --- Trace-DSL chunk ---")
    for line in payload.get("chunk_text", "").splitlines():
        print(f"  {line}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_agent(args: str, agent) -> None:
    if not args.strip():
        print("  Usage: agent <natural language question>")
        return
    print(f"\n  Thinking...\n")
    ans = agent.ask(args)
    print(f"  {_hr('═')}")
    print(f"  TraceLogAgent  [{ans.confidence} confidence]")
    print(_hr("═"))
    print()
    for line in ans.answer.splitlines():
        print(f"  {line}")
    if ans.incidents:
        print(f"\n  Referenced incidents ({len(ans.incidents)}):")
        print(_hr())
        for inc in ans.incidents:
            status_tag = f"[{inc.status}]"
            print(f"  {status_tag:<12} {inc.incident_id}  ({inc.error_type})")
            print(f"               {inc.summary}")
            if inc.root_cause:
                print(f"               root_cause : {inc.root_cause}")
            if inc.fix:
                print(f"               fix        : {inc.fix}")
    print(f"\n  sources: {', '.join(ans.sources_used)}")
    print(_hr("═"))


def cmd_search(args: str, retriever) -> None:
    if not args.strip():
        print("  Usage: search <query text>")
        return
    print(f"\n  Searching incidents for: \"{args[:80]}\"")
    results = retriever.search(args, top_k=5)
    if not results:
        print("  No results.")
        return
    print(f"\n  {len(results)} result(s):")
    print(_hr())
    for i, chunk in enumerate(results, 1):
        _print_chunk(chunk, i)
    print(_hr())


def cmd_fixes(args: str, retriever) -> None:
    if not args.strip():
        print("  Usage: fixes <query text>")
        return
    print(f"\n  Searching postmortems for: \"{args[:80]}\"")
    results = retriever.search_fixes(args, top_k=5)
    if not results:
        print("  No results.")
        return
    print(f"\n  {len(results)} result(s):")
    print(_hr())
    for i, fix in enumerate(results, 1):
        _print_fix(fix, i)
    print(_hr())


def cmd_ask(args: str, retriever, llm) -> None:
    """Natural language question → LLM rewrites to technical query → vector search."""
    if not args.strip():
        print("  Usage: ask <natural language question>")
        return

    from langchain_core.messages import HumanMessage

    rewrite_prompt = (
        "You are a search query rewriter for a software incident database.\n"
        "The database stores Python error traces in Trace-DSL format (e.g., "
        "'>> function_name !! ErrorType: message').\n"
        "Convert the user's natural language question into a short, precise English "
        "technical search query (max 15 words). Output ONLY the query — no explanation.\n\n"
        f"Question: {args}"
    )

    print(f"\n  Rewriting query...")
    response = llm.invoke([HumanMessage(content=rewrite_prompt)])
    rewritten = response.content.strip().strip('"').strip("'")
    print(f"  Rewritten: \"{rewritten}\"")

    results = retriever.search(rewritten, top_k=5)
    if not results:
        print("  No results.")
        return
    print(f"\n  {len(results)} result(s):")
    print(_hr())
    for i, chunk in enumerate(results, 1):
        _print_chunk(chunk, i)
    print(_hr())


def cmd_diagnose(args: str, retriever, diagnoser) -> None:
    if not args.strip():
        print("  Usage: diagnose <query text>")
        return
    print(f"\n  [1/2] Retrieving similar incidents...")
    similar = retriever.search(args, top_k=3)
    if not similar:
        print("  No similar incidents found — running diagnosis without RAG context.")

    print(f"  [2/2] Running LLM diagnosis (gpt-4o-mini)...")
    result = diagnoser.diagnose(current_chunk=args, similar_chunks=similar)
    meta = result.pop("_meta", {})

    print(f"\n  {_hr('═')}")
    print("  LLM Diagnosis")
    print(_hr("═"))
    if result.get("parse_error"):
        print(f"\n  (raw response)\n  {result.get('raw_response', '')}")
    else:
        for key in ["root_cause_function", "root_cause_type", "error_surface", "fix_hint", "confidence", "actionable"]:
            val = result.get(key, "—")
            print(f"  {key:<24}: {val}")
    print(
        f"\n  model={meta.get('model')}  "
        f"input_tokens={meta.get('input_tokens')}  "
        f"output_tokens={meta.get('output_tokens')}  "
        f"chunks_used={meta.get('similar_chunks_used')}"
    )
    print(_hr("═"))


def cmd_list(args: str, incident_store) -> None:
    status_filter = args.strip().lower() or None
    if status_filter and status_filter not in ("open", "resolved"):
        print("  Usage: list [open|resolved]")
        return

    filt = {"status": status_filter} if status_filter else {}
    results = incident_store.fetch_by_filter(filt) if filt else _fetch_all(incident_store)

    if not results:
        print("  No incidents found.")
        return

    label = f"({status_filter})" if status_filter else "(all)"
    print(f"\n  Incidents {label}: {len(results)}")
    print(_hr())
    print(f"  {'incident_id':<45} {'error_type':<20} {'status'}")
    print(f"  {'─'*45} {'─'*20} {'─'*10}")
    for r in sorted(results, key=lambda x: x.get("incident_id", "")):
        print(
            f"  {r.get('incident_id', '?'):<45} "
            f"{r.get('error_type', '?'):<20} "
            f"{r.get('status', '?')}"
        )
    print(_hr())


def cmd_show(args: str, incident_store, postmortem_store) -> None:
    incident_id = args.strip()
    if not incident_id:
        print("  Usage: show <incident_id>")
        return

    matches = incident_store.fetch_by_filter({"incident_id": incident_id})
    if not matches:
        print(f"  Incident not found: {incident_id}")
        return

    print(f"\n  {_hr('═')}")
    print("  INCIDENT")
    print(_hr("═"))
    _print_incident_detail(matches[0])

    pm_matches = postmortem_store.fetch_by_filter({"incident_id": incident_id})
    if pm_matches:
        pm = pm_matches[0]
        print(f"\n  {_hr('─')}")
        print("  POSTMORTEM (resolved)")
        print(_hr("─"))
        print(f"  root_cause  : {pm.get('root_cause')}")
        print(f"  fix         : {pm.get('fix')}")
        print(f"  resolved_at : {pm.get('resolved_at')}")
    else:
        print(f"\n  (no postmortem — status: {matches[0].get('status', '?')})")
    print(_hr("═"))


def cmd_count(incident_store, postmortem_store) -> None:
    print(f"\n  tracelog_incidents   : {incident_store.count()} points")
    print(f"  tracelog_postmortems : {postmortem_store.count()} points")


def _fetch_all(store) -> list[dict]:
    """Fetch all points via scroll (no filter)."""
    try:
        return store.fetch_by_filter({})
    except Exception:
        return []


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------

def run_repl() -> None:
    from langchain_openai import ChatOpenAI
    from tracelog.rag.agent import TraceLogAgent
    from tracelog.rag.diagnoser import TraceLogDiagnoser
    from tracelog.rag.retriever import TraceLogRetriever
    from tracelog.rag.stores.qdrant import QdrantStore

    incidents_col = os.environ.get("TRACELOG_INCIDENTS_COLLECTION", "tracelog_incidents")
    postmortems_col = os.environ.get("TRACELOG_POSTMORTEMS_COLLECTION", "tracelog_postmortems")

    incident_store = QdrantStore(collection_name=incidents_col)
    postmortem_store = QdrantStore(collection_name=postmortems_col)
    retriever = TraceLogRetriever(store=incident_store, postmortem_store=postmortem_store)
    diagnoser = TraceLogDiagnoser()
    llm = ChatOpenAI(model=os.getenv("TRACELOG_DIAGNOSER_MODEL", "gpt-4o-mini"), temperature=0)
    agent = TraceLogAgent(retriever=retriever)

    print(BANNER)
    print(f"\n  incidents   : {incident_store.count()} points  ({incidents_col})")
    print(f"  postmortems : {postmortem_store.count()} points  ({postmortems_col})")
    print()

    while True:
        try:
            raw = input("tracelog> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye.")
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            print("  Bye.")
            break
        elif cmd == "help":
            print(HELP_TEXT)
        elif cmd == "agent":
            cmd_agent(args, agent)
        elif cmd == "search":
            cmd_search(args, retriever)
        elif cmd == "ask":
            cmd_ask(args, retriever, llm)
        elif cmd == "fixes":
            cmd_fixes(args, retriever)
        elif cmd == "diagnose":
            cmd_diagnose(args, retriever, diagnoser)
        elif cmd == "list":
            cmd_list(args, incident_store)
        elif cmd == "show":
            cmd_show(args, incident_store, postmortem_store)
        elif cmd == "count":
            cmd_count(incident_store, postmortem_store)
        else:
            print(f"  Unknown command: '{cmd}'. Type help for usage.")


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    run_repl()
