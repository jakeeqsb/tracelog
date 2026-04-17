# Benchmark v3 — Multi-Threading Scenarios

**Date**: 2026-04-17
**Branch**: main
**Agent**: AI Engineer

## Goal

Design and write 3 new multi-threading scenario JSON files for Benchmark v3. Scenarios are specifically structured to stress-test TraceLog's span-based concurrent log separation, where 4 threads run concurrently and the bug is only traceable by isolating one thread's execution sequence.

## Steps

1. Create `docs/eval/benchmark_v3/` directory structure
2. Write `docs/eval/benchmark_v3/design.md` — model spec, env var design, scenario rationale
3. Write `worker_dispatch` scenario JSON — 4 concurrent category workers, SEASONAL uses wrong rate
4. Write `producer_aggregator` scenario JSON — 3 concurrent zone collectors + aggregator, Zone-2 uses wrong calibration variable
5. Write `ledger_processor` scenario JSON — 4 concurrent transaction processors, TRANSFER uses wrong account key for rate lookup
6. Verify all 3 scenarios raise exceptions in the correct surface function via Python execution

## Design docs referenced

- `docs/eval/benchmark_v2/scenarios/multi_threads.md`
- `docs/eval/benchmark_v2/scenarios/thread_local/thread_local.json` (reference format)
- `docs/eval/benchmark_v3/design.md` (written in this session)

## Notes

- Initial design (`closure_trap`, `unawaited_future`, `lost_update`) was rejected because it didn't genuinely test TraceLog's span separation — concurrent thread count was too low (1–2 threads) and `closure_trap` was a scoping bug invisible to threading context
- Redesigned to require 4 concurrent threads (`max_workers=4`) with bugs that span 3+ method calls within one specific thread's execution path
- All 3 scenarios verified: correct surface function raises, correct function does not raise
- Model configuration confirmed: `gpt-4o` / `gemini-2.5-pro` / `claude-opus-4-6` via per-provider env vars (`DIAGNOSER_MODEL_OPENAI`, `DIAGNOSER_MODEL_GOOGLE`, `DIAGNOSER_MODEL_ANTHROPIC`)
- Benchmark v3 framework (`benchmark_v3.py`) is deferred to a separate design phase
