"""In-process search backend for local dev and tests: BM25 + vector cosine fused with RRF (k=60),
facets, OData-equivalent filters, `<em>` highlights. Mirrors Azure AI Search semantics closely enough
for the demo and the API tests; relevance is of course not identical. Persisted as JSON per index.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from minicode.enrichment.embeddings import stem, tokenize
from minicode.search.backend import Hit, IndexNotFound, SearchRequest, SearchResponse
from minicode.storage import atomic_replace

FIELD_WEIGHTS = {"title": 3.0, "keywords": 2.0, "topics": 1.5, "summary": 1.5, "speakers": 1.0, "content": 1.0,
                 "presenter": 2.0, "rawTitle": 1.0}
RRF_K = 60
WORD_RE = re.compile(r"[\wäöåÄÖÅ]+")


def _text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(map(str, value))
    return "" if value is None else str(value)


def highlight(text: str, query_stems: set[str], fragment_chars: int = 220, max_fragments: int = 2) -> list[str]:
    """Return fragments around matching words with matches wrapped in <em></em>."""
    if not text or not query_stems:
        return []
    matches = [m for m in WORD_RE.finditer(text) if stem(m.group().lower()) in query_stems]
    fragments: list[str] = []
    used_until = -1
    for m in matches:
        if m.start() < used_until:
            continue
        start = max(0, m.start() - fragment_chars // 3)
        start = text.rfind(" ", 0, start) + 1 if start > 0 else 0
        end = min(len(text), start + fragment_chars)
        if end < len(text) and (space := text.rfind(" ", m.end(), end)) > 0:
            end = space
        frag = text[start:end]
        frag = WORD_RE.sub(lambda w: f"<em>{w.group()}</em>" if stem(w.group().lower()) in query_stems else w.group(), frag)
        fragments.append(("…" if start > 0 else "") + frag.strip() + ("…" if end < len(text) else ""))
        used_until = end
        if len(fragments) >= max_fragments:
            break
    return fragments


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class LocalSearchBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        self.definitions: dict[str, dict[str, Any]] = {}
        self.docs: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            for p in self.root.glob("*.index.json"):
                data = json.loads(p.read_text(encoding="utf-8"))
                self.definitions[data["definition"]["name"]] = data["definition"]
                self.docs[data["definition"]["name"]] = data["docs"]

    def _save(self, index: str) -> None:
        if self.root:
            p = self.root / f"{index}.index.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"definition": self.definitions[index], "docs": self.docs[index]}, ensure_ascii=False),
                           encoding="utf-8")
            atomic_replace(tmp, p)

    def _require(self, index: str) -> dict[str, Any]:
        if index not in self.definitions:
            raise IndexNotFound(f"index {index!r} does not exist")
        return self.definitions[index]

    # --- management / documents ------------------------------------------------------------

    def ensure_index(self, definition: dict[str, Any]) -> None:
        with self._lock:
            name = definition["name"]
            self.definitions[name] = definition
            self.docs.setdefault(name, {})
            self._save(name)

    def upload(self, index: str, docs: list[dict[str, Any]], merge: bool = False) -> None:
        definition = self._require(index)
        known = {f["name"] for f in definition["fields"]}
        with self._lock:
            store = self.docs[index]
            for doc in docs:
                unknown = set(doc) - known
                if unknown:
                    raise ValueError(f"unknown fields for {index}: {sorted(unknown)}")
                if merge:
                    if doc["id"] not in store:
                        raise KeyError(f"document {doc['id']!r} not found for merge")
                    store[doc["id"]] = {**store[doc["id"]], **doc}
                else:
                    store[doc["id"]] = dict(doc)
            self._save(index)

    def delete(self, index: str, ids: list[str]) -> None:
        self._require(index)
        with self._lock:
            for i in ids:
                self.docs[index].pop(i, None)
            self._save(index)

    def get(self, index: str, key: str) -> dict[str, Any] | None:
        self._require(index)
        doc = self.docs[index].get(key)
        return self._public(index, doc) if doc else None

    def _public(self, index: str, doc: dict[str, Any]) -> dict[str, Any]:
        hidden = {f["name"] for f in self.definitions[index]["fields"] if f.get("retrievable") is False}
        return {k: v for k, v in doc.items() if k not in hidden}

    # --- query --------------------------------------------------------------------------------

    def search(self, index: str, request: SearchRequest) -> SearchResponse:
        definition = self._require(index)
        fields = definition["fields"]
        searchable = [f["name"] for f in fields if f.get("searchable") and f["type"] != "Collection(Edm.Single)"]
        vector_field = next((f["name"] for f in fields if f["type"] == "Collection(Edm.Single)"), None)
        candidates = [d for d in self.docs[index].values() if request.filters.matches(d)]

        text = (request.text or "").strip()
        query_terms = tokenize(text) if text and text != "*" else []
        ranked_lists: list[list[tuple[str, float]]] = []
        if query_terms:
            ranked_lists.append(self._bm25(candidates, searchable, query_terms))
        if request.vector is not None and vector_field:
            sims = [(d["id"], cosine(request.vector, d[vector_field])) for d in candidates if d.get(vector_field)]
            sims = [s for s in sorted(sims, key=lambda s: -s[1]) if s[1] > 0.05][: request.vector_k]
            ranked_lists.append(sims)

        by_id = {d["id"]: d for d in candidates}
        if ranked_lists:
            if len(ranked_lists) == 1:
                scored = ranked_lists[0]
            else:
                fused: Counter[str] = Counter()
                for ranked in ranked_lists:
                    for rank, (doc_id, _) in enumerate(ranked, start=1):
                        fused[doc_id] += 1.0 / (RRF_K + rank)
                scored = sorted(fused.items(), key=lambda s: -s[1])
            matched = [(by_id[i], s) for i, s in scored]
        else:
            matched = [(d, 1.0) for d in candidates]

        for key, desc in reversed(request.order_by):
            present = [p for p in matched if p[0].get(key) is not None]
            present.sort(key=lambda p, k=key: p[0][k], reverse=desc)
            matched = present + [p for p in matched if p[0].get(key) is None]  # missing values last

        facets = self._facets([d for d, _ in matched], request.facets, request.facet_count)
        stems = set(query_terms)
        hits = []
        for doc, score in matched[request.skip : request.skip + request.top]:
            public = self._public(index, doc)
            if request.select:
                public = {k: v for k, v in public.items() if k in request.select or k == "id"}
            hl = {f: frags for f in request.highlight if (frags := highlight(_text(doc.get(f)), stems))}
            hits.append(Hit(public, score, hl, reranker_score=None))
        return SearchResponse(hits, facets, count=len(matched))

    @staticmethod
    def _bm25(docs: list[dict[str, Any]], fields: list[str], terms: list[str], k1: float = 1.2, b: float = 0.75):
        if not docs:
            return []
        tokenized = []
        for d in docs:
            tf: Counter[str] = Counter()
            length = 0.0
            for f in fields:
                toks = tokenize(_text(d.get(f)))
                w = FIELD_WEIGHTS.get(f, 1.0)
                for t in toks:
                    tf[t] += w
                length += len(toks)
            tokenized.append((d["id"], tf, length))
        avg = sum(t[2] for t in tokenized) / len(tokenized) or 1.0
        n = len(tokenized)
        df = Counter(t for _, tf, _ in tokenized for t in set(tf) if t in terms)
        scores = []
        for doc_id, tf, length in tokenized:
            s = 0.0
            for t in set(terms):
                if tf.get(t):
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * length / avg))
            if s > 0:
                scores.append((doc_id, s))
        return sorted(scores, key=lambda x: -x[1])

    @staticmethod
    def _facets(docs: list[dict[str, Any]], names: list[str], limit: int) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            counts: Counter[Any] = Counter()
            for d in docs:
                v = d.get(name)
                for item in v if isinstance(v, list) else [v]:
                    if item not in (None, ""):
                        counts[item] += 1
            out[name] = [{"value": v, "count": c} for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))][:limit]
        return out
