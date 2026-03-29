"""TraceLog benchmark v2: agentic diagnosis with code exploration tools.

v1 measured log format quality with a single-shot LLM call (no code access).
v2 measures end-to-end diagnosis quality when an agent can iteratively explore
the source code — matching how a real engineer debugs a production error.

Conditions
----------
A  Standard log  + code exploration agent
B  TraceLog      + code exploration agent

New metrics vs v1
-----------------
avg_tool_calls   Average number of tool calls per run (lower = more efficient)
avg_iterations   Average agent loop iterations per run
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from tracelog.ingestion.aggregator import aggregate_traces

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DIAGNOSER_MODEL = "gpt-4o"
JUDGE_MODEL     = "gpt-4o"
WRITER_MODEL    = "gpt-4o"
CONDITIONS      = ("A", "B")
CONDITION_LABELS = {
    "A": "Standard + Agent",
    "B": "TraceLog + Agent",
}
MAX_ITERATIONS = 10  # max agent loop iterations per run

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BASE_DIR = PROJECT_ROOT / "docs" / "eval" / "benchmark_v2"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BenchmarkV2Config:
    base_dir: Path = _DEFAULT_BASE_DIR
    diagnoser_model: str = DIAGNOSER_MODEL
    judge_model: str    = JUDGE_MODEL
    writer_model: str   = WRITER_MODEL
    max_iterations: int = MAX_ITERATIONS

    @property
    def prompts_dir(self) -> Path:
        return self.base_dir / "prompts"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def run_once(config: BenchmarkV2Config | None = None) -> dict[str, Any]:
    """Run a single scenario end-to-end and return the run result."""
    config = config or BenchmarkV2Config()
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI()

    run_id  = datetime.now(UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = config.base_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate scenario
    code, truth = _generate_scenario(client, config.writer_model, config.prompts_dir)
    (run_dir / "sealed_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Execute in both modes (uses original code with comments for execution)
    standard_log = _execute_mode(code, "standard", run_dir)
    tracelog_log = _execute_mode(code, "tracelog", run_dir)

    # Overwrite scenario_code.py with comment-stripped version for agents
    agent_code = _strip_comments(code)
    (run_dir / "scenario_code.py").write_text(agent_code, encoding="utf-8")
    (run_dir / "standard.log").write_text(standard_log,  encoding="utf-8")
    (run_dir / "tracelog.log").write_text(tracelog_log, encoding="utf-8")

    # 3. Run agentic fix for each condition (each gets its own writable copy)
    system_prompt_template = (config.prompts_dir / "agent_system_prompt.txt").read_text(encoding="utf-8")
    program_description = ""

    diagnoses: dict[str, Any] = {}
    for condition in CONDITIONS:
        scenario_copy = run_dir / f"scenario_{condition}.py"
        scenario_copy.write_text(agent_code, encoding="utf-8")

        log_text = standard_log if condition == "A" else tracelog_log
        messages_path = run_dir / f"agent_{condition}_messages.json"
        fix_success, usage, tool_call_count, fix_attempts, iterations, latency = _diagnose_agentic(
            client=client,
            model=config.diagnoser_model,
            log_text=log_text,
            scenario_path=str(scenario_copy),
            system_prompt_template=system_prompt_template,
            program_description=program_description,
            max_iterations=config.max_iterations,
            use_tracelog=(condition == "B"),
            save_path=messages_path,
        )
        saved_messages = json.loads(messages_path.read_text(encoding="utf-8"))
        root_cause_identified, iterations_to_diagnosis = _judge_root_cause(
            client, config.judge_model, saved_messages, truth
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

    result = {
        "run_id":       run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "truth":        truth,
        **{c: diagnoses[c] for c in CONDITIONS},
    }

    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def run_once_from_scenario(
    scenario_path: str | Path,
    config: BenchmarkV2Config | None = None,
) -> dict[str, Any]:
    """Run agents on a hand-crafted scenario JSON, skipping LLM generation.

    The JSON file must have the shape::

        {
          "code": "<Python source>",
          "sealed_truth": {
            "root_cause_function": "...",
            "surface_error_function": "...",
            "bug_description": "...",
            "expected_fix": "..."
          }
        }
    """
    config = config or BenchmarkV2Config()
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI()

    scenario_path = Path(scenario_path)
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    code  = raw["code"]
    truth = raw["sealed_truth"]
    program_description = raw.get("description", "")

    scenario_name = scenario_path.parent.name
    run_id  = scenario_name + "_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_dir = config.base_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "sealed_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    standard_log = _execute_mode(code, "standard", run_dir)
    tracelog_log = _execute_mode(code, "tracelog", run_dir)

    agent_code = _strip_comments(code)
    (run_dir / "scenario_code.py").write_text(agent_code, encoding="utf-8")
    (run_dir / "standard.log").write_text(standard_log, encoding="utf-8")
    (run_dir / "tracelog.log").write_text(tracelog_log, encoding="utf-8")

    system_prompt_template = (config.prompts_dir / "agent_system_prompt.txt").read_text(encoding="utf-8")

    diagnoses: dict[str, Any] = {}
    for condition in CONDITIONS:
        print(f"  Running agent {condition}...")
        scenario_copy = run_dir / f"scenario_{condition}.py"
        scenario_copy.write_text(agent_code, encoding="utf-8")

        log_text = standard_log if condition == "A" else tracelog_log
        messages_path = run_dir / f"agent_{condition}_messages.json"
        fix_success, usage, tool_call_count, fix_attempts, iterations, latency = _diagnose_agentic(
            client=client,
            model=config.diagnoser_model,
            log_text=log_text,
            scenario_path=str(scenario_copy),
            system_prompt_template=system_prompt_template,
            program_description=program_description,
            max_iterations=config.max_iterations,
            use_tracelog=(condition == "B"),
            save_path=messages_path,
        )
        saved_messages = json.loads(messages_path.read_text(encoding="utf-8"))
        root_cause_identified, iterations_to_diagnosis = _judge_root_cause(
            client, config.judge_model, saved_messages, truth
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
        print(f"    fix={fix_success}, root_cause={root_cause_identified}, diag_iter={iterations_to_diagnosis}, attempts={fix_attempts}, tools={tool_call_count}, latency={latency}s")

    result = {
        "run_id":       run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "truth":        truth,
        **{c: diagnoses[c] for c in CONDITIONS},
    }

    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def run_benchmark(n: int = 5, config: BenchmarkV2Config | None = None) -> dict[str, Any]:
    """Run n scenarios and return aggregated results."""
    config = config or BenchmarkV2Config()
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
            "condition":            CONDITION_LABELS[condition],
            "fix_success_rate":     m["fix_success_rate"],
            "root_cause_rate":      m["root_cause_rate"],
            "avg_iter_to_diag":     m["avg_iterations_to_diag"],
            "avg_fix_attempts":     m["avg_fix_attempts"],
            "avg_tool_calls":       m["avg_tool_calls"],
            "avg_iterations":       m["avg_iterations"],
            "avg_tokens":           m["avg_total_tokens"],
            "avg_latency_s":        m["avg_latency"],
        })
    return rows


def per_run_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for run in results["runs"]:
        for condition in CONDITIONS:
            rows.append({
                "run_id":            run["run_id"][:14],
                "condition":         CONDITION_LABELS[condition],
                "fix_success":       run[condition]["fix_success"],
                "root_cause_found":  run[condition].get("root_cause_identified", "?"),
                "iter_to_diag":      run[condition].get("iterations_to_diagnosis", "?"),
                "fix_attempts":      run[condition]["fix_attempts"],
                "tool_calls":        run[condition]["tool_call_count"],
                "iterations":        run[condition]["iterations"],
            })
    return rows


def failure_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for run in results["runs"]:
        for condition in CONDITIONS:
            if not run[condition]["fix_success"]:
                rows.append({
                    "run_id":    run["run_id"][:14],
                    "condition": CONDITION_LABELS[condition],
                    "truth_root_cause": run["truth"]["root_cause_function"],
                    "tool_calls":       run[condition]["tool_call_count"],
                    "fix_attempts":     run[condition]["fix_attempts"],
                })
    return rows


def verdict_markdown(results: dict[str, Any]) -> str:
    v = results["verdict"]
    lines = [
        "## Final Verdict",
        "",
        f"Runs evaluated: **{results['n_runs']}**",
        "",
        "### Does TraceLog improve fix success rate? (B vs A)",
        f"- Fix success delta: `{v['B_vs_A_fix_success_delta']:+.3f}`",
        f"- Result: `{'PASS ✓' if v['B_vs_A_fix_pass'] else 'FAIL ✗'}`",
        "",
        "### Does TraceLog improve efficiency? (B vs A tool calls)",
        f"- Tool call delta: `{v['B_vs_A_tool_calls_delta']:+.2f}` (negative = TraceLog needed fewer)",
        f"- Result: `{'PASS ✓' if v['B_vs_A_efficiency_pass'] else 'FAIL ✗'}`",
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
# Scenario generation  (same logic as v1)
# ---------------------------------------------------------------------------
def _strip_comments(code: str) -> str:
    """Remove all inline # comments from Python source, preserving structure."""
    import tokenize, io
    result = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            result.append(tok)
        return tokenize.untokenize(result)
    except tokenize.TokenError:
        return code  # fall back to original if tokenization fails


