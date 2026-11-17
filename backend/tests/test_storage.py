from __future__ import annotations

from pathlib import Path

import pytest

from minicode.storage import ARTIFACTS, BlobStore, LocalBlobStore, get_json, put_json


def test_local_blob_store_roundtrip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    assert isinstance(store, BlobStore)
    put_json(store, ARTIFACTS, "chunks/a.json", {"ä": 1})
    store.put_bytes(ARTIFACTS, "chunks/b.bin", b"x")
    store.put_bytes(ARTIFACTS, "other/c.bin", b"y")
    assert get_json(store, ARTIFACTS, "chunks/a.json") == {"ä": 1}
    assert store.exists(ARTIFACTS, "chunks/b.bin")
    assert list(store.list(ARTIFACTS, "chunks/")) == ["chunks/a.json", "chunks/b.bin"]
    assert store.get_read_url(ARTIFACTS, "chunks/b.bin").startswith("file://")
    store.delete(ARTIFACTS, "chunks/b.bin")
    store.delete(ARTIFACTS, "chunks/b.bin")  # idempotent
    assert not store.exists(ARTIFACTS, "chunks/b.bin")
    assert not list(tmp_path.rglob("*.tmp"))
    with pytest.raises(FileNotFoundError):
        store.get_bytes(ARTIFACTS, "missing")
    assert list(store.list("empty")) == []


@pytest.mark.parametrize("bad", ["../escape", "/abs", "a/../../b", ""])
def test_rejects_path_traversal(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        LocalBlobStore(tmp_path).put_bytes(ARTIFACTS, bad, b"x")
