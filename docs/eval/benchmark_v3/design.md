# Benchmark v3 — Design

## Overview

Benchmark v3 extends v2 along two axes:

1. **Model axis** — every scenario is run against 3 LLM providers using their flagship models
2. **Scenario axis** — 4 existing v2 scenarios reused; 3 new multi-threading scenarios added

Result structure: `scenario × model × condition(A|B)` — 7 scenarios × 3 models × 2 conditions = 42 runs total.

---

## Model Configuration

### Target Models

| Provider | Model | Env Var |
| --- | --- | --- |
| OpenAI | `gpt-4o` | `DIAGNOSER_MODEL_OPENAI` |
| Google | `gemini-2.5-pro` | `DIAGNOSER_MODEL_GOOGLE` |
| Anthropic | `claude-sonnet-4-6` | `DIAGNOSER_MODEL_ANTHROPIC` |

### Env Var Design

Per-provider env vars replace the single `DIAGNOSER_MODEL` used in v2. Each model can be swapped independently without affecting the others.

```bash
# .env additions for benchmark_v3
DIAGNOSER_MODEL_OPENAI=gpt-4o
DIAGNOSER_MODEL_GOOGLE=gemini-2.5-pro
DIAGNOSER_MODEL_ANTHROPIC=claude-sonnet-4-6
```

The existing `TRACELOG_DIAGNOSER_MODEL` is used by the production RAG diagnoser (`tracelog/rag/diagnoser.py`) and is unrelated to the benchmark runner — it stays as-is.

### LangChain Integration

Each provider requires its own LangChain chat model class:

| Provider | LangChain class | Package |
| --- | --- | --- |
| OpenAI | `ChatOpenAI` | `langchain-openai` |
| Google | `ChatGoogleGenerativeAI` | `langchain-google-genai` |
| Anthropic | `ChatAnthropic` | `langchain-anthropic` |

The benchmark v3 runner will inject the appropriate model instance based on provider, keeping the agent pipeline identical across all models.

---

## Scenario Set

### Reused from v2 (unchanged)

| Scenario | Bug type |
| --- | --- |
| `api_gateway` | Dict key typo propagates as `None` |
| `maze` | Float vs floor division → float index |
| `dynamic_pricing` | Timestamp offset produces wrong date |
| `thread_local` | threading.local() not reset → admin state leak |

### New Multi-Threading Scenarios

The 3 new scenarios are specifically designed to stress-test TraceLog's concurrent log separation. When 4 threads run simultaneously, standard logs interleave 20–40 lines across threads. TraceLog separates each thread's execution into its own span tree, making it possible to isolate the buggy thread's sequence without manual reconstruction.

| Scenario | Bug | Root cause | Surface error |
| --- | --- | --- | --- |
| `worker_dispatch` | SEASONAL worker applies `discount_rate` instead of `tax_rate` | `apply_category_rules` | `validate_margin` |
| `producer_aggregator` | Zone-2 collector applies `zone_offset` instead of `calibration_factor` | `apply_calibration` | `range_check` |
| `ledger_processor` | TRANSFER processor looks up settlement rate via wrong account key | `get_settlement_multiplier` | `verify_settlement` |

See `scenarios/*/` for full scenario JSON files.

---

## Framework Changes (deferred)

The `tracelog/eval/benchmark_v3.py` runner needs:

- **Model adapter layer** — factory function that returns the correct LangChain chat model given a provider name and the corresponding env var
- **Updated result schema** — `result.json` gains a `model` field; aggregation covers the new `scenario × model` dimensions
- **Aggregation** — summary statistics across models as well as across conditions

This is a separate implementation phase.