def _generate_scenario(
    client: OpenAI,
    model: str,
    prompts_dir: Path,
    max_retries: int = 5,
) -> tuple[str, dict[str, Any]]:
    prompt = (prompts_dir / "bug_writer_prompt.txt").read_text(encoding="utf-8")
    code, truth = "", {}
    for attempt in range(max_retries):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            print(f"  [gen attempt {attempt + 1}/{max_retries}] empty response — retrying...")
            continue
        raw   = json.loads(content)
        code  = raw["code"]
        truth = raw["sealed_truth"]
        if _verify_scenario_raises(code):
            return code, truth
        print(f"  [gen attempt {attempt + 1}/{max_retries}] no exception raised — retrying...")
    return code, truth


def _verify_scenario_raises(code: str) -> bool:
    verify_script = (
        "import sys, logging, types\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "logging.basicConfig(level=logging.DEBUG)\n"
        "logger = logging.getLogger('verify')\n"
        "mod = types.ModuleType('scenario')\n"
        f"exec(compile({code!r}, 'scenario', 'exec'), mod.__dict__)\n"
        "try:\n"
        "    mod.Scenario(logger).run()\n"
        "    print('NO_EXCEPTION')\n"
        "except Exception as e:\n"
        "    print(f'EXCEPTION:{type(e).__name__}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", verify_script],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    return "EXCEPTION:" in result.stdout


