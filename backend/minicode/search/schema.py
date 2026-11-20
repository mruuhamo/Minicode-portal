"""Azure AI Search index definitions (REST api-version 2024-07-01) as code.

Two indexes:
- `{prefix}-recordings`: one document per minicode; facets + filters + sort; backs GET /api/minicodes.
- `{prefix}-chunks`: one document per transcript chunk (plus one `kind=summary` doc per minicode)
  carrying the parent's filterable fields, a vector field and a semantic configuration. Backs
  GET /api/search (hybrid BM25 + vector, optional semantic ranker), hits keep start/end seconds.
"""

from __future__ import annotations

from typing import Any

API_VERSION = "2024-07-01"
VECTOR_PROFILE = "minicode-hnsw"
SEMANTIC_CONFIG = "minicode-semantic"
FACETS = ("topics", "contentType", "level", "presenter", "language", "year")
# Language analyzer for transcript text: most content is English, some Finnish. A single standard
# analyzer keeps mixed-language content searchable; per-language fields are an open question.
TEXT_ANALYZER = "standard.lucene"


def _f(name: str, type_: str = "Edm.String", **kw: Any) -> dict[str, Any]:
    field = {
        "name": name,
        "type": type_,
        "searchable": False,
        "filterable": False,
        "sortable": False,
        "facetable": False,
        "retrievable": True,
    }
    field.update(kw)
    if name == "id":
        field["key"] = True
    return field


def _parent_fields() -> list[dict[str, Any]]:
    """Fields shared by both indexes (recording-level metadata)."""
    return [
        _f("title", searchable=True, analyzer=TEXT_ANALYZER),
        _f("summary", searchable=True, analyzer=TEXT_ANALYZER),
        _f("presenter", searchable=True, filterable=True, facetable=True, sortable=True),
        _f("topics", "Collection(Edm.String)", filterable=True, facetable=True),
        _f("contentType", filterable=True, facetable=True),
        _f("level", "Edm.Int32", filterable=True, facetable=True, sortable=True),
        _f("language", filterable=True, facetable=True),
        _f("date", "Edm.DateTimeOffset", filterable=True, sortable=True, facetable=False),
        _f("year", "Edm.Int32", filterable=True, facetable=True, sortable=True),
        _f("keywords", "Collection(Edm.String)", searchable=True, filterable=True),
        _f("webUrl"),
        _f("durationSeconds", "Edm.Int32"),
        _f("hidden", "Edm.Boolean", filterable=True),
    ]


def recordings_index(prefix: str = "minicode") -> dict[str, Any]:
    return {
        "name": f"{prefix}-recordings",
        "fields": [
            _f("id", filterable=True),
            *_parent_fields(),
            _f("rawTitle", searchable=True),
            _f("chunkCount", "Edm.Int32"),
            _f("transcriptSource", filterable=True),
            _f("needsReview", "Edm.Boolean", filterable=True),
            _f("updatedAt", "Edm.DateTimeOffset", sortable=True, filterable=True),
        ],
        "scoringProfiles": [],
    }


def chunks_index(prefix: str = "minicode", dimensions: int = 1024, semantic: bool = True) -> dict[str, Any]:
    index: dict[str, Any] = {
        "name": f"{prefix}-chunks",
        "fields": [
            _f("id", filterable=True),
            _f("recordingId", filterable=True),
            _f("kind", filterable=True, facetable=True),  # "chunk" | "summary"
            _f("chunkIndex", "Edm.Int32", sortable=True),
            _f("start", "Edm.Double", sortable=True),
            _f("end", "Edm.Double"),
            _f("speakers", "Collection(Edm.String)", filterable=True, searchable=True),
            _f("content", searchable=True, analyzer=TEXT_ANALYZER),
            {
                "name": "contentVector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "stored": False,
                "dimensions": dimensions,
                "vectorSearchProfile": VECTOR_PROFILE,
            },
            *_parent_fields(),
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine", "m": 4,
                                                                             "efConstruction": 400, "efSearch": 500}}],
            "profiles": [{"name": VECTOR_PROFILE, "algorithm": "hnsw"}],
        },
    }
    if semantic:
        index["semantic"] = {
            "defaultConfiguration": SEMANTIC_CONFIG,
            "configurations": [
                {
                    "name": SEMANTIC_CONFIG,
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "prioritizedContentFields": [{"fieldName": "content"}, {"fieldName": "summary"}],
                        "prioritizedKeywordsFields": [{"fieldName": "topics"}, {"fieldName": "keywords"}],
                    },
                }
            ],
        }
    return index


def field_names(index: dict[str, Any]) -> set[str]:
    return {f["name"] for f in index["fields"]}


def facetable(index: dict[str, Any]) -> set[str]:
    return {f["name"] for f in index["fields"] if f.get("facetable")}
