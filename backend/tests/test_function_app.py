from __future__ import annotations

import json
from pathlib import Path

import pytest

func = pytest.importorskip("azure.functions")


def _user_function(fn):  # type: ignore[no-untyped-def]
    # v2 programming model decorators wrap the handler in a FunctionBuilder
    return fn.build().get_user_function() if hasattr(fn, "build") else fn


def test_ingest_endpoint_runs_mock_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINICODE_SOURCE", "mock")
    monkeypatch.setenv("MINICODE_STORAGE", "local")
    monkeypatch.setenv("MINICODE_LOCAL_STORE", str(tmp_path))
    import function_app

    ingest = _user_function(function_app.ingest)
    bad = ingest(func.HttpRequest("POST", "/api/manage/ingest", params={"mode": "nope"}, body=b""))
    assert bad.status_code == 400

    resp = ingest(func.HttpRequest("POST", "/api/manage/ingest", params={"mode": "backfill"}, body=b""))
    body = json.loads(resp.get_body())
    assert resp.status_code == 200 and body["mode"] == "backfill"
    assert body["outcomes"]["ingested_vtt"] == 4 and "items" not in body
    assert (tmp_path / "artifacts" / "chunks").is_dir()


@pytest.fixture
def fa(ingested_blob: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    import shutil

    import function_app

    shutil.copytree(ingested_blob, tmp_path / "blob")
    for k, v in {"MINICODE_SOURCE": "mock", "MINICODE_STORAGE": "local", "MINICODE_DATA_DIR": str(tmp_path), "AUTH_MODE": "dev",
                 "LLM_PROVIDER": "mock", "MINICODE_REPOSITORY": "local", "SEARCH_BACKEND": "local"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MINICODE_LOCAL_STORE", raising=False)
    function_app._components.cache_clear()
    function_app._api.cache_clear()
    yield function_app
    function_app._components.cache_clear()
    function_app._api.cache_clear()


def test_enrich_and_index_then_http_routes(fa) -> None:  # noqa: ANN001
    result = fa.enrich_and_index()
    assert result["index"]["recordings"] == 7

    search = _user_function(fa.search)
    resp = search(func.HttpRequest("GET", "http://localhost/api/search?q=bicep&top=3", body=b""))
    body = json.loads(resp.get_body())
    assert resp.status_code == 200 and resp.mimetype == "application/json"
    assert body["items"][0]["hits"][0]["startLabel"]

    rid = body["items"][0]["id"]
    manage = _user_function(fa.manage_minicode)
    denied = manage(func.HttpRequest("PATCH", f"http://localhost/api/manage/minicodes/{rid}", headers={"X-Dev-Roles": "none"},
                                     route_params={"id": rid}, body=b'{"title": "x"}'))
    assert denied.status_code == 403
    ok = manage(func.HttpRequest("PATCH", f"http://localhost/api/manage/minicodes/{rid}", route_params={"id": rid},
                                 body=json.dumps({"topics": ["devops-iac"]}).encode()))
    assert ok.status_code == 200 and json.loads(ok.get_body())["topics"] == ["devops-iac"]
