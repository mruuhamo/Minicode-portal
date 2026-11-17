from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from minicode.ingestion.config import Settings, build_pipeline
from minicode.ingestion.fakes import MockCloud
from minicode.ingestion.pipeline import IngestionPipeline, PipelineConfig
from minicode.ingestion.state import Stage, StateStore
from minicode.storage import ARTIFACTS, INVENTORY, TRANSCRIPTS, LocalBlobStore, get_json

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
IN_WINDOW = 7  # sample videos recorded within the last 365 days
WITH_VTT = 4


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def cloud() -> MockCloud:
    return MockCloud(now=NOW, speech_polls=2)


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blob")


def make(cloud: MockCloud, store: LocalBlobStore, clock: Clock | None = None, **cfg) -> IngestionPipeline:  # type: ignore[no-untyped-def]
    config = PipelineConfig(poll_interval=0, **cfg)
    return build_pipeline(Settings(source="mock"), store=store, config=config, cloud=cloud, clock=clock or Clock())


def stages(store: LocalBlobStore) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in StateStore(store).all():
        out[m.stage.value] = out.get(m.stage.value, 0) + 1
    return out


def test_backfill_end_to_end_with_wait(cloud: MockCloud, store: LocalBlobStore) -> None:
    summary = make(cloud, store, wait_for_speech=True).run_backfill()
    assert summary.outcomes["ingested_vtt"] == WITH_VTT
    assert summary.outcomes["transcription_submitted"] == IN_WINDOW - WITH_VTT
    assert summary.outcomes["ingested_speech"] == IN_WINDOW - WITH_VTT
    assert stages(store) == {"chunked": IN_WINDOW}
    assert summary.since == (NOW - timedelta(days=365)).isoformat()

    for m in StateStore(store).all():
        assert store.exists(TRANSCRIPTS, f"parsed/{m.id}.json")
        chunks = get_json(store, ARTIFACTS, f"chunks/{m.id}.json")["chunks"]
        assert chunks and chunks[0]["id"] == f"{m.id}-0000" and m.chunk_count == len(chunks)
        meta = get_json(store, ARTIFACTS, f"recordings/{m.id}.json")
        assert meta["normalizedTitle"]["display"].startswith("Minicode: ") or meta["normalizedTitle"]["display"]
        assert "-Meeting Recording" not in meta["normalizedTitle"]["display"]
        assert not store.exists(ARTIFACTS, f"audio/{m.id}.m4a")  # temporary Speech input cleaned up
        raw = "raw/{}.vtt" if m.transcript_source == "teams-vtt" else "raw/{}.speech.json"
        assert store.exists(TRANSCRIPTS, raw.format(m.id))
    assert not cloud.jobs  # speech jobs deleted after download
    assert store.exists(INVENTORY, "state/delta.json")
    assert len(list(store.list(INVENTORY, "runs/"))) == 1

    langs = {m.title.split("-")[0]: m.language for m in StateStore(store).all()}
    assert langs["Minicode_ CD for SQL databases"] == "fi-FI"
    assert langs["EU AI Act "] == "en-US"


def test_speech_transcript_has_speakers(cloud: MockCloud, store: LocalBlobStore) -> None:
    make(cloud, store, wait_for_speech=True).run_backfill()
    rid = cloud.find("Minicode_ CD for SQL")
    parsed = get_json(store, TRANSCRIPTS, f"parsed/{rid}.json")
    assert parsed["source"] == "azure-speech" and parsed["speakers"] == ["Speaker 1", "Speaker 2"]


def test_rerun_is_idempotent(cloud: MockCloud, store: LocalBlobStore) -> None:
    make(cloud, store, wait_for_speech=True).run_backfill()
    seen = len(cloud.requests)
    second = make(cloud, store, wait_for_speech=True).run_backfill()
    assert dict(second.outcomes) == {"unchanged": IN_WINDOW}
    assert not any(r.method == "POST" for r in cloud.requests[seen:] if "speech" in r.url.host)
    forced = make(cloud, store, force=True).run_backfill()
    assert forced.outcomes["ingested_vtt"] == WITH_VTT


