"""Unit tests for the LangChain migration of benchmark_v2.

Tests cover:
- _load_prompt  (Step 3): YAML loading, Pydantic validation, caching
- _extract_metrics (Step 6): pure function over synthetic message list
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tracelog.eval.benchmark_v2 import _extract_metrics, _load_prompt


# ---------------------------------------------------------------------------
# _load_prompt tests
# ---------------------------------------------------------------------------
class TestLoadPrompt:
    def test_loads_agent_system(self):
        template = _load_prompt("agent_system")
        assert isinstance(template, str)
        assert len(template) > 0
        # Template must contain the placeholder variables
        assert "{scenario_path}" in template
        assert "{program_description}" in template

    def test_loads_bug_writer(self):
        template = _load_prompt("bug_writer")
        assert isinstance(template, str)
        assert "Scenario" in template  # class name from prompt content

    def test_loads_judge(self):
        template = _load_prompt("judge")
        assert isinstance(template, str)
        assert "{truth_json}" in template
        assert "{turns_json}" in template

    def test_returns_string_not_dict(self):
        """Should return the template string, not the full YAML dict."""
        result = _load_prompt("agent_system")
        assert not isinstance(result, dict)

    def test_caching(self):
        """Calling twice returns the same object (cached)."""
        a = _load_prompt("judge")
        b = _load_prompt("judge")
        assert a is b

    def test_missing_prompt_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_prompt("nonexistent_prompt_xyz")


# ---------------------------------------------------------------------------
# _extract_metrics tests
# ---------------------------------------------------------------------------
def _make_ai_message(tool_call_names: list[str] | None = None, *, input_tokens: int = 10, output_tokens: int = 5) -> AIMessage:
    """Create a synthetic AIMessage with usage_metadata and optional tool calls."""
    tool_calls = []
    if tool_call_names:
        for name in tool_call_names:
            tool_calls.append({"name": name, "args": {}, "id": f"call_{name}"})
    msg = AIMessage(
        content="some response",
        tool_calls=tool_calls,
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
    )
    return msg


def _make_tool_message(tool_call_id: str = "call_x", content: str = "result") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id)


class TestExtractMetrics:
    def test_empty_messages(self):
        metrics = _extract_metrics([])
        assert metrics["tool_call_count"] == 0
        assert metrics["fix_attempts"] == 0
        assert metrics["iterations"] == 0
        assert metrics["usage"]["total_tokens"] == 0

    def test_counts_ai_messages_as_iterations(self):
        messages = [
            _make_ai_message(),
            _make_ai_message(),
        ]
        metrics = _extract_metrics(messages)
        assert metrics["iterations"] == 2

    def test_counts_tool_messages(self):
        messages = [
            _make_ai_message(["read_file_tool"]),
            _make_tool_message("call_read_file_tool"),
            _make_ai_message(["search_code_tool"]),
            _make_tool_message("call_search_code_tool"),
        ]
        metrics = _extract_metrics(messages)
        assert metrics["tool_call_count"] == 2

    def test_counts_fix_attempts_from_write_file_tool_calls(self):
        messages = [
            _make_ai_message(["read_file_tool"]),
            _make_tool_message("call_read_file_tool"),
            _make_ai_message(["write_file_tool"]),
            _make_tool_message("call_write_file_tool", "FAIL: still raises"),
            _make_ai_message(["write_file_tool"]),
            _make_tool_message("call_write_file_tool_2", "PASS: Code runs without exception."),
        ]
        metrics = _extract_metrics(messages)
        assert metrics["fix_attempts"] == 2

    def test_token_summation(self):
        messages = [
            _make_ai_message(input_tokens=100, output_tokens=50),
            _make_tool_message(),
            _make_ai_message(input_tokens=200, output_tokens=75),
        ]
        metrics = _extract_metrics(messages)
        assert metrics["usage"]["input_tokens"] == 300
        assert metrics["usage"]["output_tokens"] == 125
        assert metrics["usage"]["total_tokens"] == 425

    def test_human_messages_ignored(self):
        messages = [
            HumanMessage(content="hello"),
            _make_ai_message(input_tokens=10, output_tokens=5),
        ]
        metrics = _extract_metrics(messages)
        assert metrics["iterations"] == 1
        assert metrics["tool_call_count"] == 0

    def test_missing_usage_metadata_raises(self):
        msg = AIMessage(content="no usage")
        # usage_metadata is None by default when not provided
        with pytest.raises(AssertionError):
            _extract_metrics([msg])
