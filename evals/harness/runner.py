"""Dev runner for the eval suites.

Usage (from a repository checkout with dev dependencies):

    uv run python -m evals.harness.runner capture-baseline
    uv run python -m evals.harness.runner retrieval        # print current metrics
    uv run python -m evals.harness.runner suite            # pytest -m eval
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from evals.harness import wiki_builder
from evals.harness.cases import load_corpus_cases, load_qrels
from evals.harness.retrieval import evaluate_qrels
from evals.harness.store import write_results

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "evals" / "results" / "bm25-baseline.jsonl"
FIXTURE_QRELS = REPO_ROOT / "evals" / "retrieval" / "fixture-qrels.yaml"
CORPUS_DIR = REPO_ROOT / "evals" / "corpus"


def _all_retrieval_results() -> dict[str, dict[str, Any]]:
    """Evaluate every qrels set against freshly built wikis: scope -> result."""

    from fixtures.factory import build_clean_home

    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="hermes-wiki-evals-") as temp_dir:
        fixture = build_clean_home(Path(temp_dir) / "fixture-home")
        qrels = load_qrels(FIXTURE_QRELS)
        if qrels:
            with wiki_builder.wiki_env(fixture.home, slug=fixture.primary_slug):
                results["fixture-home"] = evaluate_qrels(qrels, wiki=fixture.primary_slug)

        for case in load_corpus_cases(CORPUS_DIR):
            if case.relevance is None:
                continue
            home = Path(temp_dir) / f"case-{case.name}"
            slug = f"eval-{case.name}"
            wiki_builder.build_corpus_wiki(
                home,
                slug=slug,
                domain=f"eval corpus: {case.name}",
                sources=case.sources,
            )
            with wiki_builder.wiki_env(home, slug=slug):
                results[case.name] = evaluate_qrels(case.relevance, wiki=slug)
    return results


def cmd_capture_baseline() -> int:
    """Write current aggregate retrieval metrics as the committed baseline."""

    rows = []
    for scope, result in sorted(_all_retrieval_results().items()):
        for metric, value in sorted(result["aggregate"].items()):
            rows.append(
                {
                    "suite": "retrieval",
                    "scope": scope,
                    "metric": metric,
                    "value": value,
                    "k": result["k"],
                }
            )
    write_results(BASELINE_PATH, rows)
    print(f"wrote {len(rows)} baseline rows to {BASELINE_PATH}")
    return 0


def cmd_retrieval() -> int:
    """Print the full per-query retrieval report as JSON (no baseline write)."""

    report = {
        scope: {"aggregate": result["aggregate"], "queries": result["queries"]}
        for scope, result in sorted(_all_retrieval_results().items())
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_suite(extra: list[str]) -> int:
    """Run the deterministic eval suite (pytest -m eval)."""

    command = [sys.executable, "-m", "pytest", "-m", "eval", str(REPO_ROOT / "evals"), *extra]
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.harness.runner", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capture-baseline", help="write evals/results/bm25-baseline.jsonl")
    subparsers.add_parser("retrieval", help="print the current retrieval report")
    suite = subparsers.add_parser("suite", help="run pytest -m eval")
    suite.add_argument("extra", nargs="*", help="extra pytest args")

    args = parser.parse_args(argv)
    if args.command == "capture-baseline":
        return cmd_capture_baseline()
    if args.command == "retrieval":
        return cmd_retrieval()
    return cmd_suite(list(args.extra))


if __name__ == "__main__":
    raise SystemExit(main())
