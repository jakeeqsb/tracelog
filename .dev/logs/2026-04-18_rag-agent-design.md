# RAG Investigation Agent — Design

**Date**: 2026-04-18
**Branch**: rag-interactive-demo
**Agent**: AI Engineer

## Goal

Design a conversational RAG agent where a user can ask a natural-language question such as "What DB lock incidents happened last time?" and the agent searches the vector store and synthesizes a clear, natural-language answer.

---

## 1. Agent Layer

### 1.1 Overview

`TraceLogAgent` — a LangChain `create_agent`-based agent.
It receives the user's natural-language question, selects and composes the appropriate tools, and returns a structured final answer.

**File location**: `tracelog/rag/agent.py`

---

### 1.2 Agent Tool Signatures

```python
# Tool 1: Semantic incident search
@tool
def search_incidents(
    query: str,
    top_k: int = 5,
    error_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Search for incident chunks semantically similar to the natural-language query.
    Can be filtered by error_type and/or date range. Returns linked POSTMORTEM if available.

    Args:
        query: Natural-language search query (e.g. "DB connection timeout")
        top_k: Maximum number of results to return (default 5)
        error_type: Error type to filter by (e.g. "ConnectionError"). None searches all.
        date_from: Start of date range in ISO-8601 format (e.g. "2026-04-01"). None = no lower bound.
        date_to: End of date range in ISO-8601 format (e.g. "2026-04-18"). None = no upper bound.
                 The agent should resolve relative expressions ("last week", "yesterday") to
                 absolute ISO-8601 dates before calling this tool.

    Returns:
        list of dict with keys:
            incident_id, error_type, file_name, occurred_at, status,
            embed_text (v2 natural-language summary),
            chunk_text (original Trace-DSL),
            root_cause (if POSTMORTEM linked), fix (if POSTMORTEM linked),
            score
    """

# Tool 2: Postmortem fix search
@tool
def search_fixes(query: str, top_k: int = 5) -> list[dict]:
    """
    Search past fixes (postmortems) directly using a natural-language query.
    Searches the root_cause + fix vector space directly, bypassing incident search.

    Args:
        query: Natural-language query about a fix (e.g. "card number validation failure fix")
        top_k: Maximum number of results to return (default 5)

    Returns:
        list of dict with keys:
            incident_id, root_cause, fix, resolved_at, score
    """

# Tool 3: Incident detail fetch
@tool
def fetch_incident(incident_id: str) -> dict:
    """
    Fetch the full data for a specific incident by incident_id.
    Combines all chunks sharing the same file_name (chunk_index 0, 1, 2...) to return
    the complete execution context. Also returns the linked POSTMORTEM if available.

    Args:
        incident_id: Incident ID to fetch (e.g. "ConnectionError_warehouse.log::0")

    Returns:
        dict with keys:
            file_name, error_type, occurred_at, status,
            chunks (list — sorted by chunk_index),
            full_trace (str — concatenation of all chunk_text),
            postmortem (dict | None — root_cause, fix, resolved_at),
            span_id, parent_span_id, trace_id (if present)
    """
```

---

### 1.3 Response Schema (Pydantic structured output)

The agent uses `with_structured_output` to produce a final `AgentAnswer` Pydantic model.
The `create_agent` loop runs freely to call tools; structured output is applied only at the final synthesis step.

```python
from pydantic import BaseModel, Field

class IncidentSummary(BaseModel):
    incident_id: str
    error_type: str
    occurred_at: str
    status: str  # "open" | "resolved"
    summary: str  # 1–2 sentence core summary of the incident
    score: float  # vector similarity score (0.0–1.0), copied as-is from search result
    error_trace: str | None = None  # 3–5 key Trace-DSL lines centred on !! marker
    trace_id: str | None = None
    span_id: str | None = None
    root_cause: str | None = None
    fix: str | None = None

class AgentAnswer(BaseModel):
    answer: str = Field(
        description="Natural-language answer to the user's question"
    )
    incidents: list[IncidentSummary] = Field(
        default_factory=list,
        description="List of incidents referenced in the answer"
    )
    confidence: str = Field(
        description="Answer confidence: 'high' | 'medium' | 'low'"
    )
    sources_used: list[str] = Field(
        default_factory=list,
        description="Names of tools used during retrieval (e.g. ['search_incidents', 'fetch_incident'])"
    )
```

