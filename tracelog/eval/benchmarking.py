"""Notebook-oriented benchmark runner for the TraceLog evaluation strategy."""

from __future__ import annotations

import json
import inspect
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from tracelog.chunking import TraceTreeSplitter
from tracelog.ingestion.aggregator import aggregate_traces

from .scenarios import IncidentSpec, incident_specs, run_incident
from . import scenarios as scenario_module

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "langchain_text_splitters is required for the benchmark notebook"
    ) from exc


EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DIAGNOSER_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
TRACE_COLLECTION = "benchmark_trace_chunks"
STANDARD_COLLECTION = "benchmark_standard_chunks"
LOG_ONLY_CONDITIONS = ("standard", "tracelog")
CODE_AWARE_CONDITIONS = ("standard_with_code", "tracelog_with_code")
ALL_CONDITIONS = LOG_ONLY_CONDITIONS + CODE_AWARE_CONDITIONS
CONDITION_LABELS = {
    "standard": "Standard Log + RAG",
    "tracelog": "TraceLog + RAG",
    "standard_with_code": "Standard Log + RAG + Code",
    "tracelog_with_code": "TraceLog + RAG + Code",
}


@dataclass(frozen=True)
class BenchmarkConfig:
    base_dir: Path = Path("docs/eval/benchmark")
    top_k: int = 3
    diagnoser_model: str = DIAGNOSER_MODEL
    judge_model: str = JUDGE_MODEL
    overwrite: bool = True


def run_benchmark(config: BenchmarkConfig | None = None) -> dict[str, Any]:
    """Generates dataset artifacts and runs the notebook-facing benchmark."""

    config = config or BenchmarkConfig()
    load_dotenv(Path(".env"))
    _ensure_dirs(config.base_dir)

    manifest = _generate_dataset(config)
    indexed = _build_indices(config, manifest)
    evaluated = _evaluate_queries(config, manifest, indexed)
    results = _summarize_results(config, manifest, evaluated)
    _write_results(config.base_dir, results)
    return results


def load_results(base_dir: Path | str = Path("docs/eval/benchmark")) -> dict[str, Any]:
    """Loads the most recent benchmark results."""

    path = Path(base_dir) / "results" / "benchmark_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "incident_id": item["incident_id"],
            "family": item["scenario_family"],
            "split": item["split"],
            "root_cause_function": item["root_cause_function"],
            "surface_error_function": item["surface_error_function"],
            "error_type": item["error_type"],
        }
        for item in results["manifest"]
    ]


def dataset_status_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in results["manifest"]:
        rows.append(
            {
                "incident_id": item["incident_id"],
                "standard_log": Path(item["standard_log_path"]).exists(),
                "tracelog_dump": Path(item["tracelog_dump_path"]).exists(),
                "aggregated_trace": Path(item["aggregated_trace_path"]).exists(),
                "truth": Path(item["truth_path"]).exists(),
            }
        )
    return rows


def split_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "split": split_name,
            "count": len(items),
            "families": ", ".join(sorted({item["scenario_family"] for item in items})),
        }
        for split_name, items in (
            ("historical", [m for m in results["manifest"] if m["split"] == "historical"]),
            ("query", [m for m in results["manifest"] if m["split"] == "query"]),
        )
    ]


def retrieval_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in ("standard", "tracelog"):
        metrics = results["retrieval"][condition]
        row = {"condition": CONDITION_LABELS.get(condition, condition)}
        row.update(metrics)
        rows.append(row)
    return rows


def diagnosis_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in (
        "standard_with_code",
        "tracelog_with_code",
        "standard",
        "tracelog",
    ):
        metrics = results["diagnosis"][condition]
        row = {"condition": CONDITION_LABELS.get(condition, condition)}
        row.update(metrics)
        rows.append(row)
    return rows


