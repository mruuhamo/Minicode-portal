"""Tag taxonomy loading and keyword-based tagging (week-1 bootstrap before LLM enrichment)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from minicode.naming import NormalizedTitle, normalize_title
from minicode.paths import TAXONOMY_FILE

LEVEL_MATCH_ORDER = (400, 300, 100, 200)


@dataclass(frozen=True)
class Tag:
    id: str
    label: str
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


@dataclass(frozen=True)
class Dimension:
    id: str
    multi: bool
    tags: tuple[Tag, ...]
    default: str | None = None
    fallback: str | None = None

    def tag_ids(self) -> list[str]:
        return [t.id for t in self.tags]

    def get(self, tag_id: str) -> Tag | None:
        return next((t for t in self.tags if t.id == tag_id), None)


@dataclass(frozen=True)
class Taxonomy:
    version: int
    dimensions: dict[str, Dimension]

    @property
    def topic(self) -> Dimension:
        return self.dimensions["topic"]

    @property
    def content_type(self) -> Dimension:
        return self.dimensions["content_type"]

    @property
    def level(self) -> Dimension:
        return self.dimensions["level"]


@dataclass(frozen=True)
class TagResult:
    topics: tuple[str, ...]
    content_type: str
    level: int
    level_source: str  # "explicit" | "keyword" | "default"


def compile_keyword(keyword: str) -> re.Pattern[str]:
    prefix = keyword.endswith("*")
    body = re.escape(keyword.rstrip("*").lower())
    return re.compile(rf"(?<!\w){body}" + ("" if prefix else r"(?!\w)"))


def _load_dimension(dim_id: str, raw: dict) -> Dimension:
    tags = tuple(
        Tag(
            id=str(t["id"]),
            label=t["label"],
            patterns=tuple(compile_keyword(str(k)) for k in t.get("keywords") or []),
        )
        for t in raw["tags"]
    )
    default = raw.get("default")
    return Dimension(
        id=dim_id,
        multi=bool(raw.get("multi", False)),
        tags=tags,
        default=None if default is None else str(default),
        fallback=raw.get("fallback"),
    )


@lru_cache(maxsize=4)
def load_taxonomy(path: Path = TAXONOMY_FILE) -> Taxonomy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Taxonomy(
        version=int(raw["version"]),
        dimensions={k: _load_dimension(k, v) for k, v in raw["dimensions"].items()},
    )


def tag_title(raw_title: str, taxonomy: Taxonomy | None = None) -> TagResult:
    taxonomy = taxonomy or load_taxonomy()
    normalized: NormalizedTitle = normalize_title(raw_title)
    text = f"{raw_title} | {normalized.title}".lower()

    topic_dim = taxonomy.topic
    topics = tuple(t.id for t in topic_dim.tags if t.id != topic_dim.fallback and t.matches(text))
    if not topics and topic_dim.fallback:
        topics = (topic_dim.fallback,)

    ct_dim = taxonomy.content_type
    if normalized.series == "project-intro":
        content_type = "project-intro"
    elif normalized.series == "training":
        content_type = "training"
    else:
        content_type = next((t.id for t in ct_dim.tags if t.matches(text)), ct_dim.default)

    level_dim = taxonomy.level
    if normalized.level_hint:
        level, source = normalized.level_hint, "explicit"
    else:
        by_id = {int(t.id): t for t in level_dim.tags}
        matched = next((lvl for lvl in LEVEL_MATCH_ORDER if by_id[lvl].matches(text)), None)
        level, source = (matched, "keyword") if matched else (int(level_dim.default), "default")

    return TagResult(topics=topics, content_type=content_type, level=level, level_source=source)
