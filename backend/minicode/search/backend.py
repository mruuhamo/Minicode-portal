"""Search backend abstraction shared by the Azure AI Search and local dev implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


class IndexNotFound(KeyError):
    """The index does not exist yet (nothing has been indexed)."""


def odata_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _day(value: str | date | None, end: bool = False) -> str | None:
    if value is None or value == "":
        return None
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{d.isoformat()}T{'23:59:59' if end else '00:00:00'}Z"


@dataclass
class Filters:
    """Facet filters: OR within a facet, AND across facets."""

    topics: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)
    presenters: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    date_from: str | None = None  # YYYY-MM-DD inclusive
    date_to: str | None = None  # YYYY-MM-DD inclusive
    recording_ids: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    include_hidden: bool = False

    def __post_init__(self) -> None:
        for bound in (self.date_from, self.date_to):
            if bound:
                date.fromisoformat(str(bound)[:10])  # raises ValueError on bad input

    def to_odata(self) -> str | None:
        clauses: list[str] = []
        if self.topics:
            clauses.append("topics/any(t: " + " or ".join(f"t eq {odata_literal(v)}" for v in self.topics) + ")")
        for name, values in (
            ("contentType", self.content_types),
            ("level", [int(v) for v in self.levels]),
            ("presenter", self.presenters),
            ("language", self.languages),
            ("recordingId", self.recording_ids),
            ("kind", self.kinds),
        ):
            if values:
                clauses.append("(" + " or ".join(f"{name} eq {odata_literal(v)}" for v in values) + ")")
        if lo := _day(self.date_from):
            clauses.append(f"date ge {lo}")
        if hi := _day(self.date_to, end=True):
            clauses.append(f"date le {hi}")
        if not self.include_hidden:
            clauses.append("hidden ne true")
        return " and ".join(clauses) or None

    def matches(self, doc: dict[str, Any]) -> bool:
        """Same semantics as to_odata(), evaluated in Python (local backend)."""
        if self.topics and not set(self.topics) & set(doc.get("topics") or []):
            return False
        for key, values in (
            ("contentType", self.content_types),
            ("level", [int(v) for v in self.levels]),
            ("presenter", self.presenters),
            ("language", self.languages),
            ("recordingId", self.recording_ids),
            ("kind", self.kinds),
        ):
            if values and doc.get(key) not in values:
                return False
        d = doc.get("date")
        if (lo := _day(self.date_from)) and (not d or d < lo):
            return False
        if (hi := _day(self.date_to, end=True)) and (not d or d > hi):
            return False
        return self.include_hidden or doc.get("hidden") is not True


@dataclass
class SearchRequest:
    text: str | None = None  # None or "*" = match all
    vector: list[float] | None = None
    filters: Filters = field(default_factory=Filters)
    facets: list[str] = field(default_factory=list)
    top: int = 10
    skip: int = 0
    order_by: list[tuple[str, bool]] = field(default_factory=list)  # (field, descending)
    select: list[str] | None = None
    highlight: list[str] = field(default_factory=list)
    semantic: bool = False
    vector_k: int = 50
    facet_count: int = 50


@dataclass
class Hit:
    doc: dict[str, Any]
    score: float
    highlights: dict[str, list[str]] = field(default_factory=dict)
    reranker_score: float | None = None


@dataclass
class SearchResponse:
    hits: list[Hit]
    facets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    count: int | None = None


class SearchBackend(Protocol):
    def ensure_index(self, definition: dict[str, Any]) -> None: ...

    def upload(self, index: str, docs: list[dict[str, Any]], merge: bool = False) -> None: ...

    def delete(self, index: str, ids: list[str]) -> None: ...

    def get(self, index: str, key: str) -> dict[str, Any] | None: ...

    def search(self, index: str, request: SearchRequest) -> SearchResponse: ...