def operational_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in (
        "standard_with_code",
        "tracelog_with_code",
        "standard",
        "tracelog",
    ):
        metrics = results["operational"][condition]
        row = {"condition": CONDITION_LABELS.get(condition, condition)}
        row.update(metrics)
        rows.append(row)
    return rows


def failure_case_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in results["per_query"]:
        for condition in ALL_CONDITIONS:
            judged = entry[condition]["judge"]
            if not judged["root_cause_function_correct"]:
                rows.append(
                    {
                        "incident_id": entry["incident_id"],
                        "condition": CONDITION_LABELS.get(condition, condition),
                        "predicted_root_cause": entry[condition]["diagnosis"].get(
                            "root_cause_function", ""
                        ),
                        "expected_root_cause": entry["truth"]["root_cause_function"],
                        "judge_reason": judged["reason"],
                    }
                )
    return rows


def final_verdict_markdown(results: dict[str, Any]) -> str:
    verdict = results["final_verdict"]
    lines = [
        f"## Final Verdict",
        "",
        "### Primary Benchmark",
        f"- Primary condition: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`",
        f"- Primary benchmark pass: `{verdict['primary_passes_exit_criteria']}`",
        f"- TraceLog root cause accuracy delta: `{verdict['primary_root_cause_accuracy_delta']:.3f}`",
        f"- TraceLog surface accuracy delta: `{verdict['primary_surface_accuracy_delta']:.3f}`",
        f"- Primary improved families: `{', '.join(verdict['primary_improved_families']) or 'none'}`",
        "",
        "### Ablation",
        f"- Ablation condition: `Standard Log + RAG` vs `TraceLog + RAG`",
        f"- Logs-only ablation pass: `{verdict['ablation_passes_exit_criteria']}`",
        f"- TraceLog root cause accuracy delta: `{verdict['ablation_root_cause_accuracy_delta']:.3f}`",
        f"- TraceLog SameRootCauseHit@3 delta: `{verdict['ablation_same_root_cause_hit_at_3_delta']:.3f}`",
        f"- Ablation improved families: `{', '.join(verdict['ablation_improved_families']) or 'none'}`",
        "",
        verdict["summary"],
        "",
        "This notebook now treats the code-aware path as the primary product benchmark.",
        "The logs-only comparison remains as an ablation to isolate formatting effects.",
    ]
    return "\n".join(lines)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No rows_"

    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(lines)


def _ensure_dirs(base_dir: Path) -> None:
    for relative in (
        "datasets/historical",
        "datasets/query",
        "results",
        "truth",
        "notebooks",
        "prompts",
    ):
        (base_dir / relative).mkdir(parents=True, exist_ok=True)