**Fields added post-design** (AI Engineer review after initial implementation):

- `score` — exposes the raw similarity score so callers can rank or threshold results without re-querying.
- `error_trace` — 3–5 key Trace-DSL lines centred on the `!!` marker (1–2 preceding `>>` call lines for context); populated from `chunk_text` by the LLM at synthesis time.
- `trace_id` / `span_id` — surfaced from the search result payload for distributed trace correlation.

---

### 1.4 Prompt File

**Location**: `tracelog/rag/prompts/agent_system.yaml`

Added to the existing `tracelog/rag/prompts/` directory (alongside `diagnostic_prompt.txt`).
Loaded via LangChain `load_prompt()`.

```yaml
description: "System prompt for TraceLog RAG Investigation Agent"
input_variables: []
template: |
  You are an incident investigation expert for the TraceLog RAG system.

  When the user asks a natural-language question about past incidents, errors, or fixes,
  use the appropriate tools to retrieve relevant information from the vector store
  and provide a clear, practical answer.

  ## Available Tools
  - search_incidents: Search for similar incidents using a natural-language query
  - search_fixes: Search past fixes (postmortems) directly using a natural-language query
  - fetch_incident: Fetch full details for a specific incident

  ## top_k Inference
  - All search tools accept a `top_k` parameter (default: 5).
  - If the user specifies a count in their question — e.g. "top 10", "top 3", "show me 3",
    "상위 10개", "3가지만" — extract that number and pass it as `top_k`.
  - If no count is specified, use the default of 5.

  ## Date Range Inference
  - search_incidents accepts `date_from` and `date_to` parameters (ISO-8601 strings).
  - If the user references a time window — e.g. "last week", "yesterday", "since April 1st",
    "이번 주", "어제" — resolve the expression to absolute ISO-8601 dates and pass them.
  - If no date range is mentioned, omit both parameters (None = no filter).

  ## Populating IncidentSummary fields
  - score: copy the numeric similarity score from the search result as-is.
  - error_trace: extract 3–5 key lines from chunk_text centred on the `!!` error marker
    (include 1–2 preceding `>>` call lines for context). Omit if chunk_text is unavailable.
  - trace_id / span_id: copy from the search result payload. Set to null if absent or empty.
  - root_cause / fix: include only for resolved incidents where postmortem data is present.

  ## Answer Principles
  - If no results are found, honestly reply "No matching incidents were found."
  - For resolved incidents (status=resolved), always include root_cause and fix.
  - When multiple incidents are returned, list them in descending order of similarity score.
  - Answer only based on retrieved results — no speculation.
  - Respond in the same language the user used (Korean question → Korean answer).

  ## Trace-DSL Notation
  - `>>` : function entry
  - `<<` : normal function return
  - `!!` : error / exception raised
  - `..` : informational log
```

---

### 1.5 Agent Construction

Follows `langchain-conventions.md` — uses `create_agent`.

```python
import os
from pathlib import Path
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.prompts import load_prompt

AGENT_MODEL = os.getenv("TRACELOG_AGENT_MODEL", "gpt-4o")

class TraceLogAgent:
    def __init__(self, retriever: TraceLogRetriever):
        self.llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
        self.tools = self._build_tools(retriever)
        system_prompt = load_prompt(
            Path(__file__).parent / "prompts" / "agent_system.yaml"
        )
        self.agent = create_agent(
            model=AGENT_MODEL,
            tools=self.tools,
            system_prompt=system_prompt.template,
        )

    def ask(self, question: str) -> AgentAnswer:
        result = self.agent.invoke({"messages": [{"role": "user", "content": question}]})
        # Structured output: applied only at the final synthesis step
        structured_llm = self.llm.with_structured_output(AgentAnswer)
        return structured_llm.invoke(
            f"Based on the following investigation result, respond using the AgentAnswer schema:\n\n"
            f"{result['messages'][-1].content}"
        )
```

