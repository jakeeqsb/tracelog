"""TraceLog blind-debug benchmark: 3-condition evaluation pipeline."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from tracelog.ingestion.aggregator import aggregate_traces
from tracelog.chunking import TraceTreeSplitter

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError as exc:
    raise RuntimeError("langchain_text_splitters required") from exc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
DIAGNOSER_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
WRITER_MODEL = "gpt-4o"
COLLECTION = "tracelog_corpus"
CONDITIONS = ("A", "B", "C")
CONDITION_LABELS = {
    "A": "Standard (no RAG)",
    "B": "TraceLog (no RAG)",
    "C": "TraceLog + RAG",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BASE_DIR = PROJECT_ROOT / "docs" / "eval" / "benchmark_v1"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BenchmarkConfig:
    base_dir: Path = _DEFAULT_BASE_DIR
    top_k: int = 3
    diagnoser_model: str = DIAGNOSER_MODEL
    judge_model: str = JUDGE_MODEL
    writer_model: str = WRITER_MODEL

    @property
    def prompts_dir(self) -> Path:
        return self.base_dir / "prompts"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def run_once(config: BenchmarkConfig | None = None) -> dict[str, Any]:
    """Run a single scenario end-to-end and return the run result."""
    config = config or BenchmarkConfig()
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI()

    run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = config.base_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate scenario
    code, truth = _generate_scenario(client, config.writer_model, prompts_dir=config.prompts_dir)
    (run_dir / "scenario_code.py").write_text(code, encoding="utf-8")
    (run_dir / "sealed_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Execute in both modes
    standard_log = _execute_mode(code, "standard", run_dir)
    tracelog_log = _execute_mode(code, "tracelog", run_dir)
    (run_dir / "standard.log").write_text(standard_log, encoding="utf-8")
    (run_dir / "tracelog.log").write_text(tracelog_log, encoding="utf-8")

    # 3. Build RAG corpus from previous runs (exclude current)
    corpus_client = _build_corpus(config.base_dir, client, exclude_run_id=run_id)

    # 4. Diagnose all three conditions
    diagnoser_prompt = (config.prompts_dir / "diagnoser_prompt.txt").read_text(encoding="utf-8")
    judge_prompt = (config.prompts_dir / "judge_prompt.txt").read_text(encoding="utf-8")

    diagnoses: dict[str, Any] = {}
    for condition in CONDITIONS:
        diagnosis, usage, latency = _diagnose(
            client=client,
            model=config.diagnoser_model,
            condition=condition,
            standard_log=standard_log,
            tracelog_log=tracelog_log,
            corpus_client=corpus_client,
            prompt_template=diagnoser_prompt,
            top_k=config.top_k,
        )
        judgment = _judge(client, config.judge_model, judge_prompt, truth, diagnosis)
        diagnoses[condition] = {
            "diagnosis": diagnosis,
            "judgment": judgment,
            "usage": usage,
            "latency": latency,
        }
        (run_dir / f"diagnosis_{condition}.json").write_text(
            json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    (run_dir / "judgment.json").write_text(
        json.dumps({c: diagnoses[c]["judgment"] for c in CONDITIONS}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 5. Index this run into corpus for future runs
    _index_run(config.base_dir, run_id, tracelog_log, truth)

    result = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "truth": truth,
        **{c: diagnoses[c] for c in CONDITIONS},
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def run_benchmark(n: int = 5, config: BenchmarkConfig | None = None) -> dict[str, Any]:
    """Run n scenarios and return aggregated results."""
    config = config or BenchmarkConfig()
    runs = []
    for i in range(n):
        print(f"Run {i + 1}/{n}...")
        runs.append(run_once(config))
    results = _aggregate(runs)
    out_path = config.base_dir / "results" / "benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def load_results(base_dir: Path | str | None = None) -> dict[str, Any]:
    base_dir = Path(base_dir) if base_dir else _DEFAULT_BASE_DIR
    return json.loads((base_dir / "results" / "benchmark_results.json").read_text(encoding="utf-8"))


def load_run_results(base_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Load all individual run results (no aggregated file needed)."""
    base_dir = Path(base_dir) if base_dir else _DEFAULT_BASE_DIR
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((base_dir / "runs").glob("*/result.json"))
    ]


