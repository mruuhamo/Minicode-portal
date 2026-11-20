from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from minicode.enrichment.embeddings import HashEmbedder, stem
from minicode.search.azure import AzureSearchBackend
from minicode.search.backend import Filters, IndexNotFound, SearchRequest, odata_literal
from minicode.search.indexer import search_key
from minicode.search.local import LocalSearchBackend, highlight
from minicode.search.schema import chunks_index, facetable, field_names, recordings_index
from minicode.search.service import timestamp_url
from minicode.taxonomy import load_taxonomy

BICEP = "01MOCK8849C117E2EDD9"


def rid(components, prefix: str) -> str:  # noqa: ANN001
    return next(d["id"] for d in components.repository.list() if d["id"].startswith(prefix))


# --- schema -------------------------------------------------------------------------------------


def test_chunk_index_schema_has_facets_vector_and_semantic_config() -> None:
    idx = chunks_index("mc-dev", dimensions=1024)
    assert idx["name"] == "mc-dev-chunks"
    assert {"topics", "presenter", "level", "contentType", "year"} <= facetable(idx)
    vec = next(f for f in idx["fields"] if f["name"] == "contentVector")
    assert vec["dimensions"] == 1024 and vec["vectorSearchProfile"] in {p["name"] for p in idx["vectorSearch"]["profiles"]}
    fields = {f["name"]: f for f in idx["fields"]}
    assert fields["id"]["key"] is True and fields["start"]["sortable"] and fields["date"]["filterable"] and fields["date"]["sortable"] and fields["topics"]["type"] == "Collection(Edm.String)"
    sem = idx["semantic"]["configurations"][0]["prioritizedFields"]
    assert sem["titleField"]["fieldName"] == "title"
    referenced = {sem["titleField"]["fieldName"], *(f["fieldName"] for k in ("prioritizedContentFields", "prioritizedKeywordsFields")
                                                   for f in sem[k])}
    assert referenced <= field_names(idx)
    assert "semantic" not in chunks_index(semantic=False)


def test_recordings_index_shares_parent_fields() -> None:
    assert {"title", "summary", "topics", "presenter", "date", "level", "hidden"} <= field_names(recordings_index())
    assert all(sum(f.get("key", False) for f in i["fields"]) == 1 for i in (recordings_index(), chunks_index()))


def test_search_key_is_azure_safe() -> None:
    key = search_key("01ABC!x/y=")
    assert key == search_key("01ABC!x/y=") and all(c.isalnum() or c in "-_=" for c in key)


# --- filters -----------------------------------------------------------------------------------


def test_filters_to_odata_and_escaping() -> None:
    f = Filters(topics=["ai-genai", "security-identity"], levels=[200], presenters=["Pekka O'Mäkelä"],
                date_from="2026-01-01", date_to="2026-03-31")
    odata = f.to_odata()
    assert "topics/any(t: t eq 'ai-genai' or t eq 'security-identity')" in odata
    assert "(level eq 200)" in odata and "(presenter eq 'Pekka O''Mäkelä')" in odata
    assert "date ge 2026-01-01T00:00:00Z" in odata and "date le 2026-03-31T23:59:59" in odata
    assert odata.endswith("hidden ne true")
    assert Filters(include_hidden=True).to_odata() is None
    assert odata_literal("a'b") == "'a''b'" and odata_literal(3) == "3"
    with pytest.raises(ValueError):
        Filters(date_from="31.1.2026")


def test_filters_matches_mirror_odata() -> None:
    doc = {"topics": ["ai-genai"], "level": 200, "presenter": "Sara", "date": "2026-04-29T10:00:00Z", "hidden": False}
    assert Filters(topics=["ai-genai", "x"]).matches(doc)
    assert not Filters(topics=["devops-iac"]).matches(doc)
    assert Filters(date_from="2026-04-29", date_to="2026-04-29").matches(doc)
    assert not Filters(date_to="2026-04-28").matches(doc)
    assert not Filters().matches({**doc, "hidden": True}) and Filters(include_hidden=True).matches({**doc, "hidden": True})


# --- local backend ------------------------------------------------------------------------------


def _local(tmp_path) -> LocalSearchBackend:  # noqa: ANN001
    be = LocalSearchBackend(tmp_path)
    be.ensure_index(chunks_index("t", dimensions=32, semantic=False))
    emb = HashEmbedder(32)
    docs = [
        {"id": "a", "recordingId": "r1", "kind": "chunk", "title": "Bicep registry", "content": "Publish Bicep modules to ACR",
         "topics": ["devops-iac"], "presenter": "Aino", "level": 200, "date": "2026-11-02T10:00:00Z", "start": 3.0},
        {"id": "b", "recordingId": "r2", "kind": "chunk", "title": "Threat modeling", "content": "STRIDE and data flow diagrams",
         "topics": ["security-identity"], "presenter": "Jussi", "level": 300, "date": "2026-06-21T10:00:00Z", "start": 60.0},
        {"id": "c", "recordingId": "r3", "kind": "chunk", "title": "Hidden", "content": "Bicep secrets", "hidden": True,
         "topics": ["devops-iac"], "presenter": "X", "level": 100, "date": "2026-01-01T10:00:00Z", "start": 0.0},
    ]
    for d in docs:
        d["contentVector"] = emb.embed([d["title"] + " " + d["content"]])[0]
    be.upload("t-chunks", docs)
    return be


