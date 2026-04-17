# Benchmark v3 — Framework Implementation

**Date**: 2026-04-17
**Branch**: main
**Agent**: AI Engineer

## Goal

Implement `tracelog/eval/benchmark_v3.py` — the multi-model runner for Benchmark v3 that extends v2 with a provider axis (OpenAI, Google, Anthropic).

## Steps

1. Add `langchain-google-genai>=2.0.0` and `langchain-anthropic>=0.3.0` to `pyproject.toml`; run `uv sync`
2. Add per-provider diagnoser env vars to `.env`: `DIAGNOSER_MODEL_OPENAI`, `DIAGNOSER_MODEL_GOOGLE`, `DIAGNOSER_MODEL_ANTHROPIC`
3. Write `tracelog/eval/benchmark_v3.py` with:
   - `BenchmarkV3Config` dataclass (per-provider model names, judge, providers tuple)
   - `_make_diagnoser_llm(provider, config)` factory → `ChatOpenAI` / `ChatGoogleGenerativeAI` / `ChatAnthropic`
   - `_use_tracelog_flag_v3` + v3-local `@tool` wrappers (separate from v2 module state)
   - `_extract_metrics_v3` — safe `usage_metadata` get (no assert)
   - `_diagnose_agentic_v3(llm, ...)` — accepts `BaseChatModel` directly
   - `run_scenario_v3` — logs executed once per scenario (shared); each provider gets its own run dir
   - `run_benchmark_v3` — full sweep across all 7 scenarios × 3 providers
   - `_aggregate_v3` — `provider × condition` + `per_scenario × provider × condition` dimensions
   - Notebook helpers: `summary_rows_v3`, `per_run_rows_v3`, `verdict_markdown_v3`
4. Verify: import, config, model factory, aggregation schema all pass

## Design docs referenced

- `docs/eval/benchmark_v3/design.md`
- `tracelog/eval/benchmark_v2.py` (shared infrastructure imported directly)

## Notes

- Installed: `anthropic==0.96.0`, `langchain-anthropic==1.4.0`, `langchain-google-genai==4.2.2`, `google-genai==1.73.1`
- Judge always uses OpenAI `gpt-4o` as stable reference evaluator
- `_extract_metrics_v3` uses safe `.get()` for `usage_metadata` instead of assert — Google/Anthropic may not populate all fields
- Run dir naming: `{scenario}_{provider}_{timestamp}` — execution shared dir prefixed with `_exec_`
- Per-run result JSON adds `scenario`, `provider`, `model` fields to v2's schema
