# LangChain Conventions

These rules apply whenever implementing any LangChain-based component — no exception.

## Model injection

Never hardcode model names or config values. Always use `os.getenv()`.
This includes embedding models, LLM models, chunk sizes, collection names, and vector dims.

```python
import os
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model=os.getenv("DIAGNOSER_MODEL", "gpt-4o"),
    temperature=0,
)
```

## Agent loops

Use `create_agent` from `langchain.agents` for all agent loops — no hand-rolled loops.

```python
from langchain.agents import create_agent

agent = create_agent(
    model=os.getenv("DIAGNOSER_MODEL", "gpt-4o"),
    tools=tools,
    system_prompt=system_prompt,
)
result = agent.invoke({"messages": messages})
```

## Prompt templates

All prompts go in `.yaml` files inside the package. Load with `load_prompt()`.
The exact path is defined in each component's design doc — check `docs/` before creating a new path.

```python
from pathlib import Path
from langchain.prompts import load_prompt

prompt = load_prompt(Path(__file__).parent / "prompts" / "diagnoser.yaml")
```

Never hardcode prompt strings in Python. Never store prompts under `docs/`.

## Metrics extraction

Extract metrics from message history post-run — never count manually during the loop.

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

## Dependencies

Use only `langchain-openai` and `langchain` unless the AI Engineer specifies otherwise.
