# /status

Check the current implementation state of the TraceLog project and surface any mismatches.

## What this skill does

Reads `CLAUDE.md` (Implementation Status table) and `docs/roadmap.md` side by side,
then reports:
1. Items marked ✅ Done in CLAUDE.md but still open ([ ]) in roadmap.md — potential stale status
2. Items marked 🔧 or ❌ in CLAUDE.md but checked ([x]) in roadmap.md — potential premature status
3. Items in roadmap.md with no corresponding row in CLAUDE.md — coverage gap
4. Which items are currently safe to implement (🔧 Designed / not yet implemented)

## Output format

Print a short status report in this structure:

---

## TraceLog Implementation Status

### Ready to implement
[Items that are designed but not yet coded — safe to start]

### Mismatches detected
[Table of inconsistencies between CLAUDE.md and roadmap.md]
| Item | CLAUDE.md status | roadmap.md status | Issue |
| --- | --- | --- | --- |

### Coverage gaps
[Items in roadmap.md with no row in CLAUDE.md]

### Summary
One sentence: "X items ready, Y mismatches, Z gaps."

---

## Rules for the agent

- Read both files fresh every time — do not rely on memory.
- Do not modify either file unless the user explicitly asks.
- If no mismatches are found, say so clearly — do not invent issues.
- After the report, ask: "Would you like to update CLAUDE.md or roadmap.md to fix any of these?"