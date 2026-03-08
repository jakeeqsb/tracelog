# TraceLog Evaluation Test Plan

## Purpose

This document defines how TraceLog should be evaluated at the current MVP stage.

The goal is not just to prove that the SDK and RAG pipeline run without errors. The goal is to verify whether the overall approach is practically useful:

- Can TraceLog reconstruct fragmented execution context correctly?
- Does Trace-DSL preserve enough context for chunking and embedding?
- Does retrieval return incidents with the same root cause?
- Does the final diagnosis become more accurate, faster, or cheaper than a standard logging baseline?

---

## Scope

This plan evaluates the current system in four layers:

1. **Aggregation correctness**
2. **Retrieval quality**
3. **Diagnosis quality**
4. **Operational efficiency**

This plan assumes the current MVP architecture:

- JSON dump emission from the SDK
- `trace_id`, `span_id`, and `parent_span_id` for reconstruction
- Aggregator-based unified Trace-DSL rendering
- `TraceTreeSplitter` for structural chunking
- embedding and vector retrieval through Qdrant

---

## Assumptions

The evaluation is based on the following assumptions.

### Core Product Assumptions

1. Trace-DSL carries more useful debugging context than standard application logs.
2. Aggregated trace structure is more useful than isolated error lines.
3. Structural chunking preserves the root-cause path better than naive text splitting.
4. Similar incidents should be retrievable from prior traces by semantic search and metadata filtering.

### MVP Engineering Assumptions

1. Whitespace indentation plus Trace-DSL symbols (`>>`, `<<`, `!!`, `..`) is sufficient for MVP chunking and embedding.
2. `trace_id`, `span_id`, and `parent_span_id` are enough to reconstruct the majority of intended parent-child relationships in MVP scenarios.
3. The current system should be judged primarily on usefulness and correctness, not on maximum sophistication.

### Non-Goals for This Evaluation

This plan does not attempt to validate:

- distributed tracing across multiple machines
- production-scale throughput
- perfect race-condition timeline reconstruction
- long-term online learning or model fine-tuning

---

## Evaluation Questions

The following questions should be answered by the test campaign.

1. Does the Aggregator reconstruct the correct execution tree?
2. Does TraceLog retrieval return the same root-cause family at useful ranks?
3. Does the LLM produce better root-cause analysis with TraceLog than with standard logs?
4. Is the token and latency cost acceptable for an MVP workflow?

---

## Test Data Strategy

The evaluation dataset should be built in three layers.

### 1. Synthetic Scenario Set

Synthetic data is used first because it gives exact ground truth.

Required scenario families:

- single-function exception
- nested call chain (`a -> b -> c`)
- async or thread worker failure under a parent span
- fan-out execution where one child fails and others succeed
- repeated surface error with different true root causes
- same root cause with varied messages and values
- noisy traces with many irrelevant info/debug lines
- short trace and long trace variants

Why this layer matters:

- ground truth is explicit
- reconstruction accuracy can be scored precisely
- retrieval relevance labels can be created cleanly

### 2. Semi-Realistic Application Fixtures

These are small but realistic application examples that simulate common debugging situations.

Recommended fixture types:

- payment or checkout flow
- authentication and authorization flow
- DB timeout and retry exhaustion
- background worker failure
- queue consumer failure
- configuration or environment error
- state mutation bug propagated through a call chain

Why this layer matters:

- logs and traces look closer to real usage
- diagnosis usefulness becomes more realistic
- retrieval quality is tested beyond toy examples

### 3. Historical or Manually Curated Incident Set

If available, add a small curated set of real or near-real incidents later.

This is not required to start MVP evaluation, but it becomes useful once the synthetic and fixture layers are stable.

---

## How to Build the Dataset

### Data Unit

Each incident should include:

- scenario ID
- scenario family
- expected root cause label
- expected evidence lines or evidence span IDs
- standard log output
- TraceLog JSON dumps
- aggregated Trace-DSL output
- chunked outputs

### Labeling Rules

Each incident should be labeled with at least:

- `root_cause_id`
- `error_family`
- `module`
- `expected_primary_span`
- `expected_primary_function`
- `difficulty`

This allows evaluation at multiple levels:

- exact same root cause
- same error family
- same module or subsystem

### Recommended Directory Layout

Recommended future structure:

```text
eval/
  scenarios/
    synthetic/
    fixtures/
  datasets/
    incidents.jsonl
  prompts/
  results/
```

---

## Evaluation Stages

### Stage 1: Aggregation Evaluation

This stage validates reconstruction before retrieval is measured.

