"""Enrichment run over ingested recordings: artifacts -> LLM -> validated catalogue documents.

Idempotent: a recording is skipped when its input hash (prompt version + model + title + transcript)
is unchanged since the last successful enrichment, unless `force`. Admin overrides are preserved.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from minicode.enrichment.enricher import Enricher
from minicode.enrichment.inputs import EnrichmentInput, load_input
from minicode.enrichment.repository import CatalogRepository, apply_llm, compute_effective, new_document
from minicode.enrichment.schema import PROMPT_VERSION
from minicode.ingestion.state import Stage, StateStore
from minicode.storage import ARTIFACTS, BlobStore

log = logging.getLogger(__name__)
ENRICHABLE = {Stage.CHUNKED, Stage.NO_TRANSCRIPT}


@dataclass
class EnrichmentSummary:
    counts: Counter[str] = field(default_factory=Counter)
    changed: list[str] = field(default_factory=list)  # (re)enriched -> must be re-indexed
    deleted: list[str] = field(default_factory=list)  # removed at source -> remove from index
    errors: dict[str, str] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "changed": self.changed, "deleted": self.deleted, "errors": self.errors,
                "needsReview": self.needs_review}


def source_fields(item: EnrichmentInput) -> dict[str, Any]:
    return {
        "rawTitle": item.raw_title,
        "webUrl": item.web_url,
        "listItemUniqueId": item.list_item_unique_id,
        "recordedAt": item.recorded_at,
        "organizer": item.organizer,
        "durationSeconds": item.duration_seconds,
        "language": item.language,
        "transcriptSource": item.transcript_source,
        "chunkCount": len(item.chunks),
        "etag": item.etag,
    }


class EnrichmentPipeline:
    def __init__(
        self,
        store: BlobStore,
        repository: CatalogRepository,
        enricher: Enricher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.repo = repository
        self.enricher = enricher
        self.state = StateStore(store)
        self.clock = clock

    def run(self, force: bool = False, only: Iterable[str] | None = None) -> EnrichmentSummary:
        summary = EnrichmentSummary()
        wanted = set(only) if only else None
        for m in self.state.all():
            if wanted is not None and m.id not in wanted:
                continue
            if m.stage == Stage.DELETED:
                if self.repo.get(m.id) is not None:
                    self.repo.delete(m.id)
                    summary.deleted.append(m.id)
                summary.counts["deleted"] += 1
                continue
            if m.stage not in ENRICHABLE or not self.store.exists(ARTIFACTS, f"recordings/{m.id}.json"):
                summary.counts[f"skipped_{m.stage}"] += 1
                continue
            outcome = self.enrich_one(m.id, force)
            summary.counts[outcome] += 1
            if outcome == "failed":
                summary.errors[m.id] = self._last_error
            elif outcome == "enriched":
                summary.changed.append(m.id)
                doc = self.repo.get(m.id) or {}
                if (doc.get("enrichment") or {}).get("needsReview"):
                    summary.needs_review.append(m.id)
        log.info("enrichment run: %s", dict(summary.counts))
        return summary

    _last_error = ""

    def enrich_one(self, recording_id: str, force: bool = False) -> str:
        item = load_input(self.store, recording_id)
        doc = self.repo.get(recording_id) or new_document(recording_id, {})
        doc.update(source_fields(item))
        input_hash = item.input_hash(PROMPT_VERSION, self.enricher.llm.name)
        if not force and doc.get("llm") and (doc.get("enrichment") or {}).get("inputHash") == input_hash:
            return "unchanged"
        try:
            outcome = self.enricher.enrich(item)
        except Exception as e:  # noqa: BLE001 - recorded per item; doc keeps fallback/previous values
            self._last_error = f"{type(e).__name__}: {e}"[:500]
            log.warning("enrichment failed for %s: %s", recording_id, self._last_error)
            doc["enrichmentError"] = self._last_error
            self.repo.upsert(compute_effective(doc))
            return "failed"
        meta = {
            "model": outcome.model,
            "client": self.enricher.llm.name,
            "promptVersion": PROMPT_VERSION,
            "inputHash": input_hash,
            "enrichedAt": self.clock().isoformat(timespec="seconds"),
            "attempts": outcome.attempts,
            "needsReview": outcome.needs_review,
            "validationErrors": outcome.errors[-5:],
            "inputTokens": outcome.input_tokens,
            "outputTokens": outcome.output_tokens,
        }
        doc.pop("enrichmentError", None)
        self.repo.upsert(apply_llm(doc, outcome.enrichment.to_dict(), meta))
        return "enriched"
