# benchmark_v2 LangChain Migration — Design Document

## Overview

`benchmark_v2.py` currently implements the agentic diagnosis loop as a hand-rolled `for` loop that calls the OpenAI Chat Completions API directly, routes tool calls, and accumulates metrics inline. This migration replaces that manual loop with LangChain's `create_agent`, moves all prompt strings out of source code into `.yaml` template files, and reads model names from environment variables. The public API surface (`run_once`, `run_benchmark`, `load_results`, etc.) and the result schema remain identical — callers and the analysis notebook see no change.

---

## Current vs Target Architecture

| Layer | Current (OpenAI SDK) | Target (LangChain) |
|---|---|---|
| LLM client | `openai.OpenAI()` instantiated in `run_once` | `ChatOpenAI(model=..., temperature=0)` injected per call |
| Model names | Module-level constants (`DIAGNOSER_MODEL = "gpt-4o"`) | Read from env vars `DIAGNOSER_MODEL`, `JUDGE_MODEL`, `WRITER_MODEL`; fall back to `"gpt-4o"` |
| Agent loop | `_diagnose_agentic()` — manual `for _ in range(max_iterations)` with tool dispatch | `create_agent(model, tools, system_prompt=...)` + `agent.invoke({"messages": [...]})` |
| Tools | Raw OpenAI JSON schema dicts in `_TOOLS`; executed by `_execute_tool()` | LangChain `@tool`-decorated functions wrapping existing `_tool_*` implementations |
| Prompt templates | `.txt` files loaded via `Path.read_text()`, interpolated with `.replace()` | `.yaml` files inside the package, loaded via `load_prompt()` |
| Metrics collection | Counters tracked inline inside the `for` loop | Extracted post-run from `AIMessage` / `ToolMessage` list via `_extract_metrics()` |
| Rate-limit retry | Manual `try/except` + exponential `time.sleep()` | `ChatOpenAI(max_retries=5)` — removed from application code |
| Message serialisation | OpenAI SDK message dicts saved to `agent_*_messages.json` | LangChain `messages_to_dict()` — content identical, format updated |

---

## Prompt Template Strategy

### Location

All prompt template files live inside the Python package alongside the code that uses them:

```
tracelog/eval/prompts/
    agent_system.yaml
    bug_writer.yaml
    judge.yaml
```

### File format

Each `.yaml` file is validated against a Pydantic model on load:

```yaml
# tracelog/eval/prompts/agent_system.yaml
description: "System prompt for the agentic diagnoser"
input_variables:
  - scenario_path
  - program_description
template: |
  You are a debugging agent ...
  Scenario file: {scenario_path}
  Program description: {program_description}
```

Pydantic schema:

```python
class PromptTemplate(BaseModel):
    description: str
    input_variables: list[str]
    template: str
```

### Loading convention

A single private helper loads, validates, and caches a template by name:

```python
def _load_prompt(name: str) -> str:
    """Load tracelog/eval/prompts/{name}.yaml and return the template string."""
```

### File mapping

| Current file | New file |
|---|---|
| `docs/eval/benchmark_v2/prompts/agent_system_prompt.txt` | `tracelog/eval/prompts/agent_system.yaml` |
| `docs/eval/benchmark_v2/prompts/bug_writer_prompt.txt` | `tracelog/eval/prompts/bug_writer.yaml` |
| *(judge prompt was inline)* | `tracelog/eval/prompts/judge.yaml` |

---

## Agent Loop Design

### Tool definitions

The three raw OpenAI schema dicts in `_TOOLS` are replaced by LangChain `@tool`-decorated functions. Each wraps the existing `_tool_read_file`, `_tool_search_code`, and `_tool_write_file` implementations — no logic change. The `use_tracelog` flag is captured via `functools.partial` before the tool list is assembled so the tool signature stays `(path, content)`.

```python
@tool
def read_file_tool(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read the contents of a source file."""
    return _tool_read_file(path, start_line, end_line)

@tool
def write_file_tool(path: str, content: str) -> str:
    """Overwrite the scenario file with fixed Python source code, then run it."""
    return _tool_write_file(path, content, use_tracelog=_use_tracelog)
```

### `create_agent` usage

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

