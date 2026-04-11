# README.md Comprehensive Rewrite

**Date**: 2026-04-11
**Branch**: collection-design
**Agent**: Software Engineer

## Goal

Rewrite README.md with architecture diagrams (Mermaid), chunking strategy visuals, benchmark results, Incident/Postmortem data model, Jira differentiation, and Quick Start — transforming it from a minimal stub into a comprehensive project overview.

## Steps

1. Hero block with tagline and 3-sentence summary
2. Trace-DSL format example with symbol legend table
3. Project Status section with MVP scope (WARNING admonition)
4. Quick Start: SDK integration (handler + @trace) and CLI commands
5. Architecture section with Mermaid `graph LR` pipeline diagram + component-to-file table
6. Chunking strategy: tiered threshold table, two-pass explanation, Mermaid `graph TD` context injection diagram, Silhouette Score comparison
7. Incident & Postmortem data model: Mermaid `erDiagram`, lifecycle list
8. Jira comparison table (5 dimensions)
9. Benchmark results: main runs table + extended scenarios (maze, dynamic pricing)
10. Development section (prerequisites, test command, env vars)
11. Documentation links

## Design docs referenced

- `docs/system_architecture.md`
- `docs/sdk/overview.md`
- `docs/rag/postmortem.md`
- `docs/eval/benchmark_v2_langchain.md`

## Notes

- All benchmark numbers sourced directly from JSON result files
- Silhouette Score: Recursive 0.39 → TraceTree 0.66 (from system_architecture.md)
- 3 Mermaid diagrams total: architecture pipeline, chunking context injection, ER data model
