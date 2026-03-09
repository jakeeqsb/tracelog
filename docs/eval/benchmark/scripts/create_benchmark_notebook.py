"""Create the notebook used for the TraceLog real RAG benchmark."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf


def main() -> None:
    project_root = Path(__file__).resolve().parents[4]
    notebook_path = (
        project_root
        / "docs"
        / "eval"
        / "benchmark"
        / "notebooks"
        / "real_rag_benchmark.ipynb"
    )
    notebook_path.parent.mkdir(parents=True, exist_ok=True)

    nb = nbf.v4.new_notebook()
    nb.cells = [
        nbf.v4.new_markdown_cell(
            "# TraceLog Real RAG Benchmark\n"
            "\n"
            "This notebook follows the constraints in `docs/eval/test_strategy.md` "
            "and runs dataset generation, retrieval evaluation, diagnosis evaluation, "
            "and reporting in one place.\n"
            "\n"
            "The primary benchmark compares `Standard Log + RAG + Code` against "
            "`TraceLog + RAG + Code`. The `logs-only` comparison is treated as an ablation."
        ),
        nbf.v4.new_markdown_cell(
            "## How This Benchmark Is Built\n"
            "\n"
            "This experiment runs on a synthetic dataset designed to resemble operational incidents. "
            "The key rule is `same codebase, different instrumentation`. "
            "Each incident is generated from the same scenario code, and only the output path changes.\n"
            "\n"
            "1. `standard logging` path: emits plain text logs.\n"
            "2. `TraceLog` path: emits TraceLog JSON dumps, then the Aggregator reconstructs them into unified Trace-DSL.\n"
            "\n"
            "Historical incidents are indexed into the vector store, and query incidents are kept as holdout cases. "
            "RAG searches the historical corpus using the query incident, the Analyst diagnoses the current incident, "
            "and the Judge compares that diagnosis against sealed truth for root cause, surface error, evidence grounding, and actionability."
        ),
        nbf.v4.new_markdown_cell(
            "## Dataset Structure\n"
            "\n"
            "The current dataset contains three scenario families.\n"
            "\n"
            "- `ecommerce_bulk_checkout`: an upstream state bug such as coupon normalization appears later as a payment failure\n"
            "- `warehouse_sync_reservation`: async/state issues such as snapshot version leaks or dedupe collisions appear as timeouts\n"
            "- `api_gateway_audit`: tenant, token, and profile mismatches appear as permission failures\n"
            "\n"
            "Each incident produces the following artifacts.\n"
            "\n"
            "- `standard.log`: baseline logs\n"
            "- `tracelog_dump.jsonl`: JSON dumps emitted by the TraceLog exporter\n"
            "- `aggregated_trace.log`: unified trace produced by the Aggregator after span reconstruction\n"
            "- `truth/*.json`: sealed truth hidden from the Analyst and shown only to the Judge\n"
            "\n"
            "The split is divided into `historical` and `query`. Historical incidents form the retrieval corpus, and query incidents are the actual evaluation targets."
        ),
        nbf.v4.new_markdown_cell(
            "## Evaluation Structure\n"
            "\n"
            "This notebook shows two layers of comparison.\n"
            "\n"
            "- Primary benchmark: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`\n"
            "- Ablation benchmark: `Standard Log + RAG` vs `TraceLog + RAG`\n"
            "\n"
            "The primary benchmark is closer to the actual product hypothesis: can the system diagnose live incidents more accurately and efficiently when it has both historical context and code? "
            "The ablation is a secondary experiment used to isolate the contribution of TraceLog formatting itself."
        ),
        nbf.v4.new_code_cell(
            "from pathlib import Path\n"
            "from IPython.display import Markdown, display\n"
            "import json\n"
            "import sys\n"
            "\n"
            "PROJECT_ROOT = Path.cwd().resolve()\n"
            "for candidate in [PROJECT_ROOT, *PROJECT_ROOT.parents]:\n"
            "    if (candidate / 'tracelog').exists():\n"
            "        PROJECT_ROOT = candidate\n"
            "        break\n"
            "if str(PROJECT_ROOT) not in sys.path:\n"
            "    sys.path.insert(0, str(PROJECT_ROOT))\n"
            "\n"
            "from tracelog.eval.benchmarking import (\n"
            "    BenchmarkConfig,\n"
            "    dataset_status_rows,\n"
            "    diagnosis_rows,\n"
            "    failure_case_rows,\n"
            "    final_verdict_markdown,\n"
            "    inventory_rows,\n"
            "    load_results,\n"
            "    markdown_table,\n"
            "    operational_rows,\n"
            "    retrieval_rows,\n"
            "    run_benchmark,\n"
            "    split_rows,\n"
            ")\n"
            "\n"
            "BASE_DIR = PROJECT_ROOT / 'docs' / 'eval' / 'benchmark'\n"
            "MODE = 'analysis'  # switch to 'run' to regenerate the benchmark\n"
            "CONFIG = BenchmarkConfig(base_dir=BASE_DIR, top_k=3, overwrite=True)\n"
            "\n"
            "if MODE == 'run':\n"
            "    results = run_benchmark(CONFIG)\n"
            "else:\n"
            "    results = load_results(BASE_DIR)\n"
            "\n"
            "display(Markdown(f\"Loaded benchmark results generated at `{results['generated_at']}`\"))"
        ),
        nbf.v4.new_markdown_cell("## 1. Experiment Configuration"),
        nbf.v4.new_markdown_cell(
            "This section shows the current execution mode and benchmark configuration. "
            "`analysis` reads existing artifacts, while `run` regenerates the dataset and reruns the full benchmark. "
            "`top_k` is the number of historical incidents retrieved during the retrieval stage."
        ),
        nbf.v4.new_code_cell(
            "display(Markdown('```json\\n' + json.dumps(results['config'], indent=2) + '\\n```'))"
        ),
        nbf.v4.new_markdown_cell("## 2. Scenario Inventory"),
        nbf.v4.new_markdown_cell(
            "This table shows the incident inventory included in the benchmark. "
            "Each row is one incident and shows its scenario family, the ground-truth root cause function, and the surface error function. "
            "The root cause is the upstream origin of the bug, while the surface error is the point where the failure becomes visible."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(inventory_rows(results))))"),
        nbf.v4.new_markdown_cell("## 3. Dataset Generation Status"),
        nbf.v4.new_markdown_cell(
            "This section checks whether the required artifacts were generated for each incident. "
            "If `standard_log`, `tracelog_dump`, `aggregated_trace`, and `truth` are all `True`, "
            "that incident is fully available for the benchmark."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(dataset_status_rows(results))))"),
        nbf.v4.new_markdown_cell("## 4. Historical / Query Split Check"),
        nbf.v4.new_markdown_cell(
            "This table shows how the retrieval corpus and holdout queries are separated. "
            "`historical` incidents are searchable corpus items, and `query` incidents are diagnosis targets. "
            "If these splits leak into each other, the benchmark becomes invalid."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(split_rows(results))))"),
        nbf.v4.new_markdown_cell("## 5. Retrieval Evaluation (Ablation Lens)"),
        nbf.v4.new_markdown_cell(
            "This section measures retrieval quality itself. "
            "At the moment it is interpreted as an ablation lens for the logs-only comparison. "
            "`SameRootCauseHit@K` means the top K results contain an incident with the same root-cause family. "
            "`MRR` measures how early a relevant incident appears, and `nDCG@3` measures ranking quality within the top 3 results."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(retrieval_rows(results))))"),
        nbf.v4.new_markdown_cell("## 6. Diagnosis Evaluation (Primary First)"),
        nbf.v4.new_markdown_cell(
            "This is the main table. It shows the code-aware primary benchmark first, then the logs-only ablation. "
            "`root_cause_accuracy` measures whether the upstream origin was identified correctly, and `surface_accuracy` measures whether the visible failure point was identified correctly. "
            "`evidence_match` and `actionability` are Judge-assigned quality scores in the 0 to 1 range."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(diagnosis_rows(results))))"),
        nbf.v4.new_markdown_cell("## 7. Failure Case Review"),
        nbf.v4.new_markdown_cell(
            "This section collects only the cases where the Judge marked the root cause as incorrect. "
            "It helps show whether the model stayed near the surface error or successfully traced the issue back to the upstream state origin."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(failure_case_rows(results))))"),
        nbf.v4.new_markdown_cell("## 8. Token / Latency / Cost Summary"),
        nbf.v4.new_markdown_cell(
            "This section measures operational efficiency. "
            "`input_tokens`, `output_tokens`, and `total_tokens` are the basic inputs for LLM cost estimation. "
            "`retrieval_latency`, `diagnosis_latency`, and `time_to_verdict` measure response speed during incident handling. "
            "Even if accuracy improves, the system may still be hard to adopt if the operational cost becomes too high."
        ),
        nbf.v4.new_code_cell("display(Markdown(markdown_table(operational_rows(results))))"),
        nbf.v4.new_markdown_cell("## 9. Final Verdict"),
        nbf.v4.new_markdown_cell(
            "The final conclusion summarizes the primary benchmark and the ablation benchmark separately. "
            "In other words, it distinguishes improvements under the product-facing `logs+code` condition from formatting effects observed in the secondary `logs-only` experiment."
        ),
        nbf.v4.new_code_cell("display(Markdown(final_verdict_markdown(results)))"),
    ]

    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
    nbf.write(nb, notebook_path)
    print(notebook_path)


if __name__ == "__main__":
    main()
