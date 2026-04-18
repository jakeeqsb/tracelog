"""Quick live test for TraceLogAgent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from tracelog.rag.stores.qdrant import QdrantStore
from tracelog.rag.retriever import TraceLogRetriever
from tracelog.rag.agent import TraceLogAgent

incident_store   = QdrantStore(collection_name="tracelog_incidents")
postmortem_store = QdrantStore(collection_name="tracelog_postmortems")
retriever = TraceLogRetriever(store=incident_store, postmortem_store=postmortem_store)
agent = TraceLogAgent(retriever=retriever)

print(f"incidents: {incident_store.count()}  postmortems: {postmortem_store.count()}")

q = "DB 연결 관련 이슈들 뭐가 있었어? resolved된 것들은 어떻게 해결됐는지도 알려줘"

print(f"\n{'═'*64}")
print(f"  Q: {q}")
print('═'*64)

ans = agent.ask(q)

print(f"\n  [{ans.confidence} confidence]\n")
for line in ans.answer.splitlines():
    print(f"  {line}")

if ans.incidents:
    print(f"\n  INCIDENTS ({len(ans.incidents)}):")
    for inc in ans.incidents:
        print(f"\n  {'─'*60}")
        print(f"  [{inc.status:<10}] {inc.incident_id}")
        print(f"  error_type  : {inc.error_type}")
        print(f"  occurred_at : {inc.occurred_at}")
        print(f"  score       : {inc.score:.4f}")
        print(f"  summary     : {inc.summary}")
        if inc.error_trace:
            print(f"  error_trace :")
            for line in inc.error_trace.splitlines():
                print(f"    {line}")
        if inc.trace_id:
            print(f"  trace_id    : {inc.trace_id}")
        if inc.span_id:
            print(f"  span_id     : {inc.span_id}")
        if inc.root_cause:
            print(f"  root_cause  : {inc.root_cause}")
        if inc.fix:
            print(f"  fix         : {inc.fix}")

print(f"\n  sources: {ans.sources_used}")
print(f"{'═'*64}")