llm   = ChatOpenAI(model=diagnoser_model, temperature=0, max_retries=config.max_retries)
tools = [read_file_tool, search_code_tool, write_file_tool_partial]

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=system_prompt,
)
result = agent.invoke({"messages": [HumanMessage(content=user_message)]})
messages = result["messages"]
```

### Early-exit behaviour

With `create_agent` the agent runs to natural completion — once it receives a `PASS` tool result it produces a final `AIMessage` with no tool calls and the graph terminates. This adds one extra LLM call compared to the current early-exit loop. The small token overhead is acceptable given the simplicity gain.

`fix_success` is determined post-run by reading the file on disk and calling `_verify_scenario_raises()`, same as the current loop-exhausted path.

---

## Metrics Extraction

All metrics are extracted post-run from the `messages` list returned by `agent.invoke()`.

```python
def _extract_metrics(messages: list) -> dict:
    tool_call_count = sum(1 for m in messages if isinstance(m, ToolMessage))
    fix_attempts    = sum(
        1 for m in messages
        if isinstance(m, AIMessage)
        for tc in (m.tool_calls or [])
        if tc["name"] == "write_file_tool"
    )
    iterations = sum(1 for m in messages if isinstance(m, AIMessage))

    input_tokens  = 0
    output_tokens = 0
    for m in messages:
        if isinstance(m, AIMessage):
            assert m.usage_metadata is not None, (
                f"usage_metadata missing on AIMessage — unexpected for non-streaming gpt-4o: {m}"
            )
            input_tokens  += m.usage_metadata["input_tokens"]
            output_tokens += m.usage_metadata["output_tokens"]

    return {
        "tool_call_count": tool_call_count,
        "fix_attempts":    fix_attempts,
        "iterations":      iterations,
        "usage": {
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "total_tokens":  input_tokens + output_tokens,
        },
    }
```

| Metric | Source |
|---|---|
| `tool_call_count` | Count of `ToolMessage` instances |
| `fix_attempts` | `AIMessage.tool_calls` entries with `name == "write_file_tool"` |
| `iterations` | Count of `AIMessage` instances |
| `latency` | `time.perf_counter()` before and after `agent.invoke()` — unchanged |
| `usage` | Sum of `AIMessage.usage_metadata` — assert non-None (non-streaming gpt-4o always populates this) |

---

## Message Serialisation

Saved `agent_*_messages.json` files switch from OpenAI SDK dicts to LangChain format via `messages_to_dict()`. Content (role, text, tool calls, tool results) is identical — only the key names differ. Human-readable in a text editor; existing `_judge_root_cause` logic is updated to read the new key names.

```python
from langchain_core.messages import messages_to_dict
save_path.write_text(json.dumps(messages_to_dict(messages), indent=2), encoding="utf-8")
```

---

## Migration Steps

1. **Add dependencies** — add `langchain`, `langchain-openai`, `pyyaml` to `pyproject.toml`. Run `uv sync`.
2. **Create prompts package** — create `tracelog/eval/prompts/` with `__init__.py`. Write `agent_system.yaml`, `bug_writer.yaml`, `judge.yaml` migrating content from existing `.txt` files.
3. **Write `_load_prompt(name)`** — reads and Pydantic-validates the `.yaml`; returns the template string. Add a unit test.
4. **Replace model-name constants** — remove the three module-level constants; set defaults in `BenchmarkV2Config` from env vars. Add `max_retries: int = 5` field.
5. **Define `@tool` wrappers** — `read_file_tool`, `search_code_tool`, `write_file_tool`. Keep `_tool_*` implementations unchanged.
6. **Write `_extract_metrics()`** — pure function over message list. Unit-test with synthetic messages.
7. **Write `_diagnose_agentic_lc()`** — same signature and return type as `_diagnose_agentic()`. Uses `create_agent`, calls `_extract_metrics()` post-run.
8. **Swap call sites** — replace `_diagnose_agentic(...)` with `_diagnose_agentic_lc(...)` in `run_once()` and `run_once_from_scenario()`. Remove `openai.OpenAI()` instantiation.
9. **Migrate `_judge_root_cause` and `_generate_scenario`** — switch to `ChatOpenAI` + `.yaml` prompts. Update message key parsing in `_judge_root_cause` to match LangChain serialisation format.
10. **Remove `openai` import** — confirm no direct `openai` SDK usage remains.
11. **Run full test suite** — `pytest tests/`. Run `run_once_from_scenario()` against a known fixture and assert result schema is unchanged.

---

## Design Decisions

| Decision | Reason |
|---|---|
| `create_agent` from `langchain.agents` | Current recommended API per project LangChain skill; more ergonomic than `create_react_agent` for tool-calling models |
| Store prompts in `tracelog/eval/prompts/` | Runtime resources must be co-located with code for `importlib.resources` to resolve them regardless of working directory |
| Pydantic validation on YAML load | Catches malformed templates at startup rather than at invocation time; cost is negligible |
| Keep `_tool_*` implementations unchanged | Limits diff surface; existing unit tests remain valid |
| Assert `usage_metadata is not None` | Non-streaming gpt-4o always populates usage; a missing value signals a bug, not a normal edge case |
| Allow extra LLM call on PASS | Avoids interrupt node complexity; token overhead is one call per successful run — acceptable |
| `messages_to_dict()` serialisation | LangChain-native, human-readable JSON; content is identical to current format, key names updated |
| `max_retries` in `BenchmarkV2Config` | Makes retry behaviour configurable without touching call sites; default 5 matches current manual retry count |
