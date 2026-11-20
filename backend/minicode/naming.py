"""Title normalization for minicode recordings.

Implements the naming convention in docs/naming-convention.md:

    <Series>: <Topic>[ - Part <N>]

Legacy titles are cleaned up (recording-tool timestamp suffixes, SharePoint-escaped
characters, inconsistent "Minicode" prefixes, part numbering, embedded dates and
presenter names) and the removed information is kept as structured metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SERIES_LABELS = {
    "minicode": "Minicode",
    "project-intro": "Project Intro",
    "training": "Training",
    "ai-series": "AI Series",
    "people": "People & Culture",
}

MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    # Finnish (partitive form used in dates, e.g. "7. syyskuuta 2018")
    "tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4, "toukokuuta": 5,
    "kesäkuuta": 6, "heinäkuuta": 7, "elokuuta": 8, "syyskuuta": 9, "lokakuuta": 10,
    "marraskuuta": 11, "joulukuuta": 12,
}  # fmt: skip

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}

EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f]")
ESCAPED_UNDERSCORE_RE = re.compile(r"\\+_")
TEAMS_FILENAME_COLON_RE = re.compile(r"(?<=\w)_(?=\s)")  # Teams file names: "Minicode: X" -> "Minicode_ X"
OPTIONAL_RE = re.compile(r"^\s*\(optional\)\s*", re.I)
MANDATORY_BRACKET_RE = re.compile(r"^\s*\[mandatory[^\]]*\]\s*", re.I)
RECORDING_SUFFIX_RE = re.compile(r"-(\d{4})(\d{2})(\d{2})_\d{4,6}(?:-Meeting Recording)?\s*$")
LONG_TIMESTAMP_RE = re.compile(
    r"\s*-\s*(?:[^\W\d_]+,?\s+)?(?P<day>\d{1,2})\.?\s+(?P<month>[^\W\d_]+)\s+(?P<year>\d{4})"
    r"\s+\d{1,2}\.\d{2}\.\d{2}\s*$"
)
ISO_DATE_RE = re.compile(r"\s*-\s*(\d{4})-(\d{2})-(\d{2})(?=\s*-|\s*$)")
DMY_DATE_RE = re.compile(r"\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
FRACTION_PART_RE = re.compile(r"[\s,]+(?:(?i:part|pt\.)\s*)?(\d)/(\d)\s*$")
MONTH_YEAR_RE = re.compile(r"\s+(\d{1,2})/(\d{4}|\d{2})\s*$")
PART_RE = re.compile(r"\s*[-,]?\s*\b(?i:part|pt\.)\s*(\d+|[IVX]+)\b(?:/\d+)?")
LEVEL_RE = re.compile(r"\s*-?\s*\b(?i:level)\s*([1-4]00)(?:\s*/\s*([1-4]00))?\b")

SERIES_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "minicode",
        re.compile(
            r"^\[?(?:zure\s+ai\s+|deepdata\s+|zureops\s+|surprise\s+)?mini[\s-]?[ck]ode\]?"
            r"(?:\s*\(\?\))?(?:\s*\(nano edition\))?\s*(?:[:\-]\s*|\s+|$)",
            re.I,
        ),
    ),
    ("project-intro", re.compile(r"^(?:double\s+)?(?:project|poc)\s+intro\s*[:\-]\s*", re.I)),
    ("ai-series", re.compile(r"^ai\s+series\s*:\s*", re.I)),
    ("training", re.compile(r"^(?:mini)?training\s*[:\-]\s*", re.I)),
    ("training", re.compile(r"^(?P<guild>[\w&\s]+?)\s+guild(?:\s+training)?\s*[:\-]\s*", re.I)),
    ("people", re.compile(r"^(?:mini(?:hr|culture|rant)|people\s*&\s*culture)\s*:\s*", re.I)),
]

_NAME = r"[A-ZÅÄÖ][a-zåäö]+ [A-ZÅÄÖ][a-zåäö]+"
JOIN_PRESENTER_RE = re.compile(r"\bJoin ([A-ZÅÄÖ]\w+(?: [A-ZÅÄÖ]\w+)?) as (?:he|she|they) presents\b")
LEADING_PRESENTER_RE = re.compile(rf"^({_NAME})\s+-\s+(.+)$")
TRAILING_PRESENTER_RE = re.compile(rf"^(.+?)\s+-\s+({_NAME})$")
NAME_ONLY_RE = re.compile(rf"^{_NAME}$")
# First words that look like "Firstname Lastname" but are not people.
NOT_PERSON_WORDS = {"Case", "Design", "Project", "Azure", "Microsoft", "Lessons", "Data", "Zure"}


@dataclass(frozen=True)
class NormalizedTitle:
    original: str
    series: str
    title: str
    part: int | None = None
    presenter: str | None = None
    date_hint: str | None = None  # "YYYY", "YYYY-MM" or "YYYY-MM-DD" found in the legacy title
    level_hint: int | None = None
    guild: str | None = None
    mandatory: bool = False
    optional: bool = False
    series_inferred: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display(self) -> str:
        text = f"{SERIES_LABELS[self.series]}: {self.title}"
        if self.part is not None:
            text += f" - Part {self.part}"
        return text

    @property
    def dedupe_key(self) -> str:
        key = re.sub(r"[^0-9a-zåäö]+", "", self.title.lower())
        return f"{key}#{self.part or ''}"


def _date(year: int, month: int | None = None, day: int | None = None) -> str:
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -:,")


def normalize_title(raw: str) -> NormalizedTitle:
    """Normalize a legacy recording title into the naming convention."""
    notes: list[str] = []
    s = EMOJI_RE.sub("", raw)
    s = ESCAPED_UNDERSCORE_RE.sub(":", s)
    s = TEAMS_FILENAME_COLON_RE.sub(":", s)
    s = _collapse(s)

    optional = bool(OPTIONAL_RE.match(s))
    s = OPTIONAL_RE.sub("", s)
    mandatory = bool(MANDATORY_BRACKET_RE.match(s)) or "mandatory" in s.lower()
    s = MANDATORY_BRACKET_RE.sub("", s)

    date_hint: str | None = None
    if m := RECORDING_SUFFIX_RE.search(s):
        date_hint = _date(int(m[1]), int(m[2]), int(m[3]))
        s = s[: m.start()].rstrip("_")  # trailing "_" = a "?" or "/" that Teams replaced in the file name
    elif (m := LONG_TIMESTAMP_RE.search(s)) and m["month"].lower() in MONTHS:
        date_hint = _date(int(m["year"]), MONTHS[m["month"].lower()], int(m["day"]))
        s = s[: m.start()]
    if m := ISO_DATE_RE.search(s):
        date_hint = date_hint or _date(int(m[1]), int(m[2]), int(m[3]))
        s = s[: m.start()] + s[m.end() :]
    if m := DMY_DATE_RE.search(s):
        date_hint = date_hint or _date(int(m[3]), int(m[2]), int(m[1]))
        s = s[: m.start()]

    part: int | None = None
    if m := FRACTION_PART_RE.search(s):
        part = int(m[1])
        s = s[: m.start()]
    elif (m := MONTH_YEAR_RE.search(s)) and 1 <= int(m[1]) <= 12:
        year = int(m[2]) if len(m[2]) == 4 else 2000 + int(m[2])
        date_hint = date_hint or _date(year, int(m[1]))
        s = s[: m.start()]
    if m := PART_RE.search(s):
        token = m[1]
        part = int(token) if token.isdigit() else ROMAN.get(token)
        s = s[: m.start()] + s[m.end() :]

    level_hint: int | None = None
    if m := LEVEL_RE.search(s):
        level_hint = max(int(x) for x in (m[1], m[2]) if x)
        s = s[: m.start()] + s[m.end() :]

    s = _collapse(s)
    series, guild, series_inferred = "minicode", None, True
    for candidate, pattern in SERIES_PATTERNS:
        if m := pattern.match(s):
            series, series_inferred = candidate, False
            guild = m.groupdict().get("guild")
            guild = _collapse(guild) if guild else None
            s = s[m.end() :]
            break
    if series_inferred:
        if re.search(r"projekti-intro|project intro", s, re.I):
            series = "project-intro"
        elif mandatory or re.search(r"\bkoulutus\b", s, re.I):
            series = "training"
    s = _collapse(s)

    presenter: str | None = None
    if m := JOIN_PRESENTER_RE.search(s):
        presenter = m[1]
    elif (m := LEADING_PRESENTER_RE.match(s)) and m[1].split()[0] not in NOT_PERSON_WORDS:
        presenter, s = m[1], m[2]
    elif (m := TRAILING_PRESENTER_RE.match(s)) and m[2].split()[0] not in NOT_PERSON_WORDS:
        s, presenter = m[1], m[2]
    elif date_hint and series_inferred and NAME_ONLY_RE.match(s):
        # Old Teams recordings were auto-named "<organizer> - <timestamp>" (no series prefix).
        presenter, s = s, ""
        notes.append("title contains only a presenter name")

    s = _collapse(s)
    if not s:
        s = "Untitled recording"
        notes.append("no topic in title")
    s = s[0].upper() + s[1:]

    return NormalizedTitle(
        original=raw,
        series=series,
        title=s,
        part=part,
        presenter=presenter,
        date_hint=date_hint,
        level_hint=level_hint,
        guild=guild,
        mandatory=mandatory,
        optional=optional,
        series_inferred=series_inferred,
        notes=tuple(notes),
    )