def test_without_wait_jobs_are_completed_by_next_run(cloud: MockCloud, store: LocalBlobStore) -> None:
    first = make(cloud, store).run_backfill()
    assert first.outcomes["transcription_submitted"] == 3
    assert stages(store) == {"chunked": 4, "transcription_pending": 3}
    rid = cloud.find("Minicode_ CD for SQL")
    assert store.exists(ARTIFACTS, f"audio/{rid}.m4a")
    m = StateStore(store).get(rid)
    assert m and m.speech_job_url and m.speech_job_url.startswith("https://mock-speech")

    second = make(cloud, store).run_incremental()  # poll 1 -> Running
    assert second.outcomes["transcription_pending"] == 3
    third = make(cloud, store).run_incremental()  # poll 2 -> Succeeded
    assert third.outcomes["ingested_speech"] == 3
    assert stages(store) == {"chunked": IN_WINDOW}


def test_speech_disabled_marks_no_transcript(cloud: MockCloud, store: LocalBlobStore) -> None:
    p = build_pipeline(Settings(source="mock", speech="off"), store=store, cloud=cloud, clock=Clock())
    summary = p.run_backfill()
    assert summary.outcomes == {"ingested_vtt": 4, "no_transcript": 3}
    assert stages(store) == {"chunked": 4, "no_transcript": 3}


def test_failures_are_isolated_retried_and_capped(cloud: MockCloud, store: LocalBlobStore) -> None:
    bad = cloud.find("Minicode_ Threat Modeling")
    good_content = cloud.content[cloud.make_id(f"{cloud.folder}/{cloud.items[bad]['name'].removesuffix('.mp4')}.vtt")]
    tid = cloud.make_id(f"{cloud.folder}/{cloud.items[bad]['name'].removesuffix('.mp4')}.vtt")
    cloud.content[tid] = b"not a vtt file"

    summary = make(cloud, store, wait_for_speech=True, max_attempts=2).run_backfill()
    assert summary.outcomes["failed"] == 1 and summary.outcomes["ingested_vtt"] == WITH_VTT - 1
    assert summary.errors == [{"id": bad, "title": cloud.items[bad]["name"].removesuffix(".mp4"), "error": "TranscriptParseError: missing WEBVTT header"}]
    assert make(cloud, store, max_attempts=2).run_backfill().outcomes["failed"] == 1  # attempt 2
    assert make(cloud, store, max_attempts=2).run_backfill().outcomes["failed_max_attempts"] == 1  # capped

    cloud.content[tid] = good_content  # fixed at the source + new version -> retried
    cloud.touch(bad)
    assert make(cloud, store, max_attempts=2).run_backfill().outcomes["ingested_vtt"] == 1
    assert StateStore(store).get(bad).stage == Stage.CHUNKED  # type: ignore[union-attr]


def test_failed_speech_job(cloud: MockCloud, store: LocalBlobStore) -> None:
    rid = cloud.find("Minicode_ CD for SQL")
    cloud.fail_speech_for = {rid}
    summary = make(cloud, store, wait_for_speech=True).run_backfill()
    assert summary.outcomes["failed"] == 1
    m = StateStore(store).get(rid)
    assert m and m.stage == Stage.FAILED and "InvalidData" in (m.error or "") and m.speech_job_url is None
    assert not cloud.jobs.get(rid)


def test_stuck_speech_job_times_out(cloud: MockCloud, store: LocalBlobStore) -> None:
    cloud.speech_polls = 99
    clock = Clock()
    make(cloud, store, clock).run_backfill()
    clock.now = NOW + timedelta(hours=25)
    summary = make(cloud, store, clock).run_incremental()
    assert summary.outcomes["failed"] == 3
    assert all("TimeoutError" in (m.error or "") for m in StateStore(store).all() if m.stage == Stage.FAILED)


def test_window_filter_and_explicit_since(cloud: MockCloud, store: LocalBlobStore) -> None:
    summary = make(cloud, store).run_backfill(since=NOW - timedelta(days=100))
    assert sum(summary.outcomes.values()) == 3  # 18, 47 and 96 days ago
    everything = make(cloud, store, wait_for_speech=True).run_backfill(since=NOW - timedelta(days=1000))
    assert stages(store) == {"chunked": 9}
    assert everything.outcomes["unchanged"] == 2  # the two vtt ones from the first run


