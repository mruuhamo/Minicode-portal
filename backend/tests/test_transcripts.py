from __future__ import annotations

import json

import pytest

from minicode.ingestion.fakes import SAMPLES_DIR, speech_result_from_script
from minicode.ingestion.transcripts import (
    Cue,
    Transcript,
    TranscriptParseError,
    format_timestamp,
    parse_speech_result,
    parse_vtt,
    to_vtt,
)

TEAMS_VTT = """\ufeffWEBVTT\r
\r
NOTE produced by Teams\r
\r
3c1e-4a/12-0\r
00:00:03.120 --> 00:00:09.480\r
<v Aino Virtanen>Hi everyone, welcome.</v>\r
\r
3c1e-4a/13-0\r
00:00:09.480 --> 00:00:17.900 align:start position:10%\r
<v Mikael Lindqvist>Two lines\r
of text &amp; an entity</v>\r
\r
00:00:18.000 --> 00:00:18.500\r
<v Aino Virtanen></v>\r
\r
broken\r
00:00:xx.000 --> 00:00:20.000\r
skip me\r
\r
01:02:03.004 --> 01:02:05.5\r
No speaker, <b>bold</b>\r
"""


def test_parse_teams_vtt() -> None:
    t = parse_vtt(TEAMS_VTT, "rec1")
    assert t.source == "teams-vtt"
    assert [c.text for c in t.cues] == ["Hi everyone, welcome.", "Two lines of text & an entity", "No speaker, bold"]
    assert [c.speaker for c in t.cues] == ["Aino Virtanen", "Mikael Lindqvist", None]
    assert t.cues[0].start == pytest.approx(3.12)
    assert t.cues[1].end == pytest.approx(17.9)
    assert t.cues[2].start == pytest.approx(3723.004)
    assert t.cues[2].end == pytest.approx(3725.5)
    assert t.speakers == ["Aino Virtanen", "Mikael Lindqvist"]
    assert t.duration == pytest.approx(3725.5)


def test_parse_vtt_without_hours_or_ids_and_comma_millis() -> None:
    t = parse_vtt("WEBVTT\n\n00:01.000 --> 00:02,500\nhello\n")
    assert t.cues == [Cue(1.0, 2.5, "hello", None)]


def test_parse_vtt_requires_header() -> None:
    with pytest.raises(TranscriptParseError):
        parse_vtt("1\n00:00:01.000 --> 00:00:02.000\nhello\n")


def test_vtt_roundtrip() -> None:
    original = Transcript("r", "teams-vtt", [Cue(0.5, 2.25, "A & B <ok>", "Ann"), Cue(3723.004, 3725.0, "plain")])
    parsed = parse_vtt(to_vtt(original), "r")
    assert parsed.cues == original.cues


def test_format_timestamp() -> None:
    assert format_timestamp(3723.004) == "01:02:03.004"
    assert format_timestamp(0) == "00:00:00.000"


@pytest.mark.parametrize("vtt", sorted((SAMPLES_DIR / "transcripts").glob("*.vtt")), ids=lambda p: p.name)
def test_sample_transcripts_parse(vtt) -> None:  # type: ignore[no-untyped-def]
    t = parse_vtt(vtt.read_text(encoding="utf-8"))
    assert len(t.cues) >= 8
    assert len(t.speakers) >= 2
    assert all(c.end >= c.start for c in t.cues)


def test_parse_speech_result() -> None:
    data = {
        "recognizedPhrases": [
            {"recognitionStatus": "Success", "channel": 0, "speaker": 2, "offsetInTicks": 35_000_000, "durationInTicks": 10_000_000,
             "locale": "fi-FI", "nBest": [{"display": "Toinen."}]},
            {"recognitionStatus": "Success", "channel": 0, "speaker": 1, "offsetInTicks": 5_000_000, "durationInTicks": 20_000_000,
             "locale": "fi-FI", "nBest": [{"display": "Ensimmäinen lause."}]},
            {"recognitionStatus": "Success", "channel": 1, "speaker": 1, "offsetInTicks": 5_000_000, "durationInTicks": 1, "nBest": [{"display": "dup"}]},
            {"recognitionStatus": "NoMatch", "channel": 0, "offsetInTicks": 0, "durationInTicks": 1},
            {"recognitionStatus": "Success", "channel": 0, "offsetInTicks": 60_000_000, "durationInTicks": 1, "locale": "en-US",
             "nBest": [{"display": "  "}]},
        ]
    }
    t = parse_speech_result(json.dumps(data), "r")
    assert t.source == "azure-speech" and t.language == "fi-FI"
    assert [(c.start, c.end, c.text, c.speaker) for c in t.cues] == [
        (0.5, 2.5, "Ensimmäinen lause.", "Speaker 1"),
        (3.5, 4.5, "Toinen.", "Speaker 2"),
    ]


def test_parse_speech_result_rejects_other_json() -> None:
    with pytest.raises(TranscriptParseError):
        parse_speech_result({"values": []})


def test_fake_speech_result_parses() -> None:
    script = (SAMPLES_DIR / "speech" / "cd-for-sql.txt").read_text(encoding="utf-8")
    t = parse_speech_result(speech_result_from_script(script))
    assert t.language == "fi-FI"
    assert t.speakers == ["Speaker 1", "Speaker 2"]
    assert all(b.start >= a.end for a, b in zip(t.cues, t.cues[1:], strict=False))
