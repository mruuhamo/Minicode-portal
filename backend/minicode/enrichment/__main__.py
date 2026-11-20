"""Enrichment + indexing CLI.

    python -m minicode.enrichment run [--force] [--ids A,B]   enrich ingested recordings, then index them
    python -m minicode.enrichment enrich [--force]            enrichment only
    python -m minicode.enrichment index                       (re)build search documents from the catalogue
    python -m minicode.enrichment search "query" [--tags ai-genai]
    python -m minicode.enrichment show <id>

Settings come from env vars (see minicode/settings.py); defaults are fully local mocks under out/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from minicode.search.backend import Filters
from minicode.settings import AppSettings, Components


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minicode.enrichment", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["run", "enrich", "index", "search", "show"])
    parser.add_argument("arg", nargs="?", help="query (search) or recording id (show)")
    parser.add_argument("--force", action="store_true", help="re-enrich even if inputs are unchanged")
    parser.add_argument("--ids", help="comma-separated recording ids")
    parser.add_argument("--llm", help="override LLM_PROVIDER (mock, mock-a, azure-openai, claude-foundry)")
    parser.add_argument("--data-dir", help="override MINICODE_DATA_DIR")
    parser.add_argument("--tags", help="search filter: comma-separated topic tags")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.data_dir:
        os.environ["MINICODE_DATA_DIR"] = args.data_dir  # also read by the ingestion blob store
    settings = AppSettings.from_env()
    if args.llm:
        settings.llm_provider = args.llm
    c = Components(settings)
    ids = [i for i in (args.ids or "").split(",") if i] or None

    if args.command in ("run", "enrich"):
        summary = c.enrichment_pipeline.run(force=args.force, only=ids)
        print(f"enrichment ({c.llm.name}): {dict(summary.counts)}")
        for rid, err in summary.errors.items():
            print(f"  FAILED {rid}: {err}")
        if summary.needs_review:
            print(f"  needs review: {', '.join(summary.needs_review)}")
        if args.command == "run":
            indexed = c.indexer.sync(None if ids is None else summary.changed, summary.deleted)
            print(f"index ({settings.search_backend}): {indexed}")
        for doc in c.repository.list():
            print(f"  {doc['id'][:14]}  {doc['date'] or '?':10}  {doc['level']}  {doc['title']}  [{', '.join(doc['topics'])}]"
                  f"  presenter={doc['presenter']}")
    elif args.command == "index":
        print(f"index ({settings.search_backend}): {c.indexer.sync()}")
    elif args.command == "search":
        tags = [t for t in (args.tags or "").split(",") if t]
        result = c.search_service.search(args.arg or "", Filters(topics=tags), top=5)
        for item in result["items"]:
            print(f"{item['score']:.4f}  {item['title']}  ({item['presenter']}, {item['date']})")
            for h in item["hits"]:
                print(f"    [{h['startLabel']}] {' … '.join(h['highlights']) or h['text']}")
        print("facets:", json.dumps({k: v[:5] for k, v in result["facets"].items()}, ensure_ascii=False))
    elif args.command == "show":
        if not args.arg:
            parser.error("show needs a recording id")
        print(json.dumps(c.search_service.get_minicode(args.arg, admin=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