# ---------------------------------------------------------------------------
# Notebook helpers
# ---------------------------------------------------------------------------
def summary_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in CONDITIONS:
        m = results["metrics"][condition]
        rows.append({
            "condition": CONDITION_LABELS[condition],
            "root_cause_acc": m["root_cause_accuracy"],
            "surface_acc": m["surface_accuracy"],
            "evidence_quality": m["evidence_quality"],
            "fix_correct": m["fix_direction_accuracy"],
            "avg_tokens": m["avg_total_tokens"],
            "avg_latency_s": m["avg_latency"],
        })
    return rows


def per_run_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for run in results["runs"]:
        for condition in CONDITIONS:
            j = run[condition]["judgment"]
            rows.append({
                "run_id": run["run_id"][:14],
                "condition": CONDITION_LABELS[condition],
                "root_cause": j["root_cause_correct"],
                "surface": j["surface_error_correct"],
                "evidence": j["evidence_quality"],
                "fix": j["fix_direction_correct"],
            })
    return rows


def failure_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for run in results["runs"]:
        for condition in CONDITIONS:
            j = run[condition]["judgment"]
            if not j["root_cause_correct"]:
                rows.append({
                    "run_id": run["run_id"][:14],
                    "condition": CONDITION_LABELS[condition],
                    "predicted": run[condition]["diagnosis"].get("root_cause_function", ""),
                    "expected": run["truth"]["root_cause_function"],
                    "reason": j["reason"],
                })
    return rows


def verdict_markdown(results: dict[str, Any]) -> str:
    v = results["verdict"]
    lines = [
        "## Final Verdict",
        "",
        f"Runs evaluated: **{results['n_runs']}**",
        "",
        "### Does TraceLog format help? (B vs A)",
        f"- Root cause accuracy delta: `{v['B_vs_A_root_cause_delta']:+.3f}`",
        f"- Result: `{'PASS ✓' if v['B_vs_A_pass'] else 'FAIL ✗'}`",
        "",
        "### Does the full system help? (C vs A)",
        f"- Root cause accuracy delta: `{v['C_vs_A_root_cause_delta']:+.3f}`",
        f"- Result: `{'PASS ✓' if v['C_vs_A_pass'] else 'FAIL ✗'}`",
        "",
        "### RAG contribution (C vs B)",
        f"- Root cause accuracy delta: `{v['C_vs_B_root_cause_delta']:+.3f}`",
        "",
        f"**{v['summary']}**",
    ]
    return "\n".join(lines)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data_"
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scenario generation
# ---------------------------------------------------------------------------
def _generate_scenario(client: OpenAI, model: str, max_retries: int = 3, prompts_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    if prompts_dir is None:
        prompts_dir = _DEFAULT_BASE_DIR / "prompts"
    prompt = (prompts_dir / "bug_writer_prompt.txt").read_text(encoding="utf-8")
    code, truth = "", {}
    for attempt in range(max_retries):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content)
        code, truth = raw["code"], raw["sealed_truth"]
        if _verify_scenario_raises(code):
            return code, truth
        print(f"  [gen attempt {attempt + 1}/{max_retries}] no exception raised — retrying...")
    return code, truth


def _verify_scenario_raises(code: str) -> bool:
    """Run the scenario code in a subprocess; return True if it raises an exception."""
    verify_script = (
        "import sys, logging, types\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "logging.basicConfig(level=logging.DEBUG)\n"
        "logger = logging.getLogger('verify')\n"
        f"mod = types.ModuleType('scenario')\n"
        f"exec(compile({code!r}, 'scenario', 'exec'), mod.__dict__)\n"
        "try:\n"
        "    mod.Scenario(logger).run()\n"
        "    print('NO_EXCEPTION')\n"
        "except Exception as e:\n"
        "    print(f'EXCEPTION:{type(e).__name__}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", verify_script],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    return "EXCEPTION:" in result.stdout


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
_LAUNCHER_TEMPLATE = '''\
import sys, os, logging, importlib.util
sys.path.insert(0, {project_root!r})

from tracelog import FileExporter, TraceLogHandler, get_buffer, trace
from tracelog.context import ContextManager

def _reset():
    ctx = ContextManager()
    ctx._trace_id.set("")
    ctx._span_id.set("")
    ctx._parent_span_id.set("")
    ctx._depth.set(0)
    try:
        get_buffer().clear()
    except Exception:
        pass

_reset()

spec = importlib.util.spec_from_file_location("scenario", {scenario_path!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Scenario = mod.Scenario

logger = logging.getLogger("tracelog.bench")
logger.setLevel(logging.DEBUG)
logger.handlers = []
logger.propagate = False

if {is_tracelog!r}:
    handler = TraceLogHandler(exporter=FileExporter({output_path!r}), capacity=2000, max_chunks=200)
else:
    handler = logging.FileHandler({output_path!r}, mode="w")
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(threadName)s] %(levelname)s - %(message)s"))

logger.addHandler(handler)
try:
    scenario = Scenario(logger)
    scenario.run()
except Exception:
    logger.exception("scenario execution failed")
finally:
    for h in list(logger.handlers):
        h.flush(); h.close(); logger.removeHandler(h)
'''