# ---------------------------------------------------------------------------
# Execution  (same logic as v1)
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
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Scenario = mod.Scenario

logger = logging.getLogger("tracelog.bench")
logger.setLevel(logging.DEBUG)
logger.handlers  = []
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
    output_path   = run_dir / f"raw_{mode}.log"
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
            timeout=30, capture_output=True,
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
# Agentic diagnosis
# ---------------------------------------------------------------------------
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a source file. Use start_line and end_line to read a specific range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":       {"type": "string",  "description": "Absolute or relative file path"},
                    "start_line": {"type": "integer", "description": "First line to read (1-indexed, optional)"},
                    "end_line":   {"type": "integer", "description": "Last line to read (inclusive, optional)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a text pattern in a source file or directory. Returns matching lines with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text pattern to search for"},
                    "path":    {"type": "string", "description": "File or directory path to search in"},
                },
                "required": ["pattern", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Overwrite the scenario file with fixed Python source code, then immediately run it. "
                "Returns 'PASS: runs clean' if the fix worked, or 'FAIL: <ExceptionType>: <message>' if it still raises. "
                "Use this to apply and verify your fix."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "Path to the scenario file to overwrite"},
                    "content": {"type": "string", "description": "Complete new Python source code"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def _tool_read_file(path: str, start_line: int | None, end_line: int | None) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return f"Error: {e}"
    if start_line is not None or end_line is not None:
        lo = (start_line or 1) - 1
        hi = end_line or len(lines)
        lines = lines[lo:hi]
        offset = lo
    else:
        offset = 0
    return "\n".join(f"{offset + i + 1}: {line}" for i, line in enumerate(lines))


def _tool_search_code(pattern: str, path: str) -> str:
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, path],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() or "(no matches found)"


