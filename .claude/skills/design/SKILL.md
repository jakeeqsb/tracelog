# /design

Generate a design document for a new TraceLog component or feature

## Usage

/design <component-name> [area]

- component-name: name of the module or feature (e.g. `incident-ingestion`, `postmortem-cli`)
- area: optional subdirectory hint - `sdk`, `ingestion`, `rag`, `eval` (defaults to inferring from context)

## What this skill does 

Create a design doc draft at the correct path under docs/<area>/<component-name>.md, following the TraceLog standard format. The draft is shown to the user for review before any file is writeen to disk.

## Output format

The generated document must follow this structure this structive exactly: 

---

# <ComponentName> - Design Document

## Overview

[2–3 sentences: what this component does and why it exists in the system.
Reference the layer it belongs to: SDK / Ingestion / Storage / Reasoning.]

---

## Role and Purpose

[Expand on the overview. Explain what problem this solves that nothing else currently handles.]

---

## Data Model

[If the component handles data: show the key structures as JSON or Python dataclasses.
Include field names, types, and a one-line comment on each non-obvious field.]

---

## Lifecycle / Data Flow

[Step-by-step flow using plain-text arrow diagrams (→ or ↓).
Show inputs, transformations, and outputs. Do not use Mermaid or external diagram syntax.]

---

## Interface

[If the component exposes a public API: show the Python function or class signatures.
Docstrings for each method. No implementation.]

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| [what was decided] | [why — including what alternatives were considered and rejected] |

---

## Open Questions

[Any decisions not yet made that require user input or further research.
Leave this section empty if none.]

---

## Rules for the agent

- Do NOT write the file to disk without explicit user approval.
- Do NOT invent implementation details — mark unknowns as open questions.
- Do NOT include sections that are genuinely not applicable (e.g. no Data Model for a pure utility). Remove empty sections rather than leaving placeholders.
- Always ask: "Does this align with the VectorStore Protocol?" if the component touches storage.
- After showing the draft, ask: "Should I write this to docs/<area>/<component-name>.md?]