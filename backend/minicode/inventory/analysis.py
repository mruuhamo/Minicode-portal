"""Inventory analysis: counts, duplicates, transcript/status breakdown and title-quality issues."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from minicode.inventory.models import Recording, RecordingStatus
from minicode.naming import (
    LONG_TIMESTAMP_RE,
    RECORDING_SUFFIX_RE,
    NormalizedTitle,
    normalize_title,
)
from minicode.taxonomy import TagResult, Taxonomy, load_taxonomy, tag_title

ISSUES: dict[str, str] = {
    "TIMESTAMP_SUFFIX": "Recording-tool timestamp in title (e.g. '-20221221_11331', '- Friday, 14 December 2018 14.03.11')",
    "DATE_IN_TITLE": "Other date in title (e.g. '17.12.2018', '09/2021', '2018-12-14')",
    "ESCAPED_CHARS": "SharePoint-escaped characters ('\\_' where ':' was)",
    "PREFIX_VARIANT": "Non-canonical Minicode prefix (MiniCode, Mini-Code, Minikode, 'Minicode -', '[Minicode]', ...)",
    "MISSING_SERIES_PREFIX": "No series prefix (Minicode / Project Intro / Training / AI Series / MiniHR ...)",
    "FINNISH": "Finnish title or Finnish words (catalogue language is English)",
    "NON_RECORDING": "Generic or non-minicode item (e.g. 'PowerPoint Presentation', 'Assets')",
    "PRESENTER_IN_TITLE": "Presenter name embedded in title (should be metadata)",
    "PART_NUMBERING": "Inconsistent part numbering (pt. 2, 1/2, Part II, part 2/2)",
    "EMOJI": "Emoji in title",
    "WHITESPACE": "Double or leading/trailing whitespace",
    "ALL_CAPS": "SHOUTING words in title",
}

FINNISH_WORDS = {
    "ja", "käyttö", "läpikäynti", "koulutus", "perjantai", "projekti-intro", "projektissa", "mobiili",
    "kyber", "atk", "seuren", "syyskuuta", "kesäkuuta",
}  # fmt: skip
NON_RECORDING_TITLES = {"powerpoint presentation", "assets", "exports", 'meeting in "minicode"'}
CANONICAL_PREFIX_RE = re.compile(r"^Minicode: \S")
YEAR_RE = re.compile(r"(?<![\w.])(20[12]\d)(?![\w])")
EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")


def title_issues(raw: str, normalized: NormalizedTitle | None = None) -> list[str]:
    n = normalized or normalize_title(raw)
    issues: list[str] = []
    unescaped = re.sub(r"\\+_", ":", raw)
    has_timestamp = bool(RECORDING_SUFFIX_RE.search(unescaped) or LONG_TIMESTAMP_RE.search(unescaped))
    if has_timestamp:
        issues.append("TIMESTAMP_SUFFIX")
    elif n.date_hint:
        issues.append("DATE_IN_TITLE")
    if "\\_" in raw:
        issues.append("ESCAPED_CHARS")
    if n.series == "minicode" and not n.series_inferred and not CANONICAL_PREFIX_RE.match(raw):
        issues.append("PREFIX_VARIANT")
    if n.series_inferred:
        issues.append("MISSING_SERIES_PREFIX")
    if FINNISH_WORDS & set(re.findall(r"[\wåäö-]+", raw.lower())):
        issues.append("FINNISH")
    if n.title.lower() in NON_RECORDING_TITLES or "no topic in title" in n.notes:
        issues.append("NON_RECORDING")
    if n.presenter:
        issues.append("PRESENTER_IN_TITLE")
    if n.part is not None and not re.search(rf" - Part {n.part}$", raw):
        issues.append("PART_NUMBERING")
    if EMOJI_RE.search(raw):
        issues.append("EMOJI")
    if "  " in raw or raw != raw.strip():
        issues.append("WHITESPACE")
    if re.search(r"\b[A-Z]{5,}\b", raw):
        issues.append("ALL_CAPS")
    return issues


@dataclass(frozen=True)
class InventoryItem:
    recording: Recording
    normalized: NormalizedTitle
    tags: TagResult
    issues: tuple[str, ...]


@dataclass
class InventoryReport:
    source: str
    items: list[InventoryItem]
    exact_duplicates: dict[str, int] = field(default_factory=dict)
    near_duplicates: list[list[str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def unique_titles(self) -> int:
        return len({i.recording.title for i in self.items})

    def status_counts(self) -> Counter[RecordingStatus]:
        return Counter(i.recording.status for i in self.items)

    def transcript_counts(self) -> Counter[str]:
        return Counter(
            {True: "yes", False: "no", None: "unknown"}[i.recording.has_transcript] for i in self.items
        )

    def issue_counts(self) -> Counter[str]:
        return Counter(code for i in self.items for code in i.issues)

    def series_counts(self) -> Counter[str]:
        return Counter(i.normalized.series for i in self.items)

    def year_hints(self) -> Counter[str]:
        years: Counter[str] = Counter()
        for i in self.items:
            if i.normalized.date_hint:
                years[i.normalized.date_hint[:4]] += 1
            elif m := YEAR_RE.search(i.recording.title):
                years[m[1]] += 1
        return years


def build_inventory(recordings: Iterable[Recording], source: str, taxonomy: Taxonomy | None = None) -> InventoryReport:
    taxonomy = taxonomy or load_taxonomy()
    items = []
    for rec in recordings:
        n = normalize_title(rec.title)
        items.append(InventoryItem(rec, n, tag_title(rec.title, taxonomy), tuple(title_issues(rec.title, n))))

    raw_counts = Counter(i.recording.title for i in items)
    exact = {title: count for title, count in raw_counts.items() if count > 1}

    by_key: dict[str, list[str]] = defaultdict(list)
    for i in items:
        if i.recording.title not in by_key[i.normalized.dedupe_key]:
            by_key[i.normalized.dedupe_key].append(i.recording.title)
    near = [titles for titles in by_key.values() if len(titles) > 1]

    return InventoryReport(source=source, items=items, exact_duplicates=exact, near_duplicates=near)
