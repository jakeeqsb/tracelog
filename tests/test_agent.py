"""Unit tests for TraceLogAgent, tool functions, and AgentAnswer schema.

All tests are fully mocked — no API calls, no Qdrant server required.
"""

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from tracelog.rag.agent import (
    AgentAnswer,
    IncidentSummary,
    TraceLogAgent,
    _build_tools,
)
from tracelog.rag.retriever import RetrievedChunk, RetrievedFix, TraceLogRetriever


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class InMemoryStore:
    def __init__(self):
        self._points: list[dict] = []

    def upsert(self, ids, vectors, payloads) -> None:
        for id_, vec, payload in zip(ids, vectors, payloads):
            self._points.append({"id": id_, "vector": vec, "payload": payload})

    def search(self, vector, top_k, filter=None) -> list[dict]:
        results = self._points
        if filter:
            results = [
                p for p in results
                if all(p["payload"].get(k) == v for k, v in filter.items()
                       if not isinstance(v, dict))
            ]
        return [{"score": 1.0, **p["payload"]} for p in results[:top_k]]

    def fetch_by_filter(self, filter: dict) -> list[dict]:
        return [
            p["payload"]
            for p in self._points
            if all(p["payload"].get(k) == v for k, v in filter.items()
                   if not isinstance(v, dict))
        ]

    def count(self) -> int:
        return len(self._points)


def _make_retriever(incident_points=None, postmortem_points=None):
    incident_store = InMemoryStore()
    postmortem_store = InMemoryStore()

    if incident_points:
        for p in incident_points:
            incident_store._points.append({"id": 1, "vector": [0.1] * 4, "payload": p})

    if postmortem_points:
        for p in postmortem_points:
            postmortem_store._points.append({"id": 2, "vector": [0.1] * 4, "payload": p})

    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.1] * 4
    mock_emb.embed_documents.return_value = [[0.1] * 4]

    retriever = TraceLogRetriever(
        store=incident_store,
        embeddings=mock_emb,
        postmortem_store=postmortem_store,
    )
    return retriever


def _make_chunk_payload(
    incident_id="ValueError_test.log::0",
    file_name="ValueError_test.log",
    chunk_index=0,
    error_type="ValueError",
    occurred_at="2026-04-18T10:00:00",
    status="open",
    has_error=True,
    chunk_text=">> fn\n  !! ValueError: bad input\n",
) -> dict:
    return {
        "incident_id": incident_id,
        "file_name": file_name,
        "chunk_index": chunk_index,
        "error_type": error_type,
        "occurred_at": occurred_at,
        "status": status,
        "has_error": has_error,
        "chunk_text": chunk_text,
        "embed_text": f"{error_type} raised in {file_name}",
        "trace_id": None,
        "span_id": None,
        "parent_span_id": None,
    }


def _make_postmortem_payload(
    incident_id="ValueError_test.log::0",
    root_cause="Bad input parsing",
    fix="Added type validation",
    resolved_at="2026-04-19T10:00:00",
) -> dict:
    return {
        "incident_id": incident_id,
        "root_cause": root_cause,
        "fix": fix,
        "resolved_at": resolved_at,
    }


# ---------------------------------------------------------------------------
# search_incidents tool
# ---------------------------------------------------------------------------

class TestSearchIncidentsTool:
    def _get_tool(self, retriever):
        tools = _build_tools(
            retriever=retriever,
            incident_store=retriever.store,
            postmortem_store=retriever.postmortem_store,
        )
        return next(t for t in tools if t.name == "search_incidents")

    def test_returns_list_of_dicts(self):
        payload = _make_chunk_payload()
        retriever = _make_retriever(incident_points=[payload])
        tool = self._get_tool(retriever)
        result = tool.invoke({"query": "bad input", "top_k": 5})
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "incident_id" in result[0]

    def test_date_from_passed_to_retriever(self):
        retriever = _make_retriever()
        captured = {}
        original = retriever.search

        def patched(*args, **kwargs):
            captured.update(kwargs)
            return original(*args, **kwargs)

        retriever.search = patched
        tool = self._get_tool(retriever)
        tool.invoke({"query": "test", "date_from": "2026-04-01"})
        assert captured.get("date_from") == "2026-04-01"

    def test_date_to_passed_to_retriever(self):
        retriever = _make_retriever()
        captured = {}
        original = retriever.search

        def patched(*args, **kwargs):
            captured.update(kwargs)
            return original(*args, **kwargs)

        retriever.search = patched
        tool = self._get_tool(retriever)
        tool.invoke({"query": "test", "date_to": "2026-04-18"})
        assert captured.get("date_to") == "2026-04-18"

    def test_error_type_filter_passed_to_retriever(self):
        retriever = _make_retriever()
        captured = {}
        original = retriever.search

        def patched(*args, **kwargs):
            captured.update(kwargs)
            return original(*args, **kwargs)

        retriever.search = patched
        tool = self._get_tool(retriever)
        tool.invoke({"query": "test", "error_type": "ConnectionError"})
        assert captured.get("filter_error_type") == "ConnectionError"


