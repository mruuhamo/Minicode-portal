"""Query layer used by the API: list with facets, detail with chapters, hybrid search grouped per minicode."""

from __future__ import annotations

import base64
import json
from collections import Counter
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from minicode.enrichment.embeddings import Embedder
from minicode.enrichment.inputs import mmss
from minicode.enrichment.repository import CatalogRepository
from minicode.search.backend import Filters, SearchBackend, SearchRequest
from minicode.search.indexer import parent_fields, search_key
from minicode.search.schema import FACETS, chunks_index, recordings_index

LIST_FIELDS = ("id", "title", "summary", "presenter", "date", "topics", "contentType", "level", "language", "keywords",
               "webUrl", "durationSeconds")
SORTS = {"date": ("date", True), "-date": ("date", True), "+date": ("date", False), "title": ("title", False),
         "level": ("level", False)}
CANDIDATES = 200  # chunk hits fetched per search before grouping by recording


def timestamp_url(web_url: str | None, seconds: float) -> str | None:
    """Open the Stream (SharePoint) player at a position.

    Uses Stream's `nav` parameter (base64 JSON playbackOptions.startTimeInSeconds), the format produced by
    Stream's "Share at current time". UNVERIFIED against the tenant - see docs/week3-enrichment-search.md.
    """
    if not web_url:
        return None
    nav = json.dumps({"playbackOptions": {"startTimeInSeconds": int(seconds)}}, separators=(",", ":"))
    parts = urlsplit(web_url)
    query = (parts.query + "&" if parts.query else "") + urlencode({"nav": base64.b64encode(nav.encode()).decode()})
    return urlunsplit(parts._replace(query=query))


def stream_embed_url(web_url: str | None, unique_id: str | None, start: float | None = None) -> str | None:
    """Stream (on SharePoint) iframe player URL, the format of Stream's "Embed code" dialog.

    `embed` is JSON: `ust` = use start time, `st` = start seconds. The player can only seek by reloading with a new
    `st`; the frontend does that. UNVERIFIED against the tenant - see docs/week4-frontend.md.
    """
    if not web_url or not unique_id:
        return None
    parts = urlsplit(web_url)
    segments = [s for s in parts.path.split("/") if s]
    site = "/" + "/".join(segments[:2]) if len(segments) >= 2 and segments[0] in ("sites", "teams") else ""
    embed: dict[str, Any] = {"ust": True, "hv": "CopyEmbedCode"}
    if start:
        embed["st"] = int(start)
    query = urlencode({"UniqueId": unique_id, "embed": json.dumps(embed, separators=(",", ":")),
                       "referrer": "StreamWebApp", "referrerScenario": "EmbedDialog.Create"})
    return urlunsplit((parts.scheme, parts.netloc, f"{site}/_layouts/15/embed.aspx", query, ""))


def api_view(doc: dict[str, Any], admin: bool = False) -> dict[str, Any]:
    edm = parent_fields(doc)["date"]
    view = {
        "id": doc["id"],
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "presenter": doc.get("presenter"),
        "date": doc.get("date"),
        "recordedAt": edm,
        "topics": doc.get("topics") or [],
        "contentType": doc.get("contentType"),
        "level": doc.get("level"),
        "language": doc.get("language"),
        "keywords": doc.get("keywords") or [],
        "webUrl": doc.get("webUrl"),
        "embedUrl": stream_embed_url(doc.get("webUrl"), doc.get("listItemUniqueId")),
        "durationSeconds": doc.get("durationSeconds"),
        "transcriptSource": doc.get("transcriptSource"),
        "chunkCount": doc.get("chunkCount"),
    }
    if admin:
        view.update(
            rawTitle=doc.get("rawTitle"),
            organizer=doc.get("organizer"),
            hidden=bool(doc.get("hidden")),
            overrides=doc.get("overrides") or {},
            overriddenFields=doc.get("overriddenFields") or [],
            llm=doc.get("llm"),
            enrichment=doc.get("enrichment"),
            enrichmentError=doc.get("enrichmentError"),
        )
    return view


def _facets_from(docs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for name in FACETS:
        counts: Counter[Any] = Counter()
        for d in docs:
            v = d.get(name)
            for item in v if isinstance(v, list) else [v]:
                if item not in (None, ""):
                    counts[item] += 1
        out[name] = [{"value": v, "count": c} for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))]
    return out


