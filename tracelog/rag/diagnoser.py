"""TraceLog RAG Diagnoser.

Combines retrieved similar error chunks with the current error chunk
and prompts an LLM to produce a structured root cause diagnosis.

Usage:
    diagnoser = TraceLogDiagnoser()
    result = diagnoser.diagnose(
        current_chunk=">> process_single_item !! Session validation failed",
        similar_chunks=retriever.search(current_chunk, top_k=3),
    )
    print(result["root_cause_function"])
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from openai import OpenAI

if TYPE_CHECKING:
    from tracelog.rag.retriever import RetrievedChunk

load_dotenv()

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "diagnostic_prompt.txt"

MODEL = "gpt-4o-mini"


class TraceLogDiagnoser:
    """Generates LLM-powered root cause diagnosis from RAG context.

    Constructs a prompt combining:
      1. Past similar error chunks (retrieved via RAG)
      2. The current failing error chunk

    Uses the versioned v2 prompt (includes Trace-DSL format guide).

    Attributes:
        openai: OpenAI client.
        prompt_template: Diagnostic prompt text loaded from file.
        model: LLM model name.

    Example:
        diagnoser = TraceLogDiagnoser()
        result = diagnoser.diagnose(current_chunk, similar_chunks)
        print(result["root_cause_function"], result["confidence"])
    """

    def __init__(self, model: str = MODEL):
        """Initializes the diagnoser with LLM config.

        Args:
            model: OpenAI model name to use for diagnosis.
        """
        self.openai = OpenAI()
        self.model = model
        self.prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def _build_context(
        self,
        current_chunk: str,
        similar_chunks: "list[RetrievedChunk]",
    ) -> str:
        """Builds the full log context from current + similar chunks.

        Prepends retrieved chunks as 'Past similar incidents' for
        the LLM to reference when diagnosing the current error.

        Args:
            current_chunk: The Trace-DSL chunk containing the current error.
            similar_chunks: Retrieved chunks from past similar incidents.

        Returns:
            Formatted log content string for injection into the prompt.
        """
        sections = []

        if similar_chunks:
            sections.append("=== PAST SIMILAR INCIDENTS (retrieved via RAG) ===")
            for i, chunk in enumerate(similar_chunks, 1):
                sections.append(
                    f"\n--- Past Incident #{i} "
                    f"(type={chunk.error_type}, score={chunk.score:.3f}) ---"
                )
                sections.append(chunk.chunk_text)

        sections.append("\n=== CURRENT ERROR (to diagnose) ===")
        sections.append(current_chunk)

        return "\n".join(sections)

    def diagnose(
        self,
        current_chunk: str,
        similar_chunks: "list[RetrievedChunk]",
    ) -> dict:
        """Runs LLM diagnosis on the current error with RAG context.

        Args:
            current_chunk: The Trace-DSL error chunk to diagnose.
            similar_chunks: Related past error chunks from retriever.

        Returns:
            Parsed JSON dict with keys:
                root_cause_function, root_cause_type, error_surface,
                fix_hint, confidence, actionable.
            On parse failure, returns {"raw_response": ..., "parse_error": True}.
        """
        log_content = self._build_context(current_chunk, similar_chunks)
        prompt = self.prompt_template.replace("{log_content}", log_content)

        response = self.openai.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM response was not valid JSON: %s", raw[:200])
            result = {"raw_response": raw, "parse_error": True}

        result["_meta"] = {
            "model": self.model,
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "similar_chunks_used": len(similar_chunks),
        }
        logger.info(
            "Diagnosis complete: confidence=%s, tokens=%d",
            result.get("confidence", "?"),
            response.usage.prompt_tokens,
        )
        return result