def _generate_dataset(config: BenchmarkConfig) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    scenario_path = Path(__file__).resolve().parent / "scenarios.py"

    for spec in incident_specs():
        incident_dir = config.base_dir / "datasets" / spec.split / spec.incident_id
        incident_dir.mkdir(parents=True, exist_ok=True)

        standard_log_path = incident_dir / "standard.log"
        tracelog_dump_path = incident_dir / "tracelog_dump.jsonl"
        aggregated_trace_path = incident_dir / "aggregated_trace.log"
        truth_path = config.base_dir / "truth" / f"{spec.incident_id}.json"

        if config.overwrite or not standard_log_path.exists():
            run_incident("standard", spec, standard_log_path)
        if config.overwrite or not tracelog_dump_path.exists():
            run_incident("tracelog", spec, tracelog_dump_path)

        truth_path.write_text(
            json.dumps(spec.truth_payload(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        aggregated = _aggregate_trace_file(tracelog_dump_path)
        aggregated_trace_path.write_text(aggregated, encoding="utf-8")

        manifest.append(
            {
                "scenario_id": spec.incident_id,
                "incident_id": spec.incident_id,
                "scenario_family": spec.scenario_family,
                "variant_id": spec.variant_id,
                "difficulty": spec.difficulty,
                "root_cause_id": spec.root_cause_id,
                "root_cause_function": spec.root_cause_function,
                "surface_error_function": spec.surface_error_function,
                "error_type": spec.error_type,
                "code_path": str(scenario_path),
                "truth_path": str(truth_path.resolve()),
                "standard_log_path": str(standard_log_path.resolve()),
                "tracelog_dump_path": str(tracelog_dump_path.resolve()),
                "aggregated_trace_path": str(aggregated_trace_path.resolve()),
                "query_split": spec.split == "query",
                "historical_split": spec.split == "historical",
                "split": spec.split,
            }
        )

    manifest_path = config.base_dir / "datasets" / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def _aggregate_trace_file(path: Path) -> str:
    dumps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            dumps.append(json.loads(line))
    aggregated = aggregate_traces(dumps)
    return "\n\n".join(text for _, text in sorted(aggregated.items()))


@dataclass
class IndexedCorpora:
    manifest_by_id: dict[str, dict[str, Any]]
    standard_client: QdrantClient
    trace_client: QdrantClient
    embedder: SentenceTransformer
    standard_chunker: RecursiveCharacterTextSplitter
    trace_chunker: TraceTreeSplitter
    standard_query_chunks: dict[str, str]
    trace_query_chunks: dict[str, str]
    standard_current_texts: dict[str, str]
    trace_current_texts: dict[str, str]
    code_contexts: dict[str, str]


def _build_indices(config: BenchmarkConfig, manifest: list[dict[str, Any]]) -> IndexedCorpora:
    embedder = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    standard_client = QdrantClient(":memory:")
    trace_client = QdrantClient(":memory:")

    for client, collection_name in (
        (standard_client, STANDARD_COLLECTION),
        (trace_client, TRACE_COLLECTION),
    ):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

    standard_chunker = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=150,
    )
    trace_chunker = TraceTreeSplitter(chunk_size=1200, chunk_overlap=100)

    standard_query_chunks: dict[str, str] = {}
    trace_query_chunks: dict[str, str] = {}
    standard_current_texts: dict[str, str] = {}
    trace_current_texts: dict[str, str] = {}
    code_contexts: dict[str, str] = {}

    manifest_by_id = {item["incident_id"]: item for item in manifest}
    historical = [item for item in manifest if item["split"] == "historical"]
    query = [item for item in manifest if item["split"] == "query"]

    standard_points: list[PointStruct] = []
    trace_points: list[PointStruct] = []
    point_id = 1

    for item in historical:
        standard_text = Path(item["standard_log_path"]).read_text(encoding="utf-8")
        standard_chunks = standard_chunker.split_text(standard_text)
        standard_vectors = embedder.encode(standard_chunks)
        for chunk_index, (chunk_text, vector) in enumerate(
            zip(standard_chunks, standard_vectors, strict=True)
        ):
            standard_points.append(
                PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload={
                        "incident_id": item["incident_id"],
                        "scenario_family": item["scenario_family"],
                        "chunk_index": chunk_index,
                        "chunk_text": chunk_text,
                        "error_type": item["error_type"],
                    },
                )
            )
            point_id += 1

        trace_text = Path(item["aggregated_trace_path"]).read_text(encoding="utf-8")
        trace_chunks = trace_chunker.split_text(trace_text)
        trace_vectors = embedder.encode(trace_chunks)
        for chunk_index, (chunk_text, vector) in enumerate(
            zip(trace_chunks, trace_vectors, strict=True)
        ):
            trace_points.append(
                PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload={
                        "incident_id": item["incident_id"],
                        "scenario_family": item["scenario_family"],
                        "chunk_index": chunk_index,
                        "chunk_text": chunk_text,
                        "error_type": item["error_type"],
                    },
                )
            )
            point_id += 1

    standard_client.upsert(collection_name=STANDARD_COLLECTION, points=standard_points)
    trace_client.upsert(collection_name=TRACE_COLLECTION, points=trace_points)

    for item in query:
        standard_text = Path(item["standard_log_path"]).read_text(encoding="utf-8")
        standard_current_texts[item["incident_id"]] = standard_text
        standard_query_chunks[item["incident_id"]] = _select_query_chunk(
            standard_chunker.split_text(standard_text),
            marker="ERROR",
            fallback_text=standard_text,
        )

        trace_text = Path(item["aggregated_trace_path"]).read_text(encoding="utf-8")
        trace_current_texts[item["incident_id"]] = trace_text
        trace_query_chunks[item["incident_id"]] = _select_query_chunk(
            trace_chunker.split_text(trace_text),
            marker="!!",
            fallback_text=trace_text,
        )
        code_contexts[item["incident_id"]] = _code_context_for_family(
            item["scenario_family"]
        )

    return IndexedCorpora(
        manifest_by_id=manifest_by_id,
        standard_client=standard_client,
        trace_client=trace_client,
        embedder=embedder,
        standard_chunker=standard_chunker,
        trace_chunker=trace_chunker,
        standard_query_chunks=standard_query_chunks,
        trace_query_chunks=trace_query_chunks,
        standard_current_texts=standard_current_texts,
        trace_current_texts=trace_current_texts,
        code_contexts=code_contexts,
    )


