"""Benchmark v3.2 — remaining scenarios (producer_aggregator, ledger_processor).

Runs the 2 scenarios not completed in the original v3.2 run.
All 3 providers × 2 scenarios = 6 runs.
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

scenarios = [
    PROJECT_ROOT / "docs" / "eval" / "benchmark_v3" / "scenarios" / "producer_aggregator" / "producer_aggregator.json",
    PROJECT_ROOT / "docs" / "eval" / "benchmark_v3" / "scenarios" / "ledger_processor" / "ledger_processor.json",
]

print("=" * 64)
print("  Benchmark v3.2 — remaining scenarios")
print(f"  OpenAI    : {config.diagnoser_model_openai}")
print(f"  Anthropic : {config.diagnoser_model_anthropic}")
print(f"  Google    : {config.diagnoser_model_google}")
print(f"  Scenarios : {[s.parent.name for s in scenarios]}")
print(f"  Results   : {config.base_dir}/runs/")
print("=" * 64)

for i, scenario_path in enumerate(scenarios, 1):
    print(f"\nScenario {i}/{len(scenarios)}: {scenario_path.parent.name}")
    results = run_scenario_v3(scenario_path, providers=["openai", "anthropic", "google"], config=config)
    print(f"  Done. {len(results)} run(s) completed.")

print("\nAll done.")