def _tool_write_file(path: str, content: str, use_tracelog: bool = False) -> str:
    try:
        Path(path).write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error writing file: {e}"

    if use_tracelog:
        # Run with TraceLog so the agent gets updated causal-chain output on failure.
        # TraceLog only flushes to file when an ERROR is logged (i.e. on exception),
        # so: file has content → FAIL, file empty / missing → PASS.
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            raw_log_path = tmp.name
        launcher_src = _LAUNCHER_TEMPLATE.format(
            project_root=str(PROJECT_ROOT),
            scenario_path=path,
            is_tracelog=True,
            output_path=raw_log_path,
        )
        subprocess.run(
            [sys.executable, "-c", launcher_src],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        raw = Path(raw_log_path).read_text(encoding="utf-8") if Path(raw_log_path).exists() else ""
        Path(raw_log_path).unlink(missing_ok=True)
        if not raw.strip():
            return "PASS: Code runs without exception. Your fix is correct."
        tracelog_text = _aggregate_tracelog(raw)
        return f"FAIL: Code still raises an exception.\n\n[Updated TraceLog]\n{tracelog_text}"

    # Standard (no tracelog) verification
    verify_script = (
        "import sys, logging, types\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "logging.basicConfig(level=logging.DEBUG)\n"
        "logger = logging.getLogger('verify')\n"
        "mod = types.ModuleType('scenario')\n"
        f"exec(compile(open({path!r}).read(), 'scenario', 'exec'), mod.__dict__)\n"
        "try:\n"
        "    mod.Scenario(logger).run()\n"
        "    print('PASS')\n"
        "except Exception as e:\n"
        "    print(f'FAIL:{type(e).__name__}:{e}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", verify_script],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    output = result.stdout.strip()
    if output.startswith("PASS"):
        return "PASS: Code runs without exception. Your fix is correct."
    if output.startswith("FAIL:"):
        return f"FAIL: Still raises — {output[5:]}"
    return f"FAIL: Unexpected output — {output}\n{result.stderr[:200]}"


def _execute_tool(name: str, args: dict[str, Any], use_tracelog: bool = False) -> str:
    if name == "read_file":
        return _tool_read_file(
            args["path"],
            args.get("start_line"),
            args.get("end_line"),
        )
    if name == "search_code":
        return _tool_search_code(args["pattern"], args["path"])
    if name == "write_file":
        return _tool_write_file(args["path"], args["content"], use_tracelog=use_tracelog)
    return f"Unknown tool: {name}"


def _diagnose_agentic(
    *,
    client: OpenAI,
    model: str,
    log_text: str,
    scenario_path: str,
    system_prompt_template: str,
    program_description: str = "",
    max_iterations: int,
    use_tracelog: bool = False,
    save_path: Path | None = None,
) -> tuple[bool, dict[str, int], int, int, int, float]:
    """Run the agentic fix loop. Returns (fix_success, usage, tool_calls, fix_attempts, iterations, latency).

    If save_path is given, the full message history is written there as JSON.
    """
    system_prompt = (
        system_prompt_template
        .replace("{scenario_path}", scenario_path)
        .replace("{program_description}", program_description or "No description provided.")
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": f"## Error Log\n\n```\n{log_text}\n```"},
    ]

    total_input_tokens  = 0
    total_output_tokens = 0
    tool_call_count     = 0
    fix_attempts        = 0
    iterations          = 0

    t0 = time.perf_counter()

    for _ in range(max_iterations):
        iterations += 1
        for _attempt in range(5):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=_TOOLS,
                    tool_choice="auto",
                    temperature=0,
                )
                break
            except Exception as _e:
                if "rate_limit" in str(_e).lower() or "429" in str(_e):
                    _wait = 2 ** _attempt * 3
                    print(f"  [agent rate limit] waiting {_wait}s...")
                    time.sleep(_wait)
                else:
                    raise
        total_input_tokens  += response.usage.prompt_tokens
        total_output_tokens += response.usage.completion_tokens

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_unset=False))

        # Agent submitted final answer (no tool calls) — stop the loop
        if not msg.tool_calls:
            break

        # Execute all tool calls in this turn
        tool_results: list[dict[str, Any]] = []
        for tc in msg.tool_calls:
            tool_call_count += 1
            args   = json.loads(tc.function.arguments)
            if tc.function.name == "write_file":
                fix_attempts += 1
            result = _execute_tool(tc.function.name, args, use_tracelog=use_tracelog)
            tool_results.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })
            # Stop as soon as a write_file returns PASS
            if tc.function.name == "write_file" and result.startswith("PASS"):
                messages.extend(tool_results)
                latency = round(time.perf_counter() - t0, 3)
                usage = {
                    "input_tokens":  total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens":  total_input_tokens + total_output_tokens,
                }
                if save_path:
                    save_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")
                return True, usage, tool_call_count, fix_attempts, iterations, latency
        messages.extend(tool_results)

    # Loop ended — check if the current file on disk passes
    try:
        final_code = Path(scenario_path).read_text(encoding="utf-8")
        fix_success = not _verify_scenario_raises(final_code)
    except Exception:
        fix_success = False

    latency = round(time.perf_counter() - t0, 3)
    usage = {
        "input_tokens":  total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens":  total_input_tokens + total_output_tokens,
    }
    if save_path:
        save_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")
    return fix_success, usage, tool_call_count, fix_attempts, iterations, latency


