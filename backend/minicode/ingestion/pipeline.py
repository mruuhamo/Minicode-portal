"""Backfill / incremental ingestion pipeline.

    discover (Graph) -> transcript: sidecar .vtt  ──────────────┐
                       └─ none: audio -> Speech batch job ──────┤ (pending until the job is done)
                                                                 └─> parse -> chunk -> artifacts

Idempotent: a recording whose manifest is `chunked` with the same eTag is skipped (unless
`force`). A Speech-transcribed recording is re-done when a Teams .vtt shows up later (better
speaker names). Resumable: manifests are saved after each step; pending Speech jobs are polled
by the next run. Errors are recorded per recording and never stop the run.

Blob layout (containers from infra/modules/storage.bicep):
    transcripts/raw/{id}.vtt | transcripts/raw/{id}.speech.json   raw transcript as received
    transcripts/parsed/{id}.json                                  normalized cues (Transcript.to_dict)
    artifacts/recordings/{id}.json                                recording metadata + normalized title
    artifacts/chunks/{id}.json                                    chunks for enrichment/embedding (week 3)
    artifacts/audio/{id}.m4a                                      temporary Speech input (deleted after)
    inventory/state/...                                           manifests, delta cursor; inventory/runs/
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from minicode.ingestion.audio import AUDIO_CONTENT_TYPE, AUDIO_EXTENSION, AudioExtractor
from minicode.ingestion.chunking import chunk_transcript
from minicode.ingestion.graph import Change
from minicode.ingestion.http import HttpError
from minicode.ingestion.speech import SUCCEEDED, SpeechBatchClient
from minicode.ingestion.state import Manifest, Stage, StateStore
from minicode.ingestion.transcripts import Transcript, parse_speech_result, parse_vtt
from minicode.inventory.models import Recording, RecordingStatus
from minicode.naming import normalize_title
from minicode.storage import ARTIFACTS, TRANSCRIPTS, BlobStore, put_json

log = logging.getLogger(__name__)


class IngestionSource(Protocol):
    name: str

    def list_recordings(self, since: datetime | None = None) -> Iterable[Recording]: ...

    def get_transcript(self, recording: Recording) -> str | None: ...

    def get_download_url(self, recording: Recording) -> str: ...

    def latest_cursor(self) -> str: ...

    def list_changes(self, cursor: str) -> tuple[list[Change], str]: ...


@dataclass
class PipelineConfig:
    lookback_days: int = 365  # scope decision: last 12 months only
    max_tokens: int = 400
    max_seconds: float = 180.0
    overlap_seconds: float = 15.0
    max_attempts: int = 3
    force: bool = False
    wait_for_speech: bool = False  # CLI: poll until jobs finish; Functions: leave for the next run
    poll_interval: float = 30.0
    max_wait: float = 4 * 3600.0
    speech_timeout: timedelta = timedelta(hours=24)


@dataclass
class RunSummary:
    mode: str
    started_at: str
    since: str | None = None
    finished_at: str | None = None
    outcomes: Counter[str] = field(default_factory=Counter)
    items: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def add(self, recording_id: str, outcome: str, title: str = "") -> None:
        self.outcomes[outcome] += 1
        self.items.append({"id": recording_id, "title": title, "outcome": outcome})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcomes"] = dict(self.outcomes)
        return d


class IngestionPipeline:
    def __init__(
        self,
        source: IngestionSource,
        store: BlobStore,
        speech: SpeechBatchClient | None = None,
        audio: AudioExtractor | None = None,
        config: PipelineConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self.store = store
        self.state = StateStore(store)
        self.speech = speech
        self.audio = audio
        self.config = config or PipelineConfig()
        self.clock = clock
        self.sleep = sleep

    # --- runs ---------------------------------------------------------------------------------

    def run_backfill(self, since: datetime | None = None) -> RunSummary:
        since = since or self.clock() - timedelta(days=self.config.lookback_days)
        summary = RunSummary(mode="backfill", started_at=self.clock().isoformat(), since=since.isoformat())
        cursor = self._try_latest_cursor()  # taken first so changes during the backfill are not missed
        seen: set[str] = set()
        for rec in self.source.list_recordings(since=since):
            seen.add(rec.id)
            summary.add(rec.id, self.process(rec, since), rec.title)
        self._poll_pending(summary, skip=seen)
        if cursor:
            self.state.save_cursor(cursor, self.clock())
        return self._finish(summary)

    def run_incremental(self) -> RunSummary:
        cursor = self.state.get_cursor()
        if not cursor:
            log.info("no delta cursor yet -> full backfill")
            return self.run_backfill()
        try:
            changes, next_cursor = self.source.list_changes(cursor)
        except HttpError as e:
            if e.status_code == 410:  # resyncRequired: token expired
                log.warning("delta token expired -> full backfill")
                return self.run_backfill()
            raise
        since = self.clock() - timedelta(days=self.config.lookback_days)
        summary = RunSummary(mode="incremental", started_at=self.clock().isoformat(), since=since.isoformat())
        seen: set[str] = set()
        for change in changes:
            rec = change.recording
            seen.add(rec.id)
            if change.deleted:
                if self.state.get(rec.id) is not None:
                    summary.add(rec.id, self.remove(rec.id), rec.title)
                continue
            summary.add(rec.id, self.process(rec, since), rec.title)
        self._poll_pending(summary, skip=seen)
        self.state.save_cursor(next_cursor, self.clock())
        return self._finish(summary)

    def _finish(self, summary: RunSummary) -> RunSummary:
        if self.config.wait_for_speech:
            self._wait_for_pending(summary)
        summary.finished_at = self.clock().isoformat()
        summary.errors = [
            {"id": m.id, "title": m.title, "error": m.error or ""} for m in self.state.all() if m.stage == Stage.FAILED
        ]
        self.state.save_run(summary.to_dict(), self.clock())
        return summary

    def _try_latest_cursor(self) -> str | None:
        try:
            return self.source.latest_cursor()
        except (AttributeError, NotImplementedError):
            return None

    # --- per recording ------------------------------------------------------------------------

    def process(self, rec: Recording, since: datetime | None = None) -> str:
        if rec.status == RecordingStatus.DELETED:
            return self.remove(rec.id)
        if since and rec.recorded_at and rec.recorded_at < since:
            return "out_of_window"
        m = self.state.get(rec.id)
        same = m is not None and m.etag == rec.etag
        if m and same and not self.config.force:
            if m.stage == Stage.CHUNKED and not (m.transcript_source == "azure-speech" and rec.has_transcript):
                return "unchanged"
            if m.stage == Stage.TRANSCRIPTION_PENDING:
                return self._poll(m)
            if m.stage == Stage.FAILED and m.attempts >= self.config.max_attempts:
                return "failed_max_attempts"
        if m is None or not same:
            m = Manifest(id=rec.id, attempts=m.attempts if m and same else 0)
        m.title, m.etag, m.file_name, m.web_url = rec.title, rec.etag, rec.file_name, rec.web_url
        m.recorded_at = rec.recorded_at.isoformat() if rec.recorded_at else None
        try:
            self._write_metadata(rec)
            vtt = self.source.get_transcript(rec)
            if vtt is not None:
                self._put_text(TRANSCRIPTS, f"raw/{rec.id}.vtt", vtt, "text/vtt")
                self._complete(m, parse_vtt(vtt, rec.id))
                return "ingested_vtt"
            if self.speech is None or self.audio is None:
                m.stage, m.error = Stage.NO_TRANSCRIPT, None
                self.state.save(m, self.clock(), "no transcript; speech disabled")
                return "no_transcript"
            return self._submit_speech(m, rec)
        except Exception as e:  # noqa: BLE001 - recorded per item, run continues
            return self._fail(m, e)

    def _submit_speech(self, m: Manifest, rec: Recording) -> str:
        assert self.speech is not None and self.audio is not None
        audio_path = f"audio/{rec.id}.{AUDIO_EXTENSION}"
        if not self.store.exists(ARTIFACTS, audio_path):
            audio = self.audio.extract(self.source.get_download_url(rec))
            self.store.put_bytes(ARTIFACTS, audio_path, audio, AUDIO_CONTENT_TYPE)
        job = self.speech.submit(self.store.get_read_url(ARTIFACTS, audio_path), display_name=f"minicode-{rec.id}")
        m.stage, m.speech_job_url, m.error = Stage.TRANSCRIPTION_PENDING, job.url, None
        m.speech_submitted_at = self.clock().isoformat()
        self.state.save(m, self.clock(), "speech job submitted")
        return "transcription_submitted"

    def _poll(self, m: Manifest) -> str:
        if self.speech is None or not m.speech_job_url:
            return "transcription_pending"
        try:
            job = self.speech.get(m.speech_job_url)
            if not job.done:
                submitted = datetime.fromisoformat(m.speech_submitted_at) if m.speech_submitted_at else self.clock()
                if self.clock() - submitted > self.config.speech_timeout:
                    self._delete_job(m.speech_job_url)
                    raise TimeoutError(f"speech job still {job.status} after {self.config.speech_timeout}")
                return "transcription_pending"
            if job.status != SUCCEEDED:
                self._delete_job(m.speech_job_url)
                raise RuntimeError(f"speech transcription failed: {job.error}")
            result = self.speech.fetch_result(m.speech_job_url)
            job_url = m.speech_job_url
            put_json(self.store, TRANSCRIPTS, f"raw/{m.id}.speech.json", result)
            self._complete(m, parse_speech_result(result, m.id))
            self._delete_job(job_url)
            self.store.delete(ARTIFACTS, f"audio/{m.id}.{AUDIO_EXTENSION}")
            return "ingested_speech"
        except Exception as e:  # noqa: BLE001
            m.speech_job_url = None
            return self._fail(m, e)

    def _delete_job(self, url: str) -> None:
        try:
            assert self.speech is not None
            self.speech.delete(url)
        except Exception as e:  # noqa: BLE001 - jobs also expire via timeToLiveHours
            log.warning("could not delete speech job %s: %s", url, e)

    def _complete(self, m: Manifest, transcript: Transcript) -> None:
        if not transcript.cues:
            raise ValueError("transcript has no cues")
        put_json(self.store, TRANSCRIPTS, f"parsed/{m.id}.json", transcript.to_dict())
        chunks = chunk_transcript(
            transcript,
            max_tokens=self.config.max_tokens,
            max_seconds=self.config.max_seconds,
            overlap_seconds=self.config.overlap_seconds,
        )
        put_json(self.store, ARTIFACTS, f"chunks/{m.id}.json", {"recordingId": m.id, "chunks": [c.to_dict() for c in chunks]})
        m.stage, m.transcript_source, m.language = Stage.CHUNKED, transcript.source, transcript.language
        m.chunk_count, m.error, m.speech_job_url, m.attempts = len(chunks), None, None, 0
        self.state.save(m, self.clock(), f"chunked ({transcript.source}, {len(chunks)} chunks)")

    def _fail(self, m: Manifest, e: Exception) -> str:
        m.stage, m.attempts, m.error = Stage.FAILED, m.attempts + 1, f"{type(e).__name__}: {e}"[:1000]
        self.state.save(m, self.clock(), "failed")
        log.warning("recording %s failed (attempt %d): %s", m.id, m.attempts, m.error)
        return "failed"

    def _write_metadata(self, rec: Recording) -> None:
        normalized = normalize_title(rec.title)
        meta = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(rec).items()}
        meta["normalizedTitle"] = {"display": normalized.display, **asdict(normalized)}
        put_json(self.store, ARTIFACTS, f"recordings/{rec.id}.json", meta)

    def _put_text(self, container: str, path: str, text: str, content_type: str) -> None:
        self.store.put_bytes(container, path, text.encode("utf-8"), f"{content_type}; charset=utf-8")

    def remove(self, recording_id: str) -> str:
        """Recording deleted in SharePoint -> drop all derived artifacts (search index follows in week 3)."""
        for container, path in (
            (TRANSCRIPTS, f"raw/{recording_id}.vtt"),
            (TRANSCRIPTS, f"raw/{recording_id}.speech.json"),
            (TRANSCRIPTS, f"parsed/{recording_id}.json"),
            (ARTIFACTS, f"chunks/{recording_id}.json"),
            (ARTIFACTS, f"recordings/{recording_id}.json"),
            (ARTIFACTS, f"audio/{recording_id}.{AUDIO_EXTENSION}"),
        ):
            self.store.delete(container, path)
        m = self.state.get(recording_id) or Manifest(id=recording_id)
        if m.speech_job_url:
            self._delete_job(m.speech_job_url)
        m.stage, m.speech_job_url, m.chunk_count = Stage.DELETED, None, 0
        self.state.save(m, self.clock(), "deleted at source")
        return "deleted"

    # --- pending Speech jobs ------------------------------------------------------------------

    def _poll_pending(self, summary: RunSummary, skip: set[str]) -> None:
        for m in self.state.all():
            if m.stage == Stage.TRANSCRIPTION_PENDING and m.id not in skip:
                summary.add(m.id, self._poll(m), m.title)

    def _wait_for_pending(self, summary: RunSummary) -> None:
        deadline = time.monotonic() + self.config.max_wait
        while True:
            pending = [m for m in self.state.all() if m.stage == Stage.TRANSCRIPTION_PENDING]
            if not pending or time.monotonic() > deadline:
                return
            self.sleep(self.config.poll_interval)
            for m in pending:
                outcome = self._poll(m)
                if outcome != "transcription_pending":
                    summary.add(m.id, outcome, m.title)
