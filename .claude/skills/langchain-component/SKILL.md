---
name: langchain-component
description: Reference patterns for implementing LangChain-based components in TraceLog — model injection, create_agent usage, metrics extraction, and prompt template conventions
---

# /langchain-component

Reference patterns for implementing LangChain-based components in TraceLog.

## Model injection

Always read model names from environment variables. Never hardcode.

```python
import os
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model=os.getenv("DIAGNOSER_MODEL", "gpt-4o"),
    temperature=0,
)
```

## Agent loop

Use `create_agent` from `langchain.agents` for all agent loops.

```python
from langchain.agents import create_agent

agent = create_agent(
    model=os.getenv("DIAGNOSER_MODEL", "gpt-4o"),
    tools=tools,
    system_prompt=system_prompt,
)
result = agent.invoke({"messages": messages})
```

## Extracting metrics from message history

Never count metrics manually during the loop. Extract post-run from message history.

```python
from langchain_core.messages import AIMessage, ToolMessage

messages = result["messages"]

tool_call_count = sum(1 for m in messages if isinstance(m, ToolMessage))
fix_attempts    = sum(
    1 for m in messages if isinstance(m, AIMessage)
    for tc in (m.tool_calls or []) if tc["name"] == "write_file"
)
iterations      = sum(1 for m in messages if isinstance(m, AIMessage))
```

## Prompt templates

All prompt templates are `.yaml` files stored inside the package. Load with `load_prompt()`.
The exact path is defined in each component's design doc — check `docs/` before creating a new path.

```python
from pathlib import Path
from langchain.prompts import load_prompt

prompt = load_prompt(Path(__file__).parent / "prompts" / "diagnoser.yaml")
```

Template format:

```yaml
# tracelog/rag/prompts/diagnoser.yaml
input_variables:
  - tracetree
  - past_incidents
template: |
  You are diagnosing a production error.

  ## Current Trace
  {tracetree}

  ## Similar Past Incidents
  {past_incidents}
```

## Rules

- Use `create_agent` from `langchain.agents` for all agent loops.
- Inject model names via env var — never hardcode model strings.
- Extract metrics (tool_call_count, iterations, fix_attempts) from message history post-run.
- All prompts in `.yaml` inside the package — never hardcoded in Python, never under `docs/`.
- Prompt file path is defined in the component's design doc — check before creating a new path.
- Use only `langchain-openai` and `langchain` unless the AI Engineer specifies otherwise.
