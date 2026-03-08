# TraceLog

> **AI-Native Context Logging for Python**  
> "An experimental approach to structurally logging execution context."

## Introduction

Traditional log formats were designed primarily for human readability and regular expression parsing. As we explore using **LLMs (Large Language Models) to assist in debugging**, standard logging can sometimes face structural challenges—especially in asynchronous, multi-threaded environments where log lines from different flows interleave.

**TraceLog** is a Python logging SDK and library intended for analyzing **LLM-based debugging workflows**.
It integrates with the standard `logging` module to capture structurally isolated **execution trajectories (Trace-DSL)** when an error occurs, aiming to provide a more predictable context for language models.

---

## The Problem Space

In our preliminary research involving standard text logs for LLM root-cause analysis and vector search, several patterns emerged:

1. **Context Fragmentation**: In asynchronous or multi-threaded environments, logs from concurrent flows (e.g., Thread A handling payment, Thread B handling user profiles) often interleave. When fed to an LLM sequentially, the model may hallucinate causality—for example, falsely associating a database timeout in Thread A with a profile fetch in Thread B simply due to textual proximity.
2. **Missing State Variability**: Standard logging often lacks the dynamic state of the application at the moment of failure. Unless a developer explicitly logs parameter values at every step (`logger.info(f"x={x}")`), the LLM might recognize that a `ValueError` occurred, but lacks the necessary trace of input arguments to determine *where* the invalid value originated.
3. **Lexical Ambiguity**: Vector retrieval (RAG) relying on semantic embeddings often struggles with generic error terminology. A search for a `TimeoutException` in a payment module might retrieve historically similar text containing "timeout" from an entirely unrelated email module. This lexical overlap can mislead the LLM into suggesting irrelevant remediation steps.

## Architecture

TraceLog attempts to address these challenges using a structural formatting language called **Trace-DSL**.

1. **TraceLog SDK (`@trace`)**: Wraps execution to capture a hierarchical tree of the call stack (including captured arguments) when an `ERROR` is triggered.
2. **TraceTree Splitter**: For RAG Vector ingestion, it proposes chunking logs by tracing boundaries rather than fixed character limits, aiming to keep parent-child contexts grouped in the Vector Space.
3. **Hybrid Retrieval**: Powered by Qdrant (Dense + BM25), the framework queries both semantic similarities and lexical artifacts to provide historical context to a `Diagnoser` LLM.

*For a comprehensive breakdown of how these components interact—from the initial data ingestion to the final LLM reasoning gateway—please refer to the [System Architecture Documentation](docs/system_architecture.md).*

---

## Benchmark Observations

In our recent V2 A/B scenario testing, which compared Trace-DSL against Standard Logging across various simulated concurrency and timeout scenarios:

- **Accuracy in Async Call-Stacks**: Trace-DSL structures appeared to help the LLM better identify the root cause in asynchronous timeout scenarios, whereas standard logging demonstrated a decline in correct identification as concurrent thread noise increased.
- **Disambiguation Cases**: In simulated 'Doppelgänger' scenarios where the text of an error is identical but the underlying cause differs, preserving the invocation path via Trace-DSL helped the LLM distinguish between the simulated failures.

*For detailed methodology and evaluation data on our chunking, embedding, and retrieval experiments, please refer to the [Eval Documentation](docs/eval/).*