**Design rationale**:
- The `create_agent` loop is kept free to call tools without restriction.
- Only the final synthesis step is forced through `with_structured_output` — eliminates the risk of JSON parsing failures inside the loop.
- Model name is injected exclusively via `os.getenv()` — no hardcoding.

---

## 2. Embedding Strategy v2

### 2.1 Current Problems

The current `indexer.py` embeds the full `chunk_text` (raw Trace-DSL).

| Problem | Cause | Impact |
|---|---|---|
| Signal dilution | 1 error line vs. 200-line Trace-DSL | "DB timeout" query returns unrelated chunks |
| Vector space mismatch | Trace-DSL symbols (`>>`, `!!`) vs. natural-language query | Lower cosine similarity |
| No `error_type` bridging | If query lacks "ConnectionError", filter is never applied | Cannot filter by type with natural-language query |

### 2.2 v2 Embedding Strategy: Natural-Language Summary Text

**Core decision**: Instead of the full `chunk_text`, embed a **natural-language summary of the error context**.
This summary is stored alongside the original `chunk_text` in the payload as an `embed_text` field.

**`embed_text` construction rules**:
1. Extract lines with a `!!` marker (error surface).
2. Extract 2–3 preceding `>>` function-entry lines (call chain).
3. Prepend the `error_type` expressed in natural language.
4. Compose everything into 1–3 natural-language sentences.

**`embed_text` construction example**:

Original `chunk_text` (Trace-DSL):
```
>> process_payment(user_id=101, amount="5000", currency="USD")
  >> validate_amount(amount="5000")
    >> parse_numeric(value="5000")
      !! ValueError: invalid literal for int() with base 10: '5000 KRW'
```

Generated `embed_text`:
```
ValueError raised — int conversion failed in parse_numeric.
Call path: process_payment > validate_amount > parse_numeric.
Error detail: invalid literal for int() with base 10: '5000 KRW'
```

**Another example** (ConnectionError):

Original `chunk_text`:
```
>> sync_inventory(service="warehouse-A", batch_size=200)
  >> fetch_db_records(table="stock", timeout=5)
    .. [INFO] Connecting to primary DB host: 10.0.1.42:5432
    !! ConnectionError: [Errno 110] Connection timed out after 5s
```

Generated `embed_text`:
```
ConnectionError raised — DB connection timeout in fetch_db_records.
Call path: sync_inventory > fetch_db_records.
Error detail: Connection timed out after 5s (host: 10.0.1.42:5432)
```

---

### 2.3 Dual Vector (Qdrant Named Vectors) Evaluation

| Option | Pros | Cons |
|---|---|---|
| **Single vector (embed_text only)** | Simple implementation, no VectorStore Protocol changes, aligned with natural-language query space | Cannot search by raw DSL structure |
| **Dual vector (Named Vectors)** | Can search both DSL-structure and natural-language spaces | Requires large-scale QdrantStore Protocol refactor, 2× indexing cost, needs vector-name selection logic at query time |

**Decision**: **Single vector (`embed_text` only)**.

Rationale:
- All current query patterns are natural language — the agent tool `search_incidents` also accepts natural-language queries.
- The original `chunk_text` is preserved in the payload so the agent can access full execution context.
- Qdrant Named Vectors would require a complete redesign of the `VectorStore` Protocol abstraction — unnecessary complexity at this stage.
- Migration to named vectors is possible later if DSL-structure-based search becomes a real requirement.

---

### 2.4 `error_type` Bridging Strategy

**Decision**: **Include `error_type` in natural language inside `embed_text`** (see examples above).