def _select_query_chunk(chunks: list[str], marker: str, fallback_text: str) -> str:
    for chunk in reversed(chunks):
        if marker in chunk:
            return chunk
    return chunks[-1] if chunks else fallback_text[-1200:]


def _evaluate_queries(
    config: BenchmarkConfig,
    manifest: list[dict[str, Any]],
    indexed: IndexedCorpora,
) -> list[dict[str, Any]]:
    client = OpenAI()
    queries = [item for item in manifest if item["split"] == "query"]
    evaluated: list[dict[str, Any]] = []

    diagnoser_prompt = _diagnoser_prompt(config.base_dir)
    diagnoser_prompt_with_code = _diagnoser_prompt_with_code(config.base_dir)
    judge_prompt = _judge_prompt(config.base_dir)

    for item in queries:
        truth = json.loads(Path(item["truth_path"]).read_text(encoding="utf-8"))
        standard_result = _run_condition(
            client=client,
            truth=truth,
            retrieval_query_text=indexed.standard_query_chunks[item["incident_id"]],
            diagnosis_text=indexed.standard_current_texts[item["incident_id"]],
            code_context=None,
            collection_name=STANDARD_COLLECTION,
            qdrant_client=indexed.standard_client,
            embedder=indexed.embedder,
            prompt=diagnoser_prompt,
            judge_prompt=judge_prompt,
            manifest_by_id=indexed.manifest_by_id,
            top_k=config.top_k,
            diagnoser_model=config.diagnoser_model,
            judge_model=config.judge_model,
        )
        trace_result = _run_condition(
            client=client,
            truth=truth,
            retrieval_query_text=indexed.trace_query_chunks[item["incident_id"]],
            diagnosis_text=indexed.trace_current_texts[item["incident_id"]],
            code_context=None,
            collection_name=TRACE_COLLECTION,
            qdrant_client=indexed.trace_client,
            embedder=indexed.embedder,
            prompt=diagnoser_prompt,
            judge_prompt=judge_prompt,
            manifest_by_id=indexed.manifest_by_id,
            top_k=config.top_k,
            diagnoser_model=config.diagnoser_model,
            judge_model=config.judge_model,
        )
        standard_with_code_result = _run_condition(
            client=client,
            truth=truth,
            retrieval_query_text=indexed.standard_query_chunks[item["incident_id"]],
            diagnosis_text=indexed.standard_current_texts[item["incident_id"]],
            code_context=indexed.code_contexts[item["incident_id"]],
            collection_name=STANDARD_COLLECTION,
            qdrant_client=indexed.standard_client,
            embedder=indexed.embedder,
            prompt=diagnoser_prompt_with_code,
            judge_prompt=judge_prompt,
            manifest_by_id=indexed.manifest_by_id,
            top_k=config.top_k,
            diagnoser_model=config.diagnoser_model,
            judge_model=config.judge_model,
        )
        trace_with_code_result = _run_condition(
            client=client,
            truth=truth,
            retrieval_query_text=indexed.trace_query_chunks[item["incident_id"]],
            diagnosis_text=indexed.trace_current_texts[item["incident_id"]],
            code_context=indexed.code_contexts[item["incident_id"]],
            collection_name=TRACE_COLLECTION,
            qdrant_client=indexed.trace_client,
            embedder=indexed.embedder,
            prompt=diagnoser_prompt_with_code,
            judge_prompt=judge_prompt,
            manifest_by_id=indexed.manifest_by_id,
            top_k=config.top_k,
            diagnoser_model=config.diagnoser_model,
            judge_model=config.judge_model,
        )
        evaluated.append(
            {
                "incident_id": item["incident_id"],
                "scenario_family": item["scenario_family"],
                "truth": truth,
                "standard": standard_result,
                "tracelog": trace_result,
                "standard_with_code": standard_with_code_result,
                "tracelog_with_code": trace_with_code_result,
            }
        )

    return evaluated


