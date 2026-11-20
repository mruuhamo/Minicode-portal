"""Curated minicode catalogue (Cosmos DB) behind a repository abstraction.

Document layout (one per recording, partition key /sourceId = id):
  source fields   rawTitle, webUrl, recordedAt, organizer, durationSeconds, language, transcriptSource, chunkCount
  llm             last validated LLM output (snake_case Enrichment fields)
  enrichment      model, promptVersion, inputHash, enrichedAt, attempts, needsReview
  overrides       admin corrections; *always win* over llm values, survive re-enrichment
  effective       title, summary, presenter, date, topics, contentType, level, keywords (what the API/search show)
Admin edits are also written to an audit container (partition key /recordingId).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from minicode.naming import normalize_title
from minicode.storage import atomic_replace
from minicode.taxonomy import Taxonomy, load_taxonomy, tag_title

# API/document field -> Enrichment attribute
EFFECTIVE_FIELDS = {
    "title": "title",
    "summary": "summary",
    "presenter": "presenter",
    "date": "date",
    "topics": "topics",
    "contentType": "content_type",
    "level": "level",
    "keywords": "keywords",
    "language": "language",
}
OVERRIDABLE = ("title", "summary", "presenter", "date", "topics", "contentType", "level", "keywords", "hidden")


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PatchError(ValueError):
    pass


def fallback_values(doc: dict[str, Any], taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    """Values used before the recording has been enriched (week 1 normalizer + keyword tagger)."""
    raw = doc.get("rawTitle") or doc["id"]
    tags = tag_title(raw, taxonomy)
    norm = normalize_title(raw)
    return {
        "title": norm.display,
        "summary": None,
        "presenter": norm.presenter or doc.get("organizer"),
        "date": (doc.get("recordedAt") or "")[:10] or None,
        "topics": list(tags.topics),
        "contentType": tags.content_type,
        "level": int(tags.level),
        "keywords": [],
        "language": doc.get("language"),
    }


def compute_effective(doc: dict[str, Any], taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    """Recompute top-level fields: overrides > llm > fallback. Mutates and returns doc."""
    base = fallback_values(doc, taxonomy)
    llm = doc.get("llm") or {}
    overrides = doc.get("overrides") or {}
    for key, attr in EFFECTIVE_FIELDS.items():
        value = base[key]
        if llm.get(attr) not in (None, [], ""):
            value = llm[attr]
        if key in overrides:
            value = overrides[key]
        doc[key] = value
    doc["hidden"] = bool(overrides.get("hidden", False))
    doc["overriddenFields"] = sorted(overrides)
    return doc


def new_document(recording_id: str, source: dict[str, Any]) -> dict[str, Any]:
    return {"id": recording_id, "sourceId": recording_id, "status": "active", "llm": None, "enrichment": None,
            "overrides": {}, **source}


def apply_llm(doc: dict[str, Any], llm: dict[str, Any], meta: dict[str, Any], taxonomy: Taxonomy | None = None) -> dict:
    """Re-enrichment replaces only the llm block; overrides are untouched and still win."""
    doc["llm"] = llm
    doc["enrichment"] = meta
    doc["updatedAt"] = utcnow()
    return compute_effective(doc, taxonomy)


def validate_patch(patch: dict[str, Any], taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    """Validate an admin PATCH body. A null value clears the override (field reverts to the LLM value)."""
    t = taxonomy or load_taxonomy()
    if not isinstance(patch, dict) or not patch:
        raise PatchError("body must be a non-empty JSON object")
    unknown = sorted(set(patch) - set(OVERRIDABLE))
    if unknown:
        raise PatchError(f"fields not editable: {', '.join(unknown)}; editable: {', '.join(OVERRIDABLE)}")
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if value is None:
            clean[key] = None
            continue
        if key in ("title", "summary", "presenter"):
            if not isinstance(value, str) or not value.strip() or len(value) > (2000 if key == "summary" else 200):
                raise PatchError(f"'{key}' must be a non-empty string")
            clean[key] = value.strip()
        elif key == "date":
            try:
                clean[key] = date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise PatchError("'date' must be YYYY-MM-DD") from exc
        elif key in ("topics", "keywords"):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise PatchError(f"'{key}' must be a list of strings")
            if key == "topics":
                bad = [v for v in value if v not in t.topic.tag_ids()]
                if bad or not value:
                    raise PatchError(f"unknown topic tags {bad}; allowed: {', '.join(t.topic.tag_ids())}")
            clean[key] = list(dict.fromkeys(v.strip() for v in value))
        elif key == "contentType":
            if value not in t.content_type.tag_ids():
                raise PatchError(f"'contentType' must be one of {', '.join(t.content_type.tag_ids())}")
            clean[key] = value
        elif key == "level":
            if str(value) not in t.level.tag_ids():
                raise PatchError(f"'level' must be one of {', '.join(t.level.tag_ids())}")
            clean[key] = int(value)
        elif key == "hidden":
            if not isinstance(value, bool):
                raise PatchError("'hidden' must be true or false")
            clean[key] = value
    return clean


def apply_patch(doc: dict[str, Any], patch: dict[str, Any], user: str, taxonomy: Taxonomy | None = None) -> dict:
    """Apply a validated patch; returns the audit entry."""
    before = {k: doc.get(k) for k in patch}
    overrides = dict(doc.get("overrides") or {})
    for key, value in patch.items():
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value
    doc["overrides"] = overrides
    doc["updatedAt"] = utcnow()
    compute_effective(doc, taxonomy)
    return {
        "id": str(uuid.uuid4()),
        "recordingId": doc["id"],
        "at": doc["updatedAt"],
        "user": user,
        "changes": {k: {"from": before[k], "to": doc.get(k)} for k in patch},
    }


class CatalogRepository(Protocol):
    def get(self, recording_id: str) -> dict[str, Any] | None: ...
    def upsert(self, doc: dict[str, Any]) -> None: ...
    def delete(self, recording_id: str) -> None: ...
    def list(self) -> Iterator[dict[str, Any]]: ...
    def add_audit(self, entry: dict[str, Any]) -> None: ...
    def audit(self, recording_id: str) -> list[dict[str, Any]]: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []

    def get(self, recording_id: str) -> dict[str, Any] | None:
        doc = self.docs.get(recording_id)
        return json.loads(json.dumps(doc)) if doc else None

    def upsert(self, doc: dict[str, Any]) -> None:
        self.docs[doc["id"]] = json.loads(json.dumps(doc))

    def delete(self, recording_id: str) -> None:
        self.docs.pop(recording_id, None)

    def list(self) -> Iterator[dict[str, Any]]:
        for rid in sorted(self.docs):
            yield self.get(rid)  # type: ignore[misc]

    def add_audit(self, entry: dict[str, Any]) -> None:
        self.audits.append(entry)

    def audit(self, recording_id: str) -> list[dict[str, Any]]:
        return [a for a in self.audits if a["recordingId"] == recording_id]


def _safe_name(recording_id: str) -> str:
    return re.sub(r"[^\w.-]", "_", recording_id)


class LocalJsonRepository:
    """One JSON file per document under <root>/recordings, audit log as JSON lines (dev only)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "recordings").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, recording_id: str) -> Path:
        return self.root / "recordings" / f"{_safe_name(recording_id)}.json"

    def get(self, recording_id: str) -> dict[str, Any] | None:
        p = self._path(recording_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def upsert(self, doc: dict[str, Any]) -> None:
        with self._lock:
            tmp = self._path(doc["id"]).with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            atomic_replace(tmp, self._path(doc["id"]))

    def delete(self, recording_id: str) -> None:
        self._path(recording_id).unlink(missing_ok=True)

    def list(self) -> Iterator[dict[str, Any]]:
        for p in sorted((self.root / "recordings").glob("*.json")):
            yield json.loads(p.read_text(encoding="utf-8"))

    def add_audit(self, entry: dict[str, Any]) -> None:
        with self._lock, (self.root / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def audit(self, recording_id: str) -> list[dict[str, Any]]:
        p = self.root / "audit.jsonl"
        if not p.exists():
            return []
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if r["recordingId"] == recording_id]


class CosmosRepository:
    """Azure Cosmos DB (NoSQL) with Entra ID auth (Function managed identity, 'Cosmos DB Built-in Data Contributor')."""

    def __init__(self, endpoint: str, database: str, container: str, audit_container: str, credential: Any = None) -> None:
        from azure.cosmos import CosmosClient

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        db = CosmosClient(endpoint, credential=credential).get_database_client(database)
        self._docs = db.get_container_client(container)
        self._audit = db.get_container_client(audit_container)

    @staticmethod
    def _strip(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if not k.startswith("_")}

    def get(self, recording_id: str) -> dict[str, Any] | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._strip(self._docs.read_item(recording_id, partition_key=recording_id))
        except CosmosResourceNotFoundError:
            return None

    def upsert(self, doc: dict[str, Any]) -> None:
        self._docs.upsert_item(doc)

    def delete(self, recording_id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self._docs.delete_item(recording_id, partition_key=recording_id)
        except CosmosResourceNotFoundError:
            pass

    def list(self) -> Iterator[dict[str, Any]]:
        for doc in self._docs.query_items("SELECT * FROM c", enable_cross_partition_query=True):
            yield self._strip(doc)

    def add_audit(self, entry: dict[str, Any]) -> None:
        self._audit.create_item(entry)

    def audit(self, recording_id: str) -> list[dict[str, Any]]:
        items = self._audit.query_items(
            "SELECT * FROM c WHERE c.recordingId = @id ORDER BY c.at",
            parameters=[{"name": "@id", "value": recording_id}],
            partition_key=recording_id,
        )
        return [self._strip(i) for i in items]