def _execute_mode(code: str, mode: str, run_dir: Path) -> str:
    scenario_path = run_dir / "scenario_code.py"
    output_path = run_dir / f"raw_{mode}.log"
    launcher_path = run_dir / f"_launcher_{mode}.py"

    scenario_path.write_text(code, encoding="utf-8")
    launcher_path.write_text(
        _LAUNCHER_TEMPLATE.format(
            project_root=str(PROJECT_ROOT),
            scenario_path=str(scenario_path),
            is_tracelog=(mode == "tracelog"),
            output_path=str(output_path),
        ),
        encoding="utf-8",
    )

    try:
        subprocess.run(
            [sys.executable, str(launcher_path)],
            timeout=30,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
    except subprocess.TimeoutExpired:
        pass

    if not output_path.exists():
        return "(no output produced)"

    raw = output_path.read_text(encoding="utf-8")
    if mode == "tracelog":
        return _aggregate_tracelog(raw)
    return raw


def _aggregate_tracelog(raw: str) -> str:
    dumps = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            try:
                dumps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not dumps:
        return raw
    aggregated = aggregate_traces(dumps)
    return "\n\n".join(text for _, text in sorted(aggregated.items()))


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
def _embed(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# RAG corpus
# ---------------------------------------------------------------------------
def _build_corpus(
    base_dir: Path,
    client: OpenAI,
    exclude_run_id: str,
) -> QdrantClient | None:
    splitter = TraceTreeSplitter(chunk_size=1200, chunk_overlap=100)
    points: list[PointStruct] = []
    point_id = 1

    for run_result_path in sorted((base_dir / "runs").glob("*/result.json")):
        run_id = run_result_path.parent.name
        if run_id == exclude_run_id:
            continue
        tracelog_path = run_result_path.parent / "tracelog.log"
        if not tracelog_path.exists():
            continue
        text = tracelog_path.read_text(encoding="utf-8")
        chunks = splitter.split_text(text)
        if not chunks:
            continue
        vectors = _embed(client, chunks)
        truth_path = run_result_path.parent / "sealed_truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else {}
        for chunk_text, vector in zip(chunks, vectors, strict=True):
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "run_id": run_id,
                        "chunk_text": chunk_text,
                        "root_cause_function": truth.get("root_cause_function", ""),
                    },
                )
            )
            point_id += 1

    if not points:
        return None

    qclient = QdrantClient(":memory:")
    qclient.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    qclient.upsert(collection_name=COLLECTION, points=points)
    return qclient


def _retrieve(
    qclient: QdrantClient,
    client: OpenAI,
    query_text: str,
    top_k: int,
) -> list[str]:
    vector = _embed(client, [query_text[-3000:]])[0]
    points = qclient.query_points(
        collection_name=COLLECTION,
        query=vector,
        limit=top_k * 3,
        with_payload=True,
    ).points

    seen: set[str] = set()
    chunks: list[str] = []
    for point in points:
        run_id = point.payload["run_id"]
        if run_id not in seen:
            seen.add(run_id)
            chunks.append(point.payload["chunk_text"])
        if len(chunks) >= top_k:
            break
    return chunks