def _run_condition(
    *,
    client: OpenAI,
    truth: dict[str, Any],
    retrieval_query_text: str,
    diagnosis_text: str,
    code_context: str | None,
    collection_name: str,
    qdrant_client: QdrantClient,
    embedder: SentenceTransformer,
    prompt: str,
    judge_prompt: str,
    manifest_by_id: dict[str, dict[str, Any]],
    top_k: int,
    diagnoser_model: str,
    judge_model: str,
) -> dict[str, Any]:
    retrieval_started = time.perf_counter()
    hits = _retrieve(
        qdrant_client=qdrant_client,
        collection_name=collection_name,
        query_text=retrieval_query_text,
        embedder=embedder,
        top_k=top_k,
    )
    retrieval_latency = time.perf_counter() - retrieval_started

    diagnosis_started = time.perf_counter()
    diagnosis, usage = _diagnose(
        client=client,
        model=diagnoser_model,
        prompt_template=prompt,
        current_text=diagnosis_text,
        hits=hits,
        code_context=code_context,
    )
    diagnosis_latency = time.perf_counter() - diagnosis_started
    judge = _judge(
        client=client,
        model=judge_model,
        prompt_template=judge_prompt,
        truth=truth,
        diagnosis=diagnosis,
    )

    ranked_incidents = []
    seen_incidents: set[str] = set()
    for hit in hits:
        incident_id = hit["incident_id"]
        if incident_id not in seen_incidents:
            seen_incidents.add(incident_id)
            ranked_incidents.append(
                {
                    "incident_id": incident_id,
                    "scenario_family": manifest_by_id[incident_id]["scenario_family"],
                    "score": round(hit["score"], 4),
                }
            )

    return {
        "retrieval": {
            "hits": hits,
            "ranked_incidents": ranked_incidents,
            "retrieval_latency": retrieval_latency,
        },
        "diagnosis": diagnosis,
        "judge": judge,
        "usage": usage,
        "diagnosis_latency": diagnosis_latency,
        "time_to_verdict": retrieval_latency + diagnosis_latency,
    }


def _retrieve(
    *,
    qdrant_client: QdrantClient,
    collection_name: str,
    query_text: str,
    embedder: SentenceTransformer,
    top_k: int,
) -> list[dict[str, Any]]:
    query_vector = embedder.encode([query_text])[0].tolist()
    points = qdrant_client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=top_k * 3,
        with_payload=True,
        query_filter=Filter(must=[]),
    ).points

    hits = []
    for point in points:
        hits.append(
            {
                "incident_id": point.payload["incident_id"],
                "chunk_text": point.payload["chunk_text"],
                "chunk_index": point.payload["chunk_index"],
                "score": float(point.score),
                "error_type": point.payload["error_type"],
            }
        )
    return hits


