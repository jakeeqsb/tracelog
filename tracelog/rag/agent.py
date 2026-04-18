"""TraceLog RAG Investigation Agent.

A conversational agent that accepts natural-language questions about past
incidents and synthesizes answers from the vector store.

Usage:
    from tracelog.rag import TraceLogAgent, TraceLogRetriever
    from tracelog.rag.stores.qdrant import QdrantStore

    incident_store = QdrantStore(collection_name="tracelog_incidents")
    postmortem_store = QdrantStore(collection_name="tracelog_postmortems")
    retriever = TraceLogRetriever(store=incident_store, postmortem_store=postmortem_store)

    agent = TraceLogAgent(retriever=retriever)
    answer = agent.ask("What DB connection incidents happened last week?")
    print(answer.answer)
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from tracelog.rag.retriever import TraceLogRetriever
from tracelog.rag.store import VectorStore

load_dotenv()

AGENT_MODEL = os.getenv("TRACELOG_AGENT_MODEL", "gpt-4o")
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_agent_prompt() -> str:
    """Load agent_system.yaml and return the template string."""
    path = _PROMPTS_DIR / "agent_system.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw["template"]


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class IncidentSummary(BaseModel):
    incident_id: str
    error_type: str
    occurred_at: str
    status: str
    summary: str = Field(description="1–2 sentence summary of the incident")
    score: float = Field(description="Vector similarity score (0.0–1.0)")
    error_trace: Optional[str] = Field(
        default=None,
        description="Key lines from the Trace-DSL around the '!!' error marker (3–5 lines max)",
    )
    trace_id: Optional[str] = Field(default=None, description="Distributed trace ID, if present")
    span_id: Optional[str] = Field(default=None, description="Span ID, if present")
    root_cause: Optional[str] = None
    fix: Optional[str] = None


class AgentAnswer(BaseModel):
    answer: str = Field(description="Natural-language answer to the user's question")
    incidents: list[IncidentSummary] = Field(
        default_factory=list,
        description="List of incidents referenced in the answer",
    )
    confidence: str = Field(description="Answer confidence: 'high' | 'medium' | 'low'")
    sources_used: list[str] = Field(
        default_factory=list,
        description="Names of tools called during retrieval",
    )


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def _build_tools(
    retriever: TraceLogRetriever,
    incident_store: VectorStore,
    postmortem_store: VectorStore,
) -> list:
    """Build LangChain tool list bound to the given retriever and stores."""

    @tool
    def search_incidents(
        query: str,
        top_k: int = 5,
        error_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """Search for incident chunks semantically similar to the natural-language query.
        Can be filtered by error_type and/or date range.
        Returns linked POSTMORTEM root_cause and fix when available.

        Args:
            query: Natural-language search query (e.g. "DB connection timeout")
            top_k: Maximum number of results to return (default 5)
            error_type: Error type to filter by (e.g. "ConnectionError"). None = search all.
            date_from: Start of date range in ISO-8601 format (e.g. "2026-04-01"). None = no lower bound.
            date_to: End of date range in ISO-8601 format (e.g. "2026-04-18"). None = no upper bound.
        """
        chunks = retriever.search(
            query_text=query,
            top_k=top_k,
            filter_error_type=error_type,
            only_error_chunks=False,
            date_from=date_from,
            date_to=date_to,
        )
        return [
            {
                "incident_id": c.incident_id,
                "error_type": c.error_type,
                "file_name": c.file_name,
                "occurred_at": c.occurred_at,
                "status": c.status,
                "score": c.score,
                "chunk_text": c.chunk_text,
                "trace_id": c.trace_id,
                "span_id": c.span_id,
                "root_cause": c.root_cause,
                "fix": c.fix,
            }
            for c in chunks
        ]

    @tool
    def search_fixes(query: str, top_k: int = 5) -> list[dict]:
        """Search past fixes (postmortems) directly using a natural-language query.
        Searches the root_cause + fix vector space, bypassing incident search.

        Args:
            query: Natural-language query about a fix (e.g. "card number validation failure fix")
            top_k: Maximum number of results to return (default 5)
        """
        fixes = retriever.search_fixes(query_text=query, top_k=top_k)
        return [
            {
                "incident_id": f.incident_id,
                "root_cause": f.root_cause,
                "fix": f.fix,
                "resolved_at": f.resolved_at,
                "score": f.score,
            }
            for f in fixes
        ]

    @tool
    def fetch_incident(incident_id: str) -> dict:
        """Fetch the full data for a specific incident by incident_id.
        Combines all chunks sharing the same file_name to return the complete
        execution context. Also returns the linked POSTMORTEM if available.

        Args:
            incident_id: Incident ID to fetch (e.g. "ConnectionError_warehouse.log::0")
        """
        # Extract file_name from incident_id ("file_name::chunk_index")
        file_name = incident_id.rsplit("::", 1)[0]

        all_chunks = incident_store.fetch_by_filter({"file_name": file_name})
        all_chunks.sort(key=lambda c: c.get("chunk_index", 0))

        full_trace = "\n".join(c.get("chunk_text", "") for c in all_chunks)

        # Use the error chunk (has_error=True) as the primary chunk for postmortem lookup
        error_chunk = next(
            (c for c in all_chunks if c.get("has_error")), all_chunks[0] if all_chunks else {}
        )
        postmortem_list = postmortem_store.fetch_by_filter(
            {"incident_id": error_chunk.get("incident_id", incident_id)}
        ) if error_chunk else []

        return {
            "file_name": file_name,
            "error_type": error_chunk.get("error_type"),
            "occurred_at": error_chunk.get("occurred_at"),
            "status": error_chunk.get("status"),
            "chunks": all_chunks,
            "full_trace": full_trace,
            "postmortem": postmortem_list[0] if postmortem_list else None,
            "span_id": error_chunk.get("span_id"),
            "parent_span_id": error_chunk.get("parent_span_id"),
            "trace_id": error_chunk.get("trace_id"),
        }

    return [search_incidents, search_fixes, fetch_incident]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class TraceLogAgent:
    """Conversational incident investigation agent backed by the TraceLog RAG pipeline.

    Accepts natural-language questions, uses LangChain tools to retrieve
    relevant incidents and postmortems from the vector store, and returns a
    structured ``AgentAnswer``.

    Args:
        retriever: ``TraceLogRetriever`` instance connected to the incident store.

    Example:
        agent = TraceLogAgent(retriever=retriever)
        answer = agent.ask("What DB connection incidents happened last week?")
        print(answer.answer)
        for inc in answer.incidents:
            print(inc.incident_id, inc.status)
    """

    def __init__(self, retriever: TraceLogRetriever) -> None:
        self.llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
        tools = _build_tools(
            retriever=retriever,
            incident_store=retriever.store,
            postmortem_store=retriever.postmortem_store,
        )
        system_prompt = _load_agent_prompt()
        self.agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
        )

    def ask(self, question: str) -> AgentAnswer:
        """Ask a natural-language question about past incidents.

        Runs the agent loop (tool calls + LLM reasoning), then synthesizes
        the final answer into a structured ``AgentAnswer``.

        Args:
            question: Natural-language question, e.g. "What DB lock incidents happened
                last week?" or "상위 5개 타임아웃 오류 보여줘".

        Returns:
            ``AgentAnswer`` with answer text, referenced incidents, confidence, and
            tool sources used.
        """
        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"recursion_limit": 30},
        )
        last_message = result["messages"][-1].content
        structured_llm = self.llm.with_structured_output(AgentAnswer)
        return structured_llm.invoke(
            "Based on the following investigation result, respond using the AgentAnswer schema.\n\n"
            f"{last_message}"
        )
