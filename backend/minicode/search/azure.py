"""Azure AI Search via REST (api-version 2024-07-01), Entra ID auth (Function MI:
'Search Index Data Contributor' + 'Search Service Contributor' for index creation)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from minicode.ingestion.http import AzureIdentityTokenProvider, HttpError, RestClient, TokenProvider
from minicode.search.backend import Hit, IndexNotFound, SearchRequest, SearchResponse
from minicode.search.schema import API_VERSION, SEMANTIC_CONFIG

SEARCH_SCOPE = "https://search.azure.com/.default"
BATCH = 500


class AzureSearchBackend:
    def __init__(
        self,
        endpoint: str,
        tokens: TokenProvider | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        vector_field: str = "contentVector",
    ) -> None:
        self._api_key = api_key
        if tokens is None and not api_key:
            tokens = AzureIdentityTokenProvider(SEARCH_SCOPE)
        self._rest = RestClient(endpoint, None if api_key else tokens, transport=transport)
        self.vector_field = vector_field
        self._params = {"api-version": API_VERSION}

    def _headers(self) -> dict[str, str]:
        return {"api-key": self._api_key} if self._api_key else {}

    def _call(self, method: str, path: str, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return self._rest.request(method, path, params=self._params, headers={**self._headers(), **(headers or {})}, **kw)

    def ensure_index(self, definition: dict[str, Any]) -> None:
        # PUT = create or update; adding fields is allowed, changing existing field types needs a rebuild.
        self._call("PUT", f"/indexes/{quote(definition['name'])}", json=definition, headers={"Prefer": "return=minimal"})

    def upload(self, index: str, docs: list[dict[str, Any]], merge: bool = False) -> None:
        action = "merge" if merge else "mergeOrUpload"
        for i in range(0, len(docs), BATCH):
            body = {"value": [{"@search.action": action, **d} for d in docs[i : i + BATCH]]}
            resp = self._call("POST", f"/indexes/{quote(index)}/docs/index", json=body)
            failed = [r for r in resp.json().get("value", []) if not r.get("status")]
            if failed:
                raise RuntimeError(f"{len(failed)} documents failed to index in {index}: {failed[:3]}")

    def delete(self, index: str, ids: list[str]) -> None:
        for i in range(0, len(ids), BATCH):
            body = {"value": [{"@search.action": "delete", "id": k} for k in ids[i : i + BATCH]]}
            self._call("POST", f"/indexes/{quote(index)}/docs/index", json=body)

    def get(self, index: str, key: str) -> dict[str, Any] | None:
        try:
            doc = self._call("GET", f"/indexes/{quote(index)}/docs/{quote(key, safe='')}").json()
        except HttpError as e:
            if e.status_code == 404:
                return None
            raise
        return {k: v for k, v in doc.items() if not k.startswith("@")}

    def build_body(self, request: SearchRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "search": request.text or "*",
            "top": request.top,
            "skip": request.skip,
            "count": True,
            "queryType": "simple",
            "searchMode": "any",
        }
        if odata := request.filters.to_odata():
            body["filter"] = odata
        if request.facets:
            body["facets"] = [f"{f},count:{request.facet_count}" for f in request.facets]
        if request.order_by:
            body["orderby"] = ", ".join(f"{f} {'desc' if d else 'asc'}" for f, d in request.order_by)
        if request.select:
            body["select"] = ",".join(request.select)
        if request.highlight and request.text and request.text != "*":
            body.update(highlight=",".join(request.highlight), highlightPreTag="<em>", highlightPostTag="</em>")
        if request.vector is not None:
            body["vectorQueries"] = [{"kind": "vector", "vector": request.vector, "fields": self.vector_field,
                                      "k": request.vector_k}]
        if request.semantic and request.text and request.text != "*":
            body.update(queryType="semantic", semanticConfiguration=SEMANTIC_CONFIG)
        return body

    def search(self, index: str, request: SearchRequest) -> SearchResponse:
        try:
            resp = self._call("POST", f"/indexes/{quote(index)}/docs/search", json=self.build_body(request))
        except HttpError as e:
            if e.status_code == 404:
                raise IndexNotFound(index) from e
            raise
        data = resp.json()
        hits = [
            Hit(
                doc={k: v for k, v in item.items() if not k.startswith("@")},
                score=item.get("@search.score", 0.0),
                highlights=item.get("@search.highlights") or {},
                reranker_score=item.get("@search.rerankerScore"),
            )
            for item in data.get("value", [])
        ]
        raw_facets = data.get("@search.facets") or {}
        facets = {k: [{"value": f["value"], "count": f["count"]} for f in v] for k, v in raw_facets.items()}
        return SearchResponse(hits, facets, data.get("@odata.count"))
