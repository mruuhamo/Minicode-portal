from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from minicode.ingestion.audio import DownloadAudioExtractor, FfmpegAudioExtractor, find_ffmpeg
from minicode.ingestion.fakes import SPEECH_ENDPOINT, MockCloud
from minicode.ingestion.http import StaticTokenProvider
from minicode.ingestion.speech import SpeechBatchClient, SpeechOptions
from minicode.ingestion.transcripts import parse_speech_result


@pytest.fixture
def cloud() -> MockCloud:
    return MockCloud(speech_polls=2)


def _client(cloud: MockCloud, **kw) -> SpeechBatchClient:  # type: ignore[no-untyped-def]
    return SpeechBatchClient(SPEECH_ENDPOINT, StaticTokenProvider(), transport=cloud.transport, **kw)


def test_request_body() -> None:
    client = SpeechBatchClient("https://x.cognitiveservices.azure.com", StaticTokenProvider(), options=SpeechOptions(max_speakers=4))
    body = client.build_request("https://blob/a.m4a?sas", "minicode-1")
    assert body["contentUrls"] == ["https://blob/a.m4a?sas"]
    assert body["locale"] == "fi-FI" and body["displayName"] == "minicode-1"
    p = body["properties"]
    assert p["timeToLiveHours"] == 48
    assert p["languageIdentification"] == {"candidateLocales": ["fi-FI", "en-US"], "mode": "Single"}
    assert p["diarization"] == {"enabled": True, "maxSpeakers": 4}


def test_single_locale_disables_language_identification() -> None:
    client = SpeechBatchClient("https://x", StaticTokenProvider(), options=SpeechOptions(locale="en-US", candidate_locales=("en-US",), diarization=False))
    p = client.build_request("u", "n")["properties"]
    assert "languageIdentification" not in p and "diarization" not in p


def test_submit_poll_fetch_delete(cloud: MockCloud) -> None:
    rec_id = cloud.find("Minicode_ CD for SQL")
    client = _client(cloud)
    job = client.submit("https://blob/audio.m4a?sas", f"minicode-{rec_id}")
    assert job.status == "NotStarted" and not job.done
    submit = cloud.requests[-1]
    assert submit.method == "POST" and submit.url.params["api-version"] == "2024-11-15"
    assert submit.url.path == "/speechtotext/transcriptions:submit"
    assert submit.headers["Authorization"] == "Bearer test-token"
    assert client.get(job.url).status == "Running"
    assert client.get(job.url).status == "Succeeded"
    result = client.fetch_result(job.url)
    assert not cloud.requests[-1].headers.get("Authorization")  # result SAS url: no bearer token leaked
    t = parse_speech_result(result)
    assert t.language == "fi-FI" and "DACPAC" in " ".join(c.text for c in t.cues)
    client.delete(job.url)
    assert not cloud.jobs


def test_failed_job_reports_error(cloud: MockCloud) -> None:
    cloud.fail_speech_for = {"r1"}
    cloud.speech_polls = 1
    client = _client(cloud)
    job = client.get(client.submit("u", "minicode-r1").url)
    assert job.done and job.status == "Failed" and job.error and "InvalidData" in job.error


def test_requires_endpoint() -> None:
    with pytest.raises(ValueError):
        SpeechBatchClient("", StaticTokenProvider())


def test_download_audio_extractor(cloud: MockCloud) -> None:
    rec_id = cloud.video_ids()[0]
    assert DownloadAudioExtractor(cloud.transport).extract(f"https://download.mock.local/{rec_id}") == f"FAKE-MEDIA:{rec_id}".encode()
    with pytest.raises(httpx.HTTPStatusError):
        DownloadAudioExtractor(cloud.transport).extract("https://download.mock.local/nope")


def test_ffmpeg_command_shape() -> None:
    cmd = FfmpegAudioExtractor(ffmpeg="ffmpeg").command("https://x/video.mp4", Path("out.m4a"))
    assert cmd[0] == "ffmpeg" and "-vn" in cmd and cmd[cmd.index("-ar") + 1] == "16000" and cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-i") + 1] == "https://x/video.mp4"


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not available")
def test_ffmpeg_extracts_mono_16k_audio(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    video = tmp_path / "v.mp4"
    subprocess.run(
        [ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)],
        check=True,
    )
    audio = FfmpegAudioExtractor(ffmpeg=ffmpeg).extract(str(video))
    assert 0 < len(audio) < video.stat().st_size
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", "-"], input=audio, capture_output=True)
    info = probe.stderr.decode(errors="replace")
    assert "16000 Hz" in info and "mono" in info and "Video:" not in info


def test_ffmpeg_failure_is_reported(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg() or shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        FfmpegAudioExtractor(ffmpeg=ffmpeg).extract(str(tmp_path / "missing.mp4"))


def test_result_json_is_serializable(cloud: MockCloud) -> None:
    client = _client(cloud)
    job = client.submit("u", "minicode-unknown")
    client.get(job.url), client.get(job.url)
    assert json.dumps(client.fetch_result(job.url))
