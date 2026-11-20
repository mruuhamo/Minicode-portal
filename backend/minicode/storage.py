"""Blob storage abstraction.

Containers match infra/modules/storage.bicep: `transcripts`, `artifacts`, `inventory`.
`LocalBlobStore` maps containers to folders for development and tests; `AzureBlobStore`
uses azure-storage-blob with Entra ID (managed identity) auth and user-delegation SAS.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, runtime_checkable

TRANSCRIPTS = "transcripts"
ARTIFACTS = "artifacts"
INVENTORY = "inventory"


@runtime_checkable
class BlobStore(Protocol):
    def put_bytes(self, container: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    def get_bytes(self, container: str, path: str) -> bytes: ...

    def exists(self, container: str, path: str) -> bool: ...

    def delete(self, container: str, path: str) -> None: ...

    def list(self, container: str, prefix: str = "") -> Iterator[str]: ...

    def get_read_url(self, container: str, path: str, expires_in: timedelta = timedelta(hours=24)) -> str:
        """URL an external service (Azure AI Speech) can read the blob from."""
        ...


def put_json(store: BlobStore, container: str, path: str, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    store.put_bytes(container, path, data, "application/json")


def get_json(store: BlobStore, container: str, path: str) -> Any:
    return json.loads(store.get_bytes(container, path).decode("utf-8"))


def atomic_replace(tmp: Path, target: Path, attempts: int = 5) -> None:
    """tmp -> target atomically; retries the transient PermissionError Windows raises when AV/indexers hold the target."""
    for attempt in range(attempts):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _safe_path(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"invalid blob path: {path!r}")
    return p


class LocalBlobStore:
    """Filesystem-backed store: <root>/<container>/<path>."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _file(self, container: str, path: str) -> Path:
        return self.root / _safe_path(container) / _safe_path(path)

    def put_bytes(self, container: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        f = self._file(container, path)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_bytes(data)
        atomic_replace(tmp, f)  # atomic on the same volume, so a crash never leaves half-written state

    def get_bytes(self, container: str, path: str) -> bytes:
        f = self._file(container, path)
        if not f.is_file():
            raise FileNotFoundError(f"{container}/{path}")
        return f.read_bytes()

    def exists(self, container: str, path: str) -> bool:
        return self._file(container, path).is_file()

    def delete(self, container: str, path: str) -> None:
        self._file(container, path).unlink(missing_ok=True)

    def list(self, container: str, prefix: str = "") -> Iterator[str]:
        base = self.root / _safe_path(container)
        if not base.is_dir():
            return
        for f in sorted(base.rglob("*")):
            if f.is_file() and not f.name.endswith(".tmp"):
                rel = f.relative_to(base).as_posix()
                if rel.startswith(prefix):
                    yield rel

    def get_read_url(self, container: str, path: str, expires_in: timedelta = timedelta(hours=24)) -> str:
        return self._file(container, path).resolve().as_uri()


class AzureBlobStore:
    """Azure Blob Storage with managed identity (shared keys are disabled on the account)."""

    def __init__(self, account_url: str, credential: Any | None = None) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self.service = BlobServiceClient(account_url, credential=credential or DefaultAzureCredential())
        self._delegation_key: Any = None
        self._delegation_expiry: datetime | None = None

    def _blob(self, container: str, path: str):  # type: ignore[no-untyped-def]
        return self.service.get_blob_client(container, str(_safe_path(path)))

    def put_bytes(self, container: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        from azure.storage.blob import ContentSettings

        self._blob(container, path).upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))

    def get_bytes(self, container: str, path: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._blob(container, path).download_blob().readall()
        except ResourceNotFoundError as e:
            raise FileNotFoundError(f"{container}/{path}") from e

    def exists(self, container: str, path: str) -> bool:
        return self._blob(container, path).exists()

    def delete(self, container: str, path: str) -> None:
        self._blob(container, path).delete_blob(delete_snapshots="include") if self.exists(container, path) else None

    def list(self, container: str, prefix: str = "") -> Iterator[str]:
        for b in self.service.get_container_client(container).list_blobs(name_starts_with=prefix or None):
            yield b.name

    def get_read_url(self, container: str, path: str, expires_in: timedelta = timedelta(hours=24)) -> str:
        """Read-only user-delegation SAS (requires Storage Blob Data Contributor/Owner on the MI)."""
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        now = datetime.now(UTC)
        expiry = now + expires_in
        if self._delegation_key is None or self._delegation_expiry is None or self._delegation_expiry < expiry:
            self._delegation_expiry = now + max(expires_in, timedelta(days=1))
            self._delegation_key = self.service.get_user_delegation_key(now - timedelta(minutes=5), self._delegation_expiry)
        blob = self._blob(container, path)
        sas = generate_blob_sas(
            account_name=blob.account_name,
            container_name=container,
            blob_name=blob.blob_name,
            user_delegation_key=self._delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        return f"{blob.url}?{sas}"
