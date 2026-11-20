from __future__ import annotations

import json
from typing import Any

import pytest

from minicode.api.routes import Api, ApiRequest

BICEP = "01MOCK8849C117E2EDD9"
NON_ADMIN = {"X-Dev-Roles": "none"}


@pytest.fixture
def api(indexed) -> Api:  # noqa: ANN001
    return Api(indexed)


def rid(api: Api, prefix: str = BICEP) -> str:
    return next(d["id"] for d in api.c.repository.list() if d["id"].startswith(prefix))


def call(api: Api, method: str, path: str, headers: dict[str, str] | None = None, body: Any = None, **params: str):  # noqa: ANN201
    resp = api.handle(ApiRequest(method, path, {k: [v] for k, v in params.items()}, headers or {},
                                 json.dumps(body).encode() if body is not None else b""))
    return resp.status, resp.body


def test_list_with_filters_and_paging(api) -> None:  # noqa: ANN001
    status, body = call(api, "GET", "/api/minicodes", top="2")
    assert status == 200 and body["count"] == 7 and len(body["items"]) == 2 and "topics" in body["facets"]
    status, body = call(api, "GET", "/api/minicodes", tags="security-identity,ai-genai", **{"from": "2026-06-01"})
    assert status == 200 and body["items"]
    assert all(i["date"] >= "2026-06-01" and {"security-identity", "ai-genai"} & set(i["topics"]) for i in body["items"])
    status, body = call(api, "GET", "/api/minicodes", presenter="Aino Virtanen")
    assert [i["title"] for i in body["items"]] == ["Minicode: Bicep private registry"]


@pytest.mark.parametrize(
    "params",
    [{"tags": "not-a-tag"}, {"contentType": "movie"}, {"top": "500"}, {"skip": "-1"}, {"from": "1.1.2026"}, {"level": "x"},
     {"sort": "random"}],
)
def test_list_rejects_bad_params(api, params) -> None:  # noqa: ANN001
    status, body = call(api, "GET", "/api/minicodes", **params)
    assert status == 400 and body["error"]


def test_search_returns_timestamped_hits_and_facets(api) -> None:  # noqa: ANN001
    status, body = call(api, "GET", "/api/search", q="threat modeling STRIDE")
    assert status == 200 and body["items"][0]["title"] == "Minicode: Threat Modeling"
    hit = body["items"][0]["hits"][0]
    assert {"start", "end", "startLabel", "speakers", "highlights", "url"} <= set(hit)
    assert {"topics", "presenter", "year", "level"} <= set(body["facets"])
    status, body = call(api, "GET", "/api/search", q="threat modeling", tags="devops-iac")
    assert status == 200 and all("devops-iac" in i["topics"] for i in body["items"])
    assert call(api, "GET", "/api/search", q="x" * 301)[0] == 400


def test_get_minicode_and_404(api) -> None:  # noqa: ANN001
    status, body = call(api, "GET", f"/api/minicodes/{rid(api)}")
    assert status == 200 and body["chapters"] and "overrides" not in body
    assert call(api, "GET", "/api/minicodes/nope")[0] == 404
    assert call(api, "GET", "/api/nothing")[0] == 404
    assert call(api, "DELETE", "/api/minicodes")[0] == 405


def test_taxonomy_endpoint(api) -> None:  # noqa: ANN001
    status, body = call(api, "GET", "/api/taxonomy")
    assert status == 200 and {"topic", "content_type", "level", "version"} <= set(body)


def test_admin_requires_role(api) -> None:  # noqa: ANN001
    rec = rid(api)
    assert call(api, "PATCH", f"/api/manage/minicodes/{rec}", NON_ADMIN, {"title": "x"})[0] == 403
    assert call(api, "GET", f"/api/manage/minicodes/{rec}", NON_ADMIN)[0] == 403
    assert call(api, "POST", "/api/manage/reindex", NON_ADMIN)[0] == 403
    assert call(api, "GET", "/api/minicodes", NON_ADMIN)[0] == 200


def test_admin_patch_updates_search_and_survives_reenrichment(api) -> None:  # noqa: ANN001
    rec = rid(api)
    status, body = call(api, "PATCH", f"/api/manage/minicodes/{rec}", body={"title": "Bicep registries in practice",
                                                                            "topics": ["devops-iac"]})
    assert status == 200 and body["title"] == "Bicep registries in practice" and set(body["overriddenFields"]) >= {"title", "topics"}
    assert body["audit"][-1]["user"] == "dev.user@localhost"
    _, found = call(api, "GET", "/api/search", q="registries in practice")
    assert found["items"][0]["title"] == "Bicep registries in practice"
    status, body = call(api, "POST", "/api/manage/enrich", body={"force": True, "ids": [rec]})
    assert status == 200 and body["enrichment"]
    _, view = call(api, "GET", f"/api/minicodes/{rec}")
    assert view["title"] == "Bicep registries in practice" and view["topics"] == ["devops-iac"]
    status, body = call(api, "PATCH", f"/api/manage/minicodes/{rec}", body={"title": None})  # clear override
    assert status == 200 and body["title"] == "Minicode: Bicep private registry"


@pytest.mark.parametrize("patch", [{"topics": ["made-up"]}, {"rawTitle": "x"}, {}, {"level": 250}, {"hidden": "yes"}])
def test_admin_patch_validation(api, patch) -> None:  # noqa: ANN001
    assert call(api, "PATCH", f"/api/manage/minicodes/{rid(api)}", body=patch)[0] == 400


def test_admin_hide_removes_from_public(api) -> None:  # noqa: ANN001
    rec = rid(api)
    assert call(api, "PATCH", f"/api/manage/minicodes/{rec}", body={"hidden": True})[0] == 200
    assert call(api, "GET", f"/api/minicodes/{rec}")[0] == 404
    assert call(api, "GET", f"/api/manage/minicodes/{rec}")[0] == 200
    _, body = call(api, "GET", "/api/minicodes")
    assert rec not in {i["id"] for i in body["items"]} and body["count"] == 6


def test_invalid_json_body(api) -> None:  # noqa: ANN001
    bad = api.handle(ApiRequest("PATCH", f"/api/manage/minicodes/{rid(api)}", body=b"{not json"))
    assert bad.status == 400 and "invalid JSON" in bad.body["error"]


def test_missing_index_is_503(demo) -> None:  # noqa: ANN001
    assert Api(demo).handle(ApiRequest("GET", "/api/search", {"q": ["bicep"]})).status == 503
