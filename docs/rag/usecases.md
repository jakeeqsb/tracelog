# TraceLog RAG — Use Cases

## Background

Production errors get investigated from scratch every time. Past fixes live in
Slack threads, PR descriptions, and individual memory — none of it is
queryable. When the same error recurs, the engineer repeats the full debugging
cycle with no institutional memory to draw from.

TraceLog RAG addresses this through three capabilities that build on each other.

---

## UC-1: Find Similar Past Errors

**Situation**

An error just occurred. The engineer has the dump file. They want to know:
*"Have we seen something like this before?"*

**Without this**

The engineer manually searches Slack, git history, or JIRA using error class
names or function names — often coming up empty because those tools don't
understand execution structure, only keywords.

**With TraceLog RAG**

```bash
tracelog index ./dumps/          # ingest today's dump as an INCIDENT
tracelog diagnose ./dumps/new_error.log
```

The system embeds the failing TraceTree chunk and searches the vector store for
structurally similar past errors — matching on execution path and error context,
not just on the exception class name. Results are printed to the terminal ranked
by similarity.

**Value**

The engineer immediately knows if this is a recurring issue or a new one,
without manually searching anything.

---

## UC-2: LLM Root Cause Diagnosis

**Situation**

The engineer is looking at a failing TraceTree chunk and wants to understand
*"Why did this fail? Which function is the actual root cause?"*

**Without this**

The engineer reads the raw Trace-DSL output line by line, traces the call stack
manually, and forms a hypothesis. For complex nested calls this takes significant
time and requires deep knowledge of the codebase.

**With TraceLog RAG**

The `diagnose` command automatically:
1. Retrieves similar past INCIDENT chunks from the vector store
2. Loads any linked POSTMORTEM (root cause and fix) for those incidents
3. Passes the current chunk + past context to an LLM
4. Prints a structured diagnosis to the terminal:

```
root_cause_function : process_payment
root_cause_type     : ValueError
error_surface       : validate_card_number
fix_hint            : Card number regex does not handle 19-digit cards
confidence          : high
```

**Value**

The LLM has both the current execution trace *and* how similar past errors were
resolved. It produces a diagnosis grounded in actual history, not just pattern
matching on the current dump alone.

---

## UC-3: Accumulate Postmortems for Future Diagnoses

**Situation**

The engineer has fixed the bug. They want to record *"what it was and how it
was fixed"* so that the next time this type of error occurs — whether it's them
or someone else — the system can surface the answer immediately.

**Without this**

The fix lives in a commit message or a PR description. The next person to hit
the same error has no way to find it unless they know exactly what to search for.

**With TraceLog RAG**

```bash
tracelog postmortem commit \
  --incident-id inc_abc123 \
  --root-cause "Card number regex does not handle 19-digit Mastercard numbers" \
  --fix "Updated regex in validate_card_number() to support 13–19 digit range"
```

This creates a POSTMORTEM node linked to the INCIDENT by `incident_id`.
The INCIDENT status is updated to `resolved`.

**Effect on future diagnoses**

Next time a similar error occurs, UC-2 returns not just the raw past trace but
also the confirmed root cause and fix from the POSTMORTEM. The LLM's diagnosis
prompt becomes:

```
=== PAST SIMILAR INCIDENTS ===
[trace chunk from inc_abc123]

=== CONFIRMED ROOT CAUSE & FIX (from postmortem) ===
root_cause : Card number regex does not handle 19-digit Mastercard numbers
fix        : Updated regex in validate_card_number() to support 13–19 digit range

=== CURRENT ERROR (to diagnose) ===
[current trace chunk]
```

**Value**

The system gets more accurate with each resolved incident. Postmortems turn
past debugging work into reusable knowledge.

---

## How the Three Capabilities Connect

```
UC-1 alone      → "Have we seen this before?" (search only)
UC-1 + UC-2     → "Here is likely why it failed" (search + diagnosis)
UC-1 + UC-2 + UC-3 → "Here is why, and here is exactly how to fix it"
                     (search + diagnosis + accumulated knowledge)
```

Each layer adds value independently. UC-3 compounds over time — the more
postmortems are committed, the more accurate UC-2 becomes.
