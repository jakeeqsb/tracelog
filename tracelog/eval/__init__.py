"""Evaluation helpers for the TraceLog blind-debug benchmark."""

from .benchmark import (
    BenchmarkConfig,
    failure_rows,
    load_results,
    load_run_results,
    markdown_table,
    per_run_rows,
    run_benchmark,
    run_once,
    summary_rows,
    verdict_markdown,
)
from .benchmark_v2 import (
    BenchmarkV2Config,
    failure_rows as failure_rows_v2,
    load_results as load_results_v2,
    load_run_results as load_run_results_v2,
    markdown_table as markdown_table_v2,
    per_run_rows as per_run_rows_v2,
    run_benchmark as run_benchmark_v2,
    run_once as run_once_v2,
    run_once_from_scenario,
    summary_rows as summary_rows_v2,
    verdict_markdown as verdict_markdown_v2,
)

__all__ = [
    # v1
    "BenchmarkConfig",
    "failure_rows",
    "load_results",
    "load_run_results",
    "markdown_table",
    "per_run_rows",
    "run_benchmark",
    "run_once",
    "summary_rows",
    "verdict_markdown",
    # v2
    "BenchmarkV2Config",
    "failure_rows_v2",
    "load_results_v2",
    "load_run_results_v2",
    "markdown_table_v2",
    "per_run_rows_v2",
    "run_benchmark_v2",
    "run_once_v2",
    "run_once_from_scenario",
    "summary_rows_v2",
    "verdict_markdown_v2",
]
