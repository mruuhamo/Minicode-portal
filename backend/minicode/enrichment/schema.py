"""Structured enrichment output: JSON schema sent to the model + strict validation.

The JSON schema is "strict mode" compatible (Azure OpenAI structured outputs / Claude tool
input): every property is required, nullable values use ["type", "null"], no additionalProperties
and no keywords strict mode rejects (minLength, maxItems, pattern...). Those limits are enforced
by `validate()` instead, whose error messages are fed back to the model on retry.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from minicode.taxonomy import Taxonomy, load_taxonomy

SCHEMA_NAME = "minicode_enrichment"
PROMPT_VERSION = "2026-11-v1"
LEVELS = (100, 200, 300, 400)
MAX_TOPICS = 3
TITLE_MAX = 120
SUMMARY_MIN, SUMMARY_MAX = 60, 1200
FILE_ARTEFACT_RE = re.compile(r"\d{8}_\d{4,6}|Meeting Recording|\\_|\.mp4\b", re.I)
LANGUAGE_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
REQUIRED = ("title", "summary", "presenter", "date", "topics", "content_type", "level", "language", "keywords", "confidence")


@dataclass
class Enrichment:
    title: str
    summary: str
    presenter: str | None
    date: str | None
    topics: list[str]
    content_type: str
    level: int
    language: str
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def json_schema(taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    t = taxonomy or load_taxonomy()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(REQUIRED),
        "properties": {
            "title": {"type": "string", "description": "Display title following the naming convention '<Series>: <Topic>'"},
            "summary": {"type": "string", "description": "2-4 sentence summary of what the recording teaches"},
            "presenter": {"type": ["string", "null"], "description": "Full name of the main presenter, null if unknown"},
            "date": {"type": ["string", "null"], "description": "Recording date YYYY-MM-DD"},
            "topics": {
                "type": "array",
                "items": {"type": "string", "enum": t.topic.tag_ids()},
                "description": f"1-{MAX_TOPICS} topic tag ids, most relevant first",
            },
            "content_type": {"type": "string", "enum": t.content_type.tag_ids()},
            "level": {"type": "integer", "enum": list(LEVELS)},
            "language": {"type": "string", "description": "Spoken language, BCP-47 e.g. fi-FI or en-US"},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Up to 8 search keywords"},
            "confidence": {"type": "number", "description": "0-1 confidence in the tags"},
        },
    }


@dataclass
class ValidationResult:
    enrichment: Enrichment | None  # None = unusable output (retry or fail)
    errors: list[str]
    tag_errors_only: bool  # output usable after dropping invalid tags

    @property
    def ok(self) -> bool:
        return not self.errors


def _topic_lookup(t: Taxonomy) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for tag in t.topic.tags:
        lookup[tag.id] = tag.id
        lookup[tag.label.lower()] = tag.id
    return lookup


def validate(data: Any, taxonomy: Taxonomy | None = None) -> ValidationResult:
    """Validate and lightly coerce model output. Invalid tags are dropped but still reported as errors."""
    t = taxonomy or load_taxonomy()
    errors: list[str] = []
    tag_errors: list[str] = []
    if not isinstance(data, dict):
        return ValidationResult(None, ["output must be a JSON object"], False)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        errors.append(f"missing properties: {', '.join(missing)}")

    def text(key: str, nullable: bool = False) -> str | None:
        v = data.get(key)
        if v is None and nullable:
            return None
        if not isinstance(v, str) or not v.strip():
            errors.append(f"'{key}' must be a non-empty string" + (" or null" if nullable else ""))
            return None
        return v.strip()

    title = text("title")
    if title and (len(title) > TITLE_MAX or FILE_ARTEFACT_RE.search(title)):
        errors.append(f"'title' must be at most {TITLE_MAX} chars without file-name artefacts (dates, 'Meeting Recording')")
    summary = text("summary")
    if summary and not SUMMARY_MIN <= len(summary) <= SUMMARY_MAX:
        errors.append(f"'summary' must be {SUMMARY_MIN}-{SUMMARY_MAX} characters (got {len(summary)})")
    presenter = text("presenter", nullable=True)
    if presenter and (len(presenter) > 80 or re.fullmatch(r"(?i)speaker\s*\d+|unknown|n/?a", presenter)):
        presenter = None  # generic diarization labels are not names

    rec_date = data.get("date")
    if rec_date is not None:
        try:
            rec_date = date.fromisoformat(str(rec_date)[:10]).isoformat()
        except ValueError:
            errors.append("'date' must be YYYY-MM-DD or null")
            rec_date = None

    lookup = _topic_lookup(t)
    raw_topics = data.get("topics")
    topics: list[str] = []
    if not isinstance(raw_topics, list) or not raw_topics:
        errors.append(f"'topics' must be a list of 1-{MAX_TOPICS} tag ids")
    else:
        for raw in raw_topics:
            tid = lookup.get(str(raw).strip().lower())
            if tid is None:
                tag_errors.append(f"unknown topic tag {raw!r}; allowed: {', '.join(t.topic.tag_ids())}")
            elif tid not in topics:
                topics.append(tid)
        if len(topics) > MAX_TOPICS:
            tag_errors.append(f"at most {MAX_TOPICS} topics allowed (got {len(topics)})")
            topics = topics[:MAX_TOPICS]
        if t.topic.fallback in topics and len(topics) > 1:
            topics.remove(t.topic.fallback)  # 'general' only when nothing else fits

    content_type = str(data.get("content_type", "")).strip().lower()
    if content_type not in t.content_type.tag_ids():
        tag_errors.append(f"'content_type' must be one of {', '.join(t.content_type.tag_ids())}")
        content_type = str(t.content_type.default)
    try:
        level = int(data.get("level"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        level = 0
    if level not in LEVELS:
        tag_errors.append(f"'level' must be one of {', '.join(map(str, LEVELS))}")
        level = int(t.level.default or 200)

    language = str(data.get("language") or "").strip()
    if not LANGUAGE_RE.match(language):
        errors.append("'language' must be a BCP-47 code like fi-FI or en-US")
    keywords = data.get("keywords") or []
    if not isinstance(keywords, list):
        errors.append("'keywords' must be a list of strings")
        keywords = []
    keywords = [str(k).strip() for k in keywords if str(k).strip()][:8]
    try:
        confidence = min(max(float(data.get("confidence", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.5

    all_errors = errors + tag_errors
    if errors or not title or not summary:
        return ValidationResult(None, all_errors, False)
    if not topics and t.topic.fallback:
        topics = [t.topic.fallback]
    result = Enrichment(
        title=title, summary=summary, presenter=presenter, date=rec_date, topics=topics, content_type=content_type,
        level=level, language=language, keywords=keywords, confidence=confidence,
    )
    return ValidationResult(result, all_errors, bool(tag_errors))