def test_local_hybrid_search_facets_filters_highlights(tmp_path) -> None:  # noqa: ANN001
    be = _local(tmp_path)
    emb = HashEmbedder(32)
    resp = be.search("t-chunks", SearchRequest(text="bicep modules", vector=emb.embed(["bicep modules"])[0],
                                               facets=["topics", "presenter"], highlight=["content"]))
    assert [h.doc["id"] for h in resp.hits][0] == "a"
    assert "c" not in {h.doc["id"] for h in resp.hits}  # hidden excluded by default
    assert "<em>Bicep</em>" in resp.hits[0].highlights["content"][0]
    assert {"value": "devops-iac", "count": 1} in resp.facets["topics"]
    assert "contentVector" not in resp.hits[0].doc  # retrievable: false
    filtered = be.search("t-chunks", SearchRequest(text="*", filters=Filters(presenters=["Jussi"])))
    assert [h.doc["id"] for h in filtered.hits] == ["b"] and filtered.count == 1
    ordered = be.search("t-chunks", SearchRequest(order_by=[("date", True)], filters=Filters(include_hidden=True)))
    assert [h.doc["id"] for h in ordered.hits] == ["a", "b", "c"]


def test_local_backend_persists_merges_deletes(tmp_path) -> None:  # noqa: ANN001
    _local(tmp_path)
    be = LocalSearchBackend(tmp_path)  # reload from disk
    be.upload("t-chunks", [{"id": "a", "title": "Renamed"}], merge=True)
    assert be.get("t-chunks", "a")["title"] == "Renamed" and be.get("t-chunks", "a")["content"].startswith("Publish")
    be.delete("t-chunks", ["a"])
    assert be.get("t-chunks", "a") is None
    with pytest.raises(IndexNotFound):
        be.search("missing", SearchRequest())


def test_highlight_wraps_stemmed_matches() -> None:
    frags = highlight("We publish a module. The module is versioned.", {stem("module")})
    assert frags and frags[0].count("<em>") == 2


# --- Azure backend (mocked REST) ----------------------------------------------------------------


