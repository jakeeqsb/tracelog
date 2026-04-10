# Plan Logging

When entering plan mode to design an implementation, save the plan to `.dev/logs/` before execution begins.

## When this applies

Any time an agent creates a plan for implementing a feature, refactor, or non-trivial change.

## File naming

```
.dev/logs/YYYY-MM-DD_<short-description>.md
```

Examples:
- `.dev/logs/2026-04-10_postmortem-vector-search.md`
- `.dev/logs/2026-04-10_env-var-config-cleanup.md`

## File format

```markdown
# <Feature / Task Title>

**Date**: YYYY-MM-DD
**Branch**: <current git branch>
**Agent**: <role — e.g. Software Engineer>

## Goal

[One sentence: what this plan achieves and why.]

## Steps

1. [Step description — file(s) affected, what changes]
2. ...

## Design docs referenced

- `docs/<area>/<file>.md`

## Notes

[Any constraints, risks, or open questions surfaced during planning.]
```

## Rules

- Write the log file **before** making any code changes — the plan is a record of intent, not a summary after the fact.
- If the plan changes during implementation, update the log file to reflect what actually happened and why it diverged.
- Do not delete log files. They are a permanent record.
