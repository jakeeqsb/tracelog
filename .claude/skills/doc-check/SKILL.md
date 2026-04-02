---
name: doc-check
description: Verify that every source file has a corresponding design document in docs/ before implementation proceeds
---

# /doc-check

Verify that every source file has a corresponding design document in `docs/` before implementation proceeds.

## Usage
/doc-check [path]

- path: optional - a specific file or directory to check  (e.g. `tracelog/rag/`, `tracelog/ingestion/aggregator.py`). Defaults to the entire `tracelog/` source tree.

## What this skill does

For each Python module in scope, checks whether a corresponding design doc exists in `docs/`.
Mapping logic:

| Source path | Expected doc location |
| --- | --- |
| `tracelog/rag/*.py` | `docs/rag/*.md` |
| `tracelog/ingestion/*.py` | `docs/ingestion/*.md` |
| `tracelog/eval/*.py` | `docs/eval/*.md` |
| `tracelog/*.py` (SDK core) | `docs/sdk/*.md` |

A match is valid if a `.md` file exists whose name corresponds to the module name (e.g. `aggregator.py` → `aggregator.md`). Exact filename match is preferred; a containing overview doc (e.g. `overview.md`) counts as a partial match.

## Output format

---

## Doc Coverage Report

### Covered — design doc found
| Source file | Design doc |
| --- | --- |

### Partial — covered by an overview doc only
| Source file | Matched doc | Note |
| --- | --- | --- |

### Missing — no design doc found
| Source file | Expected location |
| --- | --- |

### Summary
`X/Y modules covered. Z missing.`

---

## Rules for the agent

- Read the actual file system — do not guess from memory.
- Do not create missing docs automatically. If gaps are found, list them and ask: "Would you like to run `/design` for any of these?"
- `__init__.py`, `__pycache__`, and test files (`tests/`) are excluded from the check.
- If everything is covered, say so clearly.