def _index_run(base_dir: Path, run_id: str, tracelog_text: str, truth: dict[str, Any]) -> None:
    """Persist a completed run so future runs can use it as RAG corpus."""
    index_dir = base_dir / "corpus" / run_id
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "tracelog.log").write_text(tracelog_text, encoding="utf-8")
    (index_dir / "truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------
def _diagnose(
    *,
    client: OpenAI,
    model: str,
    condition: str,
    standard_log: str,
    tracelog_log: str,
    corpus_client: QdrantClient | None,
    prompt_template: str,
    top_k: int,
) -> tuple[dict[str, Any], dict[str, int], float]:
    if condition == "A":
        log_text = standard_log
        rag_section = ""
    elif condition == "B":
        log_text = tracelog_log
        rag_section = ""
    else:  # C
        log_text = tracelog_log
        if corpus_client is not None:
            chunks = _retrieve(corpus_client, client, tracelog_log, top_k)
            rag_section = _build_rag_section(chunks)
        else:
            rag_section = ""

    prompt = prompt_template.replace("{rag_section}", rag_section).replace("{current_log}", log_text)

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    latency = round(time.perf_counter() - t0, 3)

    diagnosis = json.loads(response.choices[0].message.content)
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }
    return diagnosis, usage, latency


def _build_rag_section(chunks: list[str]) -> str:
    if not chunks:
        return ""
    blocks = [f"### Past Incident {i}\n{chunk}" for i, chunk in enumerate(chunks, 1)]
    return "## Similar Past Incidents (for context)\n\n" + "\n\n".join(blocks) + "\n\n"


# ---------------------------------------------------------------------------
# Judgment
# ---------------------------------------------------------------------------
def _judge(
    client: OpenAI,
    model: str,
    prompt_template: str,
    truth: dict[str, Any],
    diagnosis: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        prompt_template
        .replace("{truth}", json.dumps(truth, indent=2, ensure_ascii=False))
        .replace("{diagnosis}", json.dumps(diagnosis, indent=2, ensure_ascii=False))
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Aggregation & metrics
# ---------------------------------------------------------------------------
def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {c: _compute_metrics(runs, c) for c in CONDITIONS}
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "n_runs": len(runs),
        "metrics": metrics,
        "verdict": _build_verdict(metrics),
        "runs": runs,
    }


def _compute_metrics(runs: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    def mean(values: list[float]) -> float:
        return round(statistics.fmean(values), 4) if values else 0.0

    return {
        "root_cause_accuracy": mean(
            [1.0 if r[condition]["judgment"]["root_cause_correct"] else 0.0 for r in runs]
        ),
        "surface_accuracy": mean(
            [1.0 if r[condition]["judgment"]["surface_error_correct"] else 0.0 for r in runs]
        ),
        "evidence_quality": mean(
            [float(r[condition]["judgment"]["evidence_quality"]) for r in runs]
        ),
        "fix_direction_accuracy": mean(
            [1.0 if r[condition]["judgment"]["fix_direction_correct"] else 0.0 for r in runs]
        ),
        "avg_total_tokens": mean([r[condition]["usage"]["total_tokens"] for r in runs]),
        "avg_latency": mean([r[condition]["latency"] for r in runs]),
    }


def _build_verdict(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    a = metrics["A"]["root_cause_accuracy"]
    b = metrics["B"]["root_cause_accuracy"]
    c = metrics["C"]["root_cause_accuracy"]

    b_vs_a = round(b - a, 4)
    c_vs_a = round(c - a, 4)
    c_vs_b = round(c - b, 4)

    if c_vs_a > 0 and b_vs_a > 0:
        summary = "TraceLog format and the full RAG system both outperform the standard log baseline."
    elif c_vs_a > 0:
        summary = "The full TraceLog + RAG system outperforms the baseline, though format alone shows limited gains."
    elif b_vs_a > 0:
        summary = "TraceLog format helps, but RAG did not add further improvement in this run set."
    else:
        summary = "Neither condition outperformed the standard log baseline. Review scenario quality."

    return {
        "B_vs_A_root_cause_delta": b_vs_a,
        "C_vs_A_root_cause_delta": c_vs_a,
        "C_vs_B_root_cause_delta": c_vs_b,
        "B_vs_A_pass": b_vs_a > 0,
        "C_vs_A_pass": c_vs_a > 0,
        "summary": summary,
    }


__all__ = [
    "BenchmarkConfig",
    "run_once",
    "run_benchmark",
    "load_results",
    "load_run_results",
    "summary_rows",
    "per_run_rows",
    "failure_rows",
    "verdict_markdown",
    "markdown_table",
]
