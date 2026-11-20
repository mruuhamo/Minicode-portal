"""Enrichment input assembled from the week 2 ingestion artifacts (metadata + chunks)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from minicode.ingestion.state import StateStore
from minicode.naming import normalize_title
from minicode.storage import ARTIFACTS, BlobStore, get_json


def mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


@dataclass
class EnrichmentInput:
    recording_id: str
    raw_title: str
    organizer: str | None = None
    recorded_at: str | None = None
    duration_seconds: int | None = None
    language: str | None = None
    transcript_source: str | None = None
    web_url: str | None = None
    etag: str | None = None
    chunks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.raw_title).display

    def speaker_seconds(self) -> list[tuple[str, int]]:
        """Approximate talk time per speaker (chunk duration split between its speakers)."""
        totals: Counter[str] = Counter()
        for c in self.chunks:
            speakers = c.get("speakers") or []
            for s in speakers:
                totals[s] += (float(c["end"]) - float(c["start"])) / len(speakers)
        return [(name, round(sec)) for name, sec in totals.most_common()]

    def transcript_text(self, max_chars: int = 16000) -> str:
        """Timestamped transcript; long recordings are sampled evenly so the whole talk is covered."""
        parts = [f"[{mmss(c['start'])}] {c['text']}" for c in self.chunks]
        if sum(len(p) for p in parts) <= max_chars:
            return "\n\n".join(parts)
        avg = max(1, sum(len(p) for p in parts) // len(parts))
        keep = max(1, max_chars // avg)
        step = len(parts) / keep
        picked = [parts[int(i * step)] for i in range(keep)]
        return "\n\n[...]\n\n".join(picked)[:max_chars]

    def metadata(self) -> dict[str, Any]:
        return {
            "rawTitle": self.raw_title,
            "normalizedTitleSuggestion": self.normalized_title,
            "organizer": self.organizer,
            "recordedAt": self.recorded_at,
            "durationMinutes": round(self.duration_seconds / 60) if self.duration_seconds else None,
            "transcriptLanguage": self.language,
            "transcriptSource": self.transcript_source,
            "speakerTalkTimeSeconds": dict(self.speaker_seconds()),
        }

    def input_hash(self, prompt_version: str, model: str) -> str:
        payload = json.dumps(
            [prompt_version, model, self.raw_title, self.organizer, self.recorded_at, [c["text"] for c in self.chunks]],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def load_input(store: BlobStore, recording_id: str, language: str | None = None) -> EnrichmentInput:
    meta = get_json(store, ARTIFACTS, f"recordings/{recording_id}.json")
    chunks_path = f"chunks/{recording_id}.json"
    chunks = get_json(store, ARTIFACTS, chunks_path)["chunks"] if store.exists(ARTIFACTS, chunks_path) else []
    manifest = StateStore(store).get(recording_id)
    return EnrichmentInput(
        recording_id=recording_id,
        raw_title=meta["title"],
        organizer=meta.get("organizer"),
        recorded_at=meta.get("recorded_at"),
        duration_seconds=meta.get("duration_seconds"),
        language=language or (manifest.language if manifest else None),
        transcript_source=manifest.transcript_source if manifest else None,
        web_url=meta.get("web_url"),
        etag=meta.get("etag"),
        chunks=chunks,
    )
