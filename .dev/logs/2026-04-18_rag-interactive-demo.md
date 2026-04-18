# RAG Interactive Demo — Seed + REPL

**Date**: 2026-04-18
**Branch**: rag-interactive-demo
**Agent**: Software Engineer

## Goal

Local dev playground for exploring the TraceLog RAG pipeline hands-on:
seed the Qdrant vector store with rich, diverse incidents/postmortems, then
query them interactively from a REPL without writing code.

## Steps

1. Create `scripts/seed_rag_demo.py` — 7 services × 2–3 incident variants (~18 incidents),
   postmortems for resolved ones, idempotent upsert, `--reset` flag
2. Create `scripts/rag_repl.py` — readline REPL with `search`, `fixes`, `diagnose`,
   `list`, `show`, `count`, `help`, `quit` commands

## Design docs referenced

- `docs/rag/interactive_demo.md`

## Notes

- No changes to `tracelog/` package code — standalone dev scripts only
- Both scripts use existing `TraceLogIndexer`, `PostmortemIndexer`, `TraceLogRetriever`,
  `TraceLogDiagnoser` from the package
- Qdrant running locally at localhost:6333 per .env