# ---------------------------------------------------------------------------
# search_fixes tool
# ---------------------------------------------------------------------------

class TestSearchFixesTool:
    def _get_tool(self, retriever):
        tools = _build_tools(
            retriever=retriever,
            incident_store=retriever.store,
            postmortem_store=retriever.postmortem_store,
        )
        return next(t for t in tools if t.name == "search_fixes")

    def test_returns_list_of_dicts(self):
        pm = _make_postmortem_payload()
        retriever = _make_retriever(postmortem_points=[pm])
        tool = self._get_tool(retriever)
        result = tool.invoke({"query": "input validation"})
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "root_cause" in result[0]
        assert "fix" in result[0]

    def test_top_k_respected(self):
        pms = [_make_postmortem_payload(incident_id=f"id{i}::0") for i in range(10)]
        retriever = _make_retriever(postmortem_points=pms)
        tool = self._get_tool(retriever)
        result = tool.invoke({"query": "input", "top_k": 3})
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# fetch_incident tool
# ---------------------------------------------------------------------------

class TestFetchIncidentTool:
    def _get_tool(self, retriever):
        tools = _build_tools(
            retriever=retriever,
            incident_store=retriever.store,
            postmortem_store=retriever.postmortem_store,
        )
        return next(t for t in tools if t.name == "fetch_incident")

    def test_single_chunk_incident(self):
        payload = _make_chunk_payload(
            incident_id="ValueError_test.log::0",
            file_name="ValueError_test.log",
            chunk_index=0,
        )
        retriever = _make_retriever(incident_points=[payload])
        tool = self._get_tool(retriever)
        result = tool.invoke({"incident_id": "ValueError_test.log::0"})
        assert result["file_name"] == "ValueError_test.log"
        assert result["error_type"] == "ValueError"
        assert "full_trace" in result
        assert result["postmortem"] is None

    def test_multi_chunk_full_trace_concatenated(self):
        chunks = [
            _make_chunk_payload(
                incident_id=f"ValueError_test.log::{i}",
                file_name="ValueError_test.log",
                chunk_index=i,
                chunk_text=f"chunk_{i}",
                has_error=(i == 1),
            )
            for i in range(3)
        ]
        retriever = _make_retriever(incident_points=chunks)
        tool = self._get_tool(retriever)
        result = tool.invoke({"incident_id": "ValueError_test.log::0"})
        assert "chunk_0" in result["full_trace"]
        assert "chunk_1" in result["full_trace"]
        assert "chunk_2" in result["full_trace"]
        # Verify sorted by chunk_index
        assert result["full_trace"].index("chunk_0") < result["full_trace"].index("chunk_1")

    def test_postmortem_linked_when_present(self):
        payload = _make_chunk_payload(
            incident_id="ValueError_test.log::0",
            file_name="ValueError_test.log",
            has_error=True,
        )
        pm = _make_postmortem_payload(incident_id="ValueError_test.log::0")
        retriever = _make_retriever(incident_points=[payload], postmortem_points=[pm])
        tool = self._get_tool(retriever)
        result = tool.invoke({"incident_id": "ValueError_test.log::0"})
        assert result["postmortem"] is not None
        assert result["postmortem"]["root_cause"] == "Bad input parsing"
        assert result["postmortem"]["fix"] == "Added type validation"

    def test_incident_not_found_returns_empty(self):
        retriever = _make_retriever()
        tool = self._get_tool(retriever)
        result = tool.invoke({"incident_id": "NonExistent_test.log::0"})
        assert result["full_trace"] == ""
        assert result["postmortem"] is None