Options evaluated:
1. Prepend "ConnectionError raised —" style text inside `embed_text` ← **adopted**
2. Automatically apply `error_type` payload filter at query time (NER or rule-based)
3. Index `error_type` as a separate sparse vector with BM25

Why option 1:
- Option 2 is unreliable — NER false positives, query may not contain the type name.
- Option 3: BM25 index not yet implemented (backlog).
- Option 1: `error_type` is always known at index time — safe and simple.

---

### 2.5 `indexer.py` Payload Changes

Add `embed_text` to existing payload fields:

```python
# Before
payloads = [{
    "incident_id": ...,
    "error_type": ...,
    "file_name": ...,
    "chunk_index": ...,
    "chunk_text": chunk,      # ← used for embedding
    "has_error": ...,
    "occurred_at": ...,
    "status": "open",
}]

# After
payloads = [{
    "incident_id": ...,
    "error_type": ...,
    "file_name": ...,
    "chunk_index": ...,
    "chunk_text": chunk,      # ← preserved as-is (for agent detail fetch)
    "embed_text": embed_text, # ← NEW: natural-language summary (embedding target)
    "has_error": ...,
    "occurred_at": ...,
    "status": "open",
    # NEW (added in section 3):
    "trace_id": ...,
    "span_id": ...,
    "parent_span_id": ...,
}]

# Embedding target changed
vectors = self._embed([p["embed_text"] for p in payloads])  # chunk_text → embed_text
```

The `embed_text` generation logic is extracted into a private method `_build_embed_text(chunk: str, error_type: str) -> str`.

---

## 3. Context Connection

### 3.1 Current Problems

| Problem | Cause |
|---|---|
| `span_id`, `parent_span_id`, `trace_id` not stored | `indexer.py` ignores dump JSON metadata and reads only the `.log` file as plain text |
| Multi-chunk incident fragmentation | Each chunk has a separate `incident_id` (`file_name::chunk_index`) with no linking |
| Agent cannot reconstruct full execution flow | `fetch_incident` tool has no logic to combine multiple chunks from the same file |

### 3.2 Storing `span_id` / `trace_id` in Payload

**Change**: When `indexer.py` parses a `.log` dump file, it reads span fields from the JSON metadata and stores them in the payload.

Currently `indexer.py` reads files as plain text and passes them to `TraceTreeSplitter`.
Dump file format (from `exporter.py`):
```json
{"trace_id": "t1a2b3c4", "span_id": "s5d6e7f8", "parent_span_id": "p9a0b1c2",
 "timestamp": "2026-03-08T10:00:00Z", "dsl_lines": [">> func_a", "!! ValueError..."]}
```

**Updated `index_file` logic**:

```python
def index_file(self, file_path: Path) -> int:
    raw = file_path.read_text(encoding="utf-8")

    # Parse metadata if the dump file is in JSON Lines format
    trace_id = parent_span_id = span_id = None
    try:
        first_line = raw.splitlines()[0]
        meta = json.loads(first_line)
        trace_id = meta.get("trace_id")
        span_id = meta.get("span_id")
        parent_span_id = meta.get("parent_span_id")
        dsl_text = "\n".join(meta.get("dsl_lines", []))
    except (json.JSONDecodeError, IndexError):
        dsl_text = raw  # plain-text fallback

    chunks = self.splitter.split_text(dsl_text)
    ...

    payloads = [{
        ...,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
    } for idx, chunk in enumerate(chunks)]
```

**Payload index creation** (`tracelog_incidents`):
```python
for field in ("trace_id", "span_id", "parent_span_id"):
    self._client.create_payload_index(
        collection_name=self.collection_name,
        field_name=field,
        field_schema=PayloadSchemaType.KEYWORD,
    )
```

---

### 3.3 Multi-Chunk Incident Reconstruction Strategy

**Decision**: The `fetch_incident` tool fetches all chunks sharing the same `file_name` via a payload filter, sorts them by `chunk_index`, and concatenates them into `full_trace`.

