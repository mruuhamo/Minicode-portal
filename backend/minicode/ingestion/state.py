"""Per-recording ingestion manifests, the delta cursor and run summaries (in the `inventory` container).

The manifest is saved after every stage so a crashed/timed-out run resumes where it stopped.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from minicode.storage import INVENTORY, BlobStore, get_json, put_json

MANIFEST_PREFIX = "state/recordings/"
CURSOR_PATH = "state/delta.json"
RUNS_PREFIX = "runs/"


class Stage(StrEnum):
    DISCOVERED = "discovered"
    NO_TRANSCRIPT = "no_transcript"  # no sidecar and Speech disabled
    TRANSCRIPTION_PENDING = "transcription_pending"
    CHUNKED = "chunked"  # done: parsed transcript + chunks written
    FAILED = "failed"
    DELETED = "deleted"


@dataclass
class Manifest:
    id: str
    title: str = ""
    stage: Stage = Stage.DISCOVERED
    etag: str | None = None
    recorded_at: str | None = None
    file_name: str | None = None
    web_url: str | None = None
    transcript_source: str | None = None  # teams-vtt | azure-speech
    language: str | None = None
    speech_job_url: str | None = None
    speech_submitted_at: str | None = None
    chunk_count: int = 0
    attempts: int = 0
    error: str | None = None
    updated_at: str | None = None
    history: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        m = cls(**known)
        m.stage = Stage(m.stage)
        return m


class StateStore:
    def __init__(self, store: BlobStore) -> None:
        self.store = store

    def get(self, recording_id: str) -> Manifest | None:
        path = f"{MANIFEST_PREFIX}{recording_id}.json"
        if not self.store.exists(INVENTORY, path):
            return None
        return Manifest.from_dict(get_json(self.store, INVENTORY, path))

    def save(self, manifest: Manifest, now: datetime, note: str | None = None) -> None:
        manifest.updated_at = now.isoformat()
        if note:
            manifest.history = [*manifest.history[-19:], f"{manifest.updated_at} {note}"]
        put_json(self.store, INVENTORY, f"{MANIFEST_PREFIX}{manifest.id}.json", asdict(manifest))

    def all(self) -> Iterator[Manifest]:
        for path in self.store.list(INVENTORY, MANIFEST_PREFIX):
            if path.endswith(".json"):
                yield Manifest.from_dict(get_json(self.store, INVENTORY, path))

    def get_cursor(self) -> str | None:
        if not self.store.exists(INVENTORY, CURSOR_PATH):
            return None
        return get_json(self.store, INVENTORY, CURSOR_PATH).get("cursor")

    def save_cursor(self, cursor: str, now: datetime) -> None:
        put_json(self.store, INVENTORY, CURSOR_PATH, {"cursor": cursor, "updatedAt": now.isoformat()})

    def save_run(self, summary: dict[str, Any], now: datetime) -> str:
        path = f"{RUNS_PREFIX}{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        put_json(self.store, INVENTORY, path, summary)
        return path