def _diagnose(
    *,
    client: OpenAI,
    model: str,
    prompt_template: str,
    current_text: str,
    hits: list[dict[str, Any]],
    code_context: str | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    context_blocks = []
    unique_hits = []
    seen = set()
    for hit in hits:
        incident_id = hit["incident_id"]
        if incident_id in seen:
            continue
        seen.add(incident_id)
        unique_hits.append(hit)
        if len(unique_hits) == 3:
            break

    for index, hit in enumerate(unique_hits, 1):
        context_blocks.append(
            f"### Retrieved Incident {index}\nscore={hit['score']:.4f}\n{hit['chunk_text']}"
        )
    prompt = prompt_template.format(
        retrieved_context="\n\n".join(context_blocks),
        current_log=current_text,
        source_code=code_context or "No source code provided for this condition.",
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }
    return parsed, usage


def _judge(
    *,
    client: OpenAI,
    model: str,
    prompt_template: str,
    truth: dict[str, Any],
    diagnosis: dict[str, Any],
) -> dict[str, Any]:
    prompt = prompt_template.format(
        truth=json.dumps(truth, ensure_ascii=False, indent=2),
        diagnosis=json.dumps(diagnosis, ensure_ascii=False, indent=2),
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _summarize_results(
    config: BenchmarkConfig,
    manifest: list[dict[str, Any]],
    evaluated: list[dict[str, Any]],
) -> dict[str, Any]:
    retrieval = {
        "standard": _compute_retrieval_metrics(manifest, evaluated, "standard"),
        "tracelog": _compute_retrieval_metrics(manifest, evaluated, "tracelog"),
    }
    diagnosis = {condition: _compute_diagnosis_metrics(evaluated, condition) for condition in ALL_CONDITIONS}
    operational = {condition: _compute_operational_metrics(evaluated, condition) for condition in ALL_CONDITIONS}
    final_verdict = _build_final_verdict(evaluated, retrieval, diagnosis)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            **asdict(config),
            "base_dir": str(config.base_dir),
        },
        "manifest": manifest,
        "per_query": evaluated,
        "retrieval": retrieval,
        "diagnosis": diagnosis,
        "operational": operational,
        "final_verdict": final_verdict,
    }


def _compute_retrieval_metrics(
    manifest: list[dict[str, Any]],
    evaluated: list[dict[str, Any]], condition: str
) -> dict[str, float]:
    truth_by_incident = {item["incident_id"]: item["root_cause_id"] for item in manifest}
    hit_at_1 = []
    hit_at_3 = []
    reciprocal_ranks = []
    ndcgs = []

    for item in evaluated:
        relevant_id = item["truth"]["root_cause_id"]
        ranked = item[condition]["retrieval"]["ranked_incidents"][:3]
        relevances = []
        rank = 0
        for index, candidate in enumerate(ranked, 1):
            is_relevant = truth_by_incident.get(candidate["incident_id"]) == relevant_id
            relevances.append(1 if is_relevant else 0)
            if is_relevant and rank == 0:
                rank = index

        hit_at_1.append(1.0 if relevances[:1] and relevances[0] == 1 else 0.0)
        hit_at_3.append(1.0 if any(relevances) else 0.0)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)

        dcg = sum(rel / math.log2(idx + 2) for idx, rel in enumerate(relevances))
        ideal = sum(1.0 / math.log2(idx + 2) for idx in range(sum(relevances)))
        ndcgs.append(dcg / ideal if ideal else 0.0)

    return {
        "SameRootCauseHit@1": round(statistics.fmean(hit_at_1), 4),
        "SameRootCauseHit@3": round(statistics.fmean(hit_at_3), 4),
        "MRR": round(statistics.fmean(reciprocal_ranks), 4),
        "nDCG@3": round(statistics.fmean(ndcgs), 4),
    }


