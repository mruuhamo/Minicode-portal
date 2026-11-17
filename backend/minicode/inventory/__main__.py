"""CLI: python -m minicode.inventory [--source mock|graph] [--out docs/inventory-report.md] [--csv ...]"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from minicode.inventory.analysis import build_inventory
from minicode.inventory.report import to_csv, to_markdown
from minicode.inventory.sources import GraphRecordingSource, MockRecordingSource, RecordingSource
from minicode.paths import REPO_ROOT, TITLES_FILE


def make_source(name: str, titles: Path) -> RecordingSource:
    if name == "mock":
        return MockRecordingSource(titles)
    if name == "graph":
        return GraphRecordingSource(
            site_id=os.environ.get("MINICODE_SITE_ID", ""),
            drive_id=os.environ.get("MINICODE_DRIVE_ID") or None,
            folder_path=os.environ.get("MINICODE_FOLDER_PATH", "General/Recordings"),
        )
    raise ValueError(f"unknown source {name!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minicode recording inventory")
    parser.add_argument("--source", choices=["mock", "graph"], default="mock")
    parser.add_argument("--titles", type=Path, default=TITLES_FILE, help="title list for the mock source")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "inventory-report.md")
    parser.add_argument("--csv", type=Path, default=REPO_ROOT / "docs" / "inventory.csv")
    args = parser.parse_args(argv)

    source = make_source(args.source, args.titles)
    report = build_inventory(source.list_recordings(), source=source.name)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_markdown(report), encoding="utf-8", newline="\n")
    to_csv(report, args.csv)
    print(
        f"{report.total} recordings ({report.unique_titles} unique) from '{source.name}' -> {args.out}, {args.csv}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
