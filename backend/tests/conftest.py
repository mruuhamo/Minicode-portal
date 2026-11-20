from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def ingested_blob(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the week 2 mock backfill once (4 VTT + 3 Speech recordings); tests copy the result."""
    from minicode.ingestion.__main__ import main

    root = tmp_path_factory.mktemp("ingested") / "blob"
    mp = pytest.MonkeyPatch()
    for var in ("MINICODE_LOCAL_STORE", "MINICODE_DATA_DIR", "MINICODE_STORAGE"):
        mp.delenv(var, raising=False)
    mp.setenv("MINICODE_SOURCE", "mock")
    try:
        assert main(["backfill", "--out", str(root), "--wait", "--poll-interval", "0"]) == 0
    finally:
        mp.undo()
    return root


@pytest.fixture
def demo(ingested_blob: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Components wired to a private copy of the ingested data: mock LLM, local catalogue + search, dev auth."""
    from minicode.settings import AppSettings, Components

    shutil.copytree(ingested_blob, tmp_path / "blob")
    monkeypatch.delenv("MINICODE_LOCAL_STORE", raising=False)
    monkeypatch.setenv("MINICODE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MINICODE_SOURCE", "mock")
    monkeypatch.setenv("MINICODE_STORAGE", "local")
    settings = AppSettings(data_dir=tmp_path, llm_provider="mock", auth_mode="dev", repository="local", search_backend="local")
    return Components(settings)


@pytest.fixture
def indexed(demo):  # noqa: ANN001, ANN201
    summary = demo.enrichment_pipeline.run()
    demo.indexer.sync(summary.changed, summary.deleted)
    return demo