def _compute_diagnosis_metrics(
    evaluated: list[dict[str, Any]], condition: str
) -> dict[str, float]:
    return {
        "root_cause_accuracy": round(
            statistics.fmean(
                1.0 if item[condition]["judge"]["root_cause_function_correct"] else 0.0
                for item in evaluated
            ),
            4,
        ),
        "surface_accuracy": round(
            statistics.fmean(
                1.0 if item[condition]["judge"]["surface_error_correct"] else 0.0
                for item in evaluated
            ),
            4,
        ),
        "evidence_match": round(
            statistics.fmean(item[condition]["judge"]["evidence_grounding"] for item in evaluated),
            4,
        ),
        "actionability": round(
            statistics.fmean(item[condition]["judge"]["actionability"] for item in evaluated),
            4,
        ),
    }


def _compute_operational_metrics(
    evaluated: list[dict[str, Any]], condition: str
) -> dict[str, float]:
    return {
        "input_tokens": round(
            statistics.fmean(item[condition]["usage"]["input_tokens"] for item in evaluated),
            2,
        ),
        "output_tokens": round(
            statistics.fmean(item[condition]["usage"]["output_tokens"] for item in evaluated),
            2,
        ),
        "total_tokens": round(
            statistics.fmean(item[condition]["usage"]["total_tokens"] for item in evaluated),
            2,
        ),
        "retrieval_latency": round(
            statistics.fmean(
                item[condition]["retrieval"]["retrieval_latency"] for item in evaluated
            ),
            4,
        ),
        "diagnosis_latency": round(
            statistics.fmean(item[condition]["diagnosis_latency"] for item in evaluated),
            4,
        ),
        "time_to_verdict": round(
            statistics.fmean(item[condition]["time_to_verdict"] for item in evaluated),
            4,
        ),
    }


def _build_final_verdict(
    evaluated: list[dict[str, Any]],
    retrieval: dict[str, dict[str, float]],
    diagnosis: dict[str, dict[str, float]],
) -> dict[str, Any]:
    primary_improved_families = []
    ablation_improved_families = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for item in evaluated:
        by_family.setdefault(item["scenario_family"], []).append(item)

    for family, items in by_family.items():
        primary_trace_hits = statistics.fmean(
            1.0 if item["tracelog_with_code"]["judge"]["root_cause_function_correct"] else 0.0
            for item in items
        )
        primary_standard_hits = statistics.fmean(
            1.0 if item["standard_with_code"]["judge"]["root_cause_function_correct"] else 0.0
            for item in items
        )
        if primary_trace_hits > primary_standard_hits:
            primary_improved_families.append(family)

        ablation_trace_hits = statistics.fmean(
            1.0 if item["tracelog"]["judge"]["root_cause_function_correct"] else 0.0
            for item in items
        )
        ablation_standard_hits = statistics.fmean(
            1.0 if item["standard"]["judge"]["root_cause_function_correct"] else 0.0
            for item in items
        )
        if ablation_trace_hits > ablation_standard_hits:
            ablation_improved_families.append(family)

    primary_root_delta = (
        diagnosis["tracelog_with_code"]["root_cause_accuracy"]
        - diagnosis["standard_with_code"]["root_cause_accuracy"]
    )
    primary_surface_delta = (
        diagnosis["tracelog_with_code"]["surface_accuracy"]
        - diagnosis["standard_with_code"]["surface_accuracy"]
    )
    ablation_root_delta = (
        diagnosis["tracelog"]["root_cause_accuracy"]
        - diagnosis["standard"]["root_cause_accuracy"]
    )
    ablation_hit_delta = (
        retrieval["tracelog"]["SameRootCauseHit@3"]
        - retrieval["standard"]["SameRootCauseHit@3"]
    )
    primary_passes = (
        primary_root_delta > 0
        and len(primary_improved_families) >= 2
    )
    ablation_passes = (
        ablation_root_delta > 0
        and ablation_hit_delta > 0
        and len(ablation_improved_families) >= 2
    )

    if primary_passes:
        summary = (
            "TraceLog met the primary, code-aware benchmark exit criteria. "
            "That means the end-to-end operating model improved across multiple "
            "scenario families when code context was available."
        )
    else:
        summary = (
            "The primary benchmark is now the code-aware comparison, because that "
            "better matches the product goal of diagnosing live incidents with "
            "historical context and relevant code. The logs-only comparison remains "
            "valuable, but only as an ablation on formatting and retrieval behavior."
        )

    return {
        "primary_passes_exit_criteria": primary_passes,
        "primary_root_cause_accuracy_delta": round(primary_root_delta, 4),
        "primary_surface_accuracy_delta": round(primary_surface_delta, 4),
        "primary_improved_families": primary_improved_families,
        "ablation_passes_exit_criteria": ablation_passes,
        "ablation_root_cause_accuracy_delta": round(ablation_root_delta, 4),
        "ablation_same_root_cause_hit_at_3_delta": round(ablation_hit_delta, 4),
        "ablation_improved_families": ablation_improved_families,
        "summary": summary,
    }


