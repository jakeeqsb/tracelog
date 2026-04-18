"""TraceLog benchmark v3: multi-model × multi-threading evaluation.

Extends v2 along two axes:

1. **Model axis** — every scenario is run against 3 providers:
     OpenAI (gpt-4o), Google (gemini-2.5-pro), Anthropic (claude-opus-4-6)
2. **Scenario axis** — 4 v2 scenarios reused + 3 new multi-threading scenarios

Result structure: scenario × provider × condition(A|B)
  7 scenarios × 3 providers × 2 conditions = 42 agent runs.

All scenarios are hand-crafted JSONs; no LLM generation step.

Conditions
----------
A  Standard log  + code exploration agent
B  TraceLog      + code exploration agent

New vs v2
---------
- Multi-provider diagnoser (OpenAI / Google / Anthropic via LangChain)
- Per-run schema adds `scenario`, `provider`, `model` fields
- Aggregation covers `provider × condition` and `per_scenario × provider × condition`
- Judge always uses OpenAI gpt-4o as a stable reference evaluator
"""

from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from tracelog.eval.benchmark_v2 import (
    _LAUNCHER_TEMPLATE,  # noqa: F401 — re-exported for test convenience
    _aggregate_tracelog,
    _execute_mode,
    _load_prompt,
    _strip_comments,
    _tool_read_file,
    _tool_search_code,
    _tool_write_file,
    _verify_scenario_raises,
)
from tracelog.ingestion.aggregator import aggregate_traces  # noqa: F401

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONDITIONS       = ("A", "B")
CONDITION_LABELS = {"A": "Standard + Agent", "B": "TraceLog + Agent"}
PROVIDERS        = ("openai", "google", "anthropic")

PROJECT_ROOT    = Path(__file__).resolve().parents[2]
_DEFAULT_BASE   = PROJECT_ROOT / "docs" / "eval" / "benchmark_v3"
_V2_SCENARIO_DIR = PROJECT_ROOT / "docs" / "eval" / "benchmark_v2" / "scenarios"
_V3_SCENARIO_DIR = _DEFAULT_BASE / "scenarios"

