"""Benchmark v3.2 — Google producer_aggregator retry.

Previous run hit GraphRecursionError (recursion_limit=30) on Condition B.
Re-runs with default config; recursion_limit is set in agent.invoke().
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

scenario_path = PROJECT_ROOT / "docs" / "eval" / "benchmark_v3" / "scenarios" / "producer_aggregator" / "producer_aggregator.json"

print("=" * 64)
print("  Benchmark v3.2 — Google retry (producer_aggregator only)")
print(f"  Model   : {config.diagnoser_model_google}")
print(f"  Scenario: {scenario_path.parent.name}")
print("=" * 64)

results = run_scenario_v3(scenario_path, providers=["google"], config=config)

print(f"\nDone. {len(results)} run(s) completed.")