def _write_results(base_dir: Path, results: dict[str, Any]) -> None:
    results_path = base_dir / "results" / "benchmark_results.json"
    report_path = base_dir / "results" / "benchmark_report.md"
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    sections = [
        "# TraceLog Real RAG Benchmark Report",
        "",
        "Primary benchmark: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`",
        "",
        "Ablation benchmark: `Standard Log + RAG` vs `TraceLog + RAG`",
        "",
        "## Scenario Inventory",
        markdown_table(inventory_rows(results)),
        "",
        "## Dataset Generation Status",
        markdown_table(dataset_status_rows(results)),
        "",
        "## Historical / Query Split",
        markdown_table(split_rows(results)),
        "",
        "## Retrieval Evaluation (Ablation Lens)",
        markdown_table(retrieval_rows(results)),
        "",
        "## Diagnosis Evaluation (Primary First)",
        markdown_table(diagnosis_rows(results)),
        "",
        "## Failure Case Review",
        markdown_table(failure_case_rows(results)),
        "",
        "## Token / Latency Summary",
        markdown_table(operational_rows(results)),
        "",
        final_verdict_markdown(results),
    ]
    report_path.write_text("\n".join(sections), encoding="utf-8")


def _diagnoser_prompt(base_dir: Path) -> str:
    return (base_dir / "prompts" / "diagnoser_prompt.txt").read_text(encoding="utf-8")


def _diagnoser_prompt_with_code(base_dir: Path) -> str:
    return (base_dir / "prompts" / "diagnoser_prompt_with_code.txt").read_text(
        encoding="utf-8"
    )


def _judge_prompt(base_dir: Path) -> str:
    return (base_dir / "prompts" / "judge_prompt.txt").read_text(encoding="utf-8")


def _code_context_for_family(scenario_family: str) -> str:
    family_to_class_name = {
        "ecommerce_bulk_checkout": "ECommerceBulkCheckoutScenario",
        "warehouse_sync_reservation": "WarehouseSyncScenario",
        "api_gateway_audit": "ApiGatewayAuditScenario",
    }
    class_name = family_to_class_name[scenario_family]
    scenario_class = getattr(scenario_module, class_name)
    source = inspect.getsource(scenario_class)
    helper_source = inspect.getsource(run_incident)
    return (
        f"# Relevant scenario class\n{source}\n\n"
        f"# Incident runner entrypoint\n{helper_source}"
    )


__all__ = [
    "BenchmarkConfig",
    "dataset_status_rows",
    "diagnosis_rows",
    "failure_case_rows",
    "final_verdict_markdown",
    "inventory_rows",
    "load_results",
    "markdown_table",
    "operational_rows",
    "retrieval_rows",
    "run_benchmark",
    "split_rows",
]
