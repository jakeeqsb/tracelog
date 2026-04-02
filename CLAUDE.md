# TraceLog

An LLM-native logging SDK that captures Python application execution flow as a structured Trace-DSL, and connects error context dumps to RAG-based diagnosis.

## Architecture

1. **SDK** — `tracelog/` — captures execution flow inside the application
    - `TraceLogHandler` → `ChunkBuffer` → `TraceExporter`
    - `@trace` decorator automatically records function entry, exit, and exceptions

2. **Integration** — `tracelog/ingestion` — reassembles fragmented distributed dumps
    - `ContextAggregator` → `TraceTreeSplitter` → `RAGIndexer`

3. **Storage** — `tracelog/rag/store.py` — vector store
    - `INCIDENT` node + `POSTMORTEM` node, linked by `incident_id`

4. **Reasoning (The Analyst)** — `tracelog/rag/` — RAG-based diagnosis
    - `retriever.py` → `diagnoser.py`

→ Full architecture diagram: `docs/system_architecture.md`

## How I work with agents

- **Design-first workflow**: write the design in a docs markdown file → get user approval → update `roadmap.md` → then write code
- Before creating or modifying any code, all work must go through a docs design phase first. The current roadmap contains both in-progress design work and the next items to be developed. Always consult it before starting.
- If an implementation diverges from the design during development, update the relevant doc first before proceeding.

→ Full roadmap: `docs/roadmap.md`

## Do Not

- Do not add features that are not in the roadmap
- Do not create code files without a corresponding doc design

## Prompt Templates

All prompt templates are managed inside the package as `.yaml` files and loaded via `langchain.prompts.load_prompt()`.

- Never hardcode prompt strings in Python source files
- Never store prompt templates under `docs/`
- Path structure (e.g. `tracelog/prompts/` vs `tracelog/rag/prompts/`) is defined per-component by the AI Engineer in the relevant design doc

## Implementation Status

Check this table before writing or modifying any code. Do not write implementation code for items that are still in the design phase.

| Phase | Item | Status |
| --- | --- | --- |
| 1 — SDK | Core SDK (buffer, handler, exporter, @trace, ChunkBuffer) | ✅ Done |
| 2.0 | Span ID propagation (ContextVar-based) | ✅ Done |
| 2.1 | TraceTreeSplitter + embeddings | ✅ Done |
| 2.2 | Qdrant-based hybrid retriever + diagnoser | ✅ Done |
| 2.3 | VectorStore Protocol abstraction | ✅ Done |
| 2.4 | Incident/Postmortem ingestion pipeline, CLI, linked retrieval | 🔧 Designed / not yet implemented |
| 2.5 | Source code–trace alignment | ❌ Not started |
| 3.1 | Distributed Aggregator MVP | ✅ Done (complex race condition cases not yet covered) |
| 3.2–3.3 | Interactive Investigation API, Agent Benchmark | ✅ Benchmark done / API not started |
| 3.4 | benchmark_v2 LangChain migration | 🔧 Designed / not yet implemented |

## Running Tests

```bash
# Setup (first time only)
uv sync

# Run all tests
pytest tests/

# Run a specific file
pytest tests/test_buffer.py
```

- **Environment variables**: `OPENAI_API_KEY`, `QDRANT_URL`, and `QDRANT_API_KEY` are required in a `.env` file for RAG-related tests only
- RAG/vector tests automatically fall back to in-memory mode when Qdrant is not configured

## Key Docs Map

| Area | Docs to read |
| --- | --- |
| SDK overview | `docs/sdk/overview.md` |
| Buffer / memory | `docs/sdk/buffer.md` |
| Exporter / dump format | `docs/sdk/exporter.md` |
| Ingestion (distributed reassembly) | `docs/ingestion/aggregator.md`, `splitter.md` |
| RAG / vector store | `docs/rag/store.md`, `postmortem.md` |
| Evaluation / benchmarks | `docs/eval/benchmark_v2_langchain.md` |
| Agent Benchmark (v2) | `docs/eval/benchmark_v2/` |
| Full architecture | `docs/system_architecture.md` |