def test_incremental_new_changed_late_transcript_and_deleted(cloud: MockCloud, store: LocalBlobStore) -> None:
    make(cloud, store, wait_for_speech=True).run_backfill()
    assert make(cloud, store).run_incremental().outcomes == {}

    new = cloud.add_recording({"stem": "Minicode_ Brand new", "days_ago": 0, "transcript": "slo-monitoring.vtt"})
    late = cloud.find("Minicode_ CD for SQL")  # was transcribed by Speech
    cloud.add_transcript(late, (cloud.samples_dir / "transcripts" / "threat-modeling.vtt").read_bytes())
    gone = cloud.find("Minicode_ Bicep")
    cloud.delete_item(gone)
    cloud.add_recording({"stem": "Ancient", "days_ago": 800, "transcript": "slo-monitoring.vtt"})

    summary = make(cloud, store).run_incremental()
    by_id = {i["id"]: i["outcome"] for i in summary.items}
    assert by_id[new["id"]] == "ingested_vtt"
    assert by_id[late] == "ingested_vtt"  # Teams transcript replaces the Speech one
    assert by_id[gone] == "deleted"
    assert "out_of_window" in by_id.values()
    assert StateStore(store).get(late).transcript_source == "teams-vtt"  # type: ignore[union-attr]
    assert StateStore(store).get(gone).stage == Stage.DELETED  # type: ignore[union-attr]
    for container, path in ((TRANSCRIPTS, f"parsed/{gone}.json"), (ARTIFACTS, f"chunks/{gone}.json"), (TRANSCRIPTS, f"raw/{gone}.vtt")):
        assert not store.exists(container, path)


def test_incremental_without_cursor_backfills(cloud: MockCloud, store: LocalBlobStore) -> None:
    summary = make(cloud, store).run_incremental()
    assert summary.mode == "backfill" and summary.outcomes["ingested_vtt"] == WITH_VTT


def test_expired_cursor_falls_back_to_backfill(cloud: MockCloud, store: LocalBlobStore) -> None:
    make(cloud, store, wait_for_speech=True).run_backfill()
    StateStore(store).save_cursor(f"https://graph.microsoft.com/v1.0/drives/{cloud.drive_id}/root/delta?token=expired", NOW)
    summary = make(cloud, store).run_incremental()
    assert summary.mode == "backfill" and summary.outcomes == {"unchanged": IN_WINDOW}


def test_resumes_after_crash_mid_run(cloud: MockCloud, store: LocalBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    p = make(cloud, store, wait_for_speech=True)
    original = p.source.get_transcript
    calls = {"n": 0}

    def crash_after_three(rec):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] > 3:
            raise KeyboardInterrupt  # not an Exception: simulates the host killing the run
        return original(rec)

    monkeypatch.setattr(p.source, "get_transcript", crash_after_three)
    with pytest.raises(KeyboardInterrupt):
        p.run_backfill()
    done_before = sum(1 for m in StateStore(store).all() if m.stage == Stage.CHUNKED)
    assert 1 <= done_before < IN_WINDOW

    summary = make(cloud, store, wait_for_speech=True).run_backfill()
    assert summary.outcomes["unchanged"] == done_before
    assert stages(store) == {"chunked": IN_WINDOW}


def test_settings_from_env(tmp_path: Path) -> None:
    s = Settings.from_env({"MINICODE_SOURCE": "GRAPH", "MINICODE_LOCAL_STORE": str(tmp_path), "SPEECH_CANDIDATE_LOCALES": "en-US, sv-SE",
                           "BACKFILL_LOOKBACK_DAYS": "30", "MINICODE_FOLDER_PATH": "Minicode/Recordings"})
    assert s.source == "graph" and s.local_root == tmp_path and s.candidate_locales == ("en-US", "sv-SE")
    assert s.lookback_days == 30 and s.folder == "Minicode/Recordings" and s.storage == "local"
    p = build_pipeline(s)
    assert p.speech is None and p.audio is None  # no AI_SERVICES_ENDPOINT -> Speech off
    with_speech = build_pipeline(Settings.from_env({"MINICODE_SOURCE": "graph", "AI_SERVICES_ENDPOINT": "https://x.cognitiveservices.azure.com",
                                                    "MINICODE_LOCAL_STORE": str(tmp_path)}))
    assert with_speech.speech is not None and with_speech.audio is not None
    with pytest.raises(ValueError):
        build_pipeline(Settings(source="nope", local_root=tmp_path))
    with pytest.raises(ValueError):
        build_pipeline(Settings(storage="azure"))