def _azure(handler) -> tuple[list[httpx.Request], AzureSearchBackend]:  # noqa: ANN001
    seen: list[httpx.Request] = []

    def wrapped(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return handler(r)

    return seen, AzureSearchBackend("https://srch.search.windows.net", api_key="k", transport=httpx.MockTransport(wrapped))


def test_azure_build_body_hybrid_semantic() -> None:
    _, be = _azure(lambda r: httpx.Response(200))
    body = be.build_body(SearchRequest(text="bicep", vector=[0.1, 0.2], filters=Filters(topics=["devops-iac"]), facets=["topics"],
                                       highlight=["content"], semantic=True, top=5, vector_k=20))
    assert body["search"] == "bicep" and body["queryType"] == "semantic" and body["semanticConfiguration"]
    assert body["vectorQueries"] == [{"kind": "vector", "vector": [0.1, 0.2], "fields": "contentVector", "k": 20}]
    assert body["facets"] == ["topics,count:50"] and body["highlight"] == "content" and body["top"] == 5
    assert body["filter"].startswith("topics/any(")
    plain = be.build_body(SearchRequest(semantic=True, highlight=["content"]))
    assert plain["search"] == "*" and plain["queryType"] == "simple" and "highlight" not in plain


def test_azure_search_parses_response_and_maps_404() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "missing" in r.url.path:
            return httpx.Response(404, json={"error": {"message": "nope"}})
        assert r.headers["api-key"] == "k" and r.url.params["api-version"]
        return httpx.Response(200, json={
            "@odata.count": 1, "@search.facets": {"topics": [{"value": "ai-genai", "count": 1}]},
            "value": [{"@search.score": 0.5, "@search.rerankerScore": 2.9, "@search.highlights": {"content": ["<em>x</em>"]},
                       "id": "a", "start": 3.0}],
        })

    seen, be = _azure(handler)
    resp = be.search("idx", SearchRequest(text="x"))
    assert resp.count == 1 and resp.hits[0].doc == {"id": "a", "start": 3.0} and resp.hits[0].reranker_score == 2.9
    assert resp.facets == {"topics": [{"value": "ai-genai", "count": 1}]}
    assert seen[0].url.path == "/indexes/idx/docs/search"
    with pytest.raises(IndexNotFound):
        be.search("missing", SearchRequest())


def test_azure_upload_reports_failures() -> None:
    _, be = _azure(lambda r: httpx.Response(200, json={"value": [{"key": "a", "status": False, "errorMessage": "bad"}]}))
    with pytest.raises(RuntimeError, match="failed to index"):
        be.upload("idx", [{"id": "a"}])


# --- indexer + service against the ingested demo ------------------------------------------------


def test_indexer_writes_summary_and_chunk_docs(indexed) -> None:  # noqa: ANN001
    bicep = rid(indexed, BICEP)
    hits = indexed.search_backend.search(indexed.indexer.chunks_name, SearchRequest(filters=Filters(recording_ids=[bicep]), top=100))
    kinds = sorted(h.doc["kind"] for h in hits.hits)
    assert kinds[-1] == "summary" and kinds.count("summary") == 1 and kinds.count("chunk") >= 1
    assert all(h.doc["title"] == "Minicode: Bicep private registry" for h in hits.hits)
    assert indexed.store.exists("artifacts", f"embeddings/{bicep}.json")


def test_indexer_reuses_embeddings_and_removes_stale(indexed, monkeypatch) -> None:  # noqa: ANN001
    bicep = rid(indexed, BICEP)
    calls: list[int] = []
    original = indexed.embedder.embed
    monkeypatch.setattr(indexed.embedder, "embed", lambda texts: calls.append(len(texts)) or original(texts))
    indexed.indexer.index_recording(bicep)
    assert calls == []  # cache hit
    name = indexed.indexer.chunks_name
    indexed.search_backend.upload(name, [{"id": "stale-1", "recordingId": bicep, "kind": "chunk", "content": "old"}])
    indexed.indexer.index_recording(bicep)
    assert indexed.search_backend.get(name, "stale-1") is None


def test_update_metadata_propagates_to_chunks(indexed) -> None:  # noqa: ANN001
    bicep = rid(indexed, BICEP)
    doc = indexed.repository.get(bicep)
    indexed.repository.upsert({**doc, "title": "Bicep registries in practice"})
    indexed.indexer.update_metadata(bicep)
    hits = indexed.search_backend.search(indexed.indexer.chunks_name, SearchRequest(filters=Filters(recording_ids=[bicep])))
    assert hits.hits and all(h.doc["title"] == "Bicep registries in practice" for h in hits.hits)
    assert indexed.search_service.get_by_key(bicep)["title"] == "Bicep registries in practice"


def test_service_search_groups_hits_with_timestamps(indexed) -> None:  # noqa: ANN001
    result = indexed.search_service.search("bicep registry", Filters(), top=5)
    top = result["items"][0]
    assert top["title"] == "Minicode: Bicep private registry"
    hit = top["hits"][0]
    assert hit["startLabel"] == f"{int(hit['start']) // 60:02d}:{int(hit['start']) % 60:02d}" and hit["end"] > hit["start"] and hit["speakers"]
    assert any("<em>" in h for h in hit["highlights"]) and "nav=" in hit["url"]
    assert {f["value"] for f in result["facets"]["presenter"]} >= {"Aino Virtanen"}
    taxonomy_ids = set(load_taxonomy().topic.tag_ids())
    assert all(f["value"] in taxonomy_ids for f in result["facets"]["topics"])


def test_service_list_filters_and_sorts(indexed) -> None:  # noqa: ANN001
    everything = indexed.search_service.list_minicodes(Filters(), top=20)
    dates = [i["date"] for i in everything["items"]]
    assert everything["count"] == 7 and dates == sorted(dates, reverse=True)
    ai = indexed.search_service.list_minicodes(Filters(topics=["ai-genai"], date_from="2026-01-01"))
    assert ai["count"] == 3 - 0 and all("ai-genai" in i["topics"] for i in ai["items"])
    assert all(i["date"] >= "2026-01-01" for i in ai["items"])
    with pytest.raises(ValueError):
        indexed.search_service.list_minicodes(Filters(), sort="random")


def test_get_minicode_has_chapters_and_hides_hidden(indexed) -> None:  # noqa: ANN001
    bicep = rid(indexed, BICEP)
    view = indexed.search_service.get_minicode(bicep)
    assert view["chapters"] and view["chapters"][0]["start"] < view["chapters"][-1]["start"] and "rawTitle" not in view
    assert "audit" in indexed.search_service.get_minicode(bicep, admin=True)
    indexed.repository.upsert({**indexed.repository.get(bicep), "hidden": True})
    assert indexed.search_service.get_minicode(bicep) is None and indexed.search_service.get_minicode(bicep, admin=True)


def test_timestamp_url_encodes_stream_nav() -> None:
    url = timestamp_url("https://t.sharepoint.com/sites/x/a b.mp4?web=1", 75.9)
    q = parse_qs(urlsplit(url).query)
    assert q["web"] == ["1"]
    assert json.loads(base64.b64decode(q["nav"][0])) == {"playbackOptions": {"startTimeInSeconds": 75}}
    assert timestamp_url(None, 3) is None