class SearchService:
    def __init__(
        self,
        backend: SearchBackend,
        repository: CatalogRepository,
        embedder: Embedder,
        prefix: str = "minicode",
        semantic: bool = False,
    ) -> None:
        self.backend = backend
        self.repo = repository
        self.embedder = embedder
        self.recordings_name = recordings_index(prefix)["name"]
        self.chunks_name = chunks_index(prefix)["name"]
        self.semantic = semantic

    def list_minicodes(self, filters: Filters, top: int = 20, skip: int = 0, sort: str = "date") -> dict[str, Any]:
        if sort not in SORTS:
            raise ValueError(f"sort must be one of {', '.join(SORTS)}")
        req = SearchRequest(filters=filters, facets=list(FACETS), top=top, skip=skip, order_by=[SORTS[sort]],
                            select=list(LIST_FIELDS))
        resp = self.backend.search(self.recordings_name, req)
        items = [{**{k: h.doc.get(k) for k in LIST_FIELDS}, "date": (h.doc.get("date") or "")[:10] or None}
                 for h in resp.hits]
        return {"items": items, "count": resp.count, "top": top, "skip": skip, "facets": resp.facets}

    def get_minicode(self, recording_id: str, admin: bool = False) -> dict[str, Any] | None:
        doc = self.repo.get(recording_id)
        if doc is None or doc.get("status") == "deleted" or (doc.get("hidden") and not admin):
            return None
        view = api_view(doc, admin)
        req = SearchRequest(filters=Filters(recording_ids=[recording_id], kinds=["chunk"], include_hidden=True), top=1000,
                            order_by=[("chunkIndex", False)], select=["id", "start", "end", "speakers", "content"])
        view["chapters"] = [
            {"start": h.doc["start"], "end": h.doc["end"], "startLabel": mmss(h.doc["start"]), "speakers": h.doc.get("speakers"),
             "preview": (h.doc.get("content") or "")[:160], "url": timestamp_url(doc.get("webUrl"), h.doc["start"])}
            for h in self.backend.search(self.chunks_name, req).hits
        ]
        if admin:
            view["audit"] = self.repo.audit(recording_id)[-20:]
        return view

    def search(self, q: str, filters: Filters, top: int = 10, skip: int = 0, hits_per_recording: int = 3) -> dict[str, Any]:
        q = (q or "").strip()
        if not q or q == "*":
            return {"query": q, **self.list_minicodes(filters, top, skip)}
        vector = self.embedder.embed([q])[0]
        req = SearchRequest(text=q, vector=vector, filters=filters, top=CANDIDATES, highlight=["content"],
                            semantic=self.semantic, vector_k=50)
        resp = self.backend.search(self.chunks_name, req)
        groups: dict[str, dict[str, Any]] = {}
        for rank, hit in enumerate(resp.hits):
            d = hit.doc
            rid = d["recordingId"]
            g = groups.get(rid)
            if g is None:
                g = groups[rid] = {
                    "id": rid, **{k: d.get(k) for k in LIST_FIELDS if k != "id"}, "date": (d.get("date") or "")[:10] or None,
                    "score": hit.reranker_score if hit.reranker_score is not None else hit.score, "rank": rank,
                    "matchedSummary": False, "hits": [], "_facet": d,
                }
            if d.get("kind") == "summary":
                g["matchedSummary"] = True
                continue
            if len(g["hits"]) < hits_per_recording:
                highlights = hit.highlights.get("content") or []
                g["hits"].append({
                    "chunkId": d["id"], "start": d["start"], "end": d["end"], "startLabel": mmss(d["start"]),
                    "speakers": d.get("speakers") or [], "highlights": highlights,
                    "text": None if highlights else (d.get("content") or "")[:240],
                    "url": timestamp_url(d.get("webUrl"), d["start"]),
                })
        ordered = sorted(groups.values(), key=lambda g: g["rank"])
        facets = _facets_from([g["_facet"] for g in ordered])
        page = ordered[skip : skip + top]
        for g in page:
            g.pop("_facet")
            g.pop("rank")
        return {"query": q, "items": page, "count": len(ordered), "top": top, "skip": skip, "facets": facets}

    def get_by_key(self, recording_id: str) -> dict[str, Any] | None:
        return self.backend.get(self.recordings_name, search_key(recording_id))
