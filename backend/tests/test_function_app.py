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
    bad = ingest(func.HttpRequest("POST", "/api/admin/ingest", params={"mode": "nope"}, body=b""))
    assert bad.status_code == 400

    resp = ingest(func.HttpRequest("POST", "/api/admin/ingest", params={"mode": "backfill"}, body=b""))
    body = json.loads(resp.get_body())
    assert resp.status_code == 200 and body["mode"] == "backfill"
    assert body["outcomes"]["ingested_vtt"] == 4 and "items" not in body
    assert (tmp_path / "artifacts" / "chunks").is_dir()