# ---------------------------------------------------------------------------
# TraceLogAgent
# ---------------------------------------------------------------------------

class TestTraceLogAgent:
    def _make_agent(self, retriever=None):
        if retriever is None:
            retriever = _make_retriever()
        mock_llm = MagicMock(spec=BaseChatModel)
        # with_structured_output returns a structured-output-enabled LLM mock
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = AgentAnswer(
            answer="Found 1 incident.",
            incidents=[],
            confidence="high",
            sources_used=["search_incidents"],
        )
        mock_llm.with_structured_output.return_value = mock_structured

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [AIMessage(content="Summary: 1 DB timeout found.")]
        }

        with patch("tracelog.rag.agent.ChatOpenAI", return_value=mock_llm), \
             patch("tracelog.rag.agent.create_agent", return_value=mock_agent):
            agent = TraceLogAgent(retriever=retriever)
            agent._mock_agent = mock_agent
            agent._mock_structured = mock_structured
        return agent

    def test_agent_constructs_without_error(self):
        agent = self._make_agent()
        assert agent is not None

    def test_ask_returns_agent_answer(self):
        agent = self._make_agent()
        result = agent.ask("What DB incidents happened?")
        assert isinstance(result, AgentAnswer)
        assert result.answer == "Found 1 incident."
        assert result.confidence == "high"

    def test_ask_calls_agent_invoke(self):
        agent = self._make_agent()
        agent.ask("Any timeout errors?")
        agent._mock_agent.invoke.assert_called_once()

    def test_ask_calls_structured_output_invoke(self):
        agent = self._make_agent()
        agent.ask("Any timeout errors?")
        agent._mock_structured.invoke.assert_called_once()
        prompt_arg = agent._mock_structured.invoke.call_args[0][0]
        assert "AgentAnswer" in prompt_arg


# ---------------------------------------------------------------------------
# AgentAnswer / IncidentSummary schema
# ---------------------------------------------------------------------------

class TestAgentAnswerSchema:
    def test_valid_answer(self):
        ans = AgentAnswer(
            answer="2 incidents found.",
            incidents=[
                IncidentSummary(
                    incident_id="ValueError_test.log::0",
                    error_type="ValueError",
                    occurred_at="2026-04-18T10:00:00",
                    status="resolved",
                    summary="ValueError in parse_numeric.",
                    score=0.92,
                    error_trace=">> parse_numeric\n  !! ValueError: bad input",
                    trace_id="t123",
                    span_id="s456",
                    root_cause="Bad int conversion",
                    fix="Added type check",
                )
            ],
            confidence="high",
            sources_used=["search_incidents"],
        )
        assert len(ans.incidents) == 1
        assert ans.incidents[0].root_cause == "Bad int conversion"
        assert ans.incidents[0].score == 0.92
        assert ans.incidents[0].trace_id == "t123"

    def test_default_empty_incidents(self):
        ans = AgentAnswer(answer="None found.", confidence="low", sources_used=[])
        assert ans.incidents == []

    def test_incident_summary_optional_fields(self):
        inc = IncidentSummary(
            incident_id="id::0",
            error_type="RuntimeError",
            occurred_at="2026-04-18T10:00:00",
            status="open",
            summary="Something broke.",
            score=0.75,
        )
        assert inc.root_cause is None
        assert inc.fix is None
        assert inc.error_trace is None
        assert inc.trace_id is None
        assert inc.span_id is None

    def test_search_incidents_tool_exposes_trace_fields(self):
        payload = _make_chunk_payload(
            incident_id="ValueError_test.log::0",
            file_name="ValueError_test.log",
        )
        # Inject trace fields into payload
        payload["trace_id"] = "t_abc"
        payload["span_id"] = "s_def"
        retriever = _make_retriever(incident_points=[payload])
        tools = _build_tools(
            retriever=retriever,
            incident_store=retriever.store,
            postmortem_store=retriever.postmortem_store,
        )
        tool = next(t for t in tools if t.name == "search_incidents")
        result = tool.invoke({"query": "bad input"})
        assert len(result) >= 1
        assert result[0]["trace_id"] == "t_abc"
        assert result[0]["span_id"] == "s_def"
        assert "score" in result[0]
        assert "chunk_text" in result[0]