# Default scenario paths (7 total: 4 v2 reused + 3 v3 new)
DEFAULT_SCENARIO_PATHS: list[Path] = [
    _V2_SCENARIO_DIR / "api_gateway"     / "api.json",
    _V2_SCENARIO_DIR / "maze"            / "maze.json",
    _V2_SCENARIO_DIR / "dynamic_pricing" / "dynamic_pricing.json",
    _V2_SCENARIO_DIR / "thread_local"    / "thread_local.json",
    _V3_SCENARIO_DIR / "worker_dispatch"    / "worker_dispatch.json",
    _V3_SCENARIO_DIR / "producer_aggregator" / "producer_aggregator.json",
    _V3_SCENARIO_DIR / "ledger_processor"   / "ledger_processor.json",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BenchmarkV3Config:
    base_dir: Path = field(default_factory=lambda: _DEFAULT_BASE)
    diagnoser_model_openai:    str = field(default_factory=lambda: os.getenv("DIAGNOSER_MODEL_OPENAI",    "gpt-4o"))
    diagnoser_model_google:    str = field(default_factory=lambda: os.getenv("DIAGNOSER_MODEL_GOOGLE",    "gemini-2.5-pro"))
    diagnoser_model_anthropic: str = field(default_factory=lambda: os.getenv("DIAGNOSER_MODEL_ANTHROPIC", "claude-opus-4-6"))
    judge_model:    str = field(default_factory=lambda: os.getenv("JUDGE_MODEL", "gpt-4o"))
    providers:      tuple[str, ...] = field(default_factory=lambda: PROVIDERS)
    max_iterations: int = 10
    max_retries:    int = 5


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------
def _make_diagnoser_llm(provider: str, config: BenchmarkV3Config) -> BaseChatModel:
    """Return the appropriate LangChain chat model for a given provider."""
    if provider == "openai":
        return ChatOpenAI(
            model=config.diagnoser_model_openai,
            temperature=0,
            max_retries=config.max_retries,
        )
    if provider == "google":
        return ChatGoogleGenerativeAI(
            model=config.diagnoser_model_google,
            temperature=0,
        )
    if provider == "anthropic":
        return ChatAnthropic(
            model=config.diagnoser_model_anthropic,
            temperature=0,
            max_retries=config.max_retries,
        )
    raise ValueError(f"Unknown provider: {provider!r}. Expected one of: openai, google, anthropic")


def _provider_model_name(provider: str, config: BenchmarkV3Config) -> str:
    return {
        "openai":    config.diagnoser_model_openai,
        "google":    config.diagnoser_model_google,
        "anthropic": config.diagnoser_model_anthropic,
    }[provider]


# ---------------------------------------------------------------------------
# Module-level flag for write_file_tool_v3 (v3-local, does not share v2 state)
# ---------------------------------------------------------------------------
_use_tracelog_flag_v3: list[bool] = [False]


@tool
def read_file_tool_v3(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read the contents of a source file. Use start_line and end_line to read a specific range."""
    return _tool_read_file(path, start_line, end_line)


@tool
def search_code_tool_v3(pattern: str, path: str) -> str:
    """Search for a text pattern in a source file or directory. Returns matching lines with line numbers."""
    return _tool_search_code(pattern, path)


@tool
def write_file_tool_v3(path: str, content: str) -> str:
    """Overwrite the scenario file with fixed Python source code, then run it. Returns PASS or FAIL."""
    return _tool_write_file(path, content, use_tracelog=_use_tracelog_flag_v3[0])


# ---------------------------------------------------------------------------
# Metrics extraction (safe usage_metadata — works across all 3 providers)
# ---------------------------------------------------------------------------
def _extract_metrics_v3(messages: list) -> dict[str, Any]:
    """Extract tool call / token metrics from a LangChain message list post-run."""
    tool_call_count = sum(1 for m in messages if isinstance(m, ToolMessage))
    fix_attempts = sum(
        1
        for m in messages
        if isinstance(m, AIMessage)
        for tc in (m.tool_calls or [])
        if tc["name"] == "write_file_tool_v3"
    )
    iterations = sum(1 for m in messages if isinstance(m, AIMessage))

    input_tokens  = 0
    output_tokens = 0
    for m in messages:
        if isinstance(m, AIMessage):
            meta = m.usage_metadata or {}
            input_tokens  += meta.get("input_tokens", 0)
            output_tokens += meta.get("output_tokens", 0)

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


# ---------------------------------------------------------------------------
# Agentic diagnosis (v3) — accepts BaseChatModel directly
# ---------------------------------------------------------------------------
def _diagnose_agentic_v3(
    *,
    llm: BaseChatModel,
    log_text: str,
    scenario_path: str,
    program_description: str = "",
    max_iterations: int,
    use_tracelog: bool = False,
    save_path: Path | None = None,
) -> tuple[bool, dict[str, int], int, int, int, float]:
    """Run the agentic fix loop with LangChain. Returns (fix_success, usage, tool_calls, fix_attempts, iterations, latency)."""
    _use_tracelog_flag_v3[0] = use_tracelog

    system_prompt_template = _load_prompt("agent_system")
    system_prompt = (
        system_prompt_template
        .replace("{scenario_path}", scenario_path)
        .replace("{program_description}", program_description or "No description provided.")
    )

    tools = [read_file_tool_v3, search_code_tool_v3, write_file_tool_v3]

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    user_message = f"## Error Log\n\n```\n{log_text}\n```"

    t0 = time.perf_counter()
    result = agent.invoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"recursion_limit": max_iterations * 3},
    )
    latency = round(time.perf_counter() - t0, 3)

    messages = result["messages"]

    metrics = _extract_metrics_v3(messages)
    fix_attempts    = metrics["fix_attempts"]
    tool_call_count = metrics["tool_call_count"]
    iterations      = metrics["iterations"]
    usage           = metrics["usage"]

    # Determine fix success
    fix_success = False
    for m in messages:
        if isinstance(m, ToolMessage) and m.content.startswith("PASS"):
            fix_success = True
            break
    if not fix_success:
        try:
            final_code = Path(scenario_path).read_text(encoding="utf-8")
            fix_success = not _verify_scenario_raises(final_code)
        except Exception:
            fix_success = False

    if save_path:
        save_path.write_text(
            json.dumps(messages_to_dict(messages), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return fix_success, usage, tool_call_count, fix_attempts, iterations, latency


# ---------------------------------------------------------------------------
# Root-cause judgment (uses OpenAI as stable reference evaluator)
# ---------------------------------------------------------------------------
def _judge_root_cause_v3(
    judge_model: str,
    messages: list[dict[str, Any]],
    truth: dict[str, Any],
) -> tuple[bool, int | None]:
    """Judge whether the agent correctly identified the root cause."""
    assistant_turns = []
    iteration = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type", "") != "ai":
            continue
        iteration += 1
        data = msg.get("data", {})
        content = data.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        assistant_turns.append({"iteration": iteration, "text": content})

    truth_json = json.dumps(truth, indent=2, ensure_ascii=False)
    turns_json = json.dumps(assistant_turns, indent=2, ensure_ascii=False)

    template = _load_prompt("judge")
    prompt = (
        template
        .replace("{truth_json}", truth_json)
        .replace("{turns_json}", turns_json)
    )

    llm = ChatOpenAI(model=judge_model, temperature=0, max_retries=5)
    response = llm.invoke([HumanMessage(content=prompt)])
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, AttributeError):
        return False, None
    return data.get("root_cause_identified", False), data.get("iterations_to_diagnosis")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def run_scenario_v3(
    scenario_path: str | Path,
    providers: list[str] | tuple[str, ...] | None = None,
    config: BenchmarkV3Config | None = None,
) -> list[dict[str, Any]]:
    """Run agents on a hand-crafted scenario JSON for all specified providers.

    Logs are executed once (shared across providers). Each provider gets its own
    run directory with agent message files and result.json.

    Returns a list of result dicts — one per provider.
    """
    load_dotenv(PROJECT_ROOT / ".env")  # must load before BenchmarkV3Config reads env vars
    config = config or BenchmarkV3Config()
    providers = list(providers or config.providers)

    scenario_path = Path(scenario_path)
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    code  = raw["code"]
    truth = raw["sealed_truth"]
    program_description = raw.get("description", "")
    scenario_name = scenario_path.parent.name

    # Execute scenario once to produce shared logs
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    shared_dir = config.base_dir / "runs" / f"_exec_{scenario_name}_{timestamp}"
    shared_dir.mkdir(parents=True, exist_ok=True)

    standard_log = _execute_mode(code, "standard", shared_dir)
    tracelog_log = _execute_mode(code, "tracelog", shared_dir)
    agent_code   = _strip_comments(code)

    results = []
    for provider in providers:
        run_id  = f"{scenario_name}_{provider}_{timestamp}"
        run_dir = config.base_dir / "runs" / run_id

        # Resume: skip if result.json already exists and is complete
        existing_result_path = run_dir / "result.json"
        if existing_result_path.exists():
            try:
                existing = json.loads(existing_result_path.read_text(encoding="utf-8"))
                if all(c in existing for c in CONDITIONS):
                    print(f"  [{provider}] skipping — result.json already exists")
                    results.append(existing)
                    continue
            except (json.JSONDecodeError, KeyError):
                pass  # corrupted — re-run

        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "sealed_truth.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (run_dir / "scenario_code.py").write_text(agent_code, encoding="utf-8")
        (run_dir / "standard.log").write_text(standard_log, encoding="utf-8")
        (run_dir / "tracelog.log").write_text(tracelog_log, encoding="utf-8")

        llm = _make_diagnoser_llm(provider, config)
        model_name = _provider_model_name(provider, config)

        diagnoses: dict[str, Any] = {}
        for condition in CONDITIONS:
            print(f"  [{provider}] condition {condition}...")
            scenario_copy = run_dir / f"scenario_{condition}.py"
            scenario_copy.write_text(agent_code, encoding="utf-8")

            log_text      = standard_log if condition == "A" else tracelog_log
            messages_path = run_dir / f"agent_{condition}_messages.json"

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    fix_success, usage, tool_call_count, fix_attempts, iterations, latency = _diagnose_agentic_v3(
                        llm=llm,
                        log_text=log_text,
                        scenario_path=str(scenario_copy),
                        program_description=program_description,
                        max_iterations=config.max_iterations,
                        use_tracelog=(condition == "B"),
                        save_path=messages_path,
                    )
                    saved_messages = json.loads(messages_path.read_text(encoding="utf-8"))
                    root_cause_identified, iterations_to_diagnosis = _judge_root_cause_v3(
                        config.judge_model, saved_messages, truth
                    )
                    diagnoses[condition] = {
                        "fix_success":             fix_success,
                        "usage":                   usage,
                        "tool_call_count":         tool_call_count,
                        "fix_attempts":            fix_attempts,
                        "iterations":              iterations,
                        "latency":                 latency,
                        "root_cause_identified":   root_cause_identified,
                        "iterations_to_diagnosis": iterations_to_diagnosis,
                    }
                    print(
                        f"    fix={fix_success}, root_cause={root_cause_identified}, "
                        f"diag_iter={iterations_to_diagnosis}, attempts={fix_attempts}, "
                        f"tools={tool_call_count}, latency={latency}s"
                    )
                    break
                except Exception as exc:
                    is_rate_limit = "429" in str(exc) or "rate_limit" in str(exc).lower() or "RateLimitError" in type(exc).__name__
                    if is_rate_limit and attempt < max_retries - 1:
                        wait = 90 * (attempt + 1)
                        print(f"    rate limit hit — waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                        time.sleep(wait)
                    else:
                        print(f"    ERROR: {type(exc).__name__}: {exc}")
                        diagnoses[condition] = {
                            "fix_success":             False,
                            "usage":                   {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                            "tool_call_count":         0,
                            "fix_attempts":            0,
                            "iterations":              0,
                            "latency":                 0.0,
                            "root_cause_identified":   False,
                            "iterations_to_diagnosis": None,
                            "error":                   f"{type(exc).__name__}: {exc}",
                        }
                        break

        result = {
            "run_id":       run_id,
            "scenario":     scenario_name,
            "provider":     provider,
            "model":        model_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "truth":        truth,
            **{c: diagnoses[c] for c in CONDITIONS},
        }
        (run_dir / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        results.append(result)

    return results


def run_benchmark_v3(
    scenario_paths: list[str | Path] | None = None,
    providers: list[str] | tuple[str, ...] | None = None,
    config: BenchmarkV3Config | None = None,
) -> dict[str, Any]:
    """Run all scenarios × all providers and return aggregated results.

    Saves results to config.base_dir / "results" / "benchmark_results.json".
    """
    load_dotenv(PROJECT_ROOT / ".env")  # must load before BenchmarkV3Config reads env vars
    config = config or BenchmarkV3Config()
    scenario_paths = [Path(p) for p in (scenario_paths or DEFAULT_SCENARIO_PATHS)]
    providers = list(providers or config.providers)

    all_runs: list[dict[str, Any]] = []
    for i, scenario_path in enumerate(scenario_paths, 1):
        print(f"Scenario {i}/{len(scenario_paths)}: {scenario_path.parent.name}")
        runs = run_scenario_v3(scenario_path, providers=providers, config=config)
        all_runs.extend(runs)

    results = _aggregate_v3(all_runs)
    out_path = config.base_dir / "results" / "benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out_path}")
    return results


def load_results_v3(base_dir: Path | str | None = None) -> dict[str, Any]:
    base_dir = Path(base_dir) if base_dir else _DEFAULT_BASE
    return json.loads((base_dir / "results" / "benchmark_results.json").read_text(encoding="utf-8"))


def load_run_results_v3(base_dir: Path | str | None = None) -> list[dict[str, Any]]:
    base_dir = Path(base_dir) if base_dir else _DEFAULT_BASE
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((base_dir / "runs").glob("*/result.json"))
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _aggregate_v3(runs: list[dict[str, Any]]) -> dict[str, Any]:
    providers = sorted({r["provider"] for r in runs})
    scenarios = sorted({r["scenario"] for r in runs})

    # Overall metrics per provider × condition
    metrics: dict[str, dict[str, Any]] = {}
    for provider in providers:
        provider_runs = [r for r in runs if r["provider"] == provider]
        metrics[provider] = {c: _compute_metrics_v3(provider_runs, c) for c in CONDITIONS}

    # Per-scenario breakdown
    per_scenario: dict[str, dict[str, dict[str, Any]]] = {}
    for scenario in scenarios:
        per_scenario[scenario] = {}
        for provider in providers:
            scen_prov_runs = [r for r in runs if r["scenario"] == scenario and r["provider"] == provider]
            per_scenario[scenario][provider] = {
                c: _compute_metrics_v3(scen_prov_runs, c) for c in CONDITIONS
            }

    verdict = {provider: _build_verdict_v3(metrics[provider]) for provider in providers}

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "n_scenarios":  len(scenarios),
        "providers":    providers,
        "metrics":      metrics,
        "per_scenario": per_scenario,
        "verdict":      verdict,
        "runs":         runs,
    }


def _compute_metrics_v3(runs: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    def mean(values: list[float]) -> float:
        return round(statistics.fmean(values), 4) if values else 0.0

    diag_iters = [
        float(r[condition]["iterations_to_diagnosis"])
        for r in runs
        if r[condition].get("iterations_to_diagnosis") is not None
    ]
    return {
        "fix_success_rate":       mean([1.0 if r[condition]["fix_success"] else 0.0 for r in runs]),
        "root_cause_rate":        mean([1.0 if r[condition].get("root_cause_identified") else 0.0 for r in runs]),
        "avg_iterations_to_diag": mean(diag_iters),
        "avg_fix_attempts":       mean([float(r[condition]["fix_attempts"])          for r in runs]),
        "avg_tool_calls":         mean([float(r[condition]["tool_call_count"])       for r in runs]),
        "avg_iterations":         mean([float(r[condition]["iterations"])            for r in runs]),
        "avg_total_tokens":       mean([float(r[condition]["usage"]["total_tokens"]) for r in runs]),
        "avg_latency":            mean([r[condition]["latency"]                      for r in runs]),
    }


def _build_verdict_v3(provider_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    a = provider_metrics["A"]
    b = provider_metrics["B"]

    fix_delta        = round(b["fix_success_rate"]       - a["fix_success_rate"],       4)
    tools_delta      = round(b["avg_tool_calls"]          - a["avg_tool_calls"],          4)
    root_cause_delta = round(b["root_cause_rate"]         - a["root_cause_rate"],         4)
    diag_iter_delta  = round(b["avg_iterations_to_diag"]  - a["avg_iterations_to_diag"],  4)

    fix_pass        = fix_delta        > 0
    efficiency_pass = tools_delta      < 0
    diagnosis_pass  = root_cause_delta > 0
    diag_speed_pass = diag_iter_delta  < 0

    if fix_pass and efficiency_pass:
        summary = "TraceLog improved both fix success rate and efficiency over the standard log baseline."
    elif fix_pass:
        summary = "TraceLog improved fix success rate but did not reduce tool call count."
    elif efficiency_pass:
        summary = "TraceLog reduced tool calls but did not improve fix success rate."
    else:
        summary = "Neither fix success rate nor efficiency improved with TraceLog."

    return {
        "B_vs_A_fix_success_delta":  fix_delta,
        "B_vs_A_tool_calls_delta":   tools_delta,
        "B_vs_A_root_cause_delta":   root_cause_delta,
        "B_vs_A_diag_iter_delta":    diag_iter_delta,
        "B_vs_A_fix_pass":           fix_pass,
        "B_vs_A_efficiency_pass":    efficiency_pass,
        "B_vs_A_diagnosis_pass":     diagnosis_pass,
        "B_vs_A_diag_speed_pass":    diag_speed_pass,
        "summary":                   summary,
    }


# ---------------------------------------------------------------------------
# Notebook helpers
# ---------------------------------------------------------------------------
def summary_rows_v3(results: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per (provider, condition) — overall metrics."""
    rows = []
    for provider in results["providers"]:
        for condition in CONDITIONS:
            m = results["metrics"][provider][condition]
            rows.append({
                "provider":         provider,
                "condition":        CONDITION_LABELS[condition],
                "fix_success_rate": m["fix_success_rate"],
                "root_cause_rate":  m["root_cause_rate"],
                "avg_iter_to_diag": m["avg_iterations_to_diag"],
                "avg_fix_attempts": m["avg_fix_attempts"],
                "avg_tool_calls":   m["avg_tool_calls"],
                "avg_iterations":   m["avg_iterations"],
                "avg_tokens":       m["avg_total_tokens"],
                "avg_latency_s":    m["avg_latency"],
            })
    return rows


def per_run_rows_v3(results: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per (scenario, provider, condition)."""
    rows = []
    for run in results["runs"]:
        for condition in CONDITIONS:
            rows.append({
                "scenario":         run["scenario"],
                "provider":         run["provider"],
                "model":            run["model"],
                "condition":        CONDITION_LABELS[condition],
                "fix_success":      run[condition]["fix_success"],
                "root_cause_found": run[condition].get("root_cause_identified", "?"),
                "iter_to_diag":     run[condition].get("iterations_to_diagnosis", "?"),
                "fix_attempts":     run[condition]["fix_attempts"],
                "tool_calls":       run[condition]["tool_call_count"],
                "iterations":       run[condition]["iterations"],
            })
    return rows


def verdict_markdown_v3(results: dict[str, Any]) -> str:
    """Per-provider verdict blocks in Markdown."""
    lines = ["## Benchmark v3 Verdict", ""]
    for provider in results["providers"]:
        v = results["verdict"][provider]
        lines += [
            f"### {provider.capitalize()}",
            "",
            f"- Fix success delta (B–A): `{v['B_vs_A_fix_success_delta']:+.3f}` → `{'PASS ✓' if v['B_vs_A_fix_pass'] else 'FAIL ✗'}`",
            f"- Tool call delta (B–A): `{v['B_vs_A_tool_calls_delta']:+.2f}` → `{'PASS ✓' if v['B_vs_A_efficiency_pass'] else 'FAIL ✗'}`",
            f"- Root cause delta (B–A): `{v['B_vs_A_root_cause_delta']:+.3f}` → `{'PASS ✓' if v['B_vs_A_diagnosis_pass'] else 'FAIL ✗'}`",
            "",
            f"**{v['summary']}**",
            "",
        ]
    return "\n".join(lines)


def markdown_table_v3(rows: list[dict[str, Any]]) -> str:
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


__all__ = [
    "BenchmarkV3Config",
    "DEFAULT_SCENARIO_PATHS",
    "run_scenario_v3",
    "run_benchmark_v3",
    "load_results_v3",
    "load_run_results_v3",
    "summary_rows_v3",
    "per_run_rows_v3",
    "verdict_markdown_v3",
    "markdown_table_v3",
]
