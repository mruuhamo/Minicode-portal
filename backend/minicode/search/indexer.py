"""Push catalogue documents + transcript chunks into the search indexes.

- Chunk vectors are cached in blob `artifacts/embeddings/{id}.json` keyed by text hash, so re-indexing
  after an admin edit or re-enrichment only embeds changed text.
- Admin metadata edits use `update_metadata()`: a merge of the parent fields into the recording doc
  and all its chunk docs, no re-embedding.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

from minicode.enrichment.embeddings import Embedder
from minicode.enrichment.repository import CatalogRepository
from minicode.search.backend import Filters, SearchBackend, SearchRequest
from minicode.search.schema import chunks_index, recordings_index
from minicode.storage import ARTIFACTS, BlobStore, get_json, put_json

log = logging.getLogger(__name__)
KEY_RE = re.compile(r"[^A-Za-z0-9_\-=]")


def search_key(value: str) -> str:
    """Azure AI Search keys allow letters, digits, '_', '-' and '='."""
    return KEY_RE.sub("_", value)


def to_edm_datetime(doc: dict[str, Any]) -> str | None:
    d = doc.get("date")
    recorded = doc.get("recordedAt")
    if recorded and (not d or str(recorded)[:10] == d):
        dt = datetime.fromisoformat(str(recorded).replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{d}T00:00:00Z" if d else None


def parent_fields(doc: dict[str, Any]) -> dict[str, Any]:
    edm = to_edm_datetime(doc)
    return {
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "presenter": doc.get("presenter"),
        "topics": doc.get("topics") or [],
        "contentType": doc.get("contentType"),
        "level": doc.get("level"),
        "language": doc.get("language"),
        "date": edm,
        "year": int(edm[:4]) if edm else None,
        "keywords": doc.get("keywords") or [],
        "webUrl": doc.get("webUrl"),
        "durationSeconds": doc.get("durationSeconds"),
        "hidden": bool(doc.get("hidden")),
    }


def recording_document(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": search_key(doc["id"]),
        **parent_fields(doc),
        "rawTitle": doc.get("rawTitle"),
        "chunkCount": doc.get("chunkCount") or 0,
        "transcriptSource": doc.get("transcriptSource"),
        "listItemUniqueId": doc.get("listItemUniqueId"),
        "needsReview": bool((doc.get("enrichment") or {}).get("needsReview")),
        "updatedAt": (doc.get("updatedAt") or datetime.now(UTC).isoformat()).replace("+00:00", "Z"),
    }


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


class Indexer:
    def __init__(
        self,
        backend: SearchBackend,
        repository: CatalogRepository,
        store: BlobStore,
        embedder: Embedder,
        prefix: str = "minicode",
        semantic: bool = True,
    ) -> None:
        self.backend = backend
        self.repo = repository
        self.store = store
        self.embedder = embedder
        self.recordings_index = recordings_index(prefix)
        self.chunks_index = chunks_index(prefix, embedder.dimensions, semantic)
        self.recordings_name = self.recordings_index["name"]
        self.chunks_name = self.chunks_index["name"]

    def ensure_indexes(self) -> None:
        self.backend.ensure_index(self.recordings_index)
        self.backend.ensure_index(self.chunks_index)

    # --- embeddings ------------------------------------------------------------------------

    def _embed(self, recording_id: str, texts: list[str]) -> list[list[float]]:
        path = f"embeddings/{recording_id}.json"
        cache: dict[str, Any] = get_json(self.store, ARTIFACTS, path) if self.store.exists(ARTIFACTS, path) else {}
        vectors: dict[str, list[float]] = cache.get("vectors", {}) if cache.get("model") == self.embedder.name else {}
        hashes = [_hash(t) for t in texts]
        missing = [(h, t) for h, t in zip(hashes, texts, strict=True) if h not in vectors]
        if missing:
            for (h, _), vec in zip(missing, self.embedder.embed([t for _, t in missing]), strict=True):
                vectors[h] = vec
            keep = {h: vectors[h] for h in hashes}
            put_json(self.store, ARTIFACTS, path, {"model": self.embedder.name, "vectors": keep})
        return [vectors[h] for h in hashes]

    # --- documents ---------------------------------------------------------------------------

    def chunk_documents(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        rid = doc["id"]
        chunks_path = f"chunks/{rid}.json"
        chunks = get_json(self.store, ARTIFACTS, chunks_path)["chunks"] if self.store.exists(ARTIFACTS, chunks_path) else []
        parent = parent_fields(doc)
        summary_text = "\n".join(x for x in (doc.get("title"), doc.get("summary"), ", ".join(doc.get("keywords") or [])) if x)
        docs: list[dict[str, Any]] = [{
            "id": search_key(f"{rid}-summary"), "recordingId": rid, "kind": "summary", "chunkIndex": -1,
            "start": 0.0, "end": 0.0, "speakers": [], "content": summary_text, **parent,
        }]
        for c in chunks:
            docs.append({
                "id": search_key(c["id"]), "recordingId": rid, "kind": "chunk", "chunkIndex": c["index"],
                "start": float(c["start"]), "end": float(c["end"]), "speakers": c.get("speakers") or [],
                "content": c["text"], **parent,
            })
        texts = [d["content"] if d["kind"] == "summary" else f"{doc.get('title') or ''}\n{d['content']}" for d in docs]
        for d, vec in zip(docs, self._embed(rid, texts), strict=True):
            d["contentVector"] = vec
        return docs

    def _existing_chunk_ids(self, recording_id: str) -> set[str]:
        req = SearchRequest(filters=Filters(recording_ids=[recording_id], include_hidden=True), top=1000, select=["id"])
        return {h.doc["id"] for h in self.backend.search(self.chunks_name, req).hits}

    def index_recording(self, recording_id: str) -> int:
        doc = self.repo.get(recording_id)
        if doc is None:
            self.remove(recording_id)
            return 0
        chunk_docs = self.chunk_documents(doc)
        stale = self._existing_chunk_ids(recording_id) - {d["id"] for d in chunk_docs}
        self.backend.upload(self.recordings_name, [recording_document(doc)])
        self.backend.upload(self.chunks_name, chunk_docs)
        if stale:
            self.backend.delete(self.chunks_name, sorted(stale))
        return len(chunk_docs)

    def update_metadata(self, recording_id: str) -> None:
        """Push edited parent fields (title/tags/...) without re-embedding."""
        doc = self.repo.get(recording_id)
        if doc is None:
            return
        self.backend.upload(self.recordings_name, [recording_document(doc)])
        parent = parent_fields(doc)
        ids = self._existing_chunk_ids(recording_id)
        if ids:
            self.backend.upload(self.chunks_name, [{"id": i, **parent} for i in sorted(ids)], merge=True)

    def remove(self, recording_id: str) -> None:
        ids = self._existing_chunk_ids(recording_id)
        if ids:
            self.backend.delete(self.chunks_name, sorted(ids))
        self.backend.delete(self.recordings_name, [search_key(recording_id)])

    def sync(self, changed: list[str] | None = None, deleted: list[str] | None = None) -> dict[str, int]:
        """Index `changed` ids (default: whole catalogue) and remove `deleted` ones."""
        self.ensure_indexes()
        ids = changed if changed is not None else [d["id"] for d in self.repo.list()]
        chunks = sum(self.index_recording(i) for i in ids)
        for rid in deleted or []:
            self.remove(rid)
        log.info("indexed %d recordings (%d docs), removed %d", len(ids), chunks, len(deleted or []))
        return {"recordings": len(ids), "documents": chunks, "removed": len(deleted or [])}
