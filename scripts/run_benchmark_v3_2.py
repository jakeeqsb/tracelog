"""Benchmark v3.2 runner — updated model lineup.

Models vs v3:
  OpenAI:     gpt-4o       → gpt-5.4
  Anthropic:  claude-opus-4-6 → claude-sonnet-4-6
  Google:     gemini-2.5-pro  (unchanged — gemini-3.1-pro-preview unstable)

Results saved to docs/eval/benchmark_v3.2/results/benchmark_results.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from tracelog.eval.benchmark_v3 import BenchmarkV3Config, run_benchmark_v3

PROJECT_ROOT = Path(__file__).parent.parent

config = BenchmarkV3Config(
    base_dir=PROJECT_ROOT / "docs" / "eval" / "benchmark_v3.2",
    diagnoser_model_openai="gpt-5.4",
    diagnoser_model_anthropic="claude-sonnet-4-6",
    diagnoser_model_google="gemini-2.5-pro",
)

print("=" * 64)
print("  Benchmark v3.2")
print(f"  OpenAI    : {config.diagnoser_model_openai}")
print(f"  Anthropic : {config.diagnoser_model_anthropic}")
print(f"  Google    : {config.diagnoser_model_google}")
print(f"  Results   : {config.base_dir}/results/")
print("=" * 64)

results = run_benchmark_v3(config=config)

print("\nDone.")
