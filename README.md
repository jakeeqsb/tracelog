# TraceLog

> **AI-Native Context Logging for Python**  
> "An experimental approach to structurally logging execution context."

## Introduction

Traditional log formats were designed primarily for human readability and regular expression parsing. As we explore using LLMs for debugging support, standard logging can become difficult to reason over, especially in asynchronous and multi-threaded environments where lines from different flows interleave.

TraceLog is a Python logging SDK and evaluation sandbox for studying LLM-assisted debugging workflows. It integrates with the standard `logging` module, captures structured execution context as Trace-DSL, and includes ingestion and benchmark assets for retrieval-augmented diagnosis experiments.

## Problem Space

The project is organized around three recurring issues observed in LLM-based debugging workflows:

1. **Context fragmentation**: concurrent flows interleave in standard logs and can blur causal chains.
2. **Missing state**: root-cause-relevant values are often not logged at the point where they are created.
3. **Lexical ambiguity**: similar error words can retrieve unrelated incidents in RAG systems.

## Architecture

TraceLog addresses those issues with a structured execution representation called **Trace-DSL**.

1. **TraceLog SDK (`TraceLogHandler`, `@trace`)**: captures execution context and emits dumps on failure.
2. **Aggregation and chunking**: reconstructs fragmented spans and splits traces with call-tree-aware chunking.
3. **RAG pipeline**: indexes historical incidents and retrieves similar cases for diagnosis.

The overall system design is documented in [docs/system_architecture.md](docs/system_architecture.md).

## Repository Status

The repository currently contains four main areas:

- **SDK**: context tracking, buffering, handler/exporter integration, and optional `@trace` instrumentation in [`tracelog/`](tracelog).
- **Ingestion**: dump aggregation and TraceTree chunking for downstream retrieval.
- **RAG components**: retriever and diagnoser prototypes under [`tracelog/rag/`](tracelog/rag).
- **Evaluation assets**: scenario generation, sealed truth artifacts, notebook orchestration, and benchmark reports under [`docs/eval/benchmark/`](docs/eval/benchmark) and [`tracelog/eval/`](tracelog/eval).

## Evaluation Workflow

Dataset generation and evaluation are organized as follows:

1. Generate operational-style incidents from shared scenario code.
2. Emit both standard logs and TraceLog dumps from the same codebase.
3. Aggregate TraceLog dumps into unified traces.
4. Split incidents into `historical` and `query`.
5. Run retrieval and diagnosis over both baseline and TraceLog conditions.
6. Compare analyst outputs against sealed truth with a judge step.

The notebook entry point is [`docs/eval/benchmark/notebooks/real_rag_benchmark.ipynb`](docs/eval/benchmark/notebooks/real_rag_benchmark.ipynb). The notebook supports:

- `analysis` mode: read existing benchmark artifacts
- `run` mode: regenerate the dataset and rerun the benchmark

## Current Benchmark Snapshot

The benchmark currently distinguishes between:

- **Primary benchmark**: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`
- **Ablation benchmark**: `Standard Log + RAG` vs `TraceLog + RAG`

In the latest stored report at [`docs/eval/benchmark/results/benchmark_report.md`](docs/eval/benchmark/results/benchmark_report.md):

- the code-aware comparison showed higher root-cause accuracy for the TraceLog condition on the current small benchmark set
- the logs-only comparison did not show a root-cause accuracy advantage
- retrieval on the current dataset was saturated enough that it was more informative as an ablation than as the primary product-facing comparison

These results should be read as the state of the current benchmark implementation, not as a general claim that TraceLog is universally better than standard logging.

## Running Tests

Example:

```bash
uv run pytest tests/test_aggregator.py tests/test_context_propagation.py
```

## Related Documentation

- [docs/system_architecture.md](docs/system_architecture.md)
- [docs/sdk/overview.md](docs/sdk/overview.md)
- [docs/eval/benchmark_v2_langchain.md](docs/eval/benchmark_v2_langchain.md)
- [docs/eval/benchmark/results/benchmark_report.md](docs/eval/benchmark/results/benchmark_report.md)