# ---------------------------------------------------------------------------
# Judgment
# ---------------------------------------------------------------------------
def _judge_root_cause(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    truth: dict[str, Any],
) -> tuple[bool, int | None]:
    """Judge whether the agent correctly identified the root cause, and at which iteration."""
    assistant_turns = []
    iteration = 0
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        iteration += 1
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        assistant_turns.append({"iteration": iteration, "text": content})

    truth_json = json.dumps(truth, indent=2, ensure_ascii=False)
    turns_json = json.dumps(assistant_turns, indent=2, ensure_ascii=False)
    prompt = (
        "You are evaluating whether a debugging agent correctly identified the root cause of a bug.\n\n"
        f"## Sealed Truth\n```json\n{truth_json}\n```\n\n"
        f"## Agent Assistant Turns (in order)\n{turns_json}\n\n"
        "Determine:\n"
        "1. Did the agent correctly identify the root cause function/method named in the sealed truth?\n"
        "2. If yes, at which iteration (1-indexed) did the agent FIRST correctly name it?\n\n"
        "Respond with JSON only:\n"
        '{"root_cause_identified": true/false, '
        '"iterations_to_diagnosis": <int or null>, '
        '"reasoning": "<one sentence>"}'
    )
    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            break
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 2 ** attempt * 3
                print(f"  [judge rate limit] waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    data = json.loads(response.choices[0].message.content)
    return data.get("root_cause_identified", False), data.get("iterations_to_diagnosis")


def _judge(
    client: OpenAI,
    model: str,
    prompt_template: str,
    truth: dict[str, Any],
    diagnosis: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        prompt_template
        .replace("{truth}",     json.dumps(truth,     indent=2, ensure_ascii=False))
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
        "n_runs":        len(runs),
        "metrics":       metrics,
        "verdict":       _build_verdict(metrics),
        "runs":          runs,
    }


def _compute_metrics(runs: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    def mean(values: list[float]) -> float:
        return round(statistics.fmean(values), 4) if values else 0.0

    diag_iters = [
        float(r[condition]["iterations_to_diagnosis"])
        for r in runs
        if r[condition].get("iterations_to_diagnosis") is not None
    ]
    return {
        "fix_success_rate":          mean([1.0 if r[condition]["fix_success"] else 0.0 for r in runs]),
        "root_cause_rate":           mean([1.0 if r[condition].get("root_cause_identified") else 0.0 for r in runs]),
        "avg_iterations_to_diag":    mean(diag_iters),
        "avg_fix_attempts":          mean([float(r[condition]["fix_attempts"])          for r in runs]),
        "avg_tool_calls":            mean([float(r[condition]["tool_call_count"])       for r in runs]),
        "avg_iterations":            mean([float(r[condition]["iterations"])            for r in runs]),
        "avg_total_tokens":          mean([float(r[condition]["usage"]["total_tokens"]) for r in runs]),
        "avg_latency":               mean([r[condition]["latency"]                      for r in runs]),
    }


def _build_verdict(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    a_fix        = metrics["A"]["fix_success_rate"]
    b_fix        = metrics["B"]["fix_success_rate"]
    a_tools      = metrics["A"]["avg_tool_calls"]
    b_tools      = metrics["B"]["avg_tool_calls"]
    a_root_cause = metrics["A"]["root_cause_rate"]
    b_root_cause = metrics["B"]["root_cause_rate"]
    a_diag_iter  = metrics["A"]["avg_iterations_to_diag"]
    b_diag_iter  = metrics["B"]["avg_iterations_to_diag"]

    fix_delta        = round(b_fix        - a_fix,        4)
    tools_delta      = round(b_tools      - a_tools,      4)
    root_cause_delta = round(b_root_cause - a_root_cause, 4)
    diag_iter_delta  = round(b_diag_iter  - a_diag_iter,  4)

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


__all__ = [
    "BenchmarkV2Config",
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
