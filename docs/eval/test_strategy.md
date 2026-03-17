# TraceLog Eval Strategy

## Goal

Prove that TraceLog helps an LLM diagnose bugs more accurately than standard logs,
by having the LLM blind-diagnose the same bug from two different log formats.

## Non-Negotiables

- Same code, same bug, same execution — only the log format differs.
- The diagnosing agent never sees the sealed truth or the source code.
- Bugs must have a different root cause function and surface error function.
- Bugs must look like natural code mistakes, not flag-controlled variants.

## Scenario Generation

An AI agent (gpt-4o) generates each scenario fresh:
- A `Scenario` class with 4–6 `@trace`-decorated methods and realistic noise logs.
- A hidden bug where the upstream function produces a wrong value that explodes downstream.
- A `sealed_truth.json` with `root_cause_function`, `surface_error_function`,
  `bug_description`, and `expected_fix`.

Completed runs are added to the RAG corpus for future runs.

## Three Conditions

| ID | Input | RAG |
|----|-------|-----|
| A  | standard.log | no |
| B  | tracelog.log | no |
| C  | tracelog.log | yes (past runs) |

- **B vs A**: Does Trace-DSL format alone improve diagnosis?
- **C vs A**: Does the full TraceLog system beat the current baseline?
- **C vs B**: How much does RAG contribute?

## Evaluation (per condition, per run)

| Metric | Type | Question |
|--------|------|----------|
| `root_cause_correct` | 0/1 | Did it find the upstream origin? |
| `surface_error_correct` | 0/1 | Did it find where the error surfaces? |
| `evidence_quality` | 0/0.5/1 | Are cited log lines real and accurate? |
| `fix_direction_correct` | 0/1 | Is the proposed fix targeting the right function? |

`root_cause_correct` is the primary metric.

## Evidence Quality Rubric

- **1.0** — All cited evidence is real log content, accurately connected to the diagnosis.
- **0.5** — Evidence is in the right area but paraphrased loosely or partially missing.
- **0.0** — Evidence is hallucinated or not present in the log.

## Exit Criteria

TraceLog passes when, across ≥ 5 runs:

1. Condition B `root_cause_correct` > Condition A
2. Condition C `root_cause_correct` > Condition A
3. The improvement holds across at least 2 different scenario types.

## Run Structure

Each run lives in `docs/eval/benchmark/runs/{run_id}/`:

```
scenario_code.py      — generated scenario (never shown to diagnoser)
sealed_truth.json     — sealed answer (Judge only)
standard.log          — standard logging output
tracelog.log          — TraceLog aggregated output
diagnosis_A.json      — standard log diagnosis
diagnosis_B.json      — tracelog diagnosis (no RAG)
diagnosis_C.json      — tracelog diagnosis (with RAG)
judgment.json         — Judge scores for all three conditions
```

Past run TraceLog outputs are indexed in `docs/eval/benchmark/corpus/` and used
as the RAG corpus for condition C.
