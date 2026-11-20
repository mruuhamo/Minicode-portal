"""Model comparison harness CLI.

    python -m minicode.evaluation --models mock-a,mock-b --judge mock
    python -m minicode.evaluation --models azure-openai,claude-foundry --judge azure-openai,claude-foundry \
        --price azure-openai=0.40/1.60 --price claude-foundry=3/15

Model names are LLM providers as in LLM_PROVIDER (`azure-openai[:deployment]`, `claude-foundry[:deployment]`, `mock-a`, ...).
--price is USD per 1M input/output tokens, keyed by provider prefix.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from minicode.evaluation.harness import DEFAULT_EVALSET, REPO_ROOT, compare, load_evalset
from minicode.evaluation.report import write_report, write_results_json, write_review_csv
from minicode.settings import AppSettings, build_llm


def parse_prices(values: list[str]) -> dict[str, tuple[float, float]]:
    prices = {}
    for v in values:
        name, _, rest = v.partition("=")
        tin, _, tout = rest.partition("/")
        try:
            prices[name.strip()] = (float(tin), float(tout))
        except ValueError as e:
            raise SystemExit(f"--price must look like provider=IN/OUT (USD per 1M tokens), got {v!r}") from e
    return prices


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minicode.evaluation", description="Compare enrichment LLMs")
    parser.add_argument("--models", default="mock-a,mock-b", help="comma-separated LLM providers to compare")
    parser.add_argument("--judge", default="mock", help="comma-separated judge providers (scores are averaged)")
    parser.add_argument("--evalset", type=Path, default=DEFAULT_EVALSET)
    parser.add_argument("--limit", type=int, help="only the first N items (smoke test real keys cheaply)")
    parser.add_argument("--price", action="append", default=[], help="provider=IN/OUT USD per 1M tokens")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "docs" / "model-comparison.md")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "eval", help="directory for CSV + results JSON")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    settings = AppSettings.from_env()
    items = load_evalset(args.evalset)[: args.limit] if args.limit else load_evalset(args.evalset)
    models = [build_llm(settings, m.strip()) for m in args.models.split(",") if m.strip()]
    judges = [build_llm(settings, j.strip()) for j in args.judge.split(",") if j.strip()]
    raw_prices = parse_prices(args.price)
    prices = {m.name: next((p for k, p in raw_prices.items() if m.name == k or m.name.startswith(k + ":")), None)
              for m in models}
    prices = {k: v for k, v in prices.items() if v}

    progress = None if args.quiet else (lambda msg: print(f"  {msg}", file=sys.stderr))
    result = compare(models, judges, items, args.evalset, prices=prices, summary_language=settings.summary_language,
                     progress=progress)

    csv_path, json_path = args.out / "tag-review.csv", args.out / "results.json"
    write_review_csv(result, items, csv_path)
    write_results_json(result, json_path)
    write_report(result, items, args.report, _rel(csv_path), _rel(json_path))
    for s in result.summaries:
        print(f"{s.client:40} composite={s.composite:.3f} judge={s.judge} failures={s.failures}")
    print(f"pick: {result.pick} ({result.pick_reason})")
    print(f"report: {_rel(args.report)}  review sheet: {_rel(csv_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
