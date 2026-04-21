"""Benchmark v3.2 — Anthropic worker_dispatch retry only.

Re-runs only the worker_dispatch scenario for Anthropic (claude-sonnet-4-6).
All other 14 runs already completed; this fills the missing result.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from tracelog.eval.benchmark_v3 import BenchmarkV3Config, run_scenario_v3

PROJECT_ROOT = Path(__file__).parent.parent

config = BenchmarkV3Config(
    base_dir=PROJECT_ROOT / "docs" / "eval" / "benchmark_v3.2",
    diagnoser_model_openai="gpt-5.4",
    diagnoser_model_anthropic="claude-sonnet-4-6",
    diagnoser_model_google="gemini-2.5-pro",
)

scenario_path = PROJECT_ROOT / "docs" / "eval" / "benchmark_v3" / "scenarios" / "worker_dispatch" / "worker_dispatch.json"

print("=" * 64)
print("  Benchmark v3.2 — Anthropic retry (worker_dispatch only)")
print(f"  Model   : {config.diagnoser_model_anthropic}")
print(f"  Scenario: {scenario_path.parent.name}")
print(f"  Results : {config.base_dir}/runs/")
print("=" * 64)

results = run_scenario_v3(scenario_path, providers=["anthropic"], config=config)

print(f"\nDone. {len(results)} run(s) completed.")
