from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from minicode.ingestion.fakes import MockCloud
from minicode.ingestion.graph import GraphClient, GraphRecordingSource
from minicode.ingestion.http import HttpError, RestClient, StaticTokenProvider
from minicode.inventory.models import RecordingStatus
from minicode.inventory.sources import RecordingSource

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def cloud() -> MockCloud:
    return MockCloud(now=NOW)


@pytest.fixture
def source(cloud: MockCloud) -> GraphRecordingSource:
    client = GraphClient(StaticTokenProvider("tkn"), transport=cloud.transport, sleep=lambda _: None)
    return GraphRecordingSource(cloud.site_id, folder_path=cloud.folder, client=client)


def test_is_a_recording_source(source: GraphRecordingSource) -> None:
    assert isinstance(source, RecordingSource)


def test_lists_videos_in_window_with_metadata(source: GraphRecordingSource, cloud: MockCloud) -> None:
    recs = list(source.list_recordings(since=NOW - timedelta(days=365)))
    assert len(recs) == 7  # 9 videos in samples, 2 older than a year; the .pptx and .vtt files are not recordings
    assert all(r.file_name and r.file_name.endswith(".mp4") for r in recs)
    bicep = next(r for r in recs if r.title.startswith("Minicode_ Bicep"))
    assert bicep.title.endswith("-Meeting Recording")
    assert bicep.organizer == "Aino Virtanen" and bicep.organizer_email == "aino.virtanen@contoso.com"
    assert bicep.has_transcript is True and bicep.status == RecordingStatus.AVAILABLE
    assert bicep.duration_seconds == 180 and bicep.recorded_at is not None
    assert bicep.recorded_at.tzinfo is not None and bicep.etag and bicep.size_bytes
    assert bicep.folder_path == "General/Recordings" and bicep.drive_item_id == bicep.id
    assert sum(1 for r in recs if r.has_transcript) == 4


def test_paging_auth_and_drive_resolution(source: GraphRecordingSource, cloud: MockCloud) -> None:
    list(source.list_recordings())
    urls = [str(r.url) for r in cloud.requests]
    assert urls[0].endswith(f"/sites/{cloud.site_id}/drive?%24select=id")
    assert sum("skiptoken" in u for u in urls) >= 3  # page_size=3 forces several pages
    assert all(r.headers["Authorization"] == "Bearer tkn" for r in cloud.requests)
    assert len(list(source.list_recordings())) == 9  # no since -> everything


def test_recurses_into_subfolders(cloud: MockCloud, source: GraphRecordingSource) -> None:
    cloud.add_recording({"stem": "Minicode_ Archived talk", "days_ago": 3, "folder": "General/Recordings/2026", "transcript": "threat-modeling.vtt"})
    recs = {r.title.split("-")[0]: r for r in source.list_recordings(since=NOW - timedelta(days=10))}
    sub = recs["Minicode_ Archived talk"]
    assert sub.folder_path == "General/Recordings/2026" and sub.has_transcript
    assert "WEBVTT" in (source.get_transcript(sub) or "")


def test_get_transcript_and_download_url(source: GraphRecordingSource) -> None:
    recs = {r.title.split("-")[0]: r for r in source.list_recordings()}
    vtt = source.get_transcript(recs["Minicode_ Threat Modeling"])
    assert vtt is not None and vtt.startswith("WEBVTT") and "<v Jussi Korhonen>" in vtt
    assert source.get_transcript(recs["Minicode_ CD for SQL databases"]) is None
    assert source.get_download_url(recs["Minicode_ CD for SQL databases"]).startswith("https://download.mock.local/")


def test_retries_throttling_with_retry_after(cloud: MockCloud) -> None:
    sleeps: list[float] = []
    cloud.throttle_next = 2
    client = GraphClient(StaticTokenProvider(), transport=cloud.transport, sleep=sleeps.append)
    source = GraphRecordingSource(cloud.site_id, folder_path=cloud.folder, client=client)
    assert len(list(source.list_recordings())) == 9
    assert sleeps == [1.0, 1.0]


def test_gives_up_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    client = RestClient("https://x.test", None, transport=httpx.MockTransport(handler), max_retries=2, sleep=lambda _: None)
    with pytest.raises(HttpError) as e:
        client.get_json("/a")
    assert e.value.status_code == 503 and calls == 3


def test_transport_errors_are_retried() -> None:
    attempts = iter([httpx.ConnectError("boom"), httpx.Response(200, json={"ok": True})])

    def handler(request: httpx.Request) -> httpx.Response:
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    client = RestClient("https://x.test", None, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    assert client.get_json("https://x.test/b") == {"ok": True}


def test_missing_token_is_rejected(cloud: MockCloud) -> None:
    client = RestClient("https://graph.microsoft.com/v1.0", None, transport=cloud.transport)
    with pytest.raises(HttpError) as e:
        client.get_json(f"/sites/{cloud.site_id}/drive")
    assert e.value.status_code == 401


def test_delta_reports_changes_in_folder_only(cloud: MockCloud, source: GraphRecordingSource) -> None:
    cursor = source.latest_cursor()
    assert source.list_changes(cursor)[0] == []

    added = cloud.add_recording({"stem": "Minicode_ New talk", "days_ago": 0, "speech": "eu-ai-act.txt"})
    cloud.add_recording({"stem": "Elsewhere", "days_ago": 0, "folder": "Other"})
    old_video = cloud.find("Minicode_ CD for SQL")
    cloud.add_transcript(old_video, b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v A>late transcript\n")
    deleted = cloud.find("Minicode_ Threat Modeling")
    cloud.delete_item(deleted)

    changes, cursor2 = source.list_changes(cursor)
    by_id = {c.recording.id: c for c in changes}
    assert set(by_id) == {added["id"], old_video, deleted}
    assert by_id[deleted].deleted and by_id[deleted].recording.status == RecordingStatus.DELETED
    assert by_id[old_video].recording.has_transcript is True  # sidecar change surfaces its video
    assert by_id[added["id"]].recording.organizer is None
    assert source.list_changes(cursor2)[0] == []


def test_expired_delta_token_raises_410(source: GraphRecordingSource, cloud: MockCloud) -> None:
    with pytest.raises(HttpError) as e:
        source.list_changes(f"https://graph.microsoft.com/v1.0/drives/{cloud.drive_id}/root/delta?token=garbage")
    assert e.value.status_code == 410


def test_explicit_drive_id_skips_site_lookup(cloud: MockCloud) -> None:
    client = GraphClient(StaticTokenProvider(), transport=cloud.transport)
    source = GraphRecordingSource("", drive_id=cloud.drive_id, folder_path=cloud.folder, client=client)
    assert list(source.list_recordings())
    assert not any("/sites/" in str(r.url) for r in cloud.requests)
