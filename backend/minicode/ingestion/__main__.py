"""CLI: run ingestion locally.

    python -m minicode.ingestion backfill --wait            # mock Graph + Speech -> out/blob
    python -m minicode.ingestion incremental
    python -m minicode.ingestion status
    MINICODE_SOURCE=graph MINICODE_SITE_ID=... python -m minicode.ingestion backfill   # real Graph (az login)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from minicode.ingestion.config import Settings, build_pipeline, build_store
from minicode.ingestion.pipeline import PipelineConfig
from minicode.ingestion.state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minicode.ingestion", description="Minicode ingestion (week 2)")
    parser.add_argument("command", choices=["backfill", "incremental", "status"])
    parser.add_argument("--source", choices=["mock", "graph"], help="overrides MINICODE_SOURCE (default mock)")
    parser.add_argument("--out", type=Path, help="local blob root (default out/blob, or MINICODE_LOCAL_STORE)")
    parser.add_argument("--storage", choices=["local", "azure"], help="overrides MINICODE_STORAGE")
    parser.add_argument("--speech", choices=["auto", "azure", "off"], help="overrides MINICODE_SPEECH")
    parser.add_argument("--days", type=int, help="look-back window in days (default 365)")
    parser.add_argument("--since", type=datetime.fromisoformat, help="explicit start date (ISO), overrides --days")
    parser.add_argument("--wait", action="store_true", help="poll Speech jobs until they finish")
    parser.add_argument("--poll-interval", type=float, default=30.0)
    parser.add_argument("--force", action="store_true", help="re-process recordings even if unchanged")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    s = Settings.from_env()
    if args.source:
        s.source = args.source
    if args.out:
        s.local_root = args.out
    if args.storage:
        s.storage = args.storage
    if args.speech:
        s.speech = args.speech
    if args.days:
        s.lookback_days = args.days

    if args.command == "status":
        stages = Counter(m.stage.value for m in StateStore(build_store(s)).all())
        print(json.dumps(dict(stages), indent=2))
        return 0

    poll = args.poll_interval if s.source == "graph" else 0.0
    config = PipelineConfig(force=args.force, wait_for_speech=args.wait, poll_interval=poll)
    pipeline = build_pipeline(s, config=config)
    since = args.since.replace(tzinfo=args.since.tzinfo or UTC) if args.since else None
    if args.command == "backfill":
        summary = pipeline.run_backfill(since=since or datetime.now(UTC) - timedelta(days=s.lookback_days))
    else:
        summary = pipeline.run_incremental()

    for item in summary.items:
        print(f"  {item['outcome']:<24} {item['title']}")
    target = s.local_root if s.storage == "local" else s.blob_endpoint
    print(f"{summary.mode}: {dict(summary.outcomes)} (since {summary.since}) -> {target}")
    for err in summary.errors:
        print(f"  ERROR {err['title']}: {err['error']}", file=sys.stderr)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