```python
@tool
def fetch_incident(incident_id: str) -> dict:
    # 1. Extract file_name from incident_id (= "file_name::chunk_index")
    file_name = incident_id.rsplit("::", 1)[0]

    # 2. Fetch all chunks with the same file_name (payload filter)
    all_chunks = incident_store.fetch_by_filter({"file_name": file_name})
    all_chunks.sort(key=lambda c: c["chunk_index"])

    # 3. Concatenate full Trace-DSL
    full_trace = "\n".join(c["chunk_text"] for c in all_chunks)

    # 4. Fetch linked postmortem (keyed by the error chunk's incident_id)
    error_chunk = next((c for c in all_chunks if c.get("has_error")), all_chunks[0])
    postmortem = postmortem_store.fetch_by_filter(
        {"incident_id": error_chunk["incident_id"]}
    )

    return {
        "file_name": file_name,
        "error_type": error_chunk.get("error_type"),
        "occurred_at": error_chunk.get("occurred_at"),
        "status": error_chunk.get("status"),
        "chunks": all_chunks,
        "full_trace": full_trace,
        "postmortem": postmortem[0] if postmortem else None,
        "span_id": error_chunk.get("span_id"),
        "parent_span_id": error_chunk.get("parent_span_id"),
        "trace_id": error_chunk.get("trace_id"),
    }
```

**Alternative evaluation**:

| Option | Pros | Cons |
|---|---|---|
| Filter by `file_name` to combine chunks ← **adopted** | No changes to existing `incident_id` scheme; reuses `fetch_by_filter` | Risk of collision if different incidents share the same file name (file name acts as unique ID) |
| Filter by `trace_id` to combine chunks | Enables distributed trace reconstruction | Incompatible with legacy dumps where `trace_id` is null |
| Unify `incident_id` to file-level (`file_name` itself) | No per-chunk ID confusion | Large schema change; breaks backward compatibility |

**Collision prevention**: `file_name` includes a timestamp (e.g. `ValueError_payment_api_20260318T143200.log`), so real collisions are unlikely.

---

### 3.4 Representing the Incident → Postmortem Link in Agent Answers

The agent expresses the link to the user in natural language via `IncidentSummary.root_cause` and `IncidentSummary.fix`.

**Answer example** (user question: "What DB lock incidents were there?"):

```
3 DB-related incidents were found.

1. [Resolved] warehouse-sync service — 2026-03-10
   Error: ConnectionError (DB connection timeout after 5s)
   Root cause: Connection pool exhausted on primary DB due to excessive concurrent requests
   Fix: Expanded connection pool from 20 to 50; reset request queue timeout

2. [Open] inventory-service — 2026-03-15
   Error: ConnectionError (connection refused to host 10.0.1.43)
   Similar past fix: Possible missing secondary failover config on host failure

3. [Resolved] order-service — 2026-03-08
   Error: TimeoutError (downstream DB query exceeded 30s)
   Root cause: Full table scan on unindexed column
   Fix: Added index on stock_level column
```

This answer format is specified in the agent prompt (`agent_system.yaml`).

---

## Open Questions

1. **`embed_text` quality validation**: The `_build_embed_text()` logic needs empirical evaluation to confirm it actually improves retrieval accuracy. Proposed metric: Recall@5 comparison on the same query set (v1 vs v2). Evaluation to be designed as a separate benchmark after Phase 2.5.

2. **`embed_text` generation fallback**: For chunks with no `!!` marker (`has_error=False`), the natural-language summary is ambiguous. Decision needed: use raw `chunk_text` as-is, or substitute a function entry/return summary.

3. **JSON Lines vs. plain-text dump**: The current `FileExporter` outputs JSON Lines, but `indexer.py` reads plain text. The JSON-parse-with-fallback pattern in `index_file` must cover both formats; robustness of this parsing logic should be validated with tests during implementation.

4. ~~**Agent language handling**~~: **Resolved during implementation.** Added "Respond in the same language the user used (Korean question → Korean answer)" to the `agent_system.yaml` Answer Principles section. No language detection logic needed — the LLM mirrors the user's language natively.