Questions:

- Was the correct root span selected?
- Were child spans attached to the correct parent?
- Was render placement correct?
- Was the final trace readable and structurally consistent?

Metrics:

- `trace_reconstruction_accuracy`
- `parent_child_linkage_accuracy`
- `render_order_accuracy`
- `trace_render_validity`

Suggested success criterion:

- Aggregation correctness should be near-perfect on synthetic scenarios before retrieval benchmarking begins.

### Stage 2: Retrieval Evaluation

This stage validates whether the indexed traces retrieve the right prior incidents.

Primary metrics:

- `HitRate@k`
- `Recall@k`
- `MRR`
- `nDCG@k`

TraceLog-specific relevance variants:

- `SameRootCauseHit@k`
- `SameErrorFamilyHit@k`
- `CorrectParentContextHit@k`

Recommended interpretation:

- `SameRootCauseHit@3` is the most important retrieval KPI for this project.
- `MRR` is useful to show whether the correct prior case is ranked early enough to help diagnosis.

### Stage 3: Diagnosis Evaluation

This stage evaluates the final LLM answer quality.

Primary metrics:

- `root_cause_accuracy`
- `groundedness`
- `evidence_match`
- `actionability`

Suggested scoring scheme:

- `Correct`
- `Partially Correct`
- `Incorrect`

Judging criteria:

- Did the answer identify the true root cause?
- Did it cite the correct evidence trace or span?
- Did it avoid unsupported hallucinations?
- Did it provide a useful next action or fix direction?

### Stage 4: Operational Evaluation

This stage measures practical cost.

Metrics:

- `aggregation_latency`
- `chunking_latency`
- `embedding_latency`
- `retrieval_latency`
- `diagnosis_latency`
- `input_tokens`
- `output_tokens`
- `cost_per_incident`

This stage is important because TraceLog is not only a correctness project. It is also a usability and cost-efficiency project.

---

## Baselines

At minimum, the following baselines should be compared.

1. **Standard Logging**
   - Plain Python logging and traceback only

2. **TraceLog without Aggregation**
   - Trace-DSL fragments before cross-span reconstruction

3. **TraceLog with Aggregation**
   - Unified Trace-DSL after Aggregator processing

4. **TraceLog Full Pipeline**
   - Aggregation + Splitter + Indexer + Retrieval + Diagnosis

This allows the project to show not only that TraceLog works, but which layer contributes actual value.

---

## Primary Decision Metrics

The following metrics should be treated as the most important.

1. `trace_reconstruction_accuracy`
2. `SameRootCauseHit@3`
3. `root_cause_accuracy`
4. `token_per_correct_diagnosis`
5. `time_to_verdict`

These metrics best reflect the project's product promise:

- better context reconstruction
- better retrieval of prior similar incidents
- better diagnosis
- acceptable efficiency

---

## Role of Embedding-Only Metrics

Embedding-space metrics such as silhouette score may still be recorded, but they should be treated as secondary diagnostics only.

They are useful for:

- comparing splitter variants
- comparing embedding models
- checking whether clustering behavior changes

They are not sufficient for:

- proving retrieval usefulness
- proving diagnosis quality
- proving product value

For this project, ranking and diagnosis metrics matter more than geometric embedding metrics.

---

## Recommended Execution Order

The evaluation should proceed in this order.

1. Freeze the scenario set and labels.
2. Validate aggregation correctness first.
3. Benchmark retrieval quality.
4. Benchmark diagnosis quality.
5. Record token, latency, and cost metrics.
6. Compare against standard logging baselines.

This order prevents weak downstream results from being misdiagnosed when the real issue is faulty aggregation or poor labels.

---

## MVP Exit Criteria

The MVP should be considered validated if the following conditions are met.

1. Aggregation is consistently correct on synthetic scenarios.
2. TraceLog retrieval improves same-root-cause retrieval over the standard logging baseline.
3. TraceLog diagnosis improves root-cause accuracy over the standard logging baseline.
4. Token and latency overhead remain acceptable for a debugging workflow.

Suggested interpretation:

- If retrieval improves but diagnosis does not, the retrieval context may still be poorly presented to the LLM.
- If diagnosis improves but cost is too high, the pipeline may need token optimization.
- If aggregation fails, all later evaluations should be treated as invalid.

---

## Next Deliverables

The next evaluation artifacts that should be created are:

1. a scenario inventory document
2. a dataset label schema
3. benchmark runner scripts
4. a result report template

This document defines the test plan only. It does not define the scenario corpus or benchmark implementation details yet.
